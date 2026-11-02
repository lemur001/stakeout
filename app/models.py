"""Validated API and model-output contracts. Unknown fields are rejected."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .core import validate_email, public_url

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)

class CityInput(Strict):
    name: str=Field(min_length=2,max_length=100)
    region: str=Field(min_length=2,max_length=100)
    country: Literal['US']='US'
    timezone: str='America/New_York'

class ClientInput(Strict):
    name: str=Field(min_length=2,max_length=160)
    website: str=''
    city_ids: list[str]=Field(default_factory=list,max_length=300)
    funded: bool=False
    budget_cents: int=Field(default=0,ge=0,le=100000000)
    max_slots: int=Field(default=1,ge=1,le=1000)
    offer: str=Field(default='Five public pages, two revision rounds, and one year of domain registration and hosting.',min_length=10,max_length=3000)
    renewal_terms: str=Field(default='',max_length=3000)
    @field_validator('website')
    @classmethod
    def url(cls,v): return public_url(v)

class Evidence(Strict):
    url: str=Field(max_length=2000)
    note: str=Field(min_length=3,max_length=1600)
    published_at: str | None=None
    @field_validator('url')
    @classmethod
    def url(cls,v): return public_url(v,required=True)

WebsiteStatus=Literal['unknown','official_website_found','hosted_chapter_page_only','social_only','no_site_found_after_checks','broken_or_parked']

class ReviewInput(Strict):
    website_status: WebsiteStatus
    website_url: str=''
    history_note: str=Field(default='',max_length=3000)
    activity_note: str=Field(default='',max_length=3000)
    evidence: list[Evidence]=Field(default_factory=list,max_length=20)
    rights_confirmed: bool=False
    contact_id: str | None=None
    verify_contact: bool=False
    contact_role_note: str=Field(default='',max_length=1500)
    contact_source_url: str=''
    @field_validator('website_url','contact_source_url')
    @classmethod
    def url(cls,v): return public_url(v)

class ContactInput(Strict):
    email: str
    source_url: str
    role_note: str=Field(min_length=3,max_length=1500)
    route: Literal['direct','liaison']='direct'
    @field_validator('email')
    @classmethod
    def email_valid(cls,v): return validate_email(v)
    @field_validator('source_url')
    @classmethod
    def url(cls,v): return public_url(v,required=True)

class ConversationInput(Strict):
    entity_ids: list[str]=Field(min_length=1,max_length=30)
    client_id: str
    contact_id: str

class MessageEdit(Strict):
    subject: str=Field(min_length=3,max_length=200)
    body: str=Field(min_length=40,max_length=12000)
    @field_validator('subject')
    @classmethod
    def headers(cls,v):
        if '\n' in v or '\r' in v: raise ValueError('Subject must be one line.')
        return v

class ResearchInput(Strict):
    city_id: str
    category: Literal['historical_preservation','neighborhood_association','legacy_civic_club','cultural_veteran','specialized_nonprofit']
    window: str=Field(pattern=r'^\d{4}-\d{2}(?:-[A-Za-z0-9]{1,12})?$')
    max_candidates: int=Field(default=30,ge=1,le=100)
    max_tool_calls: int=Field(default=80,ge=5,le=200)
    rights_acknowledged: bool=False

class ManualReport(Strict):
    city_id: str
    category: Literal['historical_preservation','neighborhood_association','legacy_civic_club','cultural_veteran','specialized_nonprofit']
    title: str=Field(min_length=3,max_length=200)
    report: str=Field(min_length=50,max_length=300000)
    rights_acknowledged: bool=False

class SourceInput(Strict):
    city_id: str | None=None
    url: str
    title: str=Field(min_length=3,max_length=200)
    rights_note: str=Field(min_length=10,max_length=2000)
    fetch_allowed: bool=False
    @field_validator('url')
    @classmethod
    def url(cls,v): return public_url(v,required=True)

class ProjectInput(Strict):
    conversation_id: str
    entity_id: str
    authorized_by: str=Field(min_length=3,max_length=200)
    agreement_note: str=Field(min_length=20,max_length=4000)
    scope: str=Field(min_length=10,max_length=4000)

class ProjectUpdate(Strict):
    stage: Literal['agreement','content','build','review','live','maintenance','handover']
    domain: str=Field(default='',max_length=255)
    public_url: str=''
    org_owns_domain: bool=False
    content_approved: bool=False
    approval_note: str=Field(default='',max_length=2000)
    notes: str=Field(default='',max_length=6000)
    renewal_date: str=Field(default='',max_length=20)
    @field_validator('public_url')
    @classmethod
    def url(cls,v): return public_url(v)

class ProfileInput(Strict):
    agency_name: str=Field(min_length=2,max_length=150)
    sender_name: str=Field(default='',max_length=150)
    sender_email: str=''
    postal_address: str=Field(default='',max_length=400)
    @field_validator('sender_email')
    @classmethod
    def email_valid(cls,v): return validate_email(v) if v else ''

class IncomingEvent(Strict):
    event_id: str=Field(min_length=5,max_length=250)
    message_id: str | None=None
    email: str | None=None
    event_type: Literal['reply','optout','bounce','complaint','delivered']
    body: str=Field(default='',max_length=12000)
    @field_validator('email')
    @classmethod
    def email_valid(cls,v): return validate_email(v) if v else None

class ExtractedContact(Strict):
    email: str
    source_url: str
    role_note: str
    route: Literal['direct','liaison']='direct'
    @field_validator('email')
    @classmethod
    def valid(cls,v): return validate_email(v)
    @field_validator('source_url')
    @classmethod
    def url(cls,v): return public_url(v,required=True)

class Candidate(Strict):
    name: str=Field(min_length=2,max_length=200)
    category: str=Field(min_length=2,max_length=100)
    website_status: WebsiteStatus='unknown'
    website_url: str=''
    history_note: str=Field(default='',max_length=3000)
    activity_note: str=Field(default='',max_length=3000)
    evidence: list[Evidence]=Field(default_factory=list,max_length=20)
    contacts: list[ExtractedContact]=Field(default_factory=list,max_length=5)
    @field_validator('website_url')
    @classmethod
    def url(cls,v): return public_url(v)

class CandidateBatch(Strict):
    candidates: list[Candidate]=Field(max_length=100)
    coverage_gaps: list[str]=Field(default_factory=list,max_length=100)
