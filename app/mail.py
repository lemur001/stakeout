"""SMTP delivery and IMAP inbound processing. No live send without all runtime gates.

SMTP acceptance is recorded as sent, not proof of inbox delivery. Ambiguous
failures are quarantined as delivery_unknown and are never automatically retried.
"""
from __future__ import annotations
import email
import hashlib
import imaplib
import re
import smtplib
import ssl
from datetime import timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, format_datetime, getaddresses
from .core import DomainError, email_key, iso, utcnow, parse_time
from .models import IncomingEvent
from .network import public_socket


class PublicSMTP(smtplib.SMTP):
    def _get_socket(self,host,port,timeout):return public_socket(host,port,timeout)


class PublicSMTPSSL(smtplib.SMTP_SSL):
    def _get_socket(self,host,port,timeout):
        sock=public_socket(host,port,timeout)
        try:return self.context.wrap_socket(sock,server_hostname=self._host)
        except Exception:
            sock.close();raise


class PublicIMAPSSL(imaplib.IMAP4_SSL):
    def _create_socket(self,timeout):
        sock=public_socket(self.host,self.port,timeout)
        try:return self.ssl_context.wrap_socket(sock,server_hostname=self.host)
        except Exception:
            sock.close();raise

OPTOUT=re.compile(r'\b(unsubscribe|remove me|stop (?:emailing|contacting|sending)|no thanks|not interested|do not (?:contact|email))\b',re.I)

def new_reply_text(text: str) -> str:
    """Exclude the quoted proposal so our own opt-out footer cannot trigger an opt-out."""
    lines=[]
    for line in text.splitlines():
        if re.match(r'^\s*(On .+wrote:|[-_]{2,}\s*Original Message|From:\s|Commercial sponsorship proposal\.)',line,re.I):break
        if not line.lstrip().startswith('>'):lines.append(line)
    return '\n'.join(lines).strip()[:12000]

def build_email(service,message: dict,context: dict,reply_to: str | None=None) -> EmailMessage:
    profile=context['profile']
    msg=EmailMessage(policy=policy.SMTP)
    msg['From']=formataddr((profile['sender_name'],profile['sender_email']))
    msg['To']=context['recipient']
    msg['Subject']=message['subject']
    msg['Date']=format_datetime(utcnow())
    msg['Message-ID']=f'<civic.{message["id"]}@{profile["sender_email"].split("@")[-1]}>'
    if reply_to:
        msg['In-Reply-To']=reply_to;msg['References']=reply_to
    msg['List-Unsubscribe']='<'+context['unsubscribe_url']+'>'
    msg['List-Unsubscribe-Post']='List-Unsubscribe=One-Click'
    msg.set_content(service.compose(message,context))
    return msg

class SMTPProvider:
    def __init__(self,config):self.config=config
    def send(self,msg: EmailMessage):
        cfg=self.config
        issues=cfg.email_readiness()
        if issues:raise DomainError('Live sending is disabled.',409,issues)
        cls=PublicSMTPSSL if cfg.smtp_ssl else PublicSMTP
        kwargs={'timeout':30}
        if cfg.smtp_ssl:kwargs['context']=ssl.create_default_context()
        with cls(cfg.smtp_host,cfg.smtp_port,**kwargs) as server:
            server.ehlo()
            if not cfg.smtp_ssl:
                server.starttls(context=ssl.create_default_context());server.ehlo()
            server.login(cfg.smtp_user,cfg.smtp_password)
            refused=server.send_message(msg,from_addr=cfg.smtp_from)
            if refused:raise RuntimeError('Recipient was refused by SMTP.')
        return str(msg['Message-ID'])

