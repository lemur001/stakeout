"""Environment-only secrets. None are returned through the browser API."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

def load_dotenv(path: Path = ROOT / '.env') -> None:
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            key,value=line.split('=',1)
            os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))

def flag(name: str, default: bool = False) -> bool:
    return os.getenv(name,str(default)).lower() in ('1','true','yes')

@dataclass
class Config:
    mode: str = field(default_factory=lambda:os.getenv('APP_MODE','local'))
    host: str = field(default_factory=lambda:os.getenv('HOST','127.0.0.1'))
    port: int = field(default_factory=lambda:int(os.getenv('PORT','8080')))
    base_url: str = field(default_factory=lambda:os.getenv('APP_URL','http://127.0.0.1:8080').rstrip('/'))
    database_url: str = field(default_factory=lambda:os.getenv('DATABASE_URL',''))
    database_path: str = field(default_factory=lambda:os.getenv('DATABASE_PATH',str(ROOT/'data'/'civic.sqlite3')))
    app_secret: str = field(default_factory=lambda:os.getenv('APP_SECRET','local-only-not-for-deployment'))
    admin_email: str = field(default_factory=lambda:os.getenv('ADMIN_EMAIL',''))
    admin_password: str = field(default_factory=lambda:os.getenv('ADMIN_PASSWORD',''))
    run_worker: bool = field(default_factory=lambda:flag('RUN_WORKER',True))
    seed_on_start: bool = field(default_factory=lambda:flag('SEED_LAKELAND',True))
    allow_live_send: bool = field(default_factory=lambda:flag('ALLOW_LIVE_SEND'))
    provider_approved: bool = field(default_factory=lambda:flag('OUTREACH_PROVIDER_APPROVED'))
    sender_auth_confirmed: bool = field(default_factory=lambda:flag('SENDER_AUTH_CONFIRMED'))
    gemini_api_key: str = field(default_factory=lambda:os.getenv('GEMINI_API_KEY',''))
    research_agent: str = field(default_factory=lambda:os.getenv('GEMINI_RESEARCH_AGENT','deep-research-preview-04-2026'))
    extraction_model: str = field(default_factory=lambda:os.getenv('GEMINI_EXTRACTION_MODEL','gemini-3.8-flash'))
    source_rights_approved: bool = field(default_factory=lambda:flag('SOURCE_RIGHTS_APPROVED'))
    brave_key: str = field(default_factory=lambda:os.getenv('BRAVE_SEARCH_API_KEY',''))
    brave_storage_rights: bool = field(default_factory=lambda:flag('BRAVE_STORAGE_RIGHTS_APPROVED'))
    smtp_host: str = field(default_factory=lambda:os.getenv('SMTP_HOST',''))
    smtp_port: int = field(default_factory=lambda:int(os.getenv('SMTP_PORT','587')))
    smtp_user: str = field(default_factory=lambda:os.getenv('SMTP_USER',''))
    smtp_password: str = field(default_factory=lambda:os.getenv('SMTP_PASSWORD',''))
    smtp_from: str = field(default_factory=lambda:os.getenv('SMTP_FROM',''))
    smtp_ssl: bool = field(default_factory=lambda:flag('SMTP_SSL'))
    imap_host: str = field(default_factory=lambda:os.getenv('IMAP_HOST',''))
    imap_port: int = field(default_factory=lambda:int(os.getenv('IMAP_PORT','993')))
    imap_user: str = field(default_factory=lambda:os.getenv('IMAP_USER',''))
    imap_password: str = field(default_factory=lambda:os.getenv('IMAP_PASSWORD',''))
    imap_mailbox: str = field(default_factory=lambda:os.getenv('IMAP_MAILBOX','INBOX'))
    webhook_secret: str = field(default_factory=lambda:os.getenv('INBOUND_WEBHOOK_SECRET',''))
    daily_send_limit: int = field(default_factory=lambda:int(os.getenv('DAILY_SEND_LIMIT','5')))
    daily_research_limit: int = field(default_factory=lambda:int(os.getenv('DAILY_RESEARCH_LIMIT','5')))
    max_research_concurrent: int = field(default_factory=lambda:int(os.getenv('MAX_RESEARCH_CONCURRENT','1')))

    def validate(self) -> None:
        if self.mode not in ('local','production','test'):
            raise ValueError('APP_MODE must be local or production.')
        if self.mode=='local' and self.host not in ('127.0.0.1','::1','localhost'):
            raise ValueError('Local mode is loopback-only. Use authenticated production mode to deploy.')
        if self.mode=='production':
            if len(self.app_secret)<32 or self.app_secret.startswith('local-'):
                raise ValueError('Production requires a random APP_SECRET of at least 32 characters.')
            if not self.admin_email or len(self.admin_password)<16:
                raise ValueError('Production requires ADMIN_EMAIL and ADMIN_PASSWORD (16+ characters).')
            if urlsplit(self.base_url).scheme!='https':
                raise ValueError('Production APP_URL must be your public HTTPS origin.')
        if self.mode!='production' and self.allow_live_send:
            raise ValueError('Live email is allowed only in authenticated production mode.')

    def research_readiness(self) -> list[str]:
        issues=[]
        if not self.gemini_api_key: issues.append('GEMINI_API_KEY is not configured')
        if not self.source_rights_approved: issues.append('SOURCE_RIGHTS_APPROVED is not enabled')
        if urlsplit(self.base_url).scheme!='https': issues.append('A public HTTPS APP_URL is required for Gemini to call the read-only source gateway')
        if not self.brave_key or not self.brave_storage_rights: issues.append('Licensed Brave Search credentials and storage approval are required')
        return issues

    def email_readiness(self) -> list[str]:
        issues=[]
        if not self.allow_live_send: issues.append('ALLOW_LIVE_SEND is off')
        if not self.provider_approved: issues.append('Email-provider outreach permission is not confirmed')
        if not self.sender_auth_confirmed: issues.append('Sender authentication is not confirmed')
        if not all((self.smtp_host,self.smtp_user,self.smtp_password,self.smtp_from)):
            issues.append('SMTP is not configured')
        if not all((self.imap_host,self.imap_user,self.imap_password)):
            issues.append('IMAP reply monitoring is not configured')
        if self.mode!='production': issues.append('Local mode never sends live email')
        return issues
