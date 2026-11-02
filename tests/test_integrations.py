import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta,datetime,timezone
import pytest
from app.core import DomainError,iso,utcnow
from app.models import *
from app.worker import Worker
from app.mail import new_reply_text,OPTOUT,build_email
from app.research import interaction_text,run_token,validate_run_token,SourceGateway
from test_service import service,prepare


def draft(s):
 c,e,k=prepare(s);cv=s.reserve(ConversationInput(entity_ids=[e['id']],client_id=c['id'],contact_id=k['id']),'test')
 m=s.create_draft(cv['id'],'test');return c,e,k,cv,m

def test_concurrent_reservation_has_one_winner(service):
 c,e,k=prepare(service);p=ConversationInput(entity_ids=[e['id']],client_id=c['id'],contact_id=k['id'])
 def attempt(_):
  try:service.reserve(p,'test');return True
  except DomainError:return False
 with ThreadPoolExecutor(max_workers=2) as pool:assert sum(pool.map(attempt,range(2)))==1

def test_shared_liaison_only_one_conversation(service):
 c,_,_=prepare(service);entities=[x for x in service.snapshot()['entities'] if any(k['route']=='liaison' for k in x['contacts'])];contact=entities[0]['contacts'][0]
 for e in entities:
  service.review_entity(e['id'],ReviewInput(website_status='no_site_found_after_checks',history_note='Synthetic scope review',activity_note='Synthetic activity review',evidence=[Evidence(url='https://example.org/source',note='Synthetic test evidence')],rights_confirmed=True,contact_id=contact['id'],verify_contact=True,contact_role_note='Current liaison role tested',contact_source_url='https://example.org/contact'),'test')
 cv=service.reserve(ConversationInput(entity_ids=[x['id'] for x in entities[:5]],client_id=c['id'],contact_id=contact['id']),'test')
 assert cv['kind']=='liaison'
 with pytest.raises(DomainError):service.reserve(ConversationInput(entity_ids=[entities[5]['id']],client_id=c['id'],contact_id=contact['id']),'test')
 assert len(service.snapshot()['conversations'])==1

def test_reply_cancels_queued_message(service):
 c,e,k,cv,m=draft(service);service.approve(m['id'],'test')
 with service.db.transaction() as tx:tx.execute("UPDATE messages SET state='queued',due_at=? WHERE id=?",(iso(),m['id']))
 service.ingest_event(IncomingEvent(event_id='reply-queued-0001',email=k['email'],event_type='reply',body='Tell me more'),'test')
 assert service.get_message(m['id'])['state']=='cancelled'

def test_existing_site_found_after_approval_cancels(service):
 c,e,k,cv,m=draft(service);service.approve(m['id'],'test')
 service.review_entity(e['id'],ReviewInput(website_status='official_website_found',website_url='https://example.org'),'test')
 assert service.get_message(m['id'])['state']=='cancelled'

def test_quoted_footer_not_misclassified_as_optout():
 text='Yes, please send the outline.\n\nOn Friday, Sender wrote:\nCommercial sponsorship proposal. Reply "no thanks" to stop.'
 assert not OPTOUT.search(new_reply_text(text))
 assert OPTOUT.search(new_reply_text('No thanks. Please remove me.'))

def test_mime_headers_stable_and_qualified_offer(service):
 c,e,k,cv,m=draft(service);msg=service.get_message(m['id']);mime=build_email(service,msg,msg['current_context'])
 assert str(mime['Message-ID'])==str(build_email(service,msg,msg['current_context'])['Message-ID'])
 assert mime['To']==k['email'] and 'List-Unsubscribe-Post' in mime
 assert 'Commercial sponsorship proposal' in mime.get_content()

def test_provider_timeout_is_not_retried(service,monkeypatch):
 c,e,k,cv,m=draft(service);service.approve(m['id'],'test');now=utcnow()
 # Only transport readiness and clock are isolated. All real database gates remain active.
 monkeypatch.setattr(service.config,'email_readiness',lambda:[])
 with service.db.transaction() as tx:
  tx.set_setting('paused',False);tx.set_setting('last_inbound_ok',iso())
  tx.execute("UPDATE messages SET state='queued',due_at=? WHERE id=?",(iso(now-timedelta(minutes=1)),m['id']))
 # Friday business hours in the actual test city's timezone.
 at=datetime(2026,10,2,16,0,tzinfo=timezone.utc)
 monkeypatch.setattr('app.worker.utcnow',lambda:at)
 class FailSMTP:
  calls=0
  def send(self,mime):self.calls+=1;raise TimeoutError('Ambiguous after DATA')
 provider=FailSMTP();worker=Worker(service,smtp=provider)
 worker.dispatch_one();worker.dispatch_one()
 assert service.get_message(m['id'])['state']=='delivery_unknown'
 assert provider.calls==1