class IMAPPoller:
    def __init__(self,service):self.service,self.config=service,service.config
    def configured(self):return all((self.config.imap_host,self.config.imap_user,self.config.imap_password))
    def poll(self) -> bool:
        if not self.configured():return False
        cfg=self.config
        account=hashlib.sha256((cfg.imap_host+'|'+cfg.imap_user+'|'+cfg.imap_mailbox).encode()).hexdigest()[:20]
        key='imap_cursor_'+account
        client=None
        try:
            client=PublicIMAPSSL(cfg.imap_host,cfg.imap_port,ssl_context=ssl.create_default_context(),timeout=25)
            client.login(cfg.imap_user,cfg.imap_password)
            result,_=client.select(cfg.imap_mailbox,readonly=True)
            if result!='OK':raise RuntimeError('The configured IMAP mailbox could not be selected.')
            validity_data=client.response('UIDVALIDITY')[1]
            validity=(validity_data[0] or b'unknown').decode() if validity_data else 'unknown'
            with self.service.db.transaction(False) as tx:cursor=tx.setting(key,{'validity':'','uid':0})
            last=cursor['uid'] if cursor['validity']==validity else 0
            if last:
                status,data=client.uid('search',None,f'UID {last+1}:*')
            else:
                since=(utcnow()-timedelta(days=2)).strftime('%d-%b-%Y')
                status,data=client.uid('search',None,'SINCE',since)
            if status!='OK':raise RuntimeError('IMAP search failed.')
            ids=sorted(int(v) for v in (data[0] or b'').split() if int(v)>last)
            for number in ids[:200]:
                status,parts=client.uid('fetch',str(number),'(BODY.PEEK[HEADER])')
                if status!='OK':raise RuntimeError('IMAP header fetch failed.')
                header=b''.join(p[1] for p in parts if isinstance(p,tuple))
                status,parts=client.uid('fetch',str(number),'(BODY.PEEK[TEXT]<0.65536>)')
                if status!='OK':raise RuntimeError('IMAP body fetch failed.')
                body=b''.join(p[1] for p in parts if isinstance(p,tuple))
                parsed=BytesParser(policy=policy.default).parsebytes(header+body)
                senders=getaddresses(parsed.get_all('From',[]))
                sender=senders[0][1] if len(senders)==1 else None
                text=''
                for part in parsed.walk():
                    if part.get_content_type()=='text/plain' and part.get_content_disposition()!='attachment':
                        try:text+=part.get_content()+'\n'
                        except Exception:pass
                if not text and not parsed.is_multipart():
                    try:text=str(parsed.get_content())
                    except Exception:pass
                text=new_reply_text(text)
                matched=None
                references=' '.join(parsed.get_all('In-Reply-To',[])+parsed.get_all('References',[]))
                match=re.search(r'<civic\.([0-9a-f-]{36})@',references,re.I)
                if match:
                    with self.service.db.transaction(False) as tx:
                        matched=tx.one('SELECT m.id,c.email_key FROM messages m JOIN conversations v ON v.id=m.conversation_id JOIN contacts c ON c.id=v.contact_id WHERE m.id=?',(match.group(1),))
                event_type='optout' if OPTOUT.search(text) else 'reply'
                # Forwarded replies from a new board member pause the thread, but do not
                # automatically treat the new address as the organization's authority.
                target_email=sender
                if matched and sender and email_key(sender)!=matched['email_key']:
                    target_email=None;event_type='reply'
                if matched or sender:
                    try:
                        self.service.ingest_event(IncomingEvent(event_id=f'imap:{account}:{validity}:{number}',message_id=matched['id'] if matched else None,email=target_email,event_type=event_type,body=text),'imap')
                    except (ValueError,DomainError):
                        # Malformed/non-contact mail is not a sponsorship reply.
                        pass
                # Structured DSNs identify the original recipient separately from From.
                if parsed.get_content_type()=='multipart/report':
                    for part in parsed.walk():
                        if part.get_content_type()=='message/delivery-status':
                            for status_part in part.get_payload() if isinstance(part.get_payload(),list) else []:
                                if status_part.get('Action','').lower()=='failed':
                                    recipient=status_part.get('Final-Recipient','').split(';')[-1].strip()
                                    try:self.service.ingest_event(IncomingEvent(event_id=f'imap-dsn:{account}:{validity}:{number}:{recipient}',email=recipient,event_type='bounce',body='Delivery-status notification: permanent failure.'),'imap')
                                    except (ValueError,DomainError):pass
                with self.service.db.transaction() as tx:tx.set_setting(key,{'validity':validity,'uid':number})
            complete=len(ids)<=200
            with self.service.db.transaction() as tx:
                if complete:tx.set_setting('last_inbound_ok',iso())
                tx.set_setting('last_inbound_error','' if complete else 'Processing an inbound backlog. Sending is paused until caught up.')
            return complete
        except Exception as exc:
            with self.service.db.transaction() as tx:tx.set_setting('last_inbound_error','IMAP monitoring failed ('+type(exc).__name__+'). Sending remains blocked until it recovers.')
            return False
        finally:
            if client:
                try:client.logout()
                except Exception:pass
