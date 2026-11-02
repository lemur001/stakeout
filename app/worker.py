"""Restart-safe research and email worker. Run in-process or as a separate service."""
from __future__ import annotations
import json
import logging
import threading
import time
from datetime import timedelta
from zoneinfo import ZoneInfo
from .core import DomainError,iso,utcnow,parse_time,add_business_days
from .research import GeminiProvider, interaction_text
from .mail import SMTPProvider,IMAPPoller,build_email
from .service import uid,loadj

log=logging.getLogger('civic.worker')

class Worker:
    def __init__(self,service,gemini=None,smtp=None,imap=None):
        self.service,self.db,self.config=service,service.db,service.config
        self.id=uid();self.stop_event=threading.Event();self.thread=None
        self.gemini=gemini or GeminiProvider(service)
        self.smtp=smtp or SMTPProvider(self.config)
        self.imap=imap or IMAPPoller(service)
        self.last_mail_poll=0
    def start(self):
        self.thread=threading.Thread(target=self.run,name='civic-worker',daemon=True);self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)
    def run(self):
        while not self.stop_event.is_set():
            try:self.tick()
            except Exception as exc:
                log.error('Worker iteration failed: %s',type(exc).__name__)
                with self.db.transaction() as tx:tx.set_setting('worker_error','Worker iteration failed: '+type(exc).__name__)
            self.stop_event.wait(10)
    def recover(self):
        with self.db.transaction() as tx:
            tx.execute("UPDATE research_runs SET state='submission_unknown',error='Submission was interrupted before a provider ID was recorded. Reconcile with Gemini before retrying.',lease_owner=NULL,lease_until=NULL,updated_at=? WHERE state='submitting' AND lease_until<? AND provider_id IS NULL",(iso(),iso()))
            tx.execute("UPDATE research_runs SET lease_owner=NULL,lease_until=NULL WHERE state IN ('researching','extracting') AND lease_until<?",(iso(),))
            tx.execute("UPDATE messages SET state='delivery_unknown',error='Sending was interrupted. Reconcile before attempting another delivery.',updated_at=? WHERE state='sending' AND started_at<?",(iso(),iso(utcnow()-timedelta(minutes=3))))
            tx.execute('DELETE FROM source_traces WHERE expires_at<?',(iso(),))
    def claim_research(self):
        with self.db.transaction() as tx:
            rows=tx.all("SELECT * FROM research_runs WHERE state IN ('queued','researching','extracting') AND next_run_at<=? AND (lease_until IS NULL OR lease_until<?) ORDER BY CASE WHEN state='queued' THEN 1 ELSE 0 END,created_at LIMIT 20",(iso(),iso()))
            active=tx.one("SELECT COUNT(*) AS n FROM research_runs WHERE state IN ('submitting','researching','extracting')")['n']
            for run in rows:
                if run['state']=='queued' and active>=self.config.max_research_concurrent:continue
                if run['state']=='queued':
                    issues=self.config.research_readiness()
                    if issues:
                        tx.execute("UPDATE research_runs SET state='setup_required',error=?,updated_at=? WHERE id=?",('; '.join(issues),iso(),run['id']));continue
                elif not self.config.gemini_api_key:
                    tx.execute("UPDATE research_runs SET state='setup_required',error='GEMINI_API_KEY is missing',updated_at=? WHERE id=?",(iso(),run['id']));continue
                tx.execute('UPDATE research_runs SET state=?,lease_owner=?,lease_until=?,updated_at=? WHERE id=?',
                    ('submitting' if run['state']=='queued' else run['state'],self.id,iso(utcnow()+timedelta(minutes=5)),iso(),run['id']))
                return run
        return None
    def advance_research(self):
        run=self.claim_research()
        if not run:return
        try:
            if run['state']=='queued':
                response=self.gemini.submit(run)
                provider_id=response.get('id')
                if not provider_id:raise DomainError('Gemini accepted a submission without returning its interaction ID.',502)
                with self.db.transaction() as tx:
                    tx.execute("UPDATE research_runs SET state='researching',provider_id=?,lease_owner=NULL,lease_until=NULL,next_run_at=?,error='',updated_at=? WHERE id=?",(provider_id,iso(utcnow()+timedelta(seconds=15)),iso(),run['id']))
                    self.service.audit(tx,'worker','research.submitted',run['id'],'Provider interaction ID saved for restart recovery.')
            elif run['state']=='researching':
                result=self.gemini.poll(run['provider_id'])
                status=result.get('status')
                if status=='completed':
                    report=interaction_text(result)
                    if not report:raise DomainError('Completed research contained no readable report.',502)
                    if len(report)>300000:raise DomainError('The report exceeded the configured ingestion limit.',502)
                    with self.db.transaction() as tx:
                        tx.execute("UPDATE research_runs SET state='extracting',report=?,attempts=0,lease_owner=NULL,lease_until=NULL,next_run_at=?,error='',updated_at=? WHERE id=?",(report,iso(),iso(),run['id']))
                elif status in ('failed','cancelled','canceled','incomplete'):
                    with self.db.transaction() as tx:
                        tx.execute("UPDATE research_runs SET state='failed',error=?,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=?",('Provider research ended with status '+status,iso(),run['id']))
                else:
                    with self.db.transaction() as tx:
                        tx.execute("UPDATE research_runs SET lease_owner=NULL,lease_until=NULL,next_run_at=?,attempts=0,updated_at=? WHERE id=?",(iso(utcnow()+timedelta(seconds=20)),iso(),run['id']))
            elif run['state']=='extracting':
                batch=self.gemini.extract(run['report'])
                self.service.import_candidates(run['id'],batch)
        except Exception as exc:
            with self.db.transaction() as tx:
                current=self.service.required(tx,'research_runs',run['id'])
                if current['state']=='completed':return
                attempts=current['attempts']+1
                if run['state']=='queued':state='submission_unknown'
                elif attempts>=5:state='polling_paused' if run['provider_id'] and not run['report'] else 'failed'
                else:state=run['state']
                message=str(exc) if isinstance(exc,DomainError) else 'Research provider or schema validation failed ('+type(exc).__name__+').'
                tx.execute('UPDATE research_runs SET state=?,attempts=?,error=?,lease_owner=NULL,lease_until=NULL,next_run_at=?,updated_at=? WHERE id=?',
                    (state,attempts,message[:1500],iso(utcnow()+timedelta(seconds=min(600,20*2**attempts))),iso(),run['id']))
                self.service.audit(tx,'worker','research.needs_attention',run['id'],state)
    def prepare_followups(self):
        with self.db.transaction(False) as tx:
            rows=tx.all("SELECT m.*,c.state AS conversation_state FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.kind='initial' AND m.state='sent' AND c.state='contacted' AND NOT EXISTS(SELECT 1 FROM messages f WHERE f.conversation_id=m.conversation_id AND f.kind='followup') LIMIT 100")
        for m in rows:
            try:self.service.create_draft(m['conversation_id'],'worker','followup')
            except DomainError:pass
    def dispatch_one(self):
        if self.config.email_readiness():return None
        with self.db.transaction() as tx:
            if tx.setting('paused',True):return None
            last=parse_time(tx.setting('last_inbound_ok'))
            if not last or utcnow()-last>timedelta(minutes=3) or tx.setting('last_inbound_error',''):
                return None
            # Include ambiguous/in-flight attempts in the ceiling, not only successes.
            attempts=tx.one("SELECT COUNT(*) AS n FROM messages WHERE started_at>=?",(iso(utcnow().replace(hour=0,minute=0,second=0,microsecond=0)),))['n']
            if attempts>=self.config.daily_send_limit:return None
            rows=tx.all("SELECT * FROM messages WHERE state='queued' AND due_at<=? ORDER BY due_at LIMIT 20",(iso(),))
            chosen=None
            for m in rows:
                try:
                    context=self.service.assert_send_eligibility(tx,m)
                    entities=self.service._entities_for_conversation(tx,m['conversation_id'])
                    city=self.service.required(tx,'cities',entities[0]['city_id'])
                    local=utcnow().astimezone(ZoneInfo(city['timezone']))
                    if local.weekday()>=5 or not 9<=local.hour<17:continue
                    reply=None
                    if m['kind']=='followup':
                        initial=tx.one("SELECT provider_id FROM messages WHERE conversation_id=? AND kind='initial'",(m['conversation_id'],))
                        reply=initial['provider_id'] if initial else None
                    mime=build_email(self.service,m,context,reply)
                    tx.execute("UPDATE messages SET state='sending',started_at=?,provider_id=?,updated_at=? WHERE id=?",(iso(),str(mime['Message-ID']),iso(),m['id']))
                    chosen=(m,mime)
                    break
                except DomainError as exc:
                    tx.execute("UPDATE messages SET state='draft',approval_hash=NULL,approved_by=NULL,approved_at=NULL,error=?,updated_at=? WHERE id=?",(str(exc),iso(),m['id']))
                    self.service.audit(tx,'worker','message.blocked',m['id'],str(exc))
        if not chosen:return None
        m,mime=chosen
        try:
            provider_id=self.smtp.send(mime)
            with self.db.transaction() as tx:
                tx.execute("UPDATE messages SET state='sent',sent_at=?,provider_id=?,error='',updated_at=? WHERE id=?",(iso(),provider_id,iso(),m['id']))
                tx.execute("UPDATE conversations SET state='contacted' WHERE id=? AND state NOT IN ('replied','suppressed','partnered','closed')",(m['conversation_id'],))
                tx.execute("UPDATE entities SET state='contacted',updated_at=? WHERE id IN(SELECT entity_id FROM reservations WHERE conversation_id=?) AND state NOT IN ('replied','suppressed','partnered','excluded')",(iso(),m['conversation_id']))
                self.service.audit(tx,'worker','message.sent',m['id'],'SMTP accepted the message; this is not proof of inbox delivery.')
            return m['id']
        except Exception as exc:
            with self.db.transaction() as tx:
                tx.execute("UPDATE messages SET state='delivery_unknown',error=?,updated_at=? WHERE id=?",('SMTP outcome needs reconciliation ('+type(exc).__name__+'). No automatic retry.',iso(),m['id']))
                self.service.audit(tx,'worker','message.delivery_unknown',m['id'])
            return None
    def tick(self):
        from .vault import IntegrationStore
        IntegrationStore(self.service).load()
        if self.config.mode=='production':
            with self.db.transaction(False) as tx:
                if not tx.setting('setup_complete',False):return
        self.recover()
        if self.imap.configured() and time.monotonic()-self.last_mail_poll>45:
            self.imap.poll();self.last_mail_poll=time.monotonic()
        self.advance_research()
        self.prepare_followups()
        self.dispatch_one()
        with self.db.transaction() as tx:
            tx.set_setting('worker_heartbeat',iso());tx.set_setting('worker_error','')
