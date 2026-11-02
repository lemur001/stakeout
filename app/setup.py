"""First-run and administrator-only configuration endpoints."""
import json
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .auth import SESSION_COOKIE, verify_password, hash_password
from .core import DomainError, validate_email, iso
from .vault import IntegrationInput


class Credentials(BaseModel):
    model_config=ConfigDict(extra='forbid')
    email: str=Field(max_length=320)
    password: str=Field(max_length=512,repr=False)
    code: str=Field(default='',max_length=64,repr=False)


class SetupEnrollment(BaseModel):
    model_config=ConfigDict(extra='forbid')
    setup_token: str=Field(max_length=256,repr=False)
    email: str=Field(max_length=320)
    @field_validator('email')
    @classmethod
    def address(cls,v):return validate_email(v)


class FirstAdmin(SetupEnrollment):
    name: str=Field(min_length=2,max_length=150)
    password: str=Field(min_length=16,max_length=512,repr=False)
    enrollment: str=Field(max_length=3000,repr=False)
    code: str=Field(min_length=6,max_length=6,repr=False)


class SecurityChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    password: str=Field(max_length=512,repr=False)
    code: str=Field(default='',max_length=64,repr=False)
    new_password: str=Field(default='',max_length=512,repr=False)
    enrollment: str=Field(default='',max_length=3000,repr=False)
    new_code: str=Field(default='',max_length=6,repr=False)


def session_response(result,config):
    result=dict(result);token=result.pop('token')
    response=JSONResponse(result)
    response.set_cookie(SESSION_COOKIE,token,max_age=43200,httponly=True,secure=config.mode=='production',samesite='strict',path='/')
    return response


def register_setup(app,auth,store):
    config,db,service=auth.config,auth.db,auth.service

    def reauthenticate(request,data):
        user_id=request.state.session['user']['id']
        if user_id=='local':raise DomainError('Account security is available in production mode.',409)
        auth.rate_limit('reauth:'+user_id,8,600)
        with db.transaction(False) as tx:user=tx.one('SELECT * FROM users WHERE id=?',(user_id,))
        if not user or not verify_password(data.password,user['password_hash']):raise DomainError('Invalid account credentials.',401)
        with db.transaction() as tx:
            current=tx.one('SELECT password_hash FROM users WHERE id=?',(user_id,))
            if not current or current['password_hash']!=user['password_hash']:raise DomainError('Sign in again.',401)
            auth.verify_mfa(tx,user_id,data.code)
        return user

    @app.get('/api/setup/status')
    def status():return {'needs_setup':auth.needs_setup()}

    @app.post('/api/setup/enrollment')
    def enrollment(data: SetupEnrollment):
        auth.check_setup_token(data.setup_token)
        return auth.enrollment('setup-enrollment',data.email)

    @app.post('/api/setup/bootstrap')
    def bootstrap(data: FirstAdmin):return session_response(auth.create_first_admin(data),config)

    @app.get('/api/settings/integrations')
    def integrations():return store.summary()

    @app.put('/api/settings/integrations')
    def save(data: IntegrationInput,request: Request):return store.save(data,request.state.session['user']['email'] or 'local-operator')

    @app.get('/api/setup/checklist')
    def checklist(request: Request):
        user_id=request.state.session['user']['id']
        with db.transaction(False) as tx:
            profile=tx.setting('profile',{})
            complete=tx.setting('setup_complete',False)
            mfa=bool(tx.one('SELECT user_id FROM user_mfa WHERE user_id=?',(user_id,)))
        return {'complete':complete,'production':config.mode=='production','mfa_enabled':mfa,'elevated':auth.elevated(request.cookies.get(SESSION_COOKIE)),'profile':profile,'integrations':store.summary(),
                'checks':{'https':config.base_url.startswith('https://'),'encrypted_storage':bool(config.encryption_key),
                          'mfa':mfa,'identity':bool(profile.get('agency_name') and profile.get('sender_name')),
                          'sending_disabled':not config.allow_live_send}}

    @app.post('/api/setup/complete')
    def complete(request: Request):
        with db.transaction() as tx:
            profile=tx.setting('profile',{})
            if not profile.get('agency_name') or not profile.get('sender_name'):
                raise DomainError('Save your agency name and sender name first.')
            if config.mode=='production' and not tx.one('SELECT user_id FROM user_mfa WHERE user_id=?',(request.state.session['user']['id'],)):
                raise DomainError('Enroll two-factor authentication before completing setup.')
            tx.set_setting('setup_complete',True)
            tx.set_setting('paused',True)
            service.audit(tx,request.state.session['user']['email'],'setup.completed','settings','Optional integrations may be configured later; outreach stays paused.')
        return {'ok':True}

    @app.post('/api/security/mfa/enrollment')
    def account_enrollment(data: SecurityChange,request: Request):
        user=reauthenticate(request,data)
        return auth.enrollment('mfa-enrollment:'+user['id'],user['email'])

    @app.post('/api/security/reauth')
    def reauth(data: SecurityChange,request: Request):
        reauthenticate(request,data)
        with db.transaction() as tx:auth.elevate(tx,request.cookies.get(SESSION_COOKIE))
        return {'ok':True}

    @app.post('/api/security/mfa/confirm')
    def account_confirm(data: SecurityChange,request: Request):
        user=reauthenticate(request,data)
        secret,counter=auth.open_enrollment('mfa-enrollment:'+user['id'],data.enrollment,user['email'],data.new_code)
        with db.transaction() as tx:
            if tx.one('SELECT password_hash FROM users WHERE id=?',(user['id'],))['password_hash']!=user['password_hash']:raise DomainError('Sign in again.',401)
            codes=auth.save_mfa(tx,user['id'],secret,counter)
            tx.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
            result=auth.issue_session(tx,user)
            service.audit(tx,user['email'],'mfa.enrolled',user['id'],'Previous sessions and recovery codes revoked.')
        return session_response({**result,'recovery_codes':codes},config)

    @app.post('/api/security/password')
    def password(data: SecurityChange,request: Request):
        if len(data.new_password)<16:raise DomainError('Use a password of at least 16 characters.')
        user=reauthenticate(request,data);password_hash=hash_password(data.new_password)
        with db.transaction() as tx:
            if tx.one('SELECT password_hash FROM users WHERE id=?',(user['id'],))['password_hash']!=user['password_hash']:raise DomainError('Sign in again.',401)
            tx.execute('UPDATE users SET password_hash=? WHERE id=?',(password_hash,user['id']))
            tx.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
            result=auth.issue_session(tx,user)
            service.audit(tx,user['email'],'password.changed',user['id'],'All previous sessions revoked.')
        return session_response(result,config)
