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
    words=list(dict.fromkeys(tokens(org['name'])));hits=sum(bool(re.search(r'\b'+re.escape(t)+r'\b',low)) for t in words)
    compact=re.sub(r'[^a-z0-9]','',low)
    joined=''.join(words)
    name_ok=bool(words) and (hits>=max(1,min(3,len(words))) or (len(joined)>=8 and joined in compact))
    town=org.get('city','').strip().lower()
    local=bool(town) and bool(re.search(r'\b'+re.escape(town)+r'\b',low))
    ein=org.get('ein','');ein_ok=bool(ein) and any(a+b==ein for a,b in re.findall(r'(?<!\d)(\d{2})[- ]?(\d{7})(?!\d)',visible))
    return {'matched':name_ok and (local or ein_ok),'name_match':name_ok,'name_terms':hits,'city_match':local,'ein_match':ein_ok}

def activity_dates(visible):
    """Visible dates are evidence hints; future events are distinct from recent past activity."""
    today=date.today();found={}
    months='January February March April May June July August September October November December'.split()
    month_ids={m.lower():i+1 for i,m in enumerate(months)}
    month_ids.update({m[:3].lower():i+1 for i,m in enumerate(months)})
    month_re='(?:'+'|'.join(sorted(month_ids,key=len,reverse=True))+')'
    patterns=[(r'\b(20\d{2})-(\d{1,2})-(\d{1,2})\b',lambda m:date(int(m[1]),int(m[2]),int(m[3]))),
        (r'\b('+month_re+r')\.?\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b',lambda m:date(int(m[3]),month_ids[m[1].lower()],int(m[2]))),
        (r'\b(\d{1,2})\s+('+month_re+r')\.?[,]?\s+(20\d{2})\b',lambda m:date(int(m[3]),month_ids[m[2].lower()],int(m[1]))),
        (r'\b(\d{1,2})/(\d{1,2})/(20\d{2})\b',lambda m:date(int(m[3]),int(m[1]),int(m[2])))]
    for pattern,parse in patterns:
        for m in re.finditer(pattern,visible,re.I):
            try:d=parse(m)
            except (ValueError,KeyError):continue
            if not date(2005,1,1)<=d<=today+timedelta(days=366):continue
            found.setdefault(d.isoformat(),{'date':d.isoformat(),'future':d>today,'context':visible[max(0,m.start()-70):m.end()+100]})
    return sorted(found.values(),key=lambda r:r['date'],reverse=True)[:30]