def test_stale_sending_intent_recovery(service):
 c,e,k,cv,m=draft(service)
 with service.db.transaction() as tx:tx.execute("UPDATE messages SET state='sending',started_at=? WHERE id=?",(iso(utcnow()-timedelta(minutes=6)),m['id']))
 Worker(service).recover()
 assert service.get_message(m['id'])['state']=='delivery_unknown'

def test_project_launch_requires_ownership_and_approval(service):
 c,e,k,cv,m=draft(service)
 p=service.create_project(ProjectInput(conversation_id=cv['id'],entity_id=e['id'],authorized_by='Test Board Representative',agreement_note='Synthetic signed agreement for integration test only.',scope='Five public pages, owned by the organization.'),'test')
 with pytest.raises(DomainError):service.update_project(p['id'],ProjectUpdate(stage='live',public_url='https://example.org'),'test')
 service.update_project(p['id'],ProjectUpdate(stage='live',public_url='https://example.org',org_owns_domain=True,content_approved=True,approval_note='Synthetic authorization recorded by test board.'),'test')
 assert service.snapshot()['projects'][0]['stage']=='live'
 with pytest.raises(DomainError):service.add_directory_update(p['id'],{'directory_url':'https://example.org/directory','state':'confirmed'},'test')

def manual(s):
 s.seed_lakeland();city=s.snapshot()['cities'][0]
 text='Example Heritage Association has a reported public contact board@example.org. Evidence: https://example.org/history . Their website status is unknown. This is synthetic test material, not a verified prospect.'
 r=s.import_report(ManualReport(city_id=city['id'],category='historical_preservation',title='Synthetic permitted report',report=text,rights_acknowledged=True),'test');return r

def batch():
 return CandidateBatch(candidates=[Candidate(name='Example Heritage Association',category='historical_preservation',history_note='Historical scope as reported, not verified.',evidence=[Evidence(url='https://example.org/history',note='Synthetic evidence')],contacts=[ExtractedContact(email='board@example.org',source_url='https://example.org/history',role_note='Reported public contact')])])

def test_candidate_extraction_stays_unverified_and_idempotent(service):
 r=manual(service);service.import_candidates(r['id'],batch());service.import_candidates(r['id'],batch())
 e=next(x for x in service.snapshot()['entities'] if x['name']=='Example Heritage Association')
 assert e['state']=='review' and e['verified_at'] is None and not e['rights_confirmed']
 assert e['contacts'][0]['status']=='unverified'
 assert len(service.snapshot()['entities'])==24

def test_orphan_source_rejects_entire_import(service):
 r=manual(service);b=batch();b.candidates[0].evidence[0].url='https://other.example.org/not-in-report'
 with pytest.raises(DomainError):service.import_candidates(r['id'],b)
 assert len(service.snapshot()['entities'])==23

def test_research_same_city_category_window_reuses_job(service):
 service.seed_lakeland();city=service.snapshot()['cities'][0]['id'];data=ResearchInput(city_id=city,category='historical_preservation',window='2026-10',rights_acknowledged=True)
 a=service.create_research(data,'test');b=service.create_research(data,'test');assert a['id']==b['id']

def test_research_unknown_submit_cannot_retry_blindly(service):
 r=manual(service)
 with service.db.transaction() as tx:tx.execute("UPDATE research_runs SET state='submission_unknown' WHERE id=?",(r['id'],))
 with pytest.raises(DomainError):service.retry_research(r['id'],'test')

def test_research_worker_extracts_existing_report(service):
 r=manual(service);service.config.gemini_api_key='test-not-live'
 service.retry_research(r['id'],'test')
 class FakeGemini:
  def extract(self,text):assert 'Example Heritage' in text;return batch()
 w=Worker(service,gemini=FakeGemini());w.advance_research()
 assert service.snapshot()['research'][0]['state']=='completed'

def test_interaction_text_supported_shapes():
 assert interaction_text({'output_text':'report'})=='report'
 assert interaction_text({'steps':[{'content':[{'type':'text','text':'report'}]}]})=='report'

