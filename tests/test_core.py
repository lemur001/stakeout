from datetime import datetime, timezone
from app.core import qualification_blockers, approval_hash, research_key, add_business_days, is_public_address

NOW = datetime(2026,10,2,16,tzinfo=timezone.utc)
GOOD = dict(website_status='no_site_found_after_checks',verified_at='2026-10-02T16:00:00Z',activity_note='Current activity checked',history_note='Historical scope checked',rights_confirmed=1,evidence_json='[{"url":"https://example.org","note":"Checked"}]',state='review')
CONTACT = dict(verified_at='2026-10-02T16:00:00Z',status='verified')
def test_unknown_is_blocked(): assert 'Website status is not eligible' in qualification_blockers({**GOOD,'website_status':'unknown'},CONTACT,NOW)
def test_official_website_is_blocked(): assert qualification_blockers({**GOOD,'website_status':'official_website_found'},CONTACT,NOW)
def test_rights_required(): assert 'Source reuse is not approved' in qualification_blockers({**GOOD,'rights_confirmed':0},CONTACT,NOW)
def test_old_review_blocked(): assert qualification_blockers({**GOOD,'verified_at':'2025-01-01T00:00:00Z'},CONTACT,NOW)
def test_missing_contact_blocked(): assert qualification_blockers(GOOD,None,NOW)
def test_verified_qualifies(): assert qualification_blockers(GOOD,CONTACT,NOW)==[]
def test_research_shared_between_clients(): assert research_key('a','history','2026-10')==research_key('a','history','2026-10')
def test_research_separates_cities(): assert research_key('a','history','2026-10')!=research_key('b','history','2026-10')
def test_hash_body_and_recipient():
 assert approval_hash(dict(body='A',recipient='a'))!=approval_hash(dict(body='B',recipient='a'))
 assert approval_hash(dict(body='A',recipient='a'))!=approval_hash(dict(body='A',recipient='b'))
def test_hash_canonical_order(): assert approval_hash(dict(body='A',recipient='a'))==approval_hash(dict(recipient='a',body='A'))
def test_business_days(): assert add_business_days(NOW,7).isoformat()=='2026-10-13T16:00:00+00:00'
def test_ssrf_private_addresses():
 for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','fc00::1','192.168.1.1','0.0.0.0']:
  assert not is_public_address(ip),ip