def inspect(url,raw,org):
    visible,links=text(raw);low=visible.lower();today=date.today();dates=activity_dates(visible)
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
    past=[d['date'] for d in dates if not d['future']];future=[d['date'] for d in dates if d['future']]
    last=max(past) if past else ''
    stale=bool(years and max(years)<=today.year-2) or bool(last and last<(today-timedelta(days=730)).isoformat())
    emails=sorted(set(re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,20}\b',visible)))[:10]
    emails=[e for e in emails if not re.search(r'example\.|sentry|wixpress|noreply|no-reply',e,re.I)]
    return {'url':url,'identity':match(raw,org),'platform':platform,'parked':parked,'spam':spam,'member_area':member,
        'store':store,'designer_credit':credit.group(0)[:120] if credit else '', 'copyright_year':max(years) if years else None,
        'latest_visible_date':last,'upcoming_event_date':min(future) if future else '', 'activity_dates':dates,
        'stale_signal':stale,'recent_activity_signal':bool(last and last>=(today-timedelta(days=183)).isoformat()),
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

class LinkParser(PageParser):
    def __init__(self):
        super().__init__();self.anchors=[];self.current=None;self.base='';self.robots=[]
    def handle_starttag(self,tag,attrs):
        super().handle_starttag(tag,attrs)
        if self.skip:return
        attrs=dict(attrs)
        if tag=='base' and not self.base:self.base=attrs.get('href','')
        if tag=='meta' and attrs.get('name','').lower() in ('robots','googlebot'):
            self.robots.extend(re.split(r'[,\s]+',attrs.get('content','').lower()))
        if tag=='a':
            self.current={'href':attrs.get('href',''),'rel':attrs.get('rel','').lower().split(),'anchor':''}
            self.anchors.append(self.current)
    def handle_endtag(self,tag):
        super().handle_endtag(tag)
        if tag=='a':self.current=None
    def handle_data(self,data):
        super().handle_data(data)
        if self.current is not None and not self.skip:self.current['anchor']=(self.current['anchor']+data)[:300]

def verify_links(raw,source_url,target_domain,org):
    p=LinkParser();p.feed(raw);matches=[];base=urljoin(source_url,p.base) if p.base else source_url
    for a in p.anchors:
        try:target=public_url(urljoin(base,a['href']),required=True)
        except Exception:continue
        if host(target)!=target_domain:continue
        rel=set(a['rel']);follow=not (rel & {'nofollow','sponsored','ugc'} or set(p.robots)&{'nofollow','none'})
        matches.append({'target_url':target,'anchor':a['anchor'].strip(),'rel':sorted(rel),'follow_observed':follow})
    identity=match(raw,org)
    return {'verified':bool(matches),'source_url':source_url,'matches':matches[:5],
        'follow_observed':any(a['follow_observed'] for a in matches) if matches else None,
        'name_context':identity['name_match'],'local_context':identity['city_match'],
        'noindex_observed':bool(set(p.robots)&{'noindex','none'})}

def link_assessment(backlinks):
    if backlinks.get('status')!='ok':return None,{},[]
    import math
    count=max(0,backlinks.get('referring_domains',0));seen={}
    for link in backlinks.get('links',[]):
        v=link.get('verification',{})
        if v.get('verified') is True:seen.setdefault(host(v.get('source_url',link.get('source_url',''))),v)
    verified=list(seen.values());follow=sum(v.get('follow_observed') is True and not v.get('noindex_observed') for v in verified)
    relevant=sum(v.get('name_context') and v.get('local_context') for v in verified)
    parts={'referring_domains':min(45,round(math.log10(1+count)*17)),
        'observed_links':min(25,round(len(verified)*12.5)),'observed_follow':min(15,follow*5),
        'name_and_local_context':min(15,relevant*5),'spam_penalty':0}
    spam=backlinks.get('spam_score')
    if isinstance(spam,(int,float)):parts['spam_penalty']=-round(max(0,min(100,spam))*.4)
    notes=[f'{count} referring domains reported; {len(verified)} distinct linking domains observed in the fetched sample.',
        f'{follow} sampled sources have an observed follow link without a noindex meta tag; indexing is not confirmed.',
        f'{relevant} sampled sources mention both the organization name and locality.']
    if spam is not None:notes.append('Provider spam signal is applied as a penalty, not treated as a confirmed spam classification.')
    return max(0,min(100,sum(parts.values()))),parts,notes

def assess(facts,site,backlinks,campaign,checks):
    reasons=[];gaps=[];fit=0;identity=site.get('identity',{}).get('matched',False)
    if identity:fit+=20;reasons.append('Name matched with locality, EIN or the website recorded in an IRS filing.')
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
    failed=sum(c.get('status') in ('unavailable','unknown') for c in checks)
    confidence=(40 if identity else 0)+(10 if facts.get('ein') else 0)
    if facts.get('filing_year') and int(facts['filing_year'])>=date.today().year-2:confidence+=10
    if site.get('recent_activity_signal'):confidence+=15
    if backlinks.get('status')=='ok':confidence+=10
    if any(l.get('verification',{}).get('verified') is True for l in backlinks.get('links',[])):confidence+=10
    if not identity:confidence=min(confidence,40)
    if failed:gaps.append(f'{failed} checks were unavailable or inconclusive.')
    link_score,link_parts,link_reasons=link_assessment(backlinks)
    if link_score is not None:reasons.extend(link_reasons)
    else:gaps.append('Backlink opportunity is unknown until backlink data and relevant links are reviewed.')
    return {'fit':min(100,fit),'link_opportunity':link_score,'confidence':confidence,'reasons':reasons,'gaps':gaps,
        'link_components':link_parts,'campaign':campaign,'qualification':'Human review required','score_version':'prospecting-v2'}
