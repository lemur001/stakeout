"""Argon2id passwords, opaque sessions, one-time TOTP and durable throttling."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import secrets
import time
import threading
from contextlib import contextmanager
from datetime import timedelta
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from .core import DomainError, iso, utcnow, email_key, validate_email
from .service import uid
from .vault import Vault

SESSION_COOKIE='__Host-civic_session'
# Argon2id: 64 MiB, three iterations, one lane; exceeds OWASP's minimum.
PASSWORD_HASHER=PasswordHasher(time_cost=3,memory_cost=65536,parallelism=1)
HASH_SLOTS=threading.BoundedSemaphore(2)


@contextmanager
def hash_slot():
    if not HASH_SLOTS.acquire(blocking=False):raise DomainError('Authentication is busy. Try again shortly.',429)
    try:yield
    finally:HASH_SLOTS.release()


def hash_password(password: str) -> str:
    with hash_slot():return PASSWORD_HASHER.hash(password)


def verify_password(password: str,stored: str) -> bool:
    if len(password)>512:return False
    try:
        if stored.startswith('$argon2id$'):
            with hash_slot():return PASSWORD_HASHER.verify(stored,password)
        # Existing accounts are upgraded after a successful login.
        algorithm,salt,digest=stored.split('$')
        if algorithm!='scrypt':return False
        result=hashlib.scrypt(password.encode(),salt=base64.b64decode(salt),n=16384,r=8,p=1,dklen=32)
        return hmac.compare_digest(result,base64.b64decode(digest))
    except (ValueError,TypeError,VerificationError,InvalidHashError):return False


def token_hash(token: str) -> str:return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    def __init__(self,service):
        self.service,self.db,self.config=service,service.db,service.config
        self.vault=Vault(self.config)

    def rate_limit(self,identity: str,limit: int,window: int):
        """Commit attempts before checking credentials; failures cannot roll them back."""
        now=int(time.time());bucket=token_hash(identity)
        with self.db.transaction() as tx:
            tx.execute('DELETE FROM auth_limits WHERE reset_at<=?',(now,))
            row=tx.one('SELECT attempts,reset_at FROM auth_limits WHERE bucket=?',(bucket,))
            count=(row['attempts'] if row else 0)+1
            tx.execute('INSERT INTO auth_limits(bucket,attempts,reset_at) VALUES(?,?,?) ON CONFLICT(bucket) DO UPDATE SET attempts=excluded.attempts',
                       (bucket,count,row['reset_at'] if row else now+window))
        if count>limit:raise DomainError('Too many attempts. Try again later.',429)

    def needs_setup(self):
        if self.config.mode!='production':return False
        with self.db.transaction(False) as tx:
            return not tx.one('SELECT id FROM users LIMIT 1') and not tx.setting('bootstrap_consumed',False)

    def bootstrap(self):
        """Retain explicit environment provisioning for existing installations."""
        if self.config.mode!='production':return
        if self.config.admin_email:
            with self.db.transaction() as tx:
                if not tx.one('SELECT id FROM users LIMIT 1') and not tx.setting('bootstrap_consumed',False):
                    tx.execute('INSERT INTO users(id,email,name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',
                        (uid(),email_key(validate_email(self.config.admin_email)),'Administrator',hash_password(self.config.admin_password),'admin',iso()))
                    tx.set_setting('bootstrap_consumed',True)
                    self.service.audit(tx,'system','admin.created','users','Administrator provisioned from environment; enroll MFA in security settings.')
        if self.needs_setup() and len(self.config.setup_token)<32:
            raise ValueError('A new production workspace needs a random SETUP_TOKEN of at least 32 characters.')

    def check_setup_token(self,token: str):
        if not self.needs_setup():raise DomainError('Initial setup is closed.',409)
        if not self.config.setup_token or not hmac.compare_digest(token_hash(token),token_hash(self.config.setup_token)):
            raise DomainError('The setup token is incorrect.',403)

    def enrollment(self,purpose: str,email: str):
        secret=pyotp.random_base32()
        return {'secret':secret,'uri':pyotp.TOTP(secret).provisioning_uri(email,issuer_name='Stakeout Civic'),
                'enrollment':self.vault.encrypt(purpose,json.dumps({'secret':secret,'expires':int(time.time())+900,'email':email_key(email)}))}

    def open_enrollment(self,purpose: str,enrollment: str,email: str,code: str):
        try:
            data=json.loads(self.vault.decrypt(purpose,enrollment))
            if data['expires']<time.time() or data['email']!=email_key(email):raise ValueError()
            counter=self.totp_counter(data['secret'],code)
            if counter is None:raise ValueError()
            return data['secret'],counter
        except (DomainError,ValueError,KeyError):
            raise DomainError('Enrollment expired or the authenticator code is incorrect. Start again if needed.',400) from None

    @staticmethod
    def totp_counter(secret: str,code: str):
        if len(code)!=6 or not code.isascii() or not code.isdigit():return None
        totp=pyotp.TOTP(secret);current=int(time.time())//30
        for counter in (current,current-1,current+1):
            if hmac.compare_digest(totp.at(counter*30),code):return counter
        return None

    def save_mfa(self,tx,user_id: str,secret: str,counter: int):
        codes=[secrets.token_hex(16) for _ in range(8)]
        tx.execute('INSERT INTO user_mfa(user_id,ciphertext,last_counter,recovery_hashes) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET ciphertext=excluded.ciphertext,last_counter=excluded.last_counter,recovery_hashes=excluded.recovery_hashes',
                   (user_id,self.vault.encrypt('mfa:'+user_id,secret),counter,json.dumps([token_hash(code) for code in codes])))
        return codes

    def create_first_admin(self,data):
        self.check_setup_token(data.setup_token)
        secret,counter=self.open_enrollment('setup-enrollment',data.enrollment,data.email,data.code)
        password_hash=hash_password(data.password)
        with self.db.transaction() as tx:
            if tx.one('SELECT id FROM users LIMIT 1') or tx.setting('bootstrap_consumed',False):
                raise DomainError('Initial setup is already complete.',409)
            user={'id':uid(),'email':email_key(validate_email(data.email)),'name':data.name,'role':'admin'}
            tx.execute('INSERT INTO users(id,email,name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',
                       (user['id'],user['email'],user['name'],password_hash,user['role'],iso()))
            codes=self.save_mfa(tx,user['id'],secret,counter)
            tx.set_setting('bootstrap_consumed',True)
            tx.set_setting('setup_complete',False)
            self.service.audit(tx,user['email'],'setup.claimed',user['id'],'Administrator and MFA created. Setup token consumed.')
            result=self.issue_session(tx,user)
        return {**result,'recovery_codes':codes}

    def issue_session(self,tx,user):
        token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
        tx.execute('DELETE FROM sessions WHERE expires_at<?',(iso(),))
        tx.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES(?,?,?,?)',
                   (token_hash(token),user['id'],csrf,iso(utcnow()+timedelta(hours=12))))
        self.elevate(tx,token)
        return {'token':token,'csrf':csrf,'user':{k:user[k] for k in ('id','name','email','role')}}

    def elevate(self,tx,token):
        tx.execute('INSERT INTO session_elevation(token_hash,expires_at) VALUES(?,?) ON CONFLICT(token_hash) DO UPDATE SET expires_at=excluded.expires_at',
                   (token_hash(token),iso(utcnow()+timedelta(minutes=15))))

    def elevated(self,token):
        if self.config.mode!='production':return True
        if not token:return False
        with self.db.transaction(False) as tx:
            return bool(tx.one('SELECT token_hash FROM session_elevation WHERE token_hash=? AND expires_at>?',(token_hash(token),iso())))

    def verify_mfa(self,tx,user_id,code):
        row=tx.one('SELECT * FROM user_mfa WHERE user_id=?',(user_id,))
        if not row:return
        secret=self.vault.decrypt('mfa:'+user_id,row['ciphertext'])
        counter=self.totp_counter(secret,code)
        if counter is not None and counter>row['last_counter']:
            tx.execute('UPDATE user_mfa SET last_counter=? WHERE user_id=?',(counter,user_id));return
        hashes=json.loads(row['recovery_hashes']);candidate=token_hash(code.strip().lower())
        matched=next((item for item in hashes if hmac.compare_digest(item,candidate)),None)
        if matched:
            hashes.remove(matched)
            tx.execute('UPDATE user_mfa SET recovery_hashes=? WHERE user_id=?',(json.dumps(hashes),user_id))
            self.service.audit(tx,'authentication','mfa.recovery_used',user_id)
            return
        raise DomainError('Invalid sign-in details or an expired authenticator code.',401)

    def login(self,email: str,password: str,code: str='') -> dict:
        if len(password)>512:raise DomainError('Invalid sign-in details.',401)
        self.rate_limit('login-account:'+email_key(email),8,600)
        with self.db.transaction(False) as tx:user=tx.one('SELECT * FROM users WHERE email=?',(email_key(email),))
        if not user:
            hash_password(password)
            raise DomainError('Invalid sign-in details or an expired authenticator code.',401)
        if not verify_password(password,user['password_hash']):
            raise DomainError('Invalid sign-in details or an expired authenticator code.',401)
        upgrade=not user['password_hash'].startswith('$argon2id$') or PASSWORD_HASHER.check_needs_rehash(user['password_hash'])
        upgraded=hash_password(password) if upgrade else None
        with self.db.transaction() as tx:
            current=tx.one('SELECT * FROM users WHERE id=?',(user['id'],))
            if not current or current['password_hash']!=user['password_hash']:raise DomainError('Sign in again.',401)
            self.verify_mfa(tx,user['id'],code)
            if upgraded:tx.execute('UPDATE users SET password_hash=? WHERE id=?',(upgraded,user['id']))
            result=self.issue_session(tx,current)
            self.service.audit(tx,user['email'],'user.login',user['id'])
        return result

    def session(self,token: str | None) -> dict | None:
        if self.config.mode in ('local','test'):
            csrf=hmac.new(self.config.app_secret.encode(),b'local-csrf',hashlib.sha256).hexdigest()
            return {'user':{'id':'local','name':'Local operator','email':'','role':'admin'},'csrf':csrf}
        if not token or len(token)>200:return None
        with self.db.transaction(False) as tx:
            row=tx.one('SELECT u.id,u.name,u.email,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?',(token_hash(token),iso()))
        if not row:return None
        return {'user':{k:row[k] for k in ('id','name','email','role')},'csrf':row['csrf']}

    def logout(self,token: str | None):
        if token:
            with self.db.transaction() as tx:tx.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash(token),))
