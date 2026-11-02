"""A bounded unit of discovery per lease; every result survives a process restart."""
import hashlib
import json
import threading
import time
import socket
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from ..core import DomainError,iso,utcnow
from ..service import uid,loadj
from .service import Discovery
from .web import PublicWeb
from .providers import Providers
from .sources import inventory,filing
from .inspection import inspect,guesses,host,assess,sitemap,verify_links,SOCIAL

class DiscoveryWorker:
    def __init__(self,service,web=None,provider=None):
        self.service=service;self.discovery=Discovery(service);self.db=service.db;self.id=uid()
        self.web=web or PublicWeb(Path(service.config.database_path).parent/'prospecting-cache')
        self.provider=provider or Providers(service.config)
        self.stop_event=threading.Event();self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True,name='prospect-discovery');self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=3)
    def run(self):
        while not self.stop_event.is_set():
            try:self.tick()
            except Exception:pass # Persisted errors are sanitized in tick; never log provider request objects.
            self.stop_event.wait(3)
    def claim(self):
        with self.db.transaction() as tx:
            # One inventory/enrichment worker per workspace, including multiple application processes.
            if tx.one('SELECT id FROM discovery_runs WHERE lease_until>?',(iso(),)):return None
            run=tx.one("SELECT * FROM discovery_runs WHERE state IN ('queued','enriching') ORDER BY created_at LIMIT 1")
            if not run:return None
            tx.execute("UPDATE discovery_targets SET state='pending' WHERE run_id=? AND state='working'",(run['id'],))
            tx.execute('UPDATE discovery_runs SET lease_owner=?,lease_until=? WHERE id=?',(self.id,iso(utcnow()+timedelta(minutes=30)),run['id']))
            return run
    def tick(self):
        if self.service.config.mode=='production':
            with self.db.transaction(False) as tx:
                if not tx.setting('setup_complete',False):return
        if not self.service.config.source_rights_approved:return
        run=self.claim()
        if not run:return
        try:
            params=loadj(run['params_json'],{})
            if run['state']=='queued':self.collect(run,params)
            else:
                with self.db.transaction() as tx:
                    target=tx.one("SELECT * FROM discovery_targets WHERE run_id=? AND state='pending' ORDER BY entity_id LIMIT 1",(run['id'],))
                    if target:tx.execute("UPDATE discovery_targets SET state='working',attempts=attempts+1 WHERE run_id=? AND entity_id=?",(run['id'],target['entity_id']))
                    else:
                        tx.execute("UPDATE discovery_runs SET state='completed',updated_at=? WHERE id=? AND state!='paused'",(iso(),run['id']));return
                result=self.enrich(run,target,params)
                unavailable=not result.get('site') and any(c['status']=='unavailable' for c in result['checks'])
                state='failed' if unavailable else 'complete'
                with self.db.transaction() as tx:
                    tx.execute('UPDATE discovery_targets SET state=?,result_json=?,error=? WHERE run_id=? AND entity_id=?',
                        (state,json.dumps(result),'Some sources could not be checked; resume to retry.' if unavailable else '',run['id'],target['entity_id']))
                    # Discovery can propose a URL but cannot change a review, campaign, suppression or qualification.
                    entity=self.service.required(tx,'entities',target['entity_id'])
                    site=result.get('site',{})
                    if not entity['verified_at'] and entity['state']=='review' and site.get('identity',{}).get('matched'):
                        proposal='broken_or_parked' if site.get('parked') or site.get('spam') else 'hosted_chapter_page_only' if site.get('hosted') else 'official_website_found'
                        tx.execute('UPDATE entities SET website_url=?,proposed_website_status=?,updated_at=? WHERE id=?',(site['url'],proposal,iso(),entity['id']))
                    completed=tx.one("SELECT COUNT(*) AS n FROM discovery_targets WHERE run_id=? AND state IN ('complete','failed')",(run['id'],))['n']
                    tx.execute('UPDATE discovery_runs SET completed=?,updated_at=? WHERE id=?',(completed,iso(),run['id']))
        except Exception as exc:
            message=str(exc) if isinstance(exc,DomainError) else 'Discovery could not complete this step ('+type(exc).__name__+'). Resume to retry.'
            with self.db.transaction() as tx:
                tx.execute("UPDATE discovery_runs SET state=CASE WHEN state='paused' THEN state ELSE 'failed' END,error=?,updated_at=? WHERE id=?",(message[:700],iso(),run['id']))
        finally:
            with self.db.transaction() as tx:tx.execute('UPDATE discovery_runs SET lease_owner=NULL,lease_until=NULL WHERE id=? AND lease_owner=?',(run['id'],self.id))
    def collect(self,run,params):
        with self.db.transaction(False) as tx:
            city=self.service.required(tx,'cities',run['city_id'])
            existing=tx.all('SELECT e.id,e.name,e.website_url,i.ein FROM entities e LEFT JOIN discovery_identity i ON i.entity_id=e.id WHERE city_id=? AND state!=?',(run['city_id'],'suppressed')) if params['include_existing'] else []
        orgs=[]
        for seed in params.get('seeds',[]):orgs.append({**seed,'city':city['name'],'state':city['region'],'source_kind':'manual'})
        for r in existing:
            orgs.append({'name':r['name'],'ein':r.get('ein') or '', 'website':r['website_url'],'city':city['name'],'state':city['region'],'source_kind':'workspace','source_url':''})
        matched=0
        if params['use_irs']:
            irs,matched=inventory(self.web,city,params);orgs.extend(irs)
        # Deduplicate before truncating so duplicate seeds do not consume the candidate limit.
        unique={}
        for o in orgs:
            key=o.get('ein') or o['name'].casefold()
            unique[key]={**unique.get(key,{}),**o}
        self.discovery.add_targets(run,list(unique.values())[:params['max_candidates']])
        with self.db.transaction() as tx:
            note=f'IRS inventory matched {matched}; this hunt is capped at {params["max_candidates"]}. ZIP distances are approximate.' if params['use_irs'] else ''
            tx.execute('UPDATE discovery_runs SET error=? WHERE id=?',(note,run['id']))

    def enrich(self,run,target,params):
        org=loadj(target['facts_json'],{});eid=target['entity_id'];rid=run['id'];checks=[];started=time.monotonic()
        def check(kind,url,fn):
            if time.monotonic()-started>600:raise DomainError('This candidate reached its time limit. Resume to continue from saved observations.')
            cache_kind=kind+':v2:'+hashlib.sha256(url.encode()).hexdigest()[:16]
            with self.db.transaction(False) as tx:
                old=tx.one("SELECT * FROM discovery_evidence WHERE entity_id=? AND kind=? AND url=? AND status='ok' AND expires_at>? ORDER BY observed_at DESC LIMIT 1",(eid,cache_kind,url,iso()))
            if old:
                value=loadj(old['observation_json'],{});checks.append({'kind':kind,'url':url,'status':'ok','cached':True,'observed_at':old['observed_at']});return value
            try:
                value=fn();status='ok'
                if isinstance(value,dict) and value.get('status') in ('unavailable','unknown','not_configured'):status=value['status']
            except socket.gaierror as exc:
                status='not_found' if exc.errno in (socket.EAI_NONAME,getattr(socket,'EAI_NODATA',socket.EAI_NONAME)) else 'unavailable'
                value={'note':'Domain did not resolve; this is not proof that the organization has no website.' if status=='not_found' else 'DNS lookup was temporarily unavailable.'}
            except Exception as exc:
                value={'note':str(exc) if isinstance(exc,DomainError) else 'Source check unavailable ('+type(exc).__name__+').'};status='unavailable'
            self.discovery.evidence(rid,eid,cache_kind,url,status,value)
            checks.append({'kind':kind,'url':url,'status':status,'note':value.get('note','') if isinstance(value,dict) else '', 'observed_at':iso()})
            return value if status=='ok' else {}
        if org.get('source_url'):check('inventory',org['source_url'],lambda:{k:v for k,v in org.items() if k not in ('website',)})
        if org.get('ein'):
            f=check('filing','https://projects.propublica.org/nonprofits/organizations/'+org['ein'],lambda:filing(self.web,org['ein']))
            if f.get('website'):org.update(website=f['website'],filed_website=f['website'],website_source=f.get('source_url',''))
            if f.get('mission'):org['mission']=f['mission']
            if str(f.get('filing_year','')).isdigit():org['filing_year']=int(f['filing_year'])
        candidates=([org['website']] if org.get('website') else [])+guesses(org)
        site={};attempted=set();matches=[]
        def try_site(url):
            nonlocal site
            if url in attempted or host(url) in SOCIAL:return
            attempted.add(url)
            def read():
                final,raw=self.web.page(url)
                result=inspect(final,raw,org)
                filed=org.get('filed_website','')
                linked=bool(filed and host(url)==host(filed) and host(final)==host(filed))
                result['identity']['filing_domain_match']=linked
                if linked and result['identity']['name_match']:
                    result['identity'].update(matched=True,filing_source=org.get('website_source',''))
                return result
            found=check('website',url,read)
            if found:
                matches.append({'url':url,'identity':found.get('identity',{})})
                if found.get('identity',{}).get('matched'):site=found
        for url in candidates[:7]:
            try_site(url)
            if site:break
        searches=[]
        if params['use_web'] and not site:
            queries=[f'"{org["name"]}" {org.get("city","")} {org.get("state","")}',f'{org["name"]} {org.get("city","")} official website chapter']
            for n,q in enumerate(queries):
                def search():return self.discovery.paid(rid,eid,'search-'+str(n),'search',{'keyword':q[:350],'location_name':'United States','language_code':'en','depth':10},self.provider)
                result=check('search','https://www.google.com/search?q='+quote(q[:350]),search)
                searches.append({'query':q,'results':result.get('items',[])})
                for item in result.get('items',[])[:5]:
                    try_site(item['url'])
                    if site:break
                if site:break
        domains={};backlinks={}
        if site:
            domain=host(site['url'])
            # Inspect at most two useful internal pages. A homepage date alone is weak activity evidence.
            import re
            details=[u for u in site.get('page_links',[]) if u!=site['url'] and re.search(r'about|contact|news|events|calendar',u,re.I)][:2]
            site['inspected_pages']=[]
            for url in details:
                def inspect_page(url=url):
                    final,raw=self.web.page(url)
                    if host(final)!=domain:raise DomainError('Internal page redirected to another domain; review it separately.')
                    return inspect(final,raw,org)
                found=check('internal_page',url,inspect_page)
                if found:
                    site['inspected_pages'].append(found)
                    for key in ('member_area','store','recent_activity_signal'):site[key]=site.get(key,False) or found.get(key,False)
                    if found.get('latest_visible_date','')>site.get('latest_visible_date',''):site['latest_visible_date']=found['latest_visible_date']
                    site['activity_dates']=(site.get('activity_dates',[])+[{**d,'source_url':url} for d in found.get('activity_dates',[])])[:60]
                    site['public_emails']=sorted(set(site.get('public_emails',[])+found.get('public_emails',[])))[:10]
                    if found.get('designer_credit'):site['designer_credit']=found['designer_credit']
            sitemap_url='https://'+domain+'/sitemap.xml'
            def read_sitemap():
                final,raw=self.web.page(sitemap_url)
                if host(final)!=domain:raise DomainError('Sitemap redirected to another domain.')
                return sitemap(raw,domain)
            site['sitemap']=check('sitemap',sitemap_url,read_sitemap)
            if not site.get('hosted'):
                rdap='https://rdap.org/domain/'+quote(domain,safe='')
                def registry():
                    j,_=self.web.json(rdap)
                    return {'events':[{'event':x.get('eventAction'),'date':x.get('eventDate')} for x in j.get('events',[])][:12]}
                domains['registry']=check('registry',rdap,registry)
                domains['openpagerank']=check('openpagerank','https://openpagerank.com/?domain='+quote(domain),lambda:self.provider.opr(domain))
                archive='https://web.archive.org/cdx/search/cdx?'+ 'url='+quote(domain)+'&output=json&fl=timestamp&collapse=timestamp:4&limit=100'
                def history():
                    j,_=self.web.json(archive);years=[r[0][:4] for r in j[1:] if r and str(r[0])[:4].isdigit()]
                    return {'first_year':min(years) if years else None,'years':len(set(years))}
                domains['archive']=check('archive',archive,history)
                if params['use_backlinks']:
                    backlinks=check('backlinks','https://'+domain,lambda:self.discovery.paid(rid,eid,'summary','summary',{'target':domain,'include_subdomains':True},self.provider))
                    data=check('backlink_list','https://'+domain,lambda:self.discovery.paid(rid,eid,'links','links',{'target':domain,'limit':20,'mode':'as_is','include_subdomains':True},self.provider))
                    links=data.get('links',[])
                    for link in links[:3]:
                        def verify(link=link):
                            final,raw=self.web.page(link['source_url'])
                            return verify_links(raw,final,domain,org)
                        link['verification']=check('verify_link',link['source_url'],verify) or {'verified':None}
                    backlinks['links']=links
        return {'facts':org,'site':site,'identity_checks':matches,'searches':searches,'domain':domains,'backlinks':backlinks,
            'checks':checks,'scores':assess(org,site,backlinks,run['campaign'],checks),'observed_at':iso()}
