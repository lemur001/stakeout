import json
from datetime import datetime,timezone
from pathlib import Path
import pytest
from app.config import Config
from app.db import Database
from app.service import Service
from app.core import DomainError,iso
from app.models import CityInput,ClientInput,ReviewInput,Evidence,ConversationInput,MessageEdit,IncomingEvent,ProjectInput

@pytest.fixture
def service(tmp_path):
 cfg=Config(mode='test',database_path=str(tmp_path/'test.sqlite3'),run_worker=False,seed_on_start=False)
 db=Database(cfg.database_path);db.migrate()
 return Service(db,cfg)

def prepare(s):
 s.seed_lakeland()
 state=s.snapshot()
 city=state['cities'][0]
 client=s.save_client(ClientInput(name='Test Sponsor',website='https://example.org',city_ids=[city['id']],funded=True,budget_cents=100000,max_slots=20,renewal_terms='One year funded. Renewal pricing and transfer agreed separately.'),'test')
 s.save_profile(dict(agency_name='Test Agency',sender_name='Test Sender',sender_email='sender@example.org',postal_address='123 Test Street, Example, FL 12345'),'test')
 entity=next(e for e in state['entities'] if e['name']=='Camphor Heights Neighborhood Association')
 contact=entity['contacts'][0]
 s.review_entity(entity['id'],ReviewInput(website_status='no_site_found_after_checks',history_note='Reviewed historical scope',activity_note='Reviewed current public activity',evidence=[Evidence(url='https://example.org/review',note='Test-only source evidence')],rights_confirmed=True,contact_id=contact['id'],verify_contact=True,contact_role_note='Reviewed public organizational contact',contact_source_url='https://example.org/contact'),'test')
 return client,entity,contact

def test_seed_counts_and_idempotency(service):
 service.seed_lakeland();service.seed_lakeland();x=service.snapshot()
 assert len(x['entities'])==23 and len(x['contacts'])==17
 assert len(x['messages'])==0
 assert all(e['verified_at'] is None for e in x['entities'])

def test_existing_site_cannot_reserve(service):
 c,e,k=prepare(service)
 entity=next(x for x in service.snapshot()['entities'] if x['name']=='Citrus Center Kiwanis')
 with pytest.raises(DomainError):service.reserve(ConversationInput(entity_ids=[entity['id']],client_id=c['id'],contact_id=entity['contacts'][0]['id']),'test')

def test_reservation_duplicate_is_rejected(service):
 c,e,k=prepare(service)
 p=ConversationInput(entity_ids=[e['id']],client_id=c['id'],contact_id=k['id'])
 service.reserve(p,'test')
 with pytest.raises(DomainError):service.reserve(p,'test')

def test_edit_revokes_approval(service):
 c,e,k=prepare(service);cv=service.reserve(ConversationInput(entity_ids=[e['id']],client_id=c['id'],contact_id=k['id']),'test')
 m=service.create_draft(cv['id'],'test');service.approve(m['id'],'test')
 service.edit_message(m['id'],MessageEdit(subject=m['subject'],body=m['body']+'\nAdditional information.'),'test')
 m=service.get_message(m['id'])
 assert m['state']=='draft' and m['approval_hash'] is None

def test_optout_cancels_approved_message(service):
 c,e,k=prepare(service);cv=service.reserve(ConversationInput(entity_ids=[e['id']],client_id=c['id'],contact_id=k['id']),'test')
 m=service.create_draft(cv['id'],'test');service.approve(m['id'],'test')
 service.ingest_event(IncomingEvent(event_id='test-optout-1',message_id=m['id'],event_type='optout',body='No thanks'),'manual')
 assert service.get_message(m['id'])['state']=='cancelled'
 with pytest.raises(DomainError):service.approve(m['id'],'test')

def test_live_send_disabled_without_credentials(service):
 c,e,k=prepare(service);cv=service.reserve(ConversationInput(entity_ids=[e['id']],client_id=c['id'],contact_id=k['id']),'test')
 m=service.create_draft(cv['id'],'test');service.approve(m['id'],'test')
 with pytest.raises(DomainError):service.queue_message(m['id'],None,'test')

def test_provider_events_deduplicate(service):
 c,e,k=prepare(service)
 ev=IncomingEvent(event_id='same-event-id',email=k['email'],event_type='reply',body='Tell me more')
 service.ingest_event(ev,'test');service.ingest_event(ev,'test')
 assert len(service.snapshot()['events'])==1

def test_unfunded_sponsor_cannot_reserve(service):
 c,e,k=prepare(service)
 with service.db.transaction() as tx:tx.execute('UPDATE clients SET funded=0 WHERE id=?',(c['id'],))
 with pytest.raises(DomainError):service.reserve(ConversationInput(entity_ids=[e['id']],client_id=c['id'],contact_id=k['id']),'test')

def test_profile_change_blocks_old_approval(service):
 c,e,k=prepare(service);cv=service.reserve(ConversationInput(entity_ids=[e['id']],client_id=c['id'],contact_id=k['id']),'test')
 m=service.create_draft(cv['id'],'test');service.approve(m['id'],'test')
 service.save_profile(dict(agency_name='Changed',sender_name='Test',sender_email='sender@example.org',postal_address='123 Test St'),'test')
 with service.db.transaction(False) as tx:
  with pytest.raises(DomainError):service.assert_send_eligibility(tx,service.get_message(m['id']),check_transport=False)
