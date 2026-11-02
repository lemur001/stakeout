"""Transactional application workflows; neither research nor imported data can approve mail."""
from __future__ import annotations
import json
import secrets
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .config import Config, ROOT
from .core import (DomainError, iso, utcnow, parse_time, normalize_name, email_key,
    validate_email, qualification_blockers, approval_hash, canonical_json,
    research_key, add_business_days, public_url, PROJECT_STAGES)
from .db import Database, Tx
from .models import *

def uid() -> str: return str(uuid.uuid4())
def loadj(value: str | None, default=None):
    return json.loads(value) if value else (default if default is not None else [])

class Service:
    def __init__(self,db: Database,config: Config): self.db,self.config=db,config

    def audit(self,tx: Tx,actor: str,action: str,target: str,detail: str=''):
        tx.execute('INSERT INTO audit_log(id,actor,action,target,detail,created_at) VALUES(?,?,?,?,?,?)',
            (uid(),actor,action,target,detail[:2000],iso()))

    def required(self,tx: Tx,table: str,id: str) -> dict:
        # The table argument is from application code only, never a request parameter.
        if table not in {'cities','clients','entities','contacts','conversations','messages','projects','research_runs','source_registry'}:
            raise ValueError('Invalid internal table')
        row=tx.one(f'SELECT * FROM {table} WHERE id=?',(id,))
        if not row: raise DomainError('Record not found.',404)
        return row

    def seed_lakeland(self):
        source=json.loads((ROOT/'seed'/'lakeland.json').read_text(encoding='utf-8'))
        city_id='city_lakeland_fl'
        with self.db.transaction() as tx:
            if tx.setting('lakeland_seed_v1'): return
            tx.execute('INSERT INTO cities(id,name,region,country,timezone,canonical_key,created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(canonical_key) DO NOTHING',
                (city_id,'Lakeland','FL','US','America/New_York','us:fl:lakeland',iso()))
            city_id=tx.one('SELECT id FROM cities WHERE canonical_key=?',('us:fl:lakeland',))['id']
            for item in source['entities']:
                checks=item.get('independent_verification',[])
                website=next((c['source_url'] for c in checks if c.get('field')=='website_status'),'')
                excluded=item['website_status']=='official_website_found'
                line=item['report_source']['line_start']
                tx.execute('INSERT INTO entities(id,city_id,name,canonical_name,category,website_status,proposed_website_status,website_url,state,route,source_note,evidence_json,excluded_reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                    (item['id'],city_id,item['name_as_reported'],normalize_name(item['name_as_reported']),item['report_category'],item['website_status'],item['website_status'],website,'excluded' if excluded else 'review',item['initial_contact_route'],
                     f'Imported from Lakeland Entities Without Websites.md, line {line}. Claims and contacts are unverified. Import is not approval.',
                     json.dumps([{'url':c['source_url'],'note':'Prior seed observation (not rechecked by this application): '+c['observation'],'published_at':None} for c in checks]),
                     'Existing official website recorded in supplied seed; excluded from the no-website campaign.' if excluded else '',iso(),iso()))
            for c in source['contact_endpoints']:
                tx.execute('INSERT INTO contacts(id,email,email_key,role_note,created_at) VALUES(?,?,?,?,?) ON CONFLICT(email_key) DO NOTHING',
                    (c['id'],c['email_as_reported'],email_key(c['email_as_reported']),'Role claimed by supplied report; not verified.',iso()))
            for r in source['entity_contact_relationships']:
                role='liaison' if r['relationship']=='introduction_route' or 'liaison' in r['relationship'] else 'direct'
                tx.execute('INSERT INTO entity_contacts(entity_id,contact_id,route) VALUES(?,?,?) ON CONFLICT(entity_id,contact_id) DO NOTHING',(r['entity_id'],r['contact_id'],role))
            tx.set_setting('lakeland_seed_v1',True)
            self.audit(tx,'system','seed.imported',city_id,'23 candidates and 17 contact endpoints imported. No outreach enabled.')

    def _contacts(self,tx: Tx,entity_id: str) -> list[dict]:
        return tx.all('SELECT c.*,ec.route,(SELECT COUNT(*) FROM entity_contacts links WHERE links.contact_id=c.id) AS shared_count FROM contacts c JOIN entity_contacts ec ON c.id=ec.contact_id WHERE ec.entity_id=? ORDER BY c.email',(entity_id,))

    def _entities_for_conversation(self,tx: Tx,conversation_id: str) -> list[dict]:
        return tx.all('SELECT e.* FROM entities e JOIN reservations r ON r.entity_id=e.id WHERE r.conversation_id=? ORDER BY e.name',(conversation_id,))

    def _slots_used(self,tx: Tx,client_id: str) -> int:
        p=tx.one("SELECT COUNT(*) AS n FROM projects WHERE client_id=? AND stage!='handover'",(client_id,))['n']
        c=tx.one("SELECT COUNT(*) AS n FROM conversations c WHERE c.client_id=? AND c.state NOT IN ('closed','suppressed') AND NOT EXISTS(SELECT 1 FROM projects p WHERE p.conversation_id=c.id)",(client_id,))['n']
        return p+c

    def snapshot(self) -> dict:
        with self.db.transaction(False) as tx:
            cities=tx.all('SELECT * FROM cities ORDER BY name')
            clients=tx.all('SELECT * FROM clients ORDER BY name')
            for c in clients:
                c['city_ids']=loadj(c.pop('city_ids_json'))
                c['slots_used']=self._slots_used(tx,c['id'])
            entities=tx.all('SELECT * FROM entities ORDER BY name')
            for e in entities:
                e['contacts']=self._contacts(tx,e['id'])
                best=next((c for c in e['contacts'] if c['status']=='verified'),e['contacts'][0] if e['contacts'] else None)
                e['blockers']=qualification_blockers(e,best)
                e['evidence']=loadj(e.pop('evidence_json'))
                e['reservation']=tx.one('SELECT * FROM reservations WHERE entity_id=?',(e['id'],))
                latest=tx.one("SELECT t.result_json FROM discovery_targets t JOIN discovery_runs r ON r.id=t.run_id WHERE t.entity_id=? AND t.result_json!='{}' ORDER BY r.created_at DESC LIMIT 1",(e['id'],))
                e['discovery_scores']=loadj(latest['result_json'],{}).get('scores') if latest else None
            conversations=tx.all('SELECT * FROM conversations ORDER BY created_at DESC')
            for c in conversations:
                c['entity_ids']=[r['entity_id'] for r in tx.all('SELECT entity_id FROM reservations WHERE conversation_id=?',(c['id'],))]
            messages=tx.all('SELECT * FROM messages ORDER BY created_at DESC')
            for m in messages:
                # Raw approval snapshots are intentionally not needed by the browser.
                m.pop('snapshot_json',None)
                m.pop('unsubscribe_token',None)
            jobs=tx.all('SELECT * FROM research_runs ORDER BY created_at DESC LIMIT 200')
            for j in jobs:
                j['request']=loadj(j.pop('request_json'),{})
                j.pop('lease_owner',None)
                j.pop('lease_until',None)
            settings={'profile':tx.setting('profile'),'paused':tx.setting('paused',True),
                'email_readiness':self.config.email_readiness(),'research_readiness':self.config.research_readiness(),
                'mode':self.config.mode,'database':'PostgreSQL' if self.db.postgres else 'SQLite',
                'daily_send_limit':self.config.daily_send_limit,'daily_research_limit':self.config.daily_research_limit,
                'research_agent':self.config.research_agent,'extraction_model':self.config.extraction_model,
                'last_inbound_ok':tx.setting('last_inbound_ok'),'last_inbound_error':tx.setting('last_inbound_error',''),
                'worker_heartbeat':tx.setting('worker_heartbeat'),'worker_error':tx.setting('worker_error','')}
            return {'cities':cities,'clients':clients,'entities':entities,'contacts':tx.all('SELECT * FROM contacts ORDER BY email'),
                'conversations':conversations,'messages':messages,'research':jobs,
                'discovery':tx.all('SELECT id,city_id,campaign,state,total,completed,spent_cents,reserved_cents,error,created_at FROM discovery_runs ORDER BY created_at DESC LIMIT 100'),
                'projects':tx.all('SELECT * FROM projects ORDER BY created_at DESC'),
                'directory_updates':tx.all('SELECT * FROM directory_updates ORDER BY updated_at DESC'),
                'sources':tx.all('SELECT * FROM source_registry ORDER BY title'),
                'suppressions':tx.all('SELECT * FROM suppressions ORDER BY created_at DESC'),
                'events':tx.all('SELECT * FROM provider_events ORDER BY created_at DESC LIMIT 200'),
                'audit':tx.all('SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 100'), 'settings':settings}

    def create_city(self,data: CityInput,actor: str) -> dict:
        try: ZoneInfo(data.timezone)
        except ZoneInfoNotFoundError: raise DomainError('Use a valid IANA timezone, such as America/New_York.')
        key=':'.join((data.country.casefold(),data.region.casefold(),normalize_name(data.name)))
        with self.db.transaction() as tx:
            existing=tx.one('SELECT * FROM cities WHERE canonical_key=?',(key,))
            if existing: return existing
            id=uid()
            tx.execute('INSERT INTO cities(id,name,region,country,timezone,canonical_key,created_at) VALUES(?,?,?,?,?,?,?)',(id,data.name,data.region,data.country,data.timezone,key,iso()))
            self.audit(tx,actor,'city.created',id,data.name)
            return self.required(tx,'cities',id)

    def save_client(self,data: ClientInput,actor: str,id: str | None=None) -> dict:
        with self.db.transaction() as tx:
            for city in set(data.city_ids): self.required(tx,'cities',city)
            if id:
                self.required(tx,'clients',id)
                if data.max_slots < self._slots_used(tx,id): raise DomainError('The slot limit cannot be below already reserved capacity.')
            else: id=uid()
            tx.execute('INSERT INTO clients(id,name,website,city_ids_json,funded,budget_cents,max_slots,offer,renewal_terms,created_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,website=excluded.website,city_ids_json=excluded.city_ids_json,funded=excluded.funded,budget_cents=excluded.budget_cents,max_slots=excluded.max_slots,offer=excluded.offer,renewal_terms=excluded.renewal_terms',
                (id,data.name,data.website,json.dumps(sorted(set(data.city_ids))),int(data.funded),data.budget_cents,data.max_slots,data.offer,data.renewal_terms,iso()))
            self.audit(tx,actor,'client.saved',id,data.name)
            return self.required(tx,'clients',id)

    def save_profile(self,data: dict,actor: str):
        value=ProfileInput.model_validate(data).model_dump()
        with self.db.transaction() as tx:
            tx.set_setting('profile',value)
            self.audit(tx,actor,'sender_profile.saved','settings','Existing approvals must match the updated profile before sending.')
        return value

    def set_pause(self,paused: bool,actor: str):
        with self.db.transaction() as tx:
            tx.set_setting('paused',paused)
            self.audit(tx,actor,'outreach.paused' if paused else 'outreach.resumed','settings')
        return {'paused':paused}

    def add_contact(self,entity_id: str,data: ContactInput,actor: str) -> dict:
        with self.db.transaction() as tx:
            self.required(tx,'entities',entity_id)
            existing=tx.one('SELECT * FROM contacts WHERE email_key=?',(email_key(data.email),))
            id=existing['id'] if existing else uid()
            if not existing:
                tx.execute('INSERT INTO contacts(id,email,email_key,source_url,role_note,created_at) VALUES(?,?,?,?,?,?)',(id,data.email,email_key(data.email),data.source_url,data.role_note,iso()))
            tx.execute('INSERT INTO entity_contacts(entity_id,contact_id,route) VALUES(?,?,?) ON CONFLICT(entity_id,contact_id) DO NOTHING',(entity_id,id,data.route))
            self.audit(tx,actor,'contact.added',entity_id,'A public contact was recorded; review still required.')
            return self.required(tx,'contacts',id)

    def review_entity(self,id: str,data: ReviewInput,actor: str) -> dict:
        if data.website_status=='official_website_found' and not data.website_url:
            raise DomainError('Record the official website URL when classifying an existing site.')
        if data.verify_contact and (not data.contact_id or not data.contact_role_note or not data.contact_source_url):
            raise DomainError('Contact verification needs a selected contact, a role note and a public source URL.')
        if data.website_status in ('social_only','no_site_found_after_checks') and not data.evidence:
            raise DomainError('Document your website checks with evidence before using this status.')
        with self.db.transaction() as tx:
            entity=self.required(tx,'entities',id)
            if entity['state']=='suppressed': raise DomainError('This organization is suppressed. A review cannot remove an opt-out.')
            if data.verify_contact:
                link=tx.one('SELECT * FROM entity_contacts WHERE entity_id=? AND contact_id=?',(id,data.contact_id))
                if not link: raise DomainError('This contact is not linked to the organization.')
                contact=self.required(tx,'contacts',data.contact_id)
                if contact['status']=='suppressed': raise DomainError('This contact is suppressed.')
                tx.execute("UPDATE contacts SET status='verified',verified_at=?,role_note=?,source_url=? WHERE id=?",(iso(),data.contact_role_note,data.contact_source_url,data.contact_id))
            state='excluded' if data.website_status=='official_website_found' and data.campaign=='first_website' else 'review'
            if entity['state'] in ('reserved','contacted','replied','partnered') and state!='excluded': state=entity['state']
            reason='An official website already exists.' if state=='excluded' else ''
            tx.execute('UPDATE entities SET website_status=?,website_url=?,history_note=?,activity_note=?,evidence_json=?,rights_confirmed=?,verified_at=?,verified_by=?,state=?,excluded_reason=?,updated_at=?,campaign=? WHERE id=?',
                (data.website_status,data.website_url,data.history_note,data.activity_note,json.dumps([e.model_dump() for e in data.evidence]),int(data.rights_confirmed),iso(),actor,state,reason,iso(),data.campaign,id))
            if entity['campaign']!=data.campaign:
                tx.execute("UPDATE messages SET state='draft',approval_hash=NULL,approved_at=NULL,approved_by=NULL,error='Campaign changed; review the proposal again.' WHERE state IN ('approved','queued') AND conversation_id IN (SELECT conversation_id FROM reservations WHERE entity_id=?)",(id,))
            updated=self.required(tx,'entities',id)
            contacts=self._contacts(tx,id)
            best=next((c for c in contacts if c['status']=='verified'),contacts[0] if contacts else None)
            if state=='review' and not qualification_blockers(updated,best):
                tx.execute("UPDATE entities SET state='qualified' WHERE id=?",(id,))
            if state=='excluded':
                tx.execute("UPDATE messages SET state='cancelled',error='An existing website was found.',updated_at=? WHERE state IN ('draft','approved','queued') AND conversation_id IN (SELECT conversation_id FROM reservations WHERE entity_id=?)",(iso(),id))
            self.audit(tx,actor,'entity.reviewed',id,data.website_status)
            return self.required(tx,'entities',id)

    def exclude(self,id: str,reason: str,actor: str):
        if len(reason.strip())<5: raise DomainError('Record a reason for exclusion.')
        with self.db.transaction() as tx:
            self.required(tx,'entities',id)
            tx.execute("UPDATE entities SET state='excluded',excluded_reason=?,updated_at=? WHERE id=?",(reason.strip(),iso(),id))
            tx.execute("UPDATE messages SET state='cancelled',error='Organization excluded',updated_at=? WHERE state IN ('draft','approved','queued') AND conversation_id IN (SELECT conversation_id FROM reservations WHERE entity_id=?)",(iso(),id))
            self.audit(tx,actor,'entity.excluded',id,reason)
        return {'ok':True}

    def _suppressed(self,tx: Tx,contact_id: str,entity_ids: list[str]) -> bool:
        if tx.one('SELECT id FROM suppressions WHERE contact_id=?',(contact_id,)): return True
        return any(tx.one('SELECT id FROM suppressions WHERE entity_id=?',(id,)) for id in entity_ids)

    def _sponsor_gate(self,tx: Tx,client: dict,entities: list[dict],new_reservation: bool=False):
        reasons=[]
        if not client['funded'] or client['budget_cents']<=0: reasons.append('Sponsor funding has not been confirmed')
        if not client['renewal_terms'].strip(): reasons.append('Renewal and handover terms are missing')
        if not client['website']: reasons.append('The actual sponsor website is missing')
        city_ids=loadj(client['city_ids_json'])
        if any(e['city_id'] not in city_ids for e in entities): reasons.append('The sponsor is not assigned to this city')
        if new_reservation and self._slots_used(tx,client['id'])>=client['max_slots']: reasons.append('No funded website-delivery slot is available')
        if reasons: raise DomainError('Sponsor is not ready.',409,reasons)

    def reserve(self,data: ConversationInput,actor: str) -> dict:
        entity_ids=list(dict.fromkeys(data.entity_ids))
        with self.db.transaction() as tx:
            client=self.required(tx,'clients',data.client_id)
            contact=self.required(tx,'contacts',data.contact_id)
            entities=[self.required(tx,'entities',id) for id in entity_ids]
            if len({e['city_id'] for e in entities})!=1: raise DomainError('A conversation must concern one city.')
            if tx.one('SELECT id FROM conversations WHERE contact_id=?',(data.contact_id,)):
                raise DomainError('This email already has a program conversation. Use the existing conversation instead of pitching again.',409)
            routes=[]
            for e in entities:
                if tx.one('SELECT entity_id FROM reservations WHERE entity_id=?',(e['id'],)):
                    raise DomainError('An organization is already reserved to a sponsor.',409)
                link=tx.one('SELECT * FROM entity_contacts WHERE entity_id=? AND contact_id=?',(e['id'],data.contact_id))
                if not link: raise DomainError('The chosen contact is not linked to every selected organization.')
                routes.append(link['route'])
                reasons=qualification_blockers(e,contact)
                if reasons: raise DomainError(e['name']+' is not ready for outreach.',409,reasons)
            if self._suppressed(tx,data.contact_id,entity_ids): raise DomainError('The organization or contact is suppressed.',409)
            kind='liaison' if all(r=='liaison' for r in routes) else 'direct'
            if len(entity_ids)>1 and kind!='liaison': raise DomainError('Only a shared liaison may receive one grouped introduction.')
            self._sponsor_gate(tx,client,entities,True)
            id=uid()
            tx.execute('INSERT INTO conversations(id,client_id,contact_id,kind,created_at) VALUES(?,?,?,?,?)',(id,client['id'],contact['id'],kind,iso()))
            for e in entities:
                tx.execute('INSERT INTO reservations(entity_id,conversation_id,client_id) VALUES(?,?,?)',(e['id'],id,client['id']))
                tx.execute("UPDATE entities SET state='reserved',updated_at=? WHERE id=?",(iso(),e['id']))
            self.audit(tx,actor,'sponsor.reserved',id,client['name']+' · '+', '.join(e['name'] for e in entities))
            return self.required(tx,'conversations',id)

    def _context(self,tx: Tx,message: dict) -> dict:
        conv=self.required(tx,'conversations',message['conversation_id'])
        client=self.required(tx,'clients',conv['client_id'])
        contact=self.required(tx,'contacts',conv['contact_id'])
        entities=self._entities_for_conversation(tx,conv['id'])
        return {'profile':tx.setting('profile'),
            'client':{k:client[k] for k in ('id','name','website','offer','renewal_terms','funded','budget_cents','city_ids_json')},
            'recipient':contact['email'],'contact_id':contact['id'],'contact_verified_at':contact['verified_at'],
            'entities':[{'id':e['id'],'name':e['name'],'campaign':e['campaign'],'website_url':e['website_url'],'website_status':e['website_status'],'verified_at':e['verified_at'],'evidence_hash':approval_hash(e['evidence_json']),'rights_confirmed':e['rights_confirmed']} for e in entities],
            'kind':message['kind'],'conversation_kind':conv['kind'],
            'unsubscribe_url':self.config.base_url+'/unsubscribe/'+message['unsubscribe_token']}

    def compose(self,message: dict,context: dict) -> str:
        p=context['profile']
        return (message['body'].rstrip()+'\n\n'+p['sender_name']+'\n'+p['agency_name']+'\n'+p['postal_address']+
            '\n\nCommercial sponsorship proposal. Reply "no thanks" to stop outreach from this program.\nUnsubscribe: '+context['unsubscribe_url'])

    def create_draft(self,conversation_id: str,actor: str,kind: str='initial') -> dict:
        if kind not in ('initial','followup'): raise DomainError('Invalid message kind.')
        with self.db.transaction() as tx:
            conv=self.required(tx,'conversations',conversation_id)
            if conv['state'] in ('replied','suppressed','partnered','closed'): raise DomainError('This conversation is paused or closed; automated drafts are stopped.',409)
            existing=tx.one('SELECT * FROM messages WHERE conversation_id=? AND kind=?',(conversation_id,kind))
            if existing: return existing
            client=self.required(tx,'clients',conv['client_id'])
            entities=self._entities_for_conversation(tx,conversation_id)
            profile=tx.setting('profile')
            if not all(profile.get(k) for k in ('agency_name','sender_name','sender_email','postal_address')):
                raise DomainError('Complete the sender profile in Settings before creating outreach.',409)
            city=self.required(tx,'cities',entities[0]['city_id'])
            names=', '.join(e['name'] for e in entities)
            rebuild=all(e.get('campaign')=='rebuild' for e in entities)
            if kind=='followup':
                first=tx.one("SELECT * FROM messages WHERE conversation_id=? AND kind='initial'",(conversation_id,))
                if not first or first['state']!='sent' or not first['sent_at']:
                    raise DomainError('An initial message must be sent before a follow-up is drafted.')
                due=add_business_days(parse_time(first['sent_at']),7,city['timezone'])
                if utcnow()<due: raise DomainError('The seven-business-day follow-up date has not arrived.')
                subject=first['subject'] if first['subject'].lower().startswith('re:') else 'Re: '+first['subject']
                body=(f'Hello,\n\nFollowing up once on the privately funded website sponsorship with {client["name"]}. '+
                    (f'A focused update to the existing website could help {names} keep its public information useful.\n\n' if rebuild else f'A simple site could give {names} one place for its approved history, events and contact information.\n\n')+
                    'Would a short scope and ownership outline be useful? If this is not relevant, no reply is needed; this is our final follow-up.')
            elif conv['kind']=='liaison':
                subject='Website sponsorship introductions for local associations'
                body=(f'Hello,\n\nI’m {profile["sender_name"]} with {profile["agency_name"]}. We’re coordinating a privately funded community website sponsorship with {client["name"]} in {city["name"]}.\n\n'
                    f'Our reviewed public contact sources list your office as a contact route for {names}. Would you be comfortable forwarding a brief outline to the appropriate representatives? '
                    'We are not requesting a city endorsement or private member contact details.\n\n'
                    'The proposed scope, organization ownership, renewal terms and visible sponsor acknowledgement would be explained before any organization agrees. '
                    'This is an introduction request, not a commitment to fund every association listed.')
            else:
                subject=('A sponsored website refresh for ' if rebuild else 'A sponsored website for ')+entities[0]['name']
                subject=subject[:200]
                body=(f'Hello {entities[0]["name"]} team,\n\nI’m {profile["sender_name"]} with {profile["agency_name"]}. We’re working with {client["name"]} to fund community websites in {city["name"]}.\n\n'+
                    ('We would like to discuss a focused refresh of your existing website, keeping your organization in control of its domain and content.\n\n' if rebuild else 'A dedicated website could give your organization one place to share its approved history, meeting details and public contact information.\n\n')+
                    f'The funded offer is: {client["offer"]}\n\n'
                    'Your organization would own the domain and content. '+client['renewal_terms']+'\n\n'
                    f'In exchange, we’d ask for a small, visible sponsorship acknowledgement linking to {client["name"]}. '
                    'There is no requirement to buy another service.\n\nWould a short outline be useful for your board?')
            id=uid()
            tx.execute('INSERT INTO messages(id,conversation_id,kind,subject,body,unsubscribe_token,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                (id,conversation_id,kind,subject,body,secrets.token_urlsafe(32),iso(),iso()))
            self.audit(tx,actor,'message.drafted',id,kind)
            return self.required(tx,'messages',id)

    def get_message(self,id: str) -> dict:
        with self.db.transaction(False) as tx:
            m=self.required(tx,'messages',id)
            context=self._context(tx,m)
            m['recipient']=context['recipient']
            m['full_body']=self.compose(m,context)
            m['approval_matches']=bool(m['approval_hash']) and m['approval_hash']==approval_hash({'context':context,'subject':m['subject'],'body':m['body']})
            m['current_context']=context
            return m

    def edit_message(self,id: str,data: MessageEdit,actor: str):
        with self.db.transaction() as tx:
            m=self.required(tx,'messages',id)
            if m['state'] not in ('draft','approved','queued'): raise DomainError('This message cannot be edited in its current state.',409)
            tx.execute("UPDATE messages SET subject=?,body=?,state='draft',approval_hash=NULL,approved_by=NULL,approved_at=NULL,due_at=NULL,snapshot_json='{}',updated_at=? WHERE id=?",(data.subject,data.body,iso(),id))
            self.audit(tx,actor,'message.edited',id,'Approval invalidated; any queued send was removed.')
        return self.get_message(id)

    def _qualification_gate(self,tx: Tx,m: dict):
        conv=self.required(tx,'conversations',m['conversation_id'])
        if conv['state'] in ('replied','suppressed','partnered','closed'): raise DomainError('This conversation is stopped.',409)
        client=self.required(tx,'clients',conv['client_id'])
        contact=self.required(tx,'contacts',conv['contact_id'])
        entities=self._entities_for_conversation(tx,conv['id'])
        if not entities: raise DomainError('Sponsor reservation is missing.',409)
        if self._suppressed(tx,contact['id'],[e['id'] for e in entities]): raise DomainError('This contact or organization is suppressed.',409)
        for e in entities:
            reasons=qualification_blockers(e,contact)
            if reasons: raise DomainError(e['name']+' needs review.',409,reasons)
        self._sponsor_gate(tx,client,entities)
        profile=tx.setting('profile')
        if not all(profile.get(k) for k in ('agency_name','sender_name','sender_email','postal_address')):
            raise DomainError('Complete the sender identity and actual postal address in Settings.',409)
        validate_email(profile['sender_email'])
        if len(profile['postal_address'])<8: raise DomainError('A complete postal address is required.')
        if client['name'].casefold() not in m['body'].casefold() or 'sponsor' not in m['body'].casefold():
            raise DomainError('The message must identify the actual sponsor and the sponsorship nature of the offer.')
        if m['kind']=='followup':
            first=tx.one("SELECT * FROM messages WHERE conversation_id=? AND kind='initial'",(conv['id'],))
            city=self.required(tx,'cities',entities[0]['city_id'])
            if not first or first['state']!='sent' or utcnow()<add_business_days(parse_time(first['sent_at']),7,city['timezone']):
                raise DomainError('Follow-up is not yet due.')
        return conv,contact,entities

    def approve(self,id: str,actor: str):
        with self.db.transaction() as tx:
            m=self.required(tx,'messages',id)
            if m['state'] not in ('draft','approved'): raise DomainError('Only a draft can be approved.',409)
            self._qualification_gate(tx,m)
            context=self._context(tx,m)
            digest=approval_hash({'context':context,'subject':m['subject'],'body':m['body']})
            tx.execute("UPDATE messages SET state='approved',snapshot_json=?,approval_hash=?,approved_by=?,approved_at=?,updated_at=? WHERE id=?",(canonical_json(context),digest,actor,iso(),iso(),id))
            self.audit(tx,actor,'message.approved',id,'Exact recipient, sponsor, terms, content and required footer frozen.')
        return self.get_message(id)

    def assert_send_eligibility(self,tx: Tx,m: dict,check_transport: bool=True):
        if m['state'] not in ('approved','queued'): raise DomainError('Message is not approved for sending.',409)
        self._qualification_gate(tx,m)
        approved_at=parse_time(m['approved_at'])
        if not approved_at or utcnow()-approved_at>timedelta(hours=48): raise DomainError('Approval is older than 48 hours. Reapprove the message.',409)
        context=self._context(tx,m)
        digest=approval_hash({'context':context,'subject':m['subject'],'body':m['body']})
        if not m['approval_hash'] or not secrets.compare_digest(m['approval_hash'],digest):
            raise DomainError('Recipient, evidence, sender or offer changed after approval. Refresh and reapprove.',409)
        if check_transport:
            issues=self.config.email_readiness()
            if tx.setting('paused',True): issues.append('The global outreach pause is on')
            if self.config.smtp_from and email_key(context['profile']['sender_email'])!=email_key(self.config.smtp_from):
                issues.append('The sender profile does not match the authorized SMTP_FROM address')
            if issues: raise DomainError('Live sending is not ready.',409,issues)
        return context

    def queue_message(self,id: str,due_at: str | None,actor: str):
        with self.db.transaction() as tx:
            m=self.required(tx,'messages',id)
            self.assert_send_eligibility(tx,m)
            dt=parse_time(due_at) if due_at else utcnow()
            if not dt: raise DomainError('Invalid send date.')
            if dt>utcnow()+timedelta(hours=47): raise DomainError('Queue within the 48-hour approval window.')
            tx.execute("UPDATE messages SET state='queued',due_at=?,updated_at=? WHERE id=?",(iso(max(dt,utcnow())),iso(),id))
            self.audit(tx,actor,'message.queued',id)
        return self.get_message(id)

    def _suppress(self,tx: Tx,contact_id: str | None,entity_id: str | None,reason: str,actor: str):
        ids=[]
        if contact_id:
            self.required(tx,'contacts',contact_id)
            if not tx.one('SELECT id FROM suppressions WHERE contact_id=?',(contact_id,)):
                tx.execute('INSERT INTO suppressions(id,contact_id,reason,created_at) VALUES(?,?,?,?)',(uid(),contact_id,reason,iso()))
            tx.execute("UPDATE contacts SET status='suppressed' WHERE id=?",(contact_id,))
            ids.extend(r['entity_id'] for r in tx.all('SELECT entity_id FROM entity_contacts WHERE contact_id=?',(contact_id,)))
        if entity_id: ids.append(entity_id)
        for eid in set(ids):
            self.required(tx,'entities',eid)
            if not tx.one('SELECT id FROM suppressions WHERE entity_id=?',(eid,)):
                tx.execute('INSERT INTO suppressions(id,entity_id,reason,created_at) VALUES(?,?,?,?)',(uid(),eid,reason,iso()))
            tx.execute("UPDATE entities SET state='suppressed',updated_at=? WHERE id=?",(iso(),eid))
            reservation=tx.one('SELECT conversation_id FROM reservations WHERE entity_id=?',(eid,))
            if reservation:
                tx.execute("UPDATE conversations SET state='suppressed' WHERE id=?",(reservation['conversation_id'],))
                tx.execute("UPDATE messages SET state='cancelled',error='Suppressed before dispatch',updated_at=? WHERE conversation_id=? AND state IN ('draft','approved','queued')",(iso(),reservation['conversation_id']))
        self.audit(tx,actor,'outreach.suppressed',contact_id or entity_id or '',reason)

    def suppress(self,contact_id: str | None,entity_id: str | None,reason: str,actor: str):
        if not contact_id and not entity_id: raise DomainError('Choose a contact or organization.')
        if len(reason.strip())<3: raise DomainError('A suppression reason is required.')
        with self.db.transaction() as tx: self._suppress(tx,contact_id,entity_id,reason,actor)
        return {'ok':True}

    def unsubscribe(self,token: str):
        with self.db.transaction() as tx:
            m=tx.one('SELECT * FROM messages WHERE unsubscribe_token=?',(token,))
            if not m: raise DomainError('This unsubscribe link is not valid.',404)
            conv=self.required(tx,'conversations',m['conversation_id'])
            self._suppress(tx,conv['contact_id'],None,'Recipient used the unsubscribe link.','recipient')
        return {'ok':True}

    def ingest_event(self,event: IncomingEvent,source: str):
        with self.db.transaction() as tx:
            if tx.one('SELECT id FROM provider_events WHERE id=?',(event.event_id,)): return {'duplicate':True}
            message=self.required(tx,'messages',event.message_id) if event.message_id else None
            contact=None
            if message:
                conv=self.required(tx,'conversations',message['conversation_id'])
                contact=self.required(tx,'contacts',conv['contact_id'])
                if event.email and email_key(event.email)!=contact['email_key']:
                    raise DomainError('Inbound sender does not match the recorded recipient.',409)
            elif event.email:
                contact=tx.one('SELECT * FROM contacts WHERE email_key=?',(email_key(event.email),))
            if not contact: return {'ignored':True,'reason':'No matching contact'}
            tx.execute('INSERT INTO provider_events(id,message_id,contact_id,event_type,source,body,created_at) VALUES(?,?,?,?,?,?,?)',
                (event.event_id,event.message_id,contact['id'],event.event_type,source,event.body,iso()))
            if event.event_type in ('optout','bounce','complaint'):
                self._suppress(tx,contact['id'],None,event.event_type+': '+event.body[:400],source)
            elif event.event_type=='reply':
                conversations=tx.all('SELECT * FROM conversations WHERE contact_id=?',(contact['id'],))
                for conv in conversations:
                    if conv['state'] not in ('suppressed','partnered','closed'):
                        tx.execute("UPDATE conversations SET state='replied' WHERE id=?",(conv['id'],))
                        tx.execute("UPDATE entities SET state='replied',updated_at=? WHERE id IN(SELECT entity_id FROM reservations WHERE conversation_id=?) AND state NOT IN ('suppressed','excluded','partnered')",(iso(),conv['id']))
                    tx.execute("UPDATE messages SET state='cancelled',error='Reply received; automation paused',updated_at=? WHERE conversation_id=? AND state IN ('draft','approved','queued')",(iso(),conv['id']))
            self.audit(tx,source,'email.'+event.event_type,event.message_id or contact['id'])
            return {'ok':True}

    def close_conversation(self,id: str,actor: str):
        with self.db.transaction() as tx:
            self.required(tx,'conversations',id)
            tx.execute("UPDATE conversations SET state='closed' WHERE id=?",(id,))
            tx.execute("UPDATE messages SET state='cancelled',error='Conversation closed',updated_at=? WHERE conversation_id=? AND state IN ('draft','approved','queued')",(iso(),id))
            self.audit(tx,actor,'conversation.closed',id,'Contact and organization collision history retained.')
        return {'ok':True}

    def create_project(self,data: ProjectInput,actor: str):
        with self.db.transaction() as tx:
            conv=self.required(tx,'conversations',data.conversation_id)
            entity=self.required(tx,'entities',data.entity_id)
            if not tx.one('SELECT entity_id FROM reservations WHERE conversation_id=? AND entity_id=?',(conv['id'],entity['id'])):
                raise DomainError('Organization does not belong to this sponsor conversation.')
            if tx.one('SELECT id FROM projects WHERE entity_id=?',(entity['id'],)): raise DomainError('A project already exists for this organization.',409)
            if conv['state']=='suppressed' or entity['state']=='suppressed': raise DomainError('Suppressed organizations cannot enter an automated partnership flow.')
            client=self.required(tx,'clients',conv['client_id'])
            self._sponsor_gate(tx,client,[entity])
            already_project=tx.one('SELECT id FROM projects WHERE conversation_id=?',(conv['id'],))
            if already_project and self._slots_used(tx,client['id'])>=client['max_slots']:
                raise DomainError('No funded delivery slot remains for another organization.',409)
            id=uid()
            tx.execute('INSERT INTO projects(id,entity_id,client_id,conversation_id,authorized_by,agreement_note,scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (id,entity['id'],client['id'],conv['id'],data.authorized_by,data.agreement_note,data.scope,iso(),iso()))
            tx.execute("UPDATE conversations SET state='partnered' WHERE id=?",(conv['id'],))
            tx.execute("UPDATE entities SET state='partnered',updated_at=? WHERE id=?",(iso(),entity['id']))
            tx.execute("UPDATE messages SET state='cancelled',error='Partnership accepted',updated_at=? WHERE conversation_id=? AND state IN ('draft','approved','queued')",(iso(),conv['id']))
            self.audit(tx,actor,'partnership.recorded',id,'Authorized acceptance recorded; no site or domain was published.')
            return self.required(tx,'projects',id)

    def update_project(self,id: str,data: ProjectUpdate,actor: str):
        if data.stage in ('live','maintenance'):
            missing=[]
            if not data.public_url: missing.append('Published website URL')
            if not data.org_owns_domain: missing.append('Organization domain ownership confirmation')
            if not data.content_approved or len(data.approval_note)<10: missing.append('Board content approval with a supporting note')
            if missing: raise DomainError('Launch requirements are missing.',409,missing)
        with self.db.transaction() as tx:
            project=self.required(tx,'projects',id)
            launched_at=project['launched_at'] or (iso() if data.stage in ('live','maintenance') else None)
            tx.execute('UPDATE projects SET stage=?,domain=?,public_url=?,org_owns_domain=?,content_approved=?,approval_note=?,notes=?,renewal_date=?,launched_at=?,updated_at=? WHERE id=?',
                (data.stage,data.domain,data.public_url,int(data.org_owns_domain),int(data.content_approved),data.approval_note,data.notes,data.renewal_date,launched_at,iso(),id))
            self.audit(tx,actor,'project.updated',id,data.stage)
            return self.required(tx,'projects',id)

    def add_directory_update(self,project_id: str,data: dict,actor: str):
        url=public_url(str(data.get('directory_url','')),required=True)
        state=data.get('state','planned')
        if state not in ('planned','submitted','confirmed','declined'): raise DomainError('Invalid directory update state.')
        confirmed=public_url(str(data.get('confirmed_url','')))
        if state=='confirmed' and not confirmed: raise DomainError('A confirmed link needs its actual URL.')
        with self.db.transaction() as tx:
            self.required(tx,'projects',project_id)
            id=uid()
            tx.execute('INSERT INTO directory_updates(id,project_id,directory_url,state,confirmed_url,note,updated_at) VALUES(?,?,?,?,?,?,?)',(id,project_id,url,state,confirmed,str(data.get('note',''))[:2000],iso()))
            self.audit(tx,actor,'directory.'+state,project_id,url)
        return {'id':id}

    def add_source(self,data: SourceInput,actor: str):
        with self.db.transaction() as tx:
            if data.city_id: self.required(tx,'cities',data.city_id)
            id=uid()
            tx.execute('INSERT INTO source_registry(id,city_id,url,host,title,rights_note,fetch_allowed,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (id,data.city_id,data.url,urlsplit(data.url).hostname.lower(),data.title,data.rights_note,int(data.fetch_allowed),iso()))
            self.audit(tx,actor,'source.registered',id,data.title)
            return self.required(tx,'source_registry',id)

    def create_research(self,data: ResearchInput,actor: str):
        if not data.rights_acknowledged: raise DomainError('Confirm that the research sources permit the intended storage and use.')
        key=research_key(data.city_id,data.category,data.window,data.campaign)
        with self.db.transaction() as tx:
            self.required(tx,'cities',data.city_id)
            existing=tx.one('SELECT * FROM research_runs WHERE research_key=?',(key,))
            if existing: return existing
            count=tx.one('SELECT COUNT(*) AS n FROM research_runs WHERE created_at>=?',(iso(utcnow().replace(hour=0,minute=0,second=0,microsecond=0)),))['n']
            count+=tx.one('SELECT COUNT(*) AS n FROM discovery_runs WHERE created_at>=?',(iso(utcnow().replace(hour=0,minute=0,second=0,microsecond=0)),))['n']
            if count>=self.config.daily_research_limit: raise DomainError('The daily research-job ceiling has been reached.',429)
            readiness=self.config.research_readiness()
            id=uid()
            tx.execute('INSERT INTO research_runs(id,city_id,category,research_key,"window",state,request_json,error,max_tool_calls,next_run_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (id,data.city_id,data.category,key,data.window,'setup_required' if readiness else 'queued',json.dumps(data.model_dump()),'; '.join(readiness),data.max_tool_calls,iso(),iso(),iso()))
            self.audit(tx,actor,'research.created',id,data.category+' · '+data.window)
            return self.required(tx,'research_runs',id)

    def import_report(self,data: ManualReport,actor: str):
        if not data.rights_acknowledged: raise DomainError('Confirm reuse permission before importing report content.')
        key='manual:'+approval_hash({'city':data.city_id,'report':data.report,'campaign':data.campaign})
        with self.db.transaction() as tx:
            self.required(tx,'cities',data.city_id)
            existing=tx.one('SELECT * FROM research_runs WHERE research_key=?',(key,))
            if existing:return existing
            day=iso(utcnow().replace(hour=0,minute=0,second=0,microsecond=0))
            count=tx.one('SELECT COUNT(*) AS n FROM research_runs WHERE created_at>=?',(day,))['n']+tx.one('SELECT COUNT(*) AS n FROM discovery_runs WHERE created_at>=?',(day,))['n']
            if count>=self.config.daily_research_limit:raise DomainError('The daily research-job ceiling has been reached.',429)
            id=uid()
            ready=bool(self.config.gemini_api_key)
            tx.execute('INSERT INTO research_runs(id,city_id,category,research_key,"window",state,request_json,report,error,next_run_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (id,data.city_id,data.category,key,iso()[:7],'extracting' if ready else 'setup_required',json.dumps({'manual':True,'title':data.title,'campaign':data.campaign,'max_candidates':100,'rights_acknowledged':True}),data.report,'' if ready else 'Add GEMINI_API_KEY to extract this stored report.',iso(),iso(),iso()))
            self.audit(tx,actor,'report.imported',id,data.title)
            return self.required(tx,'research_runs',id)

    def retry_research(self,id: str,actor: str,provider_id: str | None=None):
        with self.db.transaction() as tx:
            run=self.required(tx,'research_runs',id)
            if run['state'] not in ('setup_required','failed','submission_unknown','polling_paused'):
                raise DomainError('This research job is already active or complete.',409)
            request=loadj(run['request_json'],{})
            if run['state']=='submission_unknown' and not provider_id:
                raise DomainError('A submission may already exist at Gemini. Supply its provider interaction ID after reconciling; do not resubmit blindly.',409)
            if provider_id:
                if not all(c.isalnum() or c in '_-.' for c in provider_id) or len(provider_id)>250: raise DomainError('Invalid provider interaction ID.')
                state='researching'
            elif run['report']:
                if not self.config.gemini_api_key: raise DomainError('GEMINI_API_KEY is not configured.',409)
                state='extracting'
            else:
                issues=self.config.research_readiness()
                if issues: raise DomainError('Research setup is incomplete.',409,issues)
                state='researching' if run['provider_id'] else 'queued'
            tx.execute('UPDATE research_runs SET state=?,provider_id=?,error=\'\',attempts=0,lease_owner=NULL,lease_until=NULL,next_run_at=?,updated_at=? WHERE id=?',
                (state,provider_id or run['provider_id'],iso(),iso(),id))
            self.audit(tx,actor,'research.resumed',id,state)
            return self.required(tx,'research_runs',id)

    def import_candidates(self,run_id: str,batch: CandidateBatch,actor: str='research-worker'):
        with self.db.transaction() as tx:
            run=self.required(tx,'research_runs',run_id)
            if run['state']=='completed': return {'imported':run['imported_count'],'duplicate':True}
            request=loadj(run['request_json'],{})
            if not request.get('rights_acknowledged'): raise DomainError('Source reuse was not approved for this run.')
            report=run['report']
            report_folded=report.casefold()
            count=0
            for c in batch.candidates[:request.get('max_candidates',100)]:
                # Reject orphan facts. This is provenance validation, NOT factual verification.
                if c.name.casefold() not in report_folded: raise DomainError('Extraction contains an organization name absent from the report.')
                for e in c.evidence:
                    if e.url not in report: raise DomainError('Extraction contains an orphan source URL.')
                for contact in c.contacts:
                    if contact.email.casefold() not in report_folded or contact.source_url not in report:
                        raise DomainError('Extraction contains an email or contact source absent from the report.')
                if c.website_url and c.website_url not in report: raise DomainError('Extracted website URL is absent from the report.')
                existing=tx.one('SELECT id FROM entities WHERE city_id=? AND canonical_name=?',(run['city_id'],normalize_name(c.name)))
                if existing:
                    # Reviewed records are never silently overwritten by model output.
                    continue
                id=uid()
                campaign=request.get('campaign','first_website')
                excluded=c.website_status=='official_website_found' and bool(c.website_url) and campaign=='first_website'
                tx.execute('INSERT INTO entities(id,city_id,name,canonical_name,category,website_status,proposed_website_status,website_url,state,history_note,activity_note,source_note,evidence_json,research_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (id,run['city_id'],c.name,normalize_name(c.name),c.category,'official_website_found' if excluded else 'unknown',c.website_status,c.website_url,'excluded' if excluded else 'review',c.history_note,c.activity_note,
                     'Gemini-extracted candidate. Claims, sources, contact roles and website findings require independent human review.',json.dumps([e.model_dump() for e in c.evidence]),run_id,iso(),iso()))
                tx.execute('UPDATE entities SET campaign=? WHERE id=?',(campaign,id))
                for contact in c.contacts:
                    old=tx.one('SELECT id FROM contacts WHERE email_key=?',(email_key(contact.email),))
                    cid=old['id'] if old else uid()
                    if not old: tx.execute('INSERT INTO contacts(id,email,email_key,source_url,role_note,created_at) VALUES(?,?,?,?,?,?)',(cid,contact.email,email_key(contact.email),contact.source_url,contact.role_note,iso()))
                    tx.execute('INSERT INTO entity_contacts(entity_id,contact_id,route) VALUES(?,?,?) ON CONFLICT(entity_id,contact_id) DO NOTHING',(id,cid,contact.route))
                count+=1
            tx.execute("UPDATE research_runs SET state='completed',imported_count=?,error=?,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=?",(count,'\n'.join(batch.coverage_gaps),iso(),run_id))
            self.audit(tx,actor,'research.imported',run_id,f'{count} new candidates. No qualification or sending approval granted.')
            return {'imported':count}
