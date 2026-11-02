"""Deterministic business rules. No network or database effects in this module."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

WEBSITE_STATUSES = ('unknown','official_website_found','hosted_chapter_page_only','social_only','no_site_found_after_checks','broken_or_parked')
ELIGIBLE_WEBSITES = {'social_only','no_site_found_after_checks'}
CATEGORIES = ('historical_preservation','neighborhood_association','legacy_civic_club','cultural_veteran','specialized_nonprofit')
PROJECT_STAGES = ('agreement','content','build','review','live','maintenance','handover')
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$")

class DomainError(Exception):
    def __init__(self, message: str, status: int = 400, details: list[str] | None = None):
        super().__init__(message)
        self.status, self.details = status, details or []

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z','+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False)

def approval_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()

def normalize_name(value: str) -> str:
    # Do not merge separate chapters based on address or parent brand.
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', value.casefold())).strip()

def email_key(value: str) -> str:
    # Preserve the original spelling elsewhere. No provider-specific dot/plus rewriting.
    return value.strip().casefold()

def validate_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not EMAIL_RE.fullmatch(value) or '..' in value.split('@')[-1]:
        raise DomainError('Enter one valid public organizational email address.')
    return value

def public_url(value: str, *, required: bool = False) -> str:
    value = value.strip()
    if not value and not required:
        return ''
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        if parsed.scheme not in ('http','https') or not host or parsed.username or parsed.password:
            raise ValueError()
        if parsed.port not in (None,80,443):
            raise ValueError()
        if host.lower() in ('localhost','localhost.localdomain') or '.' not in host or host.endswith(('.local','.internal','.localhost')):
            raise ValueError()
        try:
            if not is_public_address(host):
                raise ValueError()
        except ValueError:
            # A host name is checked through DNS immediately before any server fetch.
            if re.fullmatch(r'[\d.:]+',host) or ':' in host:
                raise
        return value
    except (ValueError,TypeError):
        raise DomainError('Use a public http(s) URL without credentials or a custom port.') from None

def research_key(city_id: str, category: str, window: str, campaign: str='first_website') -> str:
    return approval_hash({'city':city_id,'category':category,'window':window,'prompt':'civic-v2','source_policy':'mcp-only-v1','campaign':campaign})

def add_business_days(dt: datetime, days: int, tz: str | None = None) -> datetime:
    local = dt.astimezone(ZoneInfo(tz)) if tz else dt
    while days:
        local += timedelta(days=1)
        if local.weekday() < 5:
            days -= 1
    return local.astimezone(dt.tzinfo)

def fresh(value: str | None, now: datetime, days: int = 7) -> bool:
    dt = parse_time(value)
    return dt is not None and now-timedelta(days=days) <= dt <= now+timedelta(minutes=5)

def qualification_blockers(entity: dict, contact: dict | None, now: datetime | None = None) -> list[str]:
    now = now or utcnow()
    reasons = []
    eligible={'official_website_found','broken_or_parked','hosted_chapter_page_only'} if entity.get('campaign')=='rebuild' else ELIGIBLE_WEBSITES
    if entity.get('website_status') not in eligible:
        reasons.append('Website status is not eligible')
    if entity.get('campaign')=='rebuild' and not entity.get('website_url'):
        reasons.append('A rebuild requires the existing website URL and an ownership review')
    if entity.get('state') in ('excluded','suppressed'):
        reasons.append('Organization is excluded or suppressed')
    if not fresh(entity.get('verified_at'),now):
        reasons.append('Website and organization review must be refreshed within 7 days')
    if not entity.get('activity_note','').strip():
        reasons.append('Current activity evidence is missing')
    if not entity.get('history_note','').strip():
        reasons.append('Historical or civic scope evidence is missing')
    if not entity.get('rights_confirmed'):
        reasons.append('Source reuse is not approved')
    try:
        evidence = json.loads(entity.get('evidence_json') or '[]')
        if not any(e.get('url') and e.get('note') for e in evidence):
            reasons.append('A supporting evidence link and note are required')
    except (ValueError,TypeError):
        reasons.append('Evidence record is invalid')
    if not contact:
        reasons.append('Select a suitable organizational contact')
    elif contact.get('status') != 'verified' or not fresh(contact.get('verified_at'),now):
        reasons.append('Contact role must be checked within 7 days')
    return reasons

def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
        if isinstance(ip,ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip.is_global and not ip.is_multicast and not ip.is_unspecified
    except ValueError:
        return False

def clean_csv_cell(value: object) -> str:
    text = str(value or '')
    return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text
