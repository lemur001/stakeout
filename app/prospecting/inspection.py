"""Conservative site inspection inspired by Backlink Hunter. Observations are not approvals."""
import html
import re
from datetime import date, timedelta
from urllib.parse import urlsplit,urljoin
from ..research import PageParser
from ..core import public_url

SOCIAL={'facebook.com','instagram.com','linkedin.com','youtube.com','x.com','twitter.com'}
HOSTED={'sites.google.com','wordpress.com','wixsite.com','weebly.com','clubrunner.ca','blogspot.com'}
PLATFORMS={'WordPress':r'wp-content|wp-includes','Wix':r'wixstatic|wix\.com','Squarespace':r'squarespace',
    'ClubRunner':r'clubrunner','SportsEngine':r'sportsengine|sportngin','Wild Apricot':r'wildapricot','ClubExpress':r'clubexpress'}
STOP={'the','and','of','inc','club','clubs','association','society','foundation','international','organization','nfp'}

def host(url):return (urlsplit(url).hostname or '').lower().removeprefix('www.')
def tokens(name):return [w for w in re.findall(r'[a-z0-9]+',name.lower()) if w not in STOP and len(w)>2]
def text(raw):
    p=PageParser();p.feed(raw)
    return re.sub(r'\s+',' ',html.unescape(' '.join(p.text))),p.links

def match(raw,org):
    visible,_=text(raw);low=visible.lower()
    words=tokens(org['name']);hits=sum(bool(re.search(r'\b'+re.escape(t)+r'\b',low)) for t in words)
    name_ok=bool(words) and hits>=max(1,min(3,len(words)))
    town=org.get('city','').strip().lower()
    local=bool(town) and town in low
    ein=org.get('ein','');ein_ok=bool(ein) and ein in re.sub(r'[^0-9]','',visible)
    return {'matched':name_ok and (local or ein_ok),'name_terms':hits,'city_match':local,'ein_match':ein_ok}

