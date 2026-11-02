import base64
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.core import DomainError,iso,utcnow,qualification_blockers
from app.db import Database
from app.models import CityInput,ReviewInput,ResearchInput,ManualReport,CandidateBatch
from app.prospecting.models import HuntInput,Seed
from app.prospecting.service import Discovery
from app.prospecting.worker import DiscoveryWorker
from app.prospecting.inspection import inspect,assess,match
from app.prospecting.web import PublicWeb
from app.prospecting.providers import Providers
from app.vault import IntegrationStore,IntegrationInput
from test_service import service,prepare
from test_api import client

def hunt(service,**changes):
    service.config.source_rights_approved=True
    city=service.create_city(CityInput(name='Example Town',region='IL'),'test')
    data=dict(city_id=city['id'],use_irs=False,include_existing=False,rights_acknowledged=True,
              seeds=[dict(name='Example Historical Society',website='https://society.example/',source_url='https://city.example/clubs')])
    data.update(changes)
    return Discovery(service).create(HuntInput(**data),'test')

class FakeWeb:
    def __init__(self,fail=False):self.fail=fail;self.calls=[]
    def page(self,url):
        self.calls.append(url)
        if self.fail:raise DomainError('Page returned HTTP 503.')
        if url.endswith('/sitemap.xml'):return url,'<urlset><url><loc>https://society.example/</loc></url></urlset>'
        return url,'<html><title>Example Historical Society</title><p>Example Historical Society serves Example Town.</p><p>Copyright 2019</p><a href="mailto:info@society.example">info@society.example</a></html>'
    def json(self,url):
        if 'cdx' in url:return [['timestamp'],['20050101'],['20250101']],url
        if 'rdap' in url:return {'events':[{'eventAction':'registration','eventDate':'2000-01-01'}]},url
        return {'organization':{}},url

class FakeProvider:
    def __init__(self,fail=False):self.calls=[];self.fail=fail
    def call(self,kind,payload):
        self.calls.append((kind,payload))
        if self.fail:raise DomainError('Provider request outcome is uncertain.')
        return ({'status':'ok','referring_domains':12} if kind=='summary' else {'links':[]} if kind=='links' else {'items':[]}),2
    def opr(self,domain):return {'status':'unavailable','value':None}

def test_v2_migration_preserves_existing_records(tmp_path):
    path=tmp_path/'old.sqlite3'
    conn=sqlite3.connect(path);conn.executescript((Path('app/schema.sql')).read_text())
    conn.execute("INSERT INTO cities(id,name,region,timezone,canonical_key,created_at) VALUES('c','Town','IL','America/Chicago','town','now')")
    conn.execute("INSERT INTO entities(id,city_id,name,canonical_name,category,created_at,updated_at) VALUES('e','c','Org','org','specialized_nonprofit','now','now')")
    conn.commit();conn.close()
    db=Database(str(path));db.migrate();db.migrate()
    with db.transaction(False) as tx:
        assert tx.one('SELECT campaign,name FROM entities WHERE id=?',('e',))=={'campaign':'first_website','name':'Org'}

def test_paid_checks_require_explicit_budget():
    with pytest.raises(ValidationError):HuntInput(city_id='x',use_web=True)
    with pytest.raises(ValidationError):HuntInput(city_id='x',types=['invented'])
    with pytest.raises(DomainError):Seed(name='Bad site',source_url='http://127.0.0.1/file')

def test_hunts_require_source_permission(service):
    city=service.create_city(CityInput(name='Town',region='IL'),'test')
    with pytest.raises(DomainError):Discovery(service).create(HuntInput(city_id=city['id'],rights_acknowledged=True),'test')

