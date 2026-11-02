"""Authenticated encryption with keys supplied separately from the database.

Versioned AES-256-GCM envelopes bind ciphertext to its purpose. Each write uses
a fresh 96-bit nonce. The previous key is decrypt-only during explicit rotation.
"""
from __future__ import annotations

import base64
import json
import secrets
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ConfigDict, Field, field_validator
from .config import Config
from .core import DomainError, iso, validate_email
from .models import Strict

SECRET_FIELDS = frozenset({'gemini_api_key','brave_key','smtp_password','imap_password','webhook_secret'})


class IntegrationInput(Strict):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    gemini_api_key: str = Field(default='', max_length=4096, repr=False)
    brave_key: str = Field(default='', max_length=4096, repr=False)
    smtp_password: str = Field(default='', max_length=4096, repr=False)
    imap_password: str = Field(default='', max_length=4096, repr=False)
    webhook_secret: str = Field(default='', max_length=4096, repr=False)
    research_agent: str = Field(default='deep-research-preview-04-2026', pattern=r'^[A-Za-z0-9._-]{1,150}$')
    extraction_model: str = Field(default='gemini-3.8-flash', pattern=r'^[A-Za-z0-9._-]{1,150}$')
    smtp_host: str = Field(default='', max_length=253)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = Field(default='', max_length=320)
    smtp_from: str = Field(default='', max_length=320)
    smtp_ssl: bool = False
    imap_host: str = Field(default='', max_length=253)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_user: str = Field(default='', max_length=320)
    imap_mailbox: str = Field(default='INBOX', min_length=1, max_length=200)
    source_rights_approved: bool = False
    brave_storage_rights: bool = False
    provider_approved: bool = False
    sender_auth_confirmed: bool = False
    daily_send_limit: int = Field(default=5, ge=1, le=100)
    daily_research_limit: int = Field(default=5, ge=1, le=100)
    max_research_concurrent: int = Field(default=1, ge=1, le=3)
    clear_secrets: list[str] = Field(default_factory=list, max_length=5)

    @field_validator('smtp_host','imap_host')
    @classmethod
    def host(cls,value):
        import re
        value=value.strip().lower()
        if value and not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',value):
            raise ValueError('Enter a hostname without a scheme, path or port.')
        if value and ('.' not in value or value.endswith(('.localhost','.local','.internal'))):
            raise ValueError('Use your public mail provider hostname.')
        return value

    @field_validator('smtp_from')
    @classmethod
    def address(cls,value):return validate_email(value) if value else ''

    @field_validator('clear_secrets')
    @classmethod
    def secret_names(cls,value):
        if set(value)-SECRET_FIELDS:raise ValueError('Unknown credential name.')
        return value


INTEGRATION_FIELDS = frozenset(IntegrationInput.model_fields)-{'clear_secrets'}


class Vault:
    def __init__(self,config):self.config=config

    def _keys(self):
        if not self.config.encryption_key:
            raise DomainError('Configure ENCRYPTION_KEY on the server before storing credentials.',503)
        return [Config.decode_key(k) for k in (self.config.encryption_key,self.config.encryption_key_previous) if k]

    def encrypt(self,purpose: str,value: str) -> str:
        nonce=secrets.token_bytes(12)
        encrypted=AESGCM(self._keys()[0]).encrypt(nonce,value.encode(),('stakeout:v1:'+purpose).encode())
        return 'v1.'+base64.urlsafe_b64encode(nonce+encrypted).decode()

    def decrypt(self,purpose: str,value: str) -> str:
        keys=self._keys()
        try:
            version,encoded=value.split('.',1)
            if version!='v1':raise ValueError()
            raw=base64.b64decode(encoded,altchars=b'-_',validate=True)
            for key in keys:
                try:return AESGCM(key).decrypt(raw[:12],raw[12:],('stakeout:v1:'+purpose).encode()).decode()
                except InvalidTag:continue
        except (ValueError,UnicodeError):pass
        raise DomainError('Encrypted data could not be opened. Restore the correct encryption key; do not reset the database.',503)


class IntegrationStore:
    def __init__(self,service):
        self.service,self.db,self.config=service,service.db,service.config
        self.vault=Vault(self.config)

    def load(self):
        with self.db.transaction(False) as tx:
            row=tx.one("SELECT ciphertext FROM secret_store WHERE name='integrations'")
        if row:
            values=json.loads(self.vault.decrypt('integrations',row['ciphertext']))
            checked=IntegrationInput.model_validate(values).model_dump(exclude={'clear_secrets'})
            # Publish the complete validated configuration in one dictionary update.
            self.config.__dict__.update(checked)

    def verify_keys(self):
        with self.db.transaction(False) as tx:
            rows=tx.all('SELECT user_id,ciphertext FROM user_mfa')
        for row in rows:self.vault.decrypt('mfa:'+row['user_id'],row['ciphertext'])

    def summary(self):
        return {
            'values':{key:getattr(self.config,key) for key in INTEGRATION_FIELDS-SECRET_FIELDS},
            'secrets_set':{key:bool(getattr(self.config,key)) for key in SECRET_FIELDS},
            'encrypted_storage':bool(self.config.encryption_key),
            'live_send_enabled':self.config.allow_live_send,
            'research_readiness':self.config.research_readiness(),
            'email_readiness':self.config.email_readiness(),
        }

    def save(self,change: IntegrationInput,actor: str):
        with self.db.transaction() as tx:
            row=tx.one("SELECT ciphertext FROM secret_store WHERE name='integrations'")
            current={key:getattr(self.config,key) for key in INTEGRATION_FIELDS}
            if row:current.update(json.loads(self.vault.decrypt('integrations',row['ciphertext'])))
            delta=change.model_dump(exclude_unset=True,exclude={'clear_secrets'})
            # Empty password boxes keep the saved value. Deletion is explicit.
            for key,value in delta.items():
                if key not in SECRET_FIELDS or value:current[key]=value
            for key in change.clear_secrets:current[key]=''
            checked=IntegrationInput.model_validate(current).model_dump(exclude={'clear_secrets'})
            encrypted=self.vault.encrypt('integrations',json.dumps(checked))
            tx.execute('INSERT INTO secret_store(name,ciphertext,updated_at) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET ciphertext=excluded.ciphertext,updated_at=excluded.updated_at',('integrations',encrypted,iso()))
            tx.set_setting('paused',True)
            self.service.audit(tx,actor,'integrations.updated','settings','Encrypted settings saved; outreach paused.')
            self.config.__dict__.update(checked)
        return self.summary()
