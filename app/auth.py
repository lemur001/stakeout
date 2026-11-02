"""Named agency accounts, opaque sessions, and CSRF tokens; no external auth provider."""
from __future__ import annotations
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from .core import DomainError, iso, utcnow, email_key, validate_email
from .service import uid

SESSION_COOKIE='civic_session'

def hash_password(password: str) -> str:
    salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
    return 'scrypt$'+base64.b64encode(salt).decode()+'$'+base64.b64encode(digest).decode()

def verify_password(password: str,stored: str) -> bool:
    try:
        algorithm,salt,digest=stored.split('$')
        if algorithm!='scrypt':return False
        result=hashlib.scrypt(password.encode(),salt=base64.b64decode(salt),n=16384,r=8,p=1,dklen=32)
        return hmac.compare_digest(result,base64.b64decode(digest))
    except (ValueError,TypeError): return False

def token_hash(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()

class Auth:
    def __init__(self,service):self.service,self.db,self.config=service,service.db,service.config
    def bootstrap(self):
        if self.config.mode!='production':return
        with self.db.transaction() as tx:
            existing=tx.one('SELECT id FROM users WHERE email=?',(email_key(self.config.admin_email),))
            if not existing:
                tx.execute('INSERT INTO users(id,email,name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',
                    (uid(),email_key(validate_email(self.config.admin_email)),'Administrator',hash_password(self.config.admin_password),'admin',iso()))
                self.service.audit(tx,'system','admin.created','users','Initial administrator provisioned from environment.')
    def login(self,email: str,password: str) -> dict:
        if len(password)>512:raise DomainError('Invalid email or password.',401)
        with self.db.transaction() as tx:
            user=tx.one('SELECT * FROM users WHERE email=?',(email_key(email),))
            # A real expensive hash is evaluated even when the account is absent.
            if not user:
                hash_password(password)
                raise DomainError('Invalid email or password.',401)
            if not verify_password(password,user['password_hash']):raise DomainError('Invalid email or password.',401)
            token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
            tx.execute('DELETE FROM sessions WHERE expires_at<?',(iso(),))
            tx.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES(?,?,?,?)',
                (token_hash(token),user['id'],csrf,iso(utcnow()+timedelta(hours=12))))
            self.service.audit(tx,user['email'],'user.login',user['id'])
            return {'token':token,'csrf':csrf,'user':{'id':user['id'],'name':user['name'],'email':user['email'],'role':user['role']}}
    def session(self,token: str | None) -> dict | None:
        if self.config.mode in ('local','test'):
            csrf=hmac.new(self.config.app_secret.encode(),b'local-csrf',hashlib.sha256).hexdigest()
            return {'user':{'id':'local','name':'Local operator','email':'','role':'admin'},'csrf':csrf}
        if not token:return None
        with self.db.transaction(False) as tx:
            row=tx.one('SELECT u.id,u.name,u.email,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?',(token_hash(token),iso()))
            if not row:return None
            return {'user':{k:row[k] for k in ('id','name','email','role')},'csrf':row['csrf']}
    def logout(self,token: str | None):
        if token:
            with self.db.transaction() as tx:tx.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash(token),))