def inspect(url,raw,org):
    visible,links=text(raw);low=visible.lower();today=date.today();dates=[]
    for value in re.findall(r'\b20\d\d-\d\d-\d\d\b',visible):
        try:
            d=date.fromisoformat(value)
            if date(2005,1,1)<=d<=today+timedelta(days=366):dates.append(d)
        except ValueError:pass
    years=[int(y) for y in re.findall(r'(?:©|copyright|&copy;)\s*(?:\d{4}\s*[-–]\s*)?(20\d\d)',raw,re.I) if int(y)<=today.year]
    normalized=[]
    for link in links[:200]:
        try:normalized.append(public_url(urljoin(url,link),required=True))
        except Exception:continue
    platform=next((k for k,v in PLATFORMS.items() if re.search(v,raw,re.I)),'Unknown')
    parked=bool(re.search(r'domain (?:is )?for sale|parked free|domain has expired|buy this domain',low[:5000]))
    spam=bool(re.search(r'slot gacor|situs judi|online casino',low[:10000]))
    member=bool(re.search(r'member(?:s|ship)? (?:login|portal|sign in|account)|memberpress|pmpro_',low+' '+raw[:200000]))
    store=bool(re.search(r'add.to.cart|/product/|/product-page/|shopify\.shop',raw,re.I))
    credit=re.search(r'(?:website|web design|site) (?:by|designed by|built by)\s+([^|©<>]{2,70})',visible[-12000:],re.I)
    last=max(dates).isoformat() if dates else ''
    stale=bool(years and max(years)<=today.year-2) or bool(last and last<(today-timedelta(days=730)).isoformat())
    emails=sorted(set(re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,20}\b',visible)))[:10]
    emails=[e for e in emails if not re.search(r'example\.|sentry|wixpress|noreply|no-reply',e,re.I)]
    return {'url':url,'identity':match(raw,org),'platform':platform,'parked':parked,'spam':spam,'member_area':member,
        'store':store,'designer_credit':credit.group(0)[:120] if credit else '', 'copyright_year':max(years) if years else None,
        'latest_visible_date':last,'stale_signal':stale,'recent_activity_signal':bool(last and last>=(today-timedelta(days=183)).isoformat()),
        'hosted':any(host(url)==h or host(url).endswith('.'+h) for h in HOSTED),
        'social_links':list(dict.fromkeys(u for u in normalized if host(u) in SOCIAL))[:5],
        'page_links':list(dict.fromkeys(u for u in normalized if host(u)==host(url)))[:30],
        'public_emails':emails,'excerpt':visible[:1800]}

def guesses(org):
    name=''.join(tokens(org['name']));city=re.sub(r'\W','',org.get('city','').lower())
    stems=[name] if 5<=len(name)<=55 else []
    for kind in ('rotary','lions','kiwanis','historical','vfw','legion'):
        if kind in org['name'].lower():stems.extend([city+kind,kind+city])
    return ['https://'+s+t+'/' for s in dict.fromkeys(stems) if s for t in ('.org','.com')][:6]

def sitemap(raw,domain):
    if re.search(r'<(?:\w+:)?sitemapindex\b',raw,re.I):
        return {'kind':'index','page_count':None,'note':'Sitemap index found; child maps were not crawled.'}
    if not re.search(r'<(?:\w+:)?urlset\b',raw,re.I):raise ValueError('Not a sitemap')
    urls=[]
    for value in re.findall(r'<(?:\w+:)?loc\b[^>]*>([^<]+)</',raw,re.I)[:5001]:
        try:
            url=public_url(html.unescape(value.strip()),required=True)
            if host(url)==domain:urls.append(url)
        except Exception:continue
    return {'kind':'urlset','page_count':len(set(urls[:5000])),'truncated':len(urls)>5000,
        'note':'Listed URLs are a size hint, not proof that pages are live or current.'}

def assess(facts,site,backlinks,campaign,checks):
    reasons=[];gaps=[];fit=0;identity=site.get('identity',{}).get('matched',False)
    if identity:fit+=20;reasons.append('Name and locality or EIN matched on the website.')
    else:gaps.append('Organization-to-website identity needs independent review.')
    if site.get('stale_signal'):fit+=25;reasons.append('The website has dated content or an old copyright signal.')
    if site.get('recent_activity_signal'):fit+=15;reasons.append('A recent visible date suggests activity; confirm its context.')
    else:gaps.append('Current organizational activity is not established.')
    if facts.get('filing_year') and int(facts['filing_year'])>=date.today().year-2:fit+=10;reasons.append('A recent IRS filing is recorded; filing alone is not activity.')
    if facts.get('revenue') is not None and facts['revenue']<=500000:fit+=10
    if site.get('public_emails'):fit+=5
    if campaign=='first_website':
        if identity and not site.get('hosted'):fit=0;reasons.append('Existing official-site candidate conflicts with this campaign.')
        elif not site:fit+=10;gaps.append('No website found is not proof of absence; review the documented searches.')
    elif identity and not site.get('hosted'):fit+=15
    for key,label in [('member_area','Member portal'),('store','Online store'),('designer_credit','Existing designer'),('spam','Possible spam or hijack'),('parked','Parked or expired site')]:
        if site.get(key):fit=max(0,fit-20);gaps.append(label+' requires manual assessment.')
    failed=sum(c.get('status')!='ok' for c in checks)
    confidence=(40 if identity else 0)+(10 if facts.get('ein') else 0)
    if facts.get('filing_year') and int(facts['filing_year'])>=date.today().year-2:confidence+=10
    if site.get('recent_activity_signal'):confidence+=15
    if backlinks.get('status')=='ok':confidence+=10
    if any(l.get('verification',{}).get('verified') is True for l in backlinks.get('links',[])):confidence+=10
    if not identity:confidence=min(confidence,40)
    if failed:gaps.append(f'{failed} checks were unavailable or inconclusive.')
    link_score=None
    if backlinks.get('status')=='ok':
        count=backlinks.get('referring_domains',0)
        import math
        link_score=min(100,round(math.log10(1+count)*30))
        reasons.append(f'{count} referring domains reported by the provider; inspect relevance and link evidence.')
    else:gaps.append('Backlink opportunity is unknown until backlink data and relevant links are reviewed.')
    return {'fit':min(100,fit),'link_opportunity':link_score,'confidence':confidence,'reasons':reasons,'gaps':gaps,
        'campaign':campaign,'qualification':'Human review required','score_version':'prospecting-v1'}
