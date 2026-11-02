"""Boot configuration; integration credentials are overlaid from the encrypted vault."""
from __future__ import annotations
import os
import base64
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

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
    base_url: str = field(default_factory=lambda:os.getenv('APP_URL',('https://'+os.environ['RAILWAY_PUBLIC_DOMAIN']) if os.getenv('RAILWAY_PUBLIC_DOMAIN') else 'http://127.0.0.1:8080').rstrip('/'))
    database_url: str = field(default_factory=lambda:os.getenv('DATABASE_URL',''),repr=False)
    database_path: str = field(default_factory=lambda:os.getenv('DATABASE_PATH',str(ROOT/'data'/'civic.sqlite3')))
    app_secret: str = field(default_factory=lambda:os.getenv('APP_SECRET','local-only-not-for-deployment'),repr=False)
    encryption_key: str = field(default_factory=lambda:os.getenv('ENCRYPTION_KEY',''),repr=False)
    encryption_key_previous: str = field(default_factory=lambda:os.getenv('ENCRYPTION_KEY_PREVIOUS',''),repr=False)
    setup_token: str = field(default_factory=lambda:os.getenv('SETUP_TOKEN',''),repr=False)
    admin_email: str = field(default_factory=lambda:os.getenv('ADMIN_EMAIL',''))
    admin_password: str = field(default_factory=lambda:os.getenv('ADMIN_PASSWORD',''),repr=False)
    run_worker: bool = field(default_factory=lambda:flag('RUN_WORKER',True))
    seed_on_start: bool = field(default_factory=lambda:flag('SEED_LAKELAND',True))
    allow_live_send: bool = field(default_factory=lambda:flag('ALLOW_LIVE_SEND'))
    provider_approved: bool = field(default_factory=lambda:flag('OUTREACH_PROVIDER_APPROVED'))
    sender_auth_confirmed: bool = field(default_factory=lambda:flag('SENDER_AUTH_CONFIRMED'))
    gemini_api_key: str = field(default_factory=lambda:os.getenv('GEMINI_API_KEY',''),repr=False)
    research_agent: str = field(default_factory=lambda:os.getenv('GEMINI_RESEARCH_AGENT','deep-research-preview-04-2026'))
    extraction_model: str = field(default_factory=lambda:os.getenv('GEMINI_EXTRACTION_MODEL','gemini-3.8-flash'))
    source_rights_approved: bool = field(default_factory=lambda:flag('SOURCE_RIGHTS_APPROVED'))
    brave_key: str = field(default_factory=lambda:os.getenv('BRAVE_SEARCH_API_KEY',''),repr=False)
    brave_storage_rights: bool = field(default_factory=lambda:flag('BRAVE_STORAGE_RIGHTS_APPROVED'))
    smtp_host: str = field(default_factory=lambda:os.getenv('SMTP_HOST',''))
    smtp_port: int = field(default_factory=lambda:int(os.getenv('SMTP_PORT','587')))
    smtp_user: str = field(default_factory=lambda:os.getenv('SMTP_USER',''))
    smtp_password: str = field(default_factory=lambda:os.getenv('SMTP_PASSWORD',''),repr=False)
    smtp_from: str = field(default_factory=lambda:os.getenv('SMTP_FROM',''))
    smtp_ssl: bool = field(default_factory=lambda:flag('SMTP_SSL'))
    imap_host: str = field(default_factory=lambda:os.getenv('IMAP_HOST',''))
    imap_port: int = field(default_factory=lambda:int(os.getenv('IMAP_PORT','993')))
    imap_user: str = field(default_factory=lambda:os.getenv('IMAP_USER',''))
    imap_password: str = field(default_factory=lambda:os.getenv('IMAP_PASSWORD',''),repr=False)
    imap_mailbox: str = field(default_factory=lambda:os.getenv('IMAP_MAILBOX','INBOX'))
    webhook_secret: str = field(default_factory=lambda:os.getenv('INBOUND_WEBHOOK_SECRET',''),repr=False)
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
            self.decode_key(self.encryption_key)
            if self.encryption_key==self.app_secret:
                raise ValueError('ENCRYPTION_KEY and APP_SECRET must be independent random values.')
            if self.encryption_key_previous:self.decode_key(self.encryption_key_previous)
            if self.setup_token and (len(self.setup_token)<32 or self.setup_token in (self.app_secret,self.encryption_key)):
                raise ValueError('SETUP_TOKEN must be a separate random value of at least 32 characters.')
            if self.admin_email and not 16<=len(self.admin_password)<=512:
                raise ValueError('ADMIN_PASSWORD must have 16–512 characters.')
            origin=urlsplit(self.base_url)
            if origin.scheme!='https' or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
                raise ValueError('Production APP_URL must be your public HTTPS origin.')
            if self.database_url:
                database=urlsplit(self.database_url)
                if database.scheme not in ('postgres','postgresql') or parse_qs(database.query).get('sslmode')!=['verify-full']:
                    raise ValueError('Production DATABASE_URL must use PostgreSQL with sslmode=verify-full and a trusted server certificate.')
            if os.getenv('RAILWAY_ENVIRONMENT_ID') and not self.database_url:
                mount=os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
                if not mount or not Path(self.database_path).resolve().is_relative_to(Path(mount).resolve()):
                    raise ValueError('Railway SQLite requires a persistent volume containing DATABASE_PATH.')
        if self.mode!='production' and self.allow_live_send:
            raise ValueError('Live email is allowed only in authenticated production mode.')

    @staticmethod
    def decode_key(value: str) -> bytes:
        try:
            key=base64.b64decode(value,altchars=b'-_',validate=True)
            if len(key)!=32:raise ValueError()
            return key
        except (ValueError,TypeError):
            raise ValueError('ENCRYPTION_KEY must be a base64-encoded random 32-byte key. Keep it outside the database.') from None

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
