"""Public inventories. No uploaded credentials, contact addresses or residential data are imported."""
import csv
import io
import re
import zipfile
from datetime import date
from ..core import DomainError
from .taxonomy import classify,display_name,zip_state,miles,_tag,clean_site

ZCTA='https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_zcta_national.zip'
PLACES='https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip'
POSTCARDS='https://apps.irs.gov/pub/epostcard/data-download-epostcard.zip'

def gazetteer(web,url):
    with zipfile.ZipFile(web.dataset(url,5_000_000,365)) as z:
        entries=[x for x in z.infolist() if x.filename.endswith('.txt')]
        if len(entries)!=1 or entries[0].file_size>15_000_000:raise DomainError('Unexpected Census dataset.')
        with z.open(entries[0]) as stream:
            for row in csv.DictReader(io.TextIOWrapper(stream,encoding='utf-8-sig'),delimiter='|'):
                yield {k.strip():v.strip() for k,v in row.items() if k and v is not None}

def place_name(name):
    return re.sub(r'\s+(?:city|village|town|CDP|municipality|borough)(?:\s+\(balance\))?$', '', name, flags=re.I).strip().casefold()

def center_point(web,city,params,zip_rows):
    if params.get('center_zip'):
        row=next((r for r in zip_rows if r['GEOID']==params['center_zip']),None)
        if row:return float(row['INTPTLAT']),float(row['INTPTLONG'])
        raise DomainError('The center ZIP is not in the Census ZCTA dataset. Try a nearby residential ZIP.')
    region=city['region'].strip().upper()
    if len(region)!=2:raise DomainError('IRS hunts need a two-letter state abbreviation in the city, or an explicit center ZIP.')
    matches=[r for r in gazetteer(web,PLACES) if r['USPS']==region and place_name(r['NAME'])==place_name(city['name'])]
    if len(matches)!=1:raise DomainError('The city could not be uniquely located in Census places. Start a hunt with a center ZIP.')
    return float(matches[0]['INTPTLAT']),float(matches[0]['INTPTLONG'])

def inventory(web,city,params):
    if city.get('country','US')!='US':raise DomainError('IRS inventory currently supports United States cities only.')
    zip_rows=list(gazetteer(web,ZCTA))
    center=center_point(web,city,params,zip_rows)
    zips={}
    for row in zip_rows:
        distance=miles(center,(float(row['INTPTLAT']),float(row['INTPTLONG'])))
        if distance<=params['radius_miles']:zips[row['GEOID']]=round(distance,1)
    if not zips:raise DomainError('No Census ZIP centroids fall within this radius. Increase the radius or choose a center ZIP.')
    states=sorted({zip_state(z) for z in zips}-{''})
    orgs=[]
    for st in states:
        url=f'https://www.irs.gov/pub/irs-soi/eo_{st.lower()}.csv'
        with web.dataset(url,40_000_000).open(encoding='utf-8-sig',newline='') as stream:
            for r in csv.DictReader(stream):
                zip_code=(r.get('ZIP') or '')[:5]
                if zip_code not in zips or r.get('STATUS') not in ('01','1') or r.get('FOUNDATION') in ('02','03','04'):continue
                revenue=int(r.get('REVENUE_AMT') or 0)
                kind=classify((r.get('NAME') or '')+' '+(r.get('SORT_NAME') or ''),r.get('NTEE_CD',''),r.get('SUBSECTION',''))
                if kind not in params['types'] or (params['max_revenue'] and revenue>params['max_revenue']):continue
                if not re.fullmatch(r'\d{9}',r.get('EIN','')):continue
                orgs.append({'ein':r['EIN'],'name':display_name(r.get('NAME'),r.get('SORT_NAME'),r.get('CITY')),
                    'city':r.get('CITY',''),'state':st,'zip':zip_code,'distance':zips[zip_code], 'type':kind,
                    'revenue':revenue,'filing_year':int((r.get('TAX_PERIOD') or '0000')[:4]),
                    'ruling_year':(r.get('RULING') or '')[:4],'source_url':url})
    # Stream the large public archive and retain only the selected EINs.
    want={r['ein'] for r in orgs};postcards={}
    if want:
        with zipfile.ZipFile(web.dataset(POSTCARDS,130_000_000)) as z:
            entries=z.infolist()
            if len(entries)!=1 or entries[0].file_size>450_000_000:raise DomainError('Unexpected IRS postcard archive.')
            with z.open(entries[0]) as stream:
                for line in io.TextIOWrapper(stream,encoding='utf-8',errors='replace'):
                    if line[:9] not in want:continue
                    fields=line.rstrip('\r\n').split('|')
                    if len(fields)<9 or not fields[1].isdigit():continue
                    year=int(fields[1])
                    if year>postcards.get(fields[0],{}).get('year',0):
                        postcards[fields[0]]={'year':year,'website':clean_site(fields[7]),'terminated':fields[4]=='T'}
    selected=[]
    for org in orgs:
        card=postcards.get(org['ein'],{})
        if card.get('terminated'):continue
        org['filing_year']=max(org['filing_year'],card.get('year',0))
        if params['recent_only'] and org['filing_year']<date.today().year-2:continue
        if card.get('website'):org.update(website=card['website'],website_source=POSTCARDS)
        selected.append(org)
    selected.sort(key=lambda r:(r['distance'],r['name'],r['ein']))
    return selected[:params['max_candidates']],len(selected)

def filing(web,ein):
    if not re.fullmatch(r'\d{9}',ein):return {}
    result,source=web.json(f'https://projects.propublica.org/nonprofits/api/v2/organizations/{int(ein)}.json')
    oid=str((result.get('organization') or {}).get('latest_object_id') or '')
    if not re.fullmatch(r'\d{10,25}',oid):return {'source_url':source}
    url=f'https://gt990datalake-rawdata.s3.amazonaws.com/EfileData/XmlFiles/{oid}_public.xml'
    code,final,_,raw=web.raw(url,6_000_000)
    if code!=200:raise DomainError(f'IRS filing mirror returned HTTP {code}.')
    xml=raw.decode('utf-8','replace')
    return {'website':clean_site(_tag(xml,'WebsiteAddressTxt','WebSiteAddressTxt')),
        'mission':_tag(xml,'ActivityOrMissionDesc','MissionDesc')[:1000],
        'filing_year':_tag(xml,'TaxYr'),'source_url':final}
