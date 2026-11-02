import hashlib,hmac,json,time
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from app.api import create_app
from app.config import Config
from app.models import ConversationInput
from app.auth import hash_password
from app.core import iso
from test_service import prepare

@pytest.fixture
def client(tmp_path):
 cfg=Config(mode='test',database_path=str(tmp_path/'api.sqlite3'),run_worker=False,seed_on_start=True)
 with TestClient(create_app(cfg)) as c:
  c.headers['x-csrf-token']=c.get('/api/session').json()['csrf']
  yield c

def test_dashboard_and_all_assets_load(client):
 assert client.get('/').status_code==200
 for path in ['styles.css','app.js','api.js','pages.js','dialogs.js','ui.js','favicon.svg']:
  assert client.get('/assets/'+path).status_code==200
 assert "script-src 'self'" in client.get('/').headers['content-security-policy']

def test_seed_state_and_no_credentials_leak(client):
 result=client.get('/api/state');assert result.status_code==200
 s=result.json();assert len(s['entities'])==23 and len(s['contacts'])==17 and not s['messages']
 for key in ['smtp_password','gemini_api_key','password_hash','app_secret']:assert key not in result.text

def test_mutation_requires_csrf(client):
 client.headers.pop('x-csrf-token')
 assert client.post('/api/cities',json={'name':'Tampa','region':'FL'}).status_code==403

def test_mutation_rejects_cross_origin(client):
 assert client.post('/api/cities',headers={'origin':'https://attacker.example'},json={'name':'Tampa','region':'FL'}).status_code==403

def test_city_roundtrip_and_unknown_fields_rejected(client):
 result=client.post('/api/cities',json={'name':'Tampa','region':'FL','timezone':'America/New_York'})
 assert result.status_code==200
 assert any(c['name']=='Tampa' for c in client.get('/api/state').json()['cities'])
 assert client.post('/api/cities',json={'name':'Tampa','region':'FL','ignore_approval':True}).status_code==422

def test_invalid_zone_rejected(client):
 assert client.post('/api/cities',json={'name':'Tampa','region':'FL','timezone':'Not/Real'}).status_code==400

def test_body_limit(client):
 assert client.post('/api/cities',content='a'*1_000_001,headers={'content-type':'application/json'}).status_code==413

def test_export_csv_and_workspace(client):
 response=client.get('/api/export/prospects.csv');assert response.status_code==200
 assert 'Citrus Center Kiwanis' in response.text
 assert 'attachment' in response.headers['content-disposition']
 assert client.get('/api/export/workspace.json').json()['settings']['paused'] is True

def message_fixture(client):
 s=client.app.state.service;c,e,k=prepare(s)
 cv=s.reserve(ConversationInput(entity_ids=[e['id']],contact_id=k['id'],client_id=c['id']),'test')
 m=s.create_draft(cv['id'],'test');return s,m

def test_get_unsubscribe_does_not_suppress_post_does(client):
 s,m=message_fixture(client);token=s.get_message(m['id'])['unsubscribe_token']
 assert client.get('/unsubscribe/'+token).status_code==200
 assert not s.snapshot()['suppressions']
 assert client.post('/unsubscribe/'+token,content='List-Unsubscribe=One-Click').status_code==200
 assert s.get_message(m['id'])['state']=='cancelled'

def test_eml_preview_never_sends(client):
 s,m=message_fixture(client)
 response=client.get('/api/messages/'+m['id']+'/preview.eml')
 assert response.status_code==200
 assert 'List-Unsubscribe-Post: List-Unsubscribe=One-Click' in response.text
 assert s.get_message(m['id'])['state']=='draft'

def test_signed_webhook_and_duplicate(client):
 s,m=message_fixture(client);s.config.webhook_secret='test-hook-key'
 body=json.dumps({'event_id':'hook-test-0001','message_id':m['id'],'event_type':'reply','body':'Please explain.'}).encode()
 stamp=str(int(time.time()));sig=hmac.new(b'test-hook-key',stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
 assert client.post('/webhooks/email',content=body).status_code==401
 response=client.post('/webhooks/email',content=body,headers={'x-civic-timestamp':stamp,'x-civic-signature':sig})
 assert response.status_code==200,response.text
 assert s.get_message(m['id'])['state']=='cancelled'
 response=client.post('/webhooks/email',content=body,headers={'x-civic-timestamp':stamp,'x-civic-signature':sig})
 assert response.json()['duplicate'] is True

def test_production_authentication_and_roles(tmp_path):
 cfg=Config(mode='production',base_url='https://civic.example.org',database_path=str(tmp_path/'prod.sqlite3'),run_worker=False,seed_on_start=False,app_secret='s'*48,admin_email='admin@example.org',admin_password='long-password-for-testing-only')
 with TestClient(create_app(cfg),base_url=cfg.base_url) as c:
  assert c.get('/api/state').status_code==401
  assert c.post('/api/login',json={'email':cfg.admin_email,'password':'wrong'}).status_code==401
  auth=c.post('/api/login',json={'email':cfg.admin_email,'password':cfg.admin_password})
  assert auth.status_code==200
  assert 'Secure' in auth.headers['set-cookie'] and 'HttpOnly' in auth.headers['set-cookie']
  c.headers['x-csrf-token']=auth.json()['csrf']
  assert c.get('/api/state').status_code==200
  with c.app.state.service.db.transaction() as tx:tx.execute("UPDATE users SET role='viewer' WHERE email=?",(cfg.admin_email,))
  assert c.post('/api/cities',json={'name':'Tampa','region':'FL'}).status_code==403
  with c.app.state.service.db.transaction() as tx:tx.execute("UPDATE users SET role='admin' WHERE email=?",(cfg.admin_email,))
  assert c.post('/api/logout',json={}).status_code==200
  assert c.get('/api/state').status_code==401

def test_local_mode_rejects_remote_host(tmp_path):
 cfg=Config(mode='local',database_path=str(tmp_path/'local.sqlite3'),run_worker=False)
 with TestClient(create_app(cfg),base_url='http://attacker.example') as c:
  assert c.get('/').status_code==403

def test_mcp_rejects_unauthenticated_call(client):
 assert client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/list'}).status_code==401