def test_hunt_restart_keeps_results_unverified(service):
    r=hunt(service);web=FakeWeb();w=DiscoveryWorker(service,web,FakeProvider())
    w.tick() # inventory
    assert Discovery(service).detail(r['id'])['run']['total']==1
    DiscoveryWorker(service,web,FakeProvider()).tick() # resume in another process
    w.tick()
    d=Discovery(service).detail(r['id']);assert d['run']['state']=='completed'
    result=d['targets'][0]['result'];assert result['site']['identity']['matched']
    assert result['scores']['link_opportunity'] is None
    entity=service.snapshot()['entities'][0]
    assert entity['campaign']=='rebuild' and entity['state']=='review' and not entity['verified_at']
    assert entity['website_status']=='unknown' and entity['proposed_website_status']=='official_website_found'

def test_unknown_failures_retry_and_never_become_zero(service):
    r=hunt(service);web=FakeWeb(True);w=DiscoveryWorker(service,web,FakeProvider())
    w.tick();w.tick();w.tick()
    d=Discovery(service).detail(r['id']);assert d['targets'][0]['state']=='failed'
    assert d['targets'][0]['result']['scores']['link_opportunity'] is None
    web.fail=False;Discovery(service).control(r['id'],'resume','test');w.tick()
    assert Discovery(service).detail(r['id'])['targets'][0]['result']['site']['identity']['matched']

def test_ein_identity_and_distinct_chapters(service):
    r=hunt(service);d=Discovery(service)
    d.add_targets(r,[{'name':'Same Club','ein':'123456789'},{'name':'Same Club','ein':'987654321'}])
    d.add_targets(r,[{'name':'Club alias','ein':'123456789'}])
    rows=d.detail(r['id'])['targets'];assert len(rows)==2
    assert len({x['entity_id'] for x in rows})==2

def test_discovery_cannot_override_suppression(service):
    r=hunt(service);w=DiscoveryWorker(service,FakeWeb(),FakeProvider());w.tick()
    eid=Discovery(service).detail(r['id'])['targets'][0]['entity_id']
    with service.db.transaction() as tx:tx.execute("UPDATE entities SET state='suppressed',website_url='https://reviewed.example/',verified_at=? WHERE id=?",(iso(),eid))
    w.tick()
    e=next(e for e in service.snapshot()['entities'] if e['id']==eid)
    assert e['state']=='suppressed' and e['website_url']=='https://reviewed.example/'

def test_paid_reservation_precedes_call_and_deduplicates(service):
    service.config.dataforseo_login='test-login';service.config.dataforseo_password='test-password'
    r=hunt(service,use_backlinks=True,paid_approved=True,budget_cents=15)
    d=Discovery(service);d.add_targets(r,[{'name':'Some Org'}]);eid=d.detail(r['id'])['targets'][0]['entity_id'];p=FakeProvider()
    result=d.paid(r['id'],eid,'summary','summary',{'target':'society.example'},p)
    assert d.paid(r['id'],eid,'summary','summary',{},p)==result and len(p.calls)==1
    with pytest.raises(DomainError):d.paid(r['id'],eid,'expensive','links',{},FakeProvider(True))
    with pytest.raises(DomainError):d.paid(r['id'],eid,'expensive','links',{},p)
    assert len(p.calls)==1
    detail=d.detail(r['id']);assert detail['run']['spent_cents']==2 and detail['run']['reserved_cents']==10
    with pytest.raises(DomainError):d.paid(r['id'],eid,'new-search','search',{},p)

def test_paused_hunt_cannot_start_paid_request(service):
    service.config.dataforseo_login='x';service.config.dataforseo_password='y'
    r=hunt(service,use_web=True,paid_approved=True,budget_cents=50);d=Discovery(service);d.add_targets(r,[{'name':'Some Org'}])
    eid=d.detail(r['id'])['targets'][0]['entity_id'];d.control(r['id'],'pause','test');p=FakeProvider()
    with pytest.raises(DomainError):d.paid(r['id'],eid,'search','search',{},p)
    assert not p.calls