def test_source_gateway_no_send_tool(service):
 r=manual(service)
 with service.db.transaction() as tx:tx.execute("UPDATE research_runs SET state='researching' WHERE id=?",(r['id'],))
 service.config.source_rights_approved=True
 with pytest.raises(DomainError):SourceGateway(service).call(r['id'],'send_email',{})

def test_run_token_tampering_rejected(service):
 r=manual(service);token=run_token(service.config,r['id'])
 assert validate_run_token(service.config,token)==r['id']
 with pytest.raises(DomainError):validate_run_token(service.config,token+'x')

def test_gemini_request_contract_is_mcp_only(service):
 import httpx
 from app.research import GeminiProvider,ALLOWED_TOOLS
 service.seed_lakeland();service.config.gemini_api_key='test-key';service.config.base_url='https://civic.example.org'
 city=service.snapshot()['cities'][0]['id']
 r=service.create_research(ResearchInput(city_id=city,category='historical_preservation',window='2026-10',rights_acknowledged=True),'test')
 seen=[]
 def handle(request):
  seen.append(json.loads(request.content));return httpx.Response(200,json={'id':'interaction-test-123','status':'in_progress'})
 client=httpx.Client(transport=httpx.MockTransport(handle))
 result=GeminiProvider(service,client).submit(r)
 body=seen[0];assert result['id']=='interaction-test-123'
 assert body['background'] is True and body['tools'][0]['type']=='mcp_server'
 assert body['tools'][0]['allowed_tools']==ALLOWED_TOOLS
 assert 'google_search' not in json.dumps(body['tools'])
 assert 'Authorization' in body['tools'][0]['headers']

def test_research_worker_restart_resumes_provider_id(service,monkeypatch):
 service.seed_lakeland();service.config.gemini_api_key='test-key'
 monkeypatch.setattr(service.config,'research_readiness',lambda:[])
 city=service.snapshot()['cities'][0]['id']
 r=service.create_research(ResearchInput(city_id=city,category='historical_preservation',window='2026-10',rights_acknowledged=True),'test')
 class Fake:
  submissions=0;polls=[]
  def submit(self,r):self.submissions+=1;return {'id':'persisted-interaction-1'}
  def poll(self,id):self.polls.append(id);return {'status':'completed','output_text':'Synthetic report with no eligible candidates. Reviewed source https://example.org .'}
  def extract(self,text):return CandidateBatch(candidates=[],coverage_gaps=['Synthetic test result'])
 fake=Fake();Worker(service,gemini=fake).advance_research()
 with service.db.transaction() as tx:tx.execute('UPDATE research_runs SET next_run_at=? WHERE id=?',(iso(),r['id']))
 Worker(service,gemini=fake).advance_research();Worker(service,gemini=fake).advance_research()
 assert fake.submissions==1 and fake.polls==['persisted-interaction-1']
 assert service.snapshot()['research'][0]['state']=='completed'

def test_dropped_research_submission_requires_reconciliation(service,monkeypatch):
 service.seed_lakeland();service.config.gemini_api_key='test-key';monkeypatch.setattr(service.config,'research_readiness',lambda:[])
 city=service.snapshot()['cities'][0]['id'];r=service.create_research(ResearchInput(city_id=city,category='historical_preservation',window='2026-10',rights_acknowledged=True),'test')
 class Fail:
  calls=0
  def submit(self,r):self.calls+=1;raise TimeoutError()
 f=Fail();w=Worker(service,gemini=f);w.advance_research();w.advance_research()
 assert service.snapshot()['research'][0]['state']=='submission_unknown' and f.calls==1

def test_source_gateway_rejects_private_urls(service):
 from app.core import public_url
 for url in ['http://127.0.0.1/','https://169.254.169.254/','https://[::1]/','https://localhost/','https://user:password@example.org/']:
  with pytest.raises(DomainError):public_url(url,required=True)

def test_sponsor_terms_change_invalidates_approved_hash(service):
 c,e,k,cv,m=draft(service);service.approve(m['id'],'test')
 with service.db.transaction() as tx:tx.execute('UPDATE clients SET offer=? WHERE id=?',('A materially changed website offer.',c['id']))
 with service.db.transaction(False) as tx:
  with pytest.raises(DomainError):service.assert_send_eligibility(tx,service.get_message(m['id']),check_transport=False)
