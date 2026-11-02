"""Same-origin FastAPI application. Static dashboard and API deploy as one service."""
from __future__ import annotations
import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import sqlite3
import time
from collections import defaultdict,deque
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

log=logging.getLogger('civic.api')

class SizeLimit:
    """Buffer at most 1 MB before parsing; this also bounds chunked requests."""
    def __init__(self,app,max_bytes=1_000_000):self.app,self.max_bytes=app,max_bytes
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method'] not in ('POST','PUT','PATCH'):
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
    worker=None
    @asynccontextmanager
    async def lifespan(app):
        nonlocal worker
        db.migrate()
        if config.seed_on_start:service.seed_lakeland()
        auth.bootstrap()
        if config.run_worker:
            from .worker import Worker
            worker=Worker(service);worker.start()
        yield
        if worker:worker.stop()
    app=FastAPI(title='Stakeout Civic',version='1.0.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(SizeLimit)
    app.state.service,app.state.auth,app.state.config=service,auth,config
    login_attempts=defaultdict(deque)
    allowed_host=urlsplit(config.base_url).hostname

    @app.exception_handler(DomainError)
    async def domain_error(request,exc):return JSONResponse({'error':str(exc),'details':exc.details},status_code=exc.status)
    @app.exception_handler(RequestValidationError)
    async def invalid_input(request,exc):
        details=['.'.join(str(x) for x in e['loc'][1:])+': '+e['msg'] for e in exc.errors()]
        return JSONResponse({'error':'Check the form fields.','details':details},status_code=422)
    @app.exception_handler(sqlite3.IntegrityError)
    async def duplicate(request,exc):return JSONResponse({'error':'A conflicting record already exists. Refresh before trying again.'},status_code=409)

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
        if path.startswith('/api/') and path not in ('/api/session','/api/login'):
            session=await run_in_threadpool(auth.session,request.cookies.get(SESSION_COOKIE))
            if not session:return JSONResponse({'error':'Sign in to continue.'},status_code=401)
            request.state.session=session
            if request.method in ('POST','PUT','PATCH','DELETE'):
                if not hmac.compare_digest(request.headers.get('x-csrf-token',''),session['csrf']):
                    return JSONResponse({'error':'Session verification failed. Reload the page.'},status_code=403)
                origin=request.headers.get('origin')
                if origin and origin.rstrip('/')!=config.base_url:
                    return JSONResponse({'error':'Cross-origin requests are not allowed.'},status_code=403)
                role=session['user']['role']
                if role=='viewer':return JSONResponse({'error':'This account is read-only.'},status_code=403)
                review_action=('/review' in path or '/contacts' in path or path.endswith('/approve') or '/draft' in path or (request.method=='PATCH' and '/messages/' in path))
                if role!='admin' and not review_action:
                    return JSONResponse({'error':'An administrator must perform this action.'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if path.startswith('/api/') or path.startswith('/unsubscribe'):
            response.headers['Cache-Control']='no-store'
        if config.mode=='production':response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    def actor(request):return request.state.session['user'].get('email') or 'local-operator'

    @app.get('/health')
    def health():return {'status':'ok','application':'stakeout-civic'}
    @app.get('/api/session')
    def session(request: Request):return auth.session(request.cookies.get(SESSION_COOKIE)) or {'user':None,'csrf':None}
    @app.post('/api/login')
    async def login(request: Request):
        if request.headers.get('origin') and request.headers['origin'].rstrip('/')!=config.base_url:raise DomainError('Cross-origin login is not allowed.',403)
        peer=request.client.host if request.client else 'unknown'
        attempts=login_attempts[peer]
        while attempts and attempts[0]<time.monotonic()-600:attempts.popleft()
        if len(attempts)>=8:raise DomainError('Too many sign-in attempts. Try again later.',429)
        attempts.append(time.monotonic())
        data=await request.json()
        if not isinstance(data,dict):raise DomainError('Invalid sign-in request.')
        result=await run_in_threadpool(auth.login,str(data.get('email',''))[:300],str(data.get('password',''))[:513])
        response=JSONResponse({'user':result['user'],'csrf':result['csrf']})
        response.set_cookie(SESSION_COOKIE,result['token'],max_age=43200,httponly=True,secure=config.mode=='production',samesite='strict',path='/')
        return response
    @app.post('/api/logout')
    def logout(request: Request):
        auth.logout(request.cookies.get(SESSION_COOKIE))
        response=JSONResponse({'ok':True});response.delete_cookie(SESSION_COOKIE,path='/');return response
    @app.get('/api/state')
    def state():return service.snapshot()
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