def test_missing_authority_not_conflated_with_zero():
    s={'identity':{'matched':True}}
    a=assess({},s,{},'rebuild',[]);b=assess({},s,{'status':'ok','referring_domains':0},'rebuild',[])
    assert a['link_opportunity'] is None and b['link_opportunity']==0

def test_name_alone_does_not_match_and_confidence_is_capped():
    org={'name':'Example Historical Society','city':'Example Town'}
    assert not match('<p>Example Historical Society</p>',org)['matched']
    assert assess({}, {}, {},'rebuild',[{'status':'ok'}]*20)['confidence']<=40

def test_rebuild_eligibility_and_campaign_change_revokes_approval(service):
    from app.models import ConversationInput
    sponsor,entity,contact=prepare(service)
    cv=service.reserve(ConversationInput(entity_ids=[entity['id']],client_id=sponsor['id'],contact_id=contact['id']),'test')
    message=service.create_draft(cv['id'],'test');service.approve(message['id'],'test')
    old=next(e for e in service.snapshot()['entities'] if e['id']==entity['id'])
    data=ReviewInput(campaign='rebuild',website_status='official_website_found',website_url='https://society.example/',
        history_note=old['history_note'],activity_note=old['activity_note'],evidence=old['evidence'],rights_confirmed=True)
    updated=service.review_entity(entity['id'],data,'test')
    verified_contact=next(c for c in service.snapshot()['contacts'] if c['id']==contact['id'])
    assert updated['state']!='excluded' and qualification_blockers(updated,verified_contact)==[]
    m=service.get_message(message['id']);assert m['state']=='draft' and m['approval_hash'] is None

def test_research_campaign_is_in_dedup_key(service):
    city=service.create_city(CityInput(name='Town',region='IL'),'test')
    a=service.create_research(ResearchInput(city_id=city['id'],category='historical_preservation',window='2026-11',rights_acknowledged=True),'test')
    b=service.create_research(ResearchInput(city_id=city['id'],category='historical_preservation',window='2026-11',rights_acknowledged=True,campaign='rebuild'),'test')
    assert a['id']!=b['id']

def test_new_credentials_encrypted_and_not_returned(service):
    service.config.encryption_key=base64.b64encode(b'x'*32).decode()
    store=IntegrationStore(service)
    values={'dataforseo_login':'private-login-example','dataforseo_password':'private-password-example','opr_key':'private-opr-example'}
    store.save(IntegrationInput(**values),'test')
    with service.db.transaction(False) as tx:raw=tx.one('SELECT ciphertext FROM secret_store WHERE name=?',('integrations',))['ciphertext']
    for value in values.values():
        assert value not in raw and value not in json.dumps(store.summary()) and value not in repr(service.config)
    store.load();assert service.config.dataforseo_password==values['dataforseo_password']

def test_discovery_api_csrf_and_validation(client):
    client.app.state.config.source_rights_approved=True
    city=client.get('/api/state').json()['cities'][0]['id']
    bad=client.post('/api/discovery',json={'city_id':city,'rights_acknowledged':True,'use_web':True})
    assert bad.status_code==422
    response=client.post('/api/discovery',json={'city_id':city,'rights_acknowledged':True,'use_irs':False})
    assert response.status_code==200
    id=response.json()['id'];assert client.get('/api/discovery/'+id).status_code==200
    assert client.get('/api/discovery-options').json()['types']['history']
    client.headers.pop('x-csrf-token');assert client.post('/api/discovery/'+id+'/pause',json={}).status_code==403

def test_private_and_non_https_fetches_rejected(tmp_path):
    web=PublicWeb(tmp_path)
    for url in ['https://127.0.0.1/','https://169.254.169.254/','file:///etc/passwd','https://user:secret@example.org/']:
        with pytest.raises(DomainError):web.page(url)

