import base64
import json
import secrets
import time
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import pyotp
import pytest
from fastapi.testclient import TestClient
from app.api import create_app
from app.auth import hash_password, verify_password, token_hash, SESSION_COOKIE
from app.config import Config
from app.core import DomainError
from app.db import Database
from app.vault import Vault, IntegrationStore, IntegrationInput
from app.service import Service


def key():return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


@pytest.fixture
def config(tmp_path):
    return Config(mode='production',base_url='https://stakeout.example.org',database_path=str(tmp_path/'security.sqlite3'),
                  app_secret=secrets.token_urlsafe(48),encryption_key=key(),setup_token=secrets.token_urlsafe(48),
                  admin_email='',admin_password='',run_worker=False,seed_on_start=False)


@pytest.fixture
def client(config):
    with TestClient(create_app(config),base_url=config.base_url) as client:yield client


def enroll(client,config,email='owner@example.org'):
    result=client.post('/api/setup/enrollment',json={'setup_token':config.setup_token,'email':email})
    assert result.status_code==200,result.text
    return result.json()


def claim(client,config):
    enrollment=enroll(client,config)
    payload={'setup_token':config.setup_token,'email':'owner@example.org','name':'Owner',
             'password':'unique passphrase with plenty of length','enrollment':enrollment['enrollment'],'code':pyotp.TOTP(enrollment['secret']).now()}
    result=client.post('/api/setup/bootstrap',json=payload)
    assert result.status_code==200,result.text
    client.headers['x-csrf-token']=result.json()['csrf']
    return result.json(),payload,enrollment


def test_first_run_is_locked_and_setup_requires_token(client,config):
    assert client.get('/health').status_code==200
    assert client.get('/api/setup/status').json()['needs_setup']
    assert client.get('/api/state').status_code==401
    assert client.get('/api/settings/integrations').status_code==401
    r=client.post('/api/setup/enrollment',json={'email':'owner@example.org','setup_token':'wrong'})
    assert r.status_code==403
    assert 'no-store' in r.headers['cache-control']
    assert 'frame-ancestors' in r.headers['content-security-policy']


def test_setup_mfa_single_use_and_secret_storage(client,config):
    result,payload,enrollment=claim(client,config)
    assert not client.get('/api/setup/status').json()['needs_setup']
    assert client.post('/api/setup/bootstrap',json=payload).status_code==409
    assert client.post('/api/setup/enrollment',json={'email':payload['email'],'setup_token':config.setup_token}).status_code==409
    with client.app.state.service.db.transaction(False) as tx:
        user=tx.one('SELECT * FROM users')
        mfa=tx.one('SELECT * FROM user_mfa')
        assert tx.setting('bootstrap_consumed') is True
    assert user['password_hash'].startswith('$argon2id$')
    assert payload['password'] not in json.dumps(user)
    assert enrollment['secret'] not in json.dumps(mfa)
    assert result['recovery_codes'][0] not in json.dumps(mfa)
    assert verify_password(payload['password'],user['password_hash'])
    assert not verify_password('wrong',user['password_hash'])


def test_setup_cannot_bypass_mfa_or_password_length(client,config):
    en=enroll(client,config)
    payload={'setup_token':config.setup_token,'email':'owner@example.org','name':'Owner','password':'short','enrollment':en['enrollment'],'code':'000000'}
    assert client.post('/api/setup/bootstrap',json=payload).status_code==422
    payload['password']='long and unique test passphrase'
    payload['code']='999999' if pyotp.TOTP(en['secret']).now()!='999999' else '888888'
    assert client.post('/api/setup/bootstrap',json=payload).status_code==400
    assert client.get('/api/setup/status').json()['needs_setup']


def test_concurrent_claim_only_creates_one_admin(client,config):
    en=enroll(client,config)
    body={'setup_token':config.setup_token,'email':'owner@example.org','name':'Owner','password':'long unique race test password',
          'enrollment':en['enrollment'],'code':pyotp.TOTP(en['secret']).now()}
    with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(lambda _:client.post('/api/setup/bootstrap',json=body).status_code,range(2)))
    assert sorted(codes)==[200,409]


def test_mfa_login_replay_and_recovery_codes(client,config,monkeypatch):
    result,payload,en=claim(client,config)
    client.post('/api/logout',json={})
    body={'email':payload['email'],'password':payload['password'],'code':payload['code']}
    assert client.post('/api/login',json=body).status_code==401  # enrolled counter was already consumed
    body['code']=result['recovery_codes'][0]
    r=client.post('/api/login',json=body)
    assert r.status_code==200
    cookie=r.headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie
    client.cookies.clear()
    assert client.post('/api/login',json=body).status_code==401
    future=time.time()+60
    monkeypatch.setattr('app.auth.time.time',lambda:future)
    body['code']=pyotp.TOTP(en['secret']).at(future)
    assert client.post('/api/login',json=body).status_code==200
    client.cookies.clear()
    assert client.post('/api/login',json=body).status_code==401


