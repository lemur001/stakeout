"""Fixed-origin provider adapters. Provider errors never include credential-bearing requests."""
import math
import httpx
from ..core import DomainError, public_url

ESTIMATE_CENTS={'search':5,'summary':10,'links':10}
PATHS={'search':'serp/google/organic/live/regular','summary':'backlinks/summary/live','links':'backlinks/backlinks/live'}

class Providers:
    def __init__(self,config):self.config=config
    def call(self,kind,payload):
        if kind not in PATHS:raise ValueError('Unknown provider operation')
        try:
            with httpx.Client(timeout=45,follow_redirects=False,trust_env=False) as client:
                r=client.post('https://api.dataforseo.com/v3/'+PATHS[kind],json=[payload],
                    auth=(self.config.dataforseo_login,self.config.dataforseo_password))
            if r.status_code!=200:raise DomainError(f'DataForSEO returned HTTP {r.status_code}. Check the account console.')
            if len(r.content)>4_000_000:raise DomainError('Provider result exceeded the size limit.')
            data=r.json();tasks=data.get('tasks') or []
            if not tasks or tasks[0].get('status_code')!=20000:raise DomainError('DataForSEO did not complete the request. Reconcile any charge in the provider console.')
            task=tasks[0];results=task.get('result') or []
            cost=math.ceil(float(task.get('cost',data.get('cost',0)) or 0)*100)
            if kind=='search':
                items=[]
                for item in (results[0].get('items',[]) if results else []):
                    if item.get('type')!='organic':continue
                    try:url=public_url(item.get('url',''),required=True)
                    except DomainError:continue
                    items.append({'url':url,'title':str(item.get('title',''))[:240],'description':str(item.get('description',''))[:1000]})
                return {'items':items[:10]},cost
            if kind=='summary':
                if not results:raise DomainError('Backlink summary was empty; authority remains unknown.')
                r=results[0]
                count=r.get('referring_main_domains',r.get('referring_domains'))
                if count is None:raise DomainError('Backlink summary omitted referring domains; authority remains unknown.')
                return {'status':'ok','referring_domains':max(0,int(count)),
                    'backlinks':int(r.get('backlinks',0) or 0),'rank':r.get('rank'),'spam_score':r.get('backlinks_spam_score')},cost
            links=[]
            for item in (results[0].get('items',[]) if results else []):
                try:
                    source=public_url(item.get('url_from',''),required=True);target=public_url(item.get('url_to',''),required=True)
                except DomainError:continue
                links.append({'source_url':source,'target_url':target,'anchor':str(item.get('anchor',''))[:300],
                    'dofollow':item.get('dofollow'),'last_seen':item.get('last_seen'),'provider_rank':item.get('domain_from_rank')})
            return {'links':links[:20]},cost
        except DomainError:raise
        except Exception:raise DomainError('Provider request outcome is uncertain. Check billing before retrying.') from None

    def opr(self,domain):
        if not self.config.opr_key:return {'status':'not_configured','value':None}
        try:
            with httpx.Client(timeout=20,follow_redirects=False,trust_env=False) as c:
                r=c.get('https://openpagerank.com/api/v1.0/getPageRank',params={'domains[]':domain},headers={'API-OPR':self.config.opr_key})
            if r.status_code!=200 or len(r.content)>100000:return {'status':'unavailable','value':None}
            items=r.json().get('response') or []
            if not items or items[0].get('status_code')!=200:return {'status':'unknown','value':None}
            return {'status':'ok','value':items[0].get('page_rank_decimal')}
        except Exception:return {'status':'unavailable','value':None}