def test_expired_evidence_is_refetched(service):
    r=hunt(service);web=FakeWeb();w=DiscoveryWorker(service,web,FakeProvider());w.tick();w.tick();w.tick()
    first=len(web.calls);Discovery(service).control(r['id'],'resume','test');w.tick();w.tick()
    assert len(web.calls)==first
    with service.db.transaction() as tx:tx.execute('UPDATE discovery_evidence SET expires_at=?',(iso(utcnow()-timedelta(days=1)),))
    Discovery(service).control(r['id'],'resume','test');w.tick()
    assert len(web.calls)>first

def test_only_one_discovery_lease_and_expired_work_recovers(service):
    r=hunt(service);one=DiscoveryWorker(service,FakeWeb(),FakeProvider());two=DiscoveryWorker(service,FakeWeb(),FakeProvider())
    one.tick();claimed=one.claim();assert claimed and two.claim() is None
    with service.db.transaction() as tx:
        tx.execute("UPDATE discovery_targets SET state='working' WHERE run_id=?",(r['id'],))
        tx.execute('UPDATE discovery_runs SET lease_until=? WHERE id=?',(iso(utcnow()-timedelta(seconds=1)),r['id']))
    two.tick()
    assert Discovery(service).detail(r['id'])['targets'][0]['state']=='complete'

def test_large_observation_is_valid_json_or_rejected(service):
    r=hunt(service);d=Discovery(service);d.add_targets(r,[{'name':'Some Org'}]);eid=d.detail(r['id'])['targets'][0]['entity_id']
    d.evidence(r['id'],eid,'test','https://example.org','ok',{'text':'x'*45000})
    with service.db.transaction(False) as tx:
        assert len(json.loads(tx.one('SELECT observation_json FROM discovery_evidence')['observation_json'])['text'])==45000
    with pytest.raises(DomainError):d.evidence(r['id'],eid,'test','https://example.org','ok',{'text':'x'*110000})

def test_irs_inventory_uses_census_and_preserves_provenance(tmp_path):
    import zipfile
    from datetime import date
    from app.prospecting.sources import inventory,ZCTA,PLACES,POSTCARDS
    def zipped(name,data):
        path=tmp_path/(name+'.zip')
        with zipfile.ZipFile(path,'w') as z:z.writestr(name+'.txt',data)
        return path
    year=date.today().year
    zcta=zipped('zcta','GEOID|INTPTLAT|INTPTLONG\n60016|42.03|-87.89\n60601|41.88|-87.62\n')
    places=zipped('places','USPS|NAME|INTPTLAT|INTPTLONG\nIL|Des Plaines city|42.03|-87.89\n')
    card=zipped('cards',f'123456789|{year}|x|x|F|x|x|society.example|Private officer\n987654321|{year}|x|x|T|x|x|terminated.example|Private officer\n')
    bmf=tmp_path/'bmf.csv';bmf.write_text(f'EIN,NAME,SORT_NAME,CITY,ZIP,STATUS,FOUNDATION,REVENUE_AMT,NTEE_CD,SUBSECTION,TAX_PERIOD\n123456789,DES PLAINES HISTORICAL SOCIETY,,DES PLAINES,60016,01,10,15000,A80,03,202001\n987654321,TERMINATED HISTORICAL SOCIETY,,DES PLAINES,60016,01,10,15000,A80,03,202001\n')
    class DatasetWeb:
        def dataset(self,url,*args):return {ZCTA:zcta,PLACES:places,POSTCARDS:card}.get(url,bmf)
    params=HuntInput(city_id='test').model_dump()
    rows,count=inventory(DatasetWeb(),{'name':'Des Plaines','region':'IL'},params)
    assert count==len(rows)==1 and rows[0]['ein']=='123456789' and rows[0]['filing_year']==year
    assert rows[0]['website_source']==POSTCARDS and rows[0]['distance']==0
    assert 'Private officer' not in json.dumps(rows)
    params['center_zip']='60016'
    assert inventory(DatasetWeb(),{'name':'Unincorporated place','region':'Illinois'},params)[1]==1

