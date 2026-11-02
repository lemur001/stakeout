"""Same-origin FastAPI application. Static dashboard and API deploy as one service."""
from __future__ import annotations
import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse,HTMLResponse,Response,FileResponse,PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from .config import Config,ROOT,load_dotenv
from .core import DomainError,clean_csv_cell,iso,utcnow,parse_time
from .db import Database
from .service import Service,loadj
from .auth import Auth,SESSION_COOKIE
from .models import *
from .research import SourceGateway,TOOL_DESCRIPTIONS,validate_run_token
from .mail import build_email
from .vault import IntegrationStore
from .setup import Credentials, register_setup, session_response
from .prospecting.models import HuntInput
from .prospecting.service import Discovery


class SecurityHeaders:
    """Also cover early authentication failures and request-size rejections."""
    def __init__(self,app,production=False):self.app,self.production=app,production
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        started=False
        async def secured(message):
            nonlocal started
            if message['type']=='http.response.start':
                started=True
                headers=list(message.get('headers',[]))
                headers.extend([
                    (b'x-content-type-options',b'nosniff'),(b'x-frame-options',b'DENY'),
                    (b'referrer-policy',b'no-referrer'),(b'cache-control',b'no-store'),
                    (b'permissions-policy',b'camera=(), microphone=(), geolocation=()'),
                    (b'content-security-policy',b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")])
                if self.production:headers.append((b'strict-transport-security',b'max-age=31536000'))
                message={**message,'headers':headers}
            await send(message)
        try:await self.app(scope,receive,secured)
        except Exception as exc:
            # Do not let provider exception strings reach Uvicorn's traceback log.
            log.error('Request failed: %s',type(exc).__name__)
            if not started:
                await JSONResponse({'error':'The request could not be completed.'},status_code=500)(scope,receive,secured)

log=logging.getLogger('civic.api')

class SizeLimit:
    """Buffer at most 1 MB before parsing; this also bounds chunked requests."""
    def __init__(self,app,max_bytes=1_000_000):self.app,self.max_bytes=app,max_bytes
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method'] not in ('POST','PUT','PATCH','DELETE'):
            return await self.app(scope,receive,send)
        chunks=[];total=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            chunk=message.get('body',b'');total+=len(chunk)
            if total>self.max_bytes:
                await JSONResponse({'error':'Request exceeds the 1 MB limit.'},status_code=413)(scope,receive,send);return
            chunks.append(chunk)
            if not message.get('more_body',False):break
        used=False
        async def replay():
            nonlocal used
            if not used:
                used=True
                return {'type':'http.request','body':b''.join(chunks),'more_body':False}
            return await receive()
        await self.app(scope,replay,send)

def create_app(config: Config | None=None) -> FastAPI:
    if config is None:load_dotenv();config=Config()
    config.validate()
    db=Database(config.database_path,config.database_url)
    service=Service(db,config);auth=Auth(service);gateway=SourceGateway(service)
    store=IntegrationStore(service)
    worker=None
    discovery_worker=None
    discovery=Discovery(service)
    @asynccontextmanager
    async def lifespan(app):
        nonlocal worker,discovery_worker
        db.migrate()
        store.load()
        store.verify_keys()
        if config.seed_on_start:service.seed_lakeland()
        auth.bootstrap()
        if config.run_worker:
            from .worker import Worker
            worker=Worker(service);worker.start()
            from .prospecting.worker import DiscoveryWorker
            discovery_worker=DiscoveryWorker(service);discovery_worker.start()
        yield
        if worker:worker.stop()
        if discovery_worker:discovery_worker.stop()
    app=FastAPI(title='Stakeout Civic',version='1.0.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(SizeLimit)
    app.state.service,app.state.auth,app.state.config=service,auth,config
    allowed_host=urlsplit(config.base_url).hostname

    @app.exception_handler(DomainError)
    async def domain_error(request,exc):return JSONResponse({'error':str(exc),'details':exc.details},status_code=exc.status)
    @app.exception_handler(RequestValidationError)
    async def invalid_input(request,exc):
        details=['.'.join(str(x) for x in e['loc'][1:])+': '+e['msg'] for e in exc.errors()]
        return JSONResponse({'error':'Check the form fields.','details':details},status_code=422)
    @app.exception_handler(sqlite3.IntegrityError)
    async def duplicate(request,exc):return JSONResponse({'error':'A conflicting record already exists. Refresh before trying again.'},status_code=409)
    @app.exception_handler(json.JSONDecodeError)
    async def invalid_json(request,exc):return JSONResponse({'error':'Enter valid JSON.'},status_code=400)
    @app.exception_handler(Exception)
    async def unexpected(request,exc):
        # Exception messages and tracebacks may contain provider credentials.
        log.error('Request failed: %s',type(exc).__name__)
        return JSONResponse({'error':'The request could not be completed.'},status_code=500,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @app.middleware('http')
    async def security(request: Request,call_next):
        path=request.url.path
        if path!='/health':
            host=request.url.hostname
            if config.mode=='local':
                peer=request.client.host if request.client else ''
                if host not in ('127.0.0.1','localhost','::1') or peer not in ('127.0.0.1','::1','testclient'):
                    return JSONResponse({'error':'Local mode only accepts loopback requests.'},status_code=403)
            elif config.mode=='production' and host!=allowed_host:
                return JSONResponse({'error':'Unrecognized host.'},status_code=400)
            if config.mode=='production' and request.url.scheme!='https':
                # Railway terminates TLS and overwrites this header. Never trust
                # client-supplied forwarded addresses for authentication limits.
                edge_https=bool(os.getenv('RAILWAY_ENVIRONMENT_ID')) and request.headers.get('x-forwarded-proto')=='https'
                if not edge_https:return JSONResponse({'error':'Use the configured HTTPS application address.'},status_code=400)
        public_api={'/api/session','/api/login','/api/setup/status','/api/setup/enrollment','/api/setup/bootstrap'}
        if path.startswith('/api/') and request.method in ('POST','PUT','PATCH','DELETE'):
            origin=request.headers.get('origin')
            if (origin and origin.rstrip('/')!=config.base_url) or request.headers.get('sec-fetch-site')=='cross-site':
                return JSONResponse({'error':'Cross-origin requests are not allowed.'},status_code=403)
            if request.headers.get('content-type','').split(';')[0].lower()!='application/json':
                return JSONResponse({'error':'Use application/json.'},status_code=415)
            try:
                if path=='/api/login':await run_in_threadpool(auth.rate_limit,'login-global',60,60)
                if path in ('/api/setup/enrollment','/api/setup/bootstrap'):
                    await run_in_threadpool(auth.rate_limit,'setup-global',20,600)
            except DomainError as exc:
                return JSONResponse({'error':str(exc)},status_code=exc.status)
        if path.startswith('/api/') and path not in public_api:
            session=await run_in_threadpool(auth.session,request.cookies.get(SESSION_COOKIE))
            if not session:return JSONResponse({'error':'Sign in to continue.'},status_code=401)
            request.state.session=session
            role=session['user']['role']
            if (path.startswith('/api/settings/integrations') or path.startswith('/api/setup/')) and role!='admin':
                return JSONResponse({'error':'Administrator access required.'},status_code=403)
            if request.method in ('POST','PUT','PATCH','DELETE'):
                if not hmac.compare_digest(request.headers.get('x-csrf-token',''),session['csrf']):
                    return JSONResponse({'error':'Session verification failed. Reload the page.'},status_code=403)
                if path=='/api/settings/integrations' and not await run_in_threadpool(auth.elevated,request.cookies.get(SESSION_COOKIE)):
                    return JSONResponse({'error':'Confirm your password and authenticator again. Reopen Setup & connections.'},status_code=403)
                origin=request.headers.get('origin')
                if origin and origin.rstrip('/')!=config.base_url:
                    return JSONResponse({'error':'Cross-origin requests are not allowed.'},status_code=403)
                own_security=path.startswith('/api/security/')
                if role=='viewer' and not own_security and path!='/api/logout':return JSONResponse({'error':'This account is read-only.'},status_code=403)
                review_action=(request.method=='POST' and re.fullmatch(r'/api/(entities/[^/]+/(review|contacts)|messages/[^/]+/approve|conversations/[^/]+/draft)',path)) or (request.method=='PATCH' and re.fullmatch(r'/api/messages/[^/]+',path)) or own_security or path=='/api/logout'
                if role!='admin' and not review_action:
                    return JSONResponse({'error':'An administrator must perform this action.'},status_code=403)
        return await call_next(request)

    app.add_middleware(SecurityHeaders,production=config.mode=='production')
    register_setup(app,auth,store)

    def actor(request):return request.state.session['user'].get('email') or 'local-operator'

    @app.get('/health')
    def health():
        with db.transaction(False) as tx:tx.one('SELECT version FROM schema_versions LIMIT 1')
        return {'status':'ok','application':'stakeout-civic'}
    @app.get('/api/session')
    def session(request: Request):return auth.session(request.cookies.get(SESSION_COOKIE)) or {'user':None,'csrf':None}
    @app.post('/api/login')
    def login(data: Credentials):
        return session_response(auth.login(data.email,data.password,data.code),config)
    @app.post('/api/logout')
    def logout(request: Request):
        auth.logout(request.cookies.get(SESSION_COOKIE))
        response=JSONResponse({'ok':True});response.delete_cookie(SESSION_COOKIE,path='/');return response
    @app.get('/api/state')
    def state():return service.snapshot()
    @app.get('/api/discovery')
    def hunts():return discovery.list()
    @app.get('/api/discovery-options')
    def hunt_options():
        from .prospecting.taxonomy import TYPE_LABEL
        from .prospecting.providers import ESTIMATE_CENTS
        return {'types':TYPE_LABEL,'estimates':ESTIMATE_CENTS}
    @app.post('/api/discovery')
    def new_hunt(data:HuntInput,request:Request):return discovery.create(data,actor(request))
    @app.get('/api/discovery/{id}')
    def hunt_detail(id:str):return discovery.detail(id)
    @app.get('/api/discovery/{id}/export.csv')
    def hunt_export(id:str):
        return Response(discovery.export_csv(id),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="hunt-{id}.csv"'})
    @app.post('/api/discovery/{id}/{action}')
    def hunt_action(id:str,action:str,request:Request):return discovery.control(id,action,actor(request))
    @app.get('/api/entities/{id}/discovery-evidence')
    def discovery_evidence(id:str):
        with db.transaction(False) as tx:
            service.required(tx,'entities',id)
            rows=tx.all('SELECT * FROM discovery_evidence WHERE entity_id=? ORDER BY observed_at DESC LIMIT 200',(id,))
        for row in rows:row['observation']=loadj(row.pop('observation_json'),{})
        return rows
    @app.post('/api/cities')
    def city(data: CityInput,request: Request):return service.create_city(data,actor(request))
    @app.post('/api/clients')
    def client(data: ClientInput,request: Request):return service.save_client(data,actor(request))
    @app.put('/api/clients/{id}')
    def update_client(id: str,data: ClientInput,request: Request):return service.save_client(data,actor(request),id)
    @app.put('/api/settings/profile')
    def profile(data: ProfileInput,request: Request):return service.save_profile(data.model_dump(),actor(request))
    @app.post('/api/settings/pause')
    async def pause(request: Request):
        data=await request.json()
        if type(data.get('paused')) is not bool:raise DomainError('paused must be true or false.')
        return service.set_pause(data['paused'],actor(request))
    @app.post('/api/entities/{id}/contacts')
    def add_contact(id: str,data: ContactInput,request: Request):return service.add_contact(id,data,actor(request))
    @app.post('/api/entities/{id}/review')
    def review(id: str,data: ReviewInput,request: Request):return service.review_entity(id,data,actor(request))
    @app.post('/api/entities/{id}/exclude')
    async def exclude(id: str,request: Request):
        data=await request.json();return service.exclude(id,str(data.get('reason','')),actor(request))
    @app.post('/api/conversations')
    def reserve(data: ConversationInput,request: Request):return service.reserve(data,actor(request))
    @app.post('/api/conversations/{id}/draft')
    def draft(id: str,request: Request):return service.create_draft(id,actor(request))
    @app.post('/api/conversations/{id}/followup')
    def followup(id: str,request: Request):return service.create_draft(id,actor(request),'followup')
    @app.post('/api/conversations/{id}/close')
    def close_conversation(id: str,request: Request):return service.close_conversation(id,actor(request))
    @app.get('/api/messages/{id}')
    def message(id: str):return service.get_message(id)
    @app.patch('/api/messages/{id}')
    def edit_message(id: str,data: MessageEdit,request: Request):return service.edit_message(id,data,actor(request))
    @app.post('/api/messages/{id}/approve')
    def approve(id: str,request: Request):return service.approve(id,actor(request))
    @app.post('/api/messages/{id}/queue')
    async def queue(id: str,request: Request):
        data=await request.json();return service.queue_message(id,data.get('due_at'),actor(request))
    @app.get('/api/messages/{id}/preview.eml')
    def eml(id: str):
        msg=service.get_message(id)
        mime=build_email(service,msg,msg['current_context'])
        return Response(mime.as_bytes(),media_type='message/rfc822',headers={'Content-Disposition':f'attachment; filename="civic-preview-{id[:8]}.eml"'})
    @app.post('/api/messages/{id}/reconcile')
    async def reconcile(id: str,request: Request):
        data=await request.json();outcome=data.get('outcome');note=str(data.get('note',''))
        if outcome not in ('sent','not_sent') or len(note)<20:raise DomainError('Record a verified delivery outcome and supporting reconciliation evidence.')
        with db.transaction() as tx:
            m=service.required(tx,'messages',id)
            if m['state']!='delivery_unknown':raise DomainError('Only an ambiguous delivery can be reconciled.',409)
            if outcome=='sent':
                tx.execute("UPDATE messages SET state='sent',sent_at=?,error=?,updated_at=? WHERE id=?",(m['started_at'] or iso(),'Manually reconciled: '+note,iso(),id))
                tx.execute("UPDATE conversations SET state='contacted' WHERE id=? AND state NOT IN ('replied','suppressed','partnered','closed')",(m['conversation_id'],))
            else:
                tx.execute("UPDATE messages SET state='draft',approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=?,updated_at=? WHERE id=?",('Verified not sent: '+note,iso(),id))
            service.audit(tx,actor(request),'delivery.reconciled',id,outcome+': '+note)
        return service.get_message(id)
    @app.post('/api/events')
    def event(data: IncomingEvent,request: Request):return service.ingest_event(data,'manual:'+actor(request))
    @app.post('/api/suppressions')
    async def suppress(request: Request):
        data=await request.json()
        return service.suppress(data.get('contact_id'),data.get('entity_id'),str(data.get('reason','')),actor(request))
    @app.post('/api/projects')
    def create_project(data: ProjectInput,request: Request):return service.create_project(data,actor(request))
    @app.put('/api/projects/{id}')
    def update_project(id: str,data: ProjectUpdate,request: Request):return service.update_project(id,data,actor(request))
    @app.post('/api/projects/{id}/directories')
    async def directory(id: str,request: Request):return service.add_directory_update(id,await request.json(),actor(request))
    @app.get('/api/projects/{id}/brief.md')
    def project_brief(id: str):
        with db.transaction(False) as tx:
            p=service.required(tx,'projects',id);e=service.required(tx,'entities',p['entity_id']);c=service.required(tx,'clients',p['client_id'])
        brief=f'''# Website project: {e['name']}\n\nSponsor: {c['name']}\nStage: {p['stage']}\nAuthorized representative: {p['authorized_by']}\n\n## Agreement record\n{p['agreement_note']}\n\n## Scope\n{p['scope']}\n\n## Ownership and renewal\n{c['renewal_terms']}\nOrganization owns the domain and approved content. Confirm asset permissions and board approval before publishing.\n\n## Sponsor credit\nWebsite sponsored by {c['name']}. Use a visible branded acknowledgement and a link qualified with rel="sponsored" or rel="nofollow".\n\n## Notes\n{p['notes']}\n\n## Launch checks\nConfirm domain ownership, content authorization, mobile and keyboard usability, working contact details, hosting renewal and transfer instructions. No government endorsement or ranking promise.\n'''
        return PlainTextResponse(brief,headers={'Content-Disposition':f'attachment; filename="project-{id[:8]}-brief.md"'})
    @app.post('/api/sources')
    def source(data: SourceInput,request: Request):return service.add_source(data,actor(request))
    @app.post('/api/research')
    def research(data: ResearchInput,request: Request):return service.create_research(data,actor(request))
    @app.post('/api/research/import')
    def import_report(data: ManualReport,request: Request):return service.import_report(data,actor(request))
    @app.post('/api/research/{id}/retry')
    async def retry(id: str,request: Request):
        data=await request.json();return service.retry_research(id,actor(request),data.get('provider_id'))
    @app.get('/api/research/{id}/report.md')
    def report(id: str):
        with db.transaction(False) as tx:r=service.required(tx,'research_runs',id)
        return PlainTextResponse(r['report'] or 'No report has been returned yet.',headers={'Content-Disposition':f'attachment; filename="research-{id[:8]}.md"'})
    @app.get('/api/research/{id}/traces')
    def traces(id: str):
        with db.transaction(False) as tx:
            service.required(tx,'research_runs',id)
            return tx.all('SELECT tool,url,title,observation,created_at FROM source_traces WHERE run_id=? ORDER BY created_at',(id,))
    @app.post('/api/research/{id}/import-candidates')
    def import_candidates(id: str,data: CandidateBatch,request: Request):return service.import_candidates(id,data,'manual:'+actor(request))
    @app.get('/api/export/prospects.csv')
    def export_csv():
        state=service.snapshot();out=io.StringIO();writer=csv.writer(out)
        writer.writerow(['Organization','City','Category','Website status','Workflow','Contacts (unverified unless reviewed)','Reviewed at','Source note'])
        cities={c['id']:c['name']+', '+c['region'] for c in state['cities']}
        for e in state['entities']:
            writer.writerow([clean_csv_cell(v) for v in (e['name'],cities[e['city_id']],e['category'],e['website_status'],e['state'],'; '.join(c['email'] for c in e['contacts']),e['verified_at'],e['source_note'])])
        return Response('\ufeff'+out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="civic-prospects.csv"'})
    @app.get('/api/export/workspace.json')
    def export_workspace():return Response(json.dumps(service.snapshot(),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="civic-workspace-export.json"'})
    @app.post('/webhooks/email')
    async def email_hook(request: Request):
        raw=await request.body();stamp=request.headers.get('x-civic-timestamp','');signature=request.headers.get('x-civic-signature','')
        if not config.webhook_secret:raise DomainError('Webhook is not configured.',403)
        try:age=abs(time.time()-int(stamp))
        except ValueError:raise DomainError('Invalid webhook signature.',401)
        expected=hmac.new(config.webhook_secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        if age>300 or not hmac.compare_digest(expected,signature):raise DomainError('Invalid webhook signature.',401)
        event=IncomingEvent.model_validate_json(raw)
        return await run_in_threadpool(service.ingest_event,event,'signed-webhook')
    @app.get('/unsubscribe/{token}')
    def unsubscribe_form(token: str):
        if len(token)>100:raise DomainError('Invalid link.',404)
        # GET never suppresses: mail scanners commonly follow links automatically.
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stop sponsorship outreach</title><link rel="stylesheet" href="/assets/styles.css"><main class="public-card"><h1>Stop sponsorship outreach</h1><p>Confirm to stop messages from this community website sponsorship program.</p><form method="post"><button class="btn primary" type="submit">Unsubscribe</button></form></main></html>')
    @app.post('/unsubscribe/{token}')
    def unsubscribe(token: str):
        service.unsubscribe(token)
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Unsubscribed</title><link rel="stylesheet" href="/assets/styles.css"><main class="public-card"><h1>You are unsubscribed.</h1><p>No further outreach will be sent to this address from the program.</p></main></html>')
    @app.post('/mcp')
    async def mcp(request: Request):
        authorization=request.headers.get('authorization','')
        if not authorization.startswith('Bearer '):raise DomainError('Research authentication required.',401)
        run_id=validate_run_token(config,authorization[7:])
        data=await request.json()
        if not isinstance(data,dict) or data.get('jsonrpc')!='2.0':raise DomainError('Invalid JSON-RPC request.')
        method=data.get('method');id=data.get('id');params=data.get('params',{})
        if method=='notifications/initialized':return Response(status_code=202)
        if method=='initialize':
            requested=params.get('protocolVersion','2025-03-26')
            version=requested if requested in ('2025-03-26','2025-06-18','2025-11-25','2026-07-28') else '2025-03-26'
            result={'protocolVersion':version,'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'stakeout-civic-sources','version':'1.0.0'}}
        elif method=='ping':result={}
        elif method=='tools/list':result={'tools':TOOL_DESCRIPTIONS}
        elif method=='tools/call':
            try:
                output=await run_in_threadpool(gateway.call,run_id,str(params.get('name','')),params.get('arguments',{}))
                result={'content':[{'type':'text','text':json.dumps(output,ensure_ascii=False)}],'isError':False}
            except DomainError as exc:result={'content':[{'type':'text','text':str(exc)}],'isError':True}
            except Exception:result={'content':[{'type':'text','text':'Source retrieval failed. No private data or alternative unapproved source was accessed.'}],'isError':True}
        else:return JSONResponse({'jsonrpc':'2.0','id':id,'error':{'code':-32601,'message':'Method not supported'}})
        return JSONResponse({'jsonrpc':'2.0','id':id,'result':result})
    app.mount('/assets',StaticFiles(directory=ROOT/'web'/'assets'),name='assets')
    @app.get('/')
    def index():return FileResponse(ROOT/'web'/'index.html')
    return app