def test_credentials_encrypted_not_returned_or_exported_and_persist(client,config):
    claim(client,config)
    secret='SENSITIVE_TEST_CREDENTIAL_'+secrets.token_hex(12)
    r=client.put('/api/settings/integrations',json={'gemini_api_key':secret,'smtp_password':secret,'source_rights_approved':True})
    assert r.status_code==200,r.text
    assert r.json()['secrets_set']['gemini_api_key'] is True
    for path in ['/api/settings/integrations','/api/state','/api/export/workspace.json','/api/setup/checklist']:
        assert secret not in client.get(path).text
    with client.app.state.service.db.transaction(False) as tx:
        saved=tx.one('SELECT * FROM secret_store')
        assert secret not in json.dumps(saved)
        assert secret not in json.dumps(tx.all('SELECT * FROM audit_log'))
        assert tx.setting('paused') is True
    fresh=replace(config,gemini_api_key='',smtp_password='',source_rights_approved=False)
    store=IntegrationStore(Service(Database(fresh.database_path),fresh));store.load()
    assert fresh.gemini_api_key==secret and fresh.source_rights_approved
    client.put('/api/settings/integrations',json={'gemini_api_key':''})
    assert config.gemini_api_key==secret
    client.put('/api/settings/integrations',json={'clear_secrets':['gemini_api_key']})
    assert config.gemini_api_key==''


def test_vault_authenticated_ciphertext_key_and_purpose(config):
    vault=Vault(config);a=vault.encrypt('test','secret');b=vault.encrypt('test','secret')
    assert a!=b and vault.decrypt('test',a)=='secret'
    with pytest.raises(DomainError):vault.decrypt('different',a)
    raw=bytearray(base64.urlsafe_b64decode(a[3:]));raw[-1]^=1
    with pytest.raises(DomainError):vault.decrypt('test','v1.'+base64.urlsafe_b64encode(raw).decode())
    with pytest.raises(DomainError):Vault(replace(config,encryption_key=key())).decrypt('test',a)
    rotated=Vault(replace(config,encryption_key=key(),encryption_key_previous=config.encryption_key))
    assert rotated.decrypt('test',a)=='secret'


def test_missing_or_wrong_key_fails_closed(client,config):
    claim(client,config)
    with pytest.raises(ValueError):create_app(replace(config,encryption_key=''))
    with pytest.raises(DomainError):
        with TestClient(create_app(replace(config,encryption_key=key())),base_url=config.base_url):pass


def test_roles_csrf_and_sensitive_configuration(client,config):
    result,_,_=claim(client,config)
    assert client.put('/api/settings/integrations',json={'smtp_password':'secret'},headers={'x-csrf-token':'wrong'}).status_code==403
    assert client.put('/api/settings/integrations',json={'allow_live_send':True}).status_code==422
    with client.app.state.service.db.transaction() as tx:tx.execute("UPDATE users SET role='reviewer'")
    for path in ['/api/settings/integrations','/api/setup/checklist']:
        assert client.get(path).status_code==403
    assert client.put('/api/settings/integrations',json={}).status_code==403
    assert client.post('/api/messages/review/queue',json={}).status_code==403
    with client.app.state.service.db.transaction() as tx:tx.execute("UPDATE users SET role='viewer'")
    assert client.post('/api/logout',json={}).status_code==200
    assert client.get('/api/state').status_code==401


def test_cross_origin_setup_and_json_validation(client,config):
    body={'setup_token':config.setup_token,'email':'owner@example.org'}
    assert client.post('/api/setup/enrollment',json=body,headers={'origin':'https://evil.example'}).status_code==403
    assert client.post('/api/setup/enrollment',json=body,headers={'sec-fetch-site':'cross-site'}).status_code==403
    assert client.post('/api/setup/enrollment',content=json.dumps(body),headers={'content-type':'text/plain'}).status_code==415
    assert client.post('/api/setup/enrollment',content='{bad',headers={'content-type':'application/json'}).status_code==422
    assert config.setup_token not in client.get('/').text


def test_throttle_survives_restart_and_ignores_forwarded_ip(client,config):
    for n in range(8):
        assert client.post('/api/login',json={'email':'nobody@example.org','password':'wrong'},headers={'x-forwarded-for':f'192.0.2.{n}'}).status_code==401
    with TestClient(create_app(config),base_url=config.base_url) as again:
        r=again.post('/api/login',json={'email':'nobody@example.org','password':'wrong'})
        assert r.status_code==429 and 'no-store' in r.headers['cache-control']