def test_redirect_rechecks_destination_robots_and_rejects_private_dns(tmp_path,monkeypatch):
    from app.prospecting import web as module
    from app.research import validated_host as validate
    import socket
    requested=[]
    responses={
        ('origin.example','/robots.txt'):(404,{},b''),
        ('origin.example','/'):(302,{'Location':'https://destination.example/blocked'},b''),
        ('destination.example','/robots.txt'):(200,{},b'User-agent: *\nDisallow: /blocked')}
    class Response:
        def __init__(self,data):self.status,self.headers,self.body=data
        def getheader(self,name,default=None):return self.headers.get(name,default)
        def read1(self,n):out=self.body[:n];self.body=self.body[n:];return out
    class Connection:
        def __init__(self,host,address):self.host=host
        def request(self,method,path,headers):self.path=path;requested.append((self.host,path))
        def getresponse(self):return Response(responses[(self.host,self.path)])
        def close(self):pass
    def resolver(host,*args,**kwargs):return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1' if host=='private.example' else '93.184.216.34',443))]
    monkeypatch.setattr(module,'validated_host',lambda url,allowed:validate(url,allowed,resolver=resolver))
    monkeypatch.setattr(module,'PinnedHTTPS',Connection)
    with pytest.raises(DomainError,match='Robots'):PublicWeb(tmp_path).page('https://origin.example/')
    assert ('destination.example','/blocked') not in requested
    responses[('origin.example','/')]=(302,{'Location':'https://private.example/'},b'')
    with pytest.raises(DomainError,match='private'):PublicWeb(tmp_path).page('https://origin.example/')
    assert not any(h=='private.example' for h,p in requested)

def test_provider_missing_count_is_unknown_and_errors_are_sanitized(service,monkeypatch):
    import httpx
    from app.prospecting import providers as module
    real=httpx.Client
    service.config.dataforseo_password='synthetic-secret-never-log'
    responses=[{'tasks':[{'status_code':20000,'cost':0.0006,'result':[{}]}]},
               {'tasks':[{'status_code':20000,'cost':0.0006,'result':[{'referring_main_domains':0}]}]}]
    def respond(request):return httpx.Response(200,json=responses.pop(0))
    monkeypatch.setattr(module.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(respond),**kw))
    p=Providers(service.config)
    with pytest.raises(DomainError,match='unknown') as err:p.call('summary',{})
    assert service.config.dataforseo_password not in str(err.value)
    value,cost=p.call('summary',{})
    assert value['referring_domains']==0 and cost==1

def test_case_sensitive_site_paths_and_private_filing_urls():
    from app.prospecting.taxonomy import clean_site
    assert clean_site('https://society.org/About/Index.html')=='https://society.org/About/Index.html'
    assert clean_site('society.org/About')=='https://society.org/About'
    assert not clean_site('https://127.0.0.1/private')

def test_ai_rebuild_import_keeps_existing_site_as_candidate(service):
    city=service.create_city(CityInput(name='Town',region='IL'),'test')
    report='Example Historical Society owns https://society.example/ according to https://city.example/clubs and needs review.'
    run=service.import_report(ManualReport(city_id=city['id'],category='historical_preservation',campaign='rebuild',title='Rebuild candidates',report=report,rights_acknowledged=True),'test')
    service.import_candidates(run['id'],CandidateBatch(candidates=[dict(name='Example Historical Society',category='historical_preservation',website_status='official_website_found',website_url='https://society.example/',evidence=[dict(url='https://city.example/clubs',note='Name and website recorded')])]))
    e=service.snapshot()['entities'][0]
    assert e['campaign']=='rebuild' and e['state']=='review' and e['website_status']=='unknown'

def test_daily_ceiling_shared_across_research_and_discovery(service):
    service.config.daily_research_limit=1
    r=hunt(service)
    with pytest.raises(DomainError) as err:
        service.create_research(ResearchInput(city_id=r['city_id'],category='historical_preservation',window='2026-11',rights_acknowledged=True),'test')
    assert err.value.status==429