def test_setup_completion_requires_identity_then_remains_paused(client,config):
    claim(client,config)
    assert client.post('/api/setup/complete',json={}).status_code==400
    assert client.put('/api/settings/profile',json={'agency_name':'Agency','sender_name':'Owner'}).status_code==200
    assert client.post('/api/setup/complete',json={}).status_code==200
    assert client.get('/api/setup/checklist').json()['complete']
    assert client.get('/api/state').json()['settings']['paused'] is True
    assert not config.allow_live_send


def test_password_change_revokes_existing_sessions(client,config):
    result,payload,en=claim(client,config)
    old_cookie=client.cookies.get(SESSION_COOKIE)
    r=client.post('/api/security/password',json={'password':payload['password'],'code':result['recovery_codes'][0],'new_password':'replacement unique passphrase for testing'})
    assert r.status_code==200,r.text
    assert client.app.state.auth.session(old_cookie) is None
    assert client.get('/api/state').status_code==200


def test_secrets_omitted_from_config_repr(config):
    assert config.encryption_key not in repr(config)
    assert config.app_secret not in repr(config)
    assert config.setup_token not in repr(config)


def test_railway_rejects_ephemeral_sqlite(config,monkeypatch):
    monkeypatch.setenv('RAILWAY_ENVIRONMENT_ID','test-environment')
    monkeypatch.delenv('RAILWAY_VOLUME_MOUNT_PATH',raising=False)
    with pytest.raises(ValueError,match='persistent volume'):config.validate()


@pytest.mark.parametrize('address',['127.0.0.1','10.0.0.1','169.254.169.254','::1','fc00::1','0.0.0.0'])
def test_mail_connections_reject_private_dns(address,monkeypatch):
    from app.network import public_socket
    monkeypatch.setattr('app.network.socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',(address,587))])
    with pytest.raises(DomainError):public_socket('smtp.example.org',587,10)


def test_mail_dns_is_pinned(monkeypatch):
    from app.network import public_socket
    monkeypatch.setattr('app.network.socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('8.8.8.8',587))])
    calls=[]
    monkeypatch.setattr('app.network.socket.create_connection',lambda address,timeout:calls.append(address) or 'socket')
    assert public_socket('smtp.example.org',587,10)=='socket'
    assert calls==[('8.8.8.8',587)]


def test_unexpected_errors_do_not_leak_or_log_secrets(client,config,monkeypatch,caplog):
    claim(client,config)
    def fail():raise RuntimeError('SENSITIVE_PROVIDER_PASSWORD')
    monkeypatch.setattr(client.app.state.service,'snapshot',fail)
    r=client.get('/api/state')
    assert r.status_code==500
    assert 'SENSITIVE_PROVIDER_PASSWORD' not in r.text+caplog.text
    assert 'content-security-policy' in r.headers


def test_production_rejects_direct_http_and_unverified_database_tls(config):
    with TestClient(create_app(config),base_url=config.base_url.replace('https:','http:')) as c:
        assert c.get('/').status_code==400
        assert c.get('/health').status_code==200
    with pytest.raises(ValueError,match='verify-full'):
        replace(config,database_url='postgresql://user:password@db.example.org/app').validate()


def test_credential_changes_require_recent_password_and_mfa(client,config):
    result,payload,_=claim(client,config)
    with client.app.state.service.db.transaction() as tx:tx.execute("UPDATE session_elevation SET expires_at='2000-01-01T00:00:00Z'")
    assert client.put('/api/settings/integrations',json={'smtp_host':'attacker.example.org'}).status_code==403
    assert client.get('/api/setup/checklist').json()['elevated'] is False
    r=client.post('/api/security/reauth',json={'password':payload['password'],'code':result['recovery_codes'][0]})
    assert r.status_code==200
    assert client.put('/api/settings/integrations',json={'gemini_api_key':'test-key'}).status_code==200


def test_rotation_reencrypts_vault_and_mfa(client,config,monkeypatch):
    from scripts import rotate_encryption_key
    claim(client,config)
    client.put('/api/settings/integrations',json={'gemini_api_key':'rotation-test-secret'})
    rotated=replace(config,encryption_key=key(),encryption_key_previous=config.encryption_key)
    monkeypatch.setattr(rotate_encryption_key,'Config',lambda:rotated)
    monkeypatch.setattr(rotate_encryption_key,'load_dotenv',lambda:None)
    rotate_encryption_key.main()
    rotated.encryption_key_previous=''
    store=IntegrationStore(Service(Database(rotated.database_path),rotated))
    store.load();store.verify_keys()
    assert rotated.gemini_api_key=='rotation-test-secret'
    with pytest.raises(DomainError):IntegrationStore(client.app.state.service).load()
