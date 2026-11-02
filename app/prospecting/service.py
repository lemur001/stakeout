"""Discovery persistence and explicit spending approvals. No discovery operation approves outreach."""
import json
from datetime import timedelta
from ..core import DomainError,iso,utcnow,normalize_name
from ..service import uid,loadj
from .models import HuntInput
from .providers import ESTIMATE_CENTS

class Discovery:
    def __init__(self,service):self.service=service;self.db=service.db;self.config=service.config
    def required(self,tx,id):
        row=tx.one('SELECT * FROM discovery_runs WHERE id=?',(id,))
        if not row:raise DomainError('Hunt not found.',404)
        return row

    def create(self,data:HuntInput,actor):
        if not data.rights_acknowledged or not self.config.source_rights_approved:
            raise DomainError('Confirm source retrieval and storage permissions in Connections and on this hunt.')
        if (data.use_web or data.use_backlinks) and not (self.config.dataforseo_login and self.config.dataforseo_password):
            raise DomainError('Save DataForSEO credentials in encrypted Connections before approving paid checks.')
        with self.db.transaction() as tx:
            self.service.required(tx,'cities',data.city_id)
            day=iso(utcnow().replace(hour=0,minute=0,second=0,microsecond=0))
            count=tx.one('SELECT COUNT(*) AS n FROM discovery_runs WHERE created_at>=?',(day,))['n']+tx.one('SELECT COUNT(*) AS n FROM research_runs WHERE created_at>=?',(day,))['n']
            if count>=self.config.daily_research_limit:raise DomainError('The daily hunt limit has been reached.',429)
            id=uid()
            tx.execute('INSERT INTO discovery_runs(id,city_id,campaign,state,params_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                (id,data.city_id,data.campaign,'queued',data.model_dump_json(),iso(),iso()))
            self.service.audit(tx,actor,'discovery.created',id,f'{data.campaign}; approved estimate envelope {data.budget_cents} cents')
            return self.required(tx,id)

    def list(self):
        with self.db.transaction(False) as tx:
            runs=tx.all('SELECT * FROM discovery_runs ORDER BY created_at DESC LIMIT 100')
        for r in runs:
            r['params']=loadj(r.pop('params_json'),{});r.pop('lease_owner',None);r.pop('lease_until',None)
        return runs

    def detail(self,id):
        with self.db.transaction(False) as tx:
            r=self.required(tx,id)
            rows=tx.all('SELECT t.*,e.name,e.campaign AS entity_campaign FROM discovery_targets t JOIN entities e ON e.id=t.entity_id WHERE run_id=?',(id,))
            ledger=tx.all('SELECT operation,state,reserved_cents,actual_cents,created_at FROM discovery_spend WHERE run_id=?',(id,))
        for row in rows:
            row['facts']=loadj(row.pop('facts_json'),{});row['result']=loadj(row.pop('result_json'),{})
        rows.sort(key=lambda r:-(r['result'].get('scores',{}).get('fit') or 0))
        r['params']=loadj(r.pop('params_json'),{});r.pop('lease_owner',None);r.pop('lease_until',None)
        return {'run':r,'targets':rows,'spend':ledger}

    def export_csv(self,id):
        import csv,io
        from ..core import clean_csv_cell
        data=self.detail(id);out=io.StringIO(newline='');writer=csv.writer(out)
        writer.writerow(['Organization','Campaign','Check status','Website candidate','EIN','Distance miles','Revenue USD','Filing year','Project fit','Link opportunity','Evidence confidence','Referring domains','Evidence gaps'])
        for row in data['targets']:
            r=row['result'];s=r.get('scores',{});f=r.get('facts',row['facts'])
            values=[row['name'],data['run']['campaign'],row['state'],r.get('site',{}).get('url',''),f.get('ein',''),f.get('distance'),f.get('revenue'),f.get('filing_year'),s.get('fit'),s.get('link_opportunity'),s.get('confidence'),r.get('backlinks',{}).get('referring_domains'),' | '.join(s.get('gaps',[]))]
            writer.writerow([clean_csv_cell('' if v is None else str(v)) for v in values])
        return '\ufeff'+out.getvalue()

    def control(self,id,action,actor):
        with self.db.transaction() as tx:
            r=self.required(tx,id)
            if action=='pause':state='paused'
            elif action=='resume':
                if r['state'] not in ('paused','failed','completed'):raise DomainError('Pause the hunt before resuming it.')
                # Completed targets stay cached; failed/unavailable targets can retry without repeating paid calls.
                if r['state']=='completed':tx.execute("UPDATE discovery_targets SET state='pending',attempts=0 WHERE run_id=?",(id,))
                else:tx.execute("UPDATE discovery_targets SET state='pending',attempts=0 WHERE run_id=? AND state='failed'",(id,))
                state='enriching' if r['total'] else 'queued'
            else:raise DomainError('Unknown hunt action.')
            tx.execute('UPDATE discovery_runs SET state=?,error=\'\',updated_at=? WHERE id=?',(state,iso(),id))
            if action=='resume':
                completed=tx.one("SELECT COUNT(*) AS n FROM discovery_targets WHERE run_id=? AND state IN ('complete','failed')",(id,))['n']
                tx.execute('UPDATE discovery_runs SET completed=? WHERE id=?',(completed,id))
            self.service.audit(tx,actor,'discovery.'+action,id)
            return self.required(tx,id)

    def add_targets(self,run,orgs):
        with self.db.transaction() as tx:
            current=self.required(tx,run['id'])
            for org in orgs:
                if not org.get('name'):continue
                found=tx.one('SELECT e.* FROM entities e JOIN discovery_identity i ON i.entity_id=e.id WHERE i.ein=?',(org['ein'],)) if org.get('ein') else None
                if not found:found=tx.one('SELECT * FROM entities WHERE city_id=? AND canonical_name=?',(run['city_id'],normalize_name(org['name'])))
                if found and found['state']=='suppressed':continue
                if found:id=found['id']
                else:
                    id=uid()
                    tx.execute('INSERT INTO entities(id,city_id,name,canonical_name,category,campaign,source_note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                        (id,run['city_id'],org['name'],normalize_name(org['name']),'specialized_nonprofit',run['campaign'],
                         'Discovered candidate; website identity, activity and contacts require review.',iso(),iso()))
                if org.get('ein'):
                    existing=tx.one('SELECT ein FROM discovery_identity WHERE entity_id=?',(id,))
                    if existing and existing['ein']!=org['ein']:
                        # Same name with a different EIN is a separate chapter or organization; never merge it.
                        id=uid();name=org['name']+' ('+org['ein']+')'
                        prior=tx.one('SELECT id FROM entities WHERE city_id=? AND canonical_name=?',(run['city_id'],normalize_name(name)))
                        if prior:id=prior['id']
                        else:tx.execute('INSERT INTO entities(id,city_id,name,canonical_name,category,campaign,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(id,run['city_id'],name,normalize_name(name),'specialized_nonprofit',run['campaign'],iso(),iso()))
                    tx.execute('INSERT INTO discovery_identity(ein,entity_id) VALUES(?,?) ON CONFLICT(ein) DO NOTHING',(org['ein'],id))
                tx.execute('INSERT INTO discovery_targets(run_id,entity_id,facts_json) VALUES(?,?,?) ON CONFLICT(run_id,entity_id) DO NOTHING',(run['id'],id,json.dumps(org)))
            total=tx.one('SELECT COUNT(*) AS n FROM discovery_targets WHERE run_id=?',(run['id'],))['n']
            state='paused' if current['state']=='paused' else 'enriching'
            tx.execute('UPDATE discovery_runs SET state=?,total=?,updated_at=? WHERE id=?',(state,total,iso(),run['id']))

    def evidence(self,run_id,entity_id,kind,url,status,observation):
        encoded=json.dumps(observation)
        if len(encoded)>100000:raise DomainError('Observation exceeds the storage limit.')
        with self.db.transaction() as tx:
            tx.execute('INSERT INTO discovery_evidence(id,run_id,entity_id,kind,url,status,observation_json,observed_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (uid(),run_id,entity_id,kind,url,status,encoded,iso(),iso(utcnow()+timedelta(days=21 if status=='ok' else 1))))

    def paid(self,run_id,entity_id,operation,kind,payload,provider):
        operation=entity_id+':'+operation;estimate=ESTIMATE_CENTS[kind]
        with self.db.transaction() as tx:
            run=self.required(tx,run_id);params=loadj(run['params_json'],{})
            prior=tx.one('SELECT * FROM discovery_spend WHERE run_id=? AND operation=?',(run_id,operation))
            if prior:
                if prior['state']=='complete':return loadj(prior['result_json'],{})
                raise DomainError('An earlier paid check has an uncertain outcome; it will not be repeated automatically.')
            if run['state']=='paused':raise DomainError('The hunt was paused.')
            if not params.get('paid_approved') or run['spent_cents']+run['reserved_cents']+estimate>params['budget_cents']:
                raise DomainError('The approved estimate envelope is exhausted. Start a new approved hunt to spend more.')
            id=uid()
            tx.execute('INSERT INTO discovery_spend(id,run_id,entity_id,operation,state,reserved_cents,created_at) VALUES(?,?,?,?,?,?,?)',(id,run_id,entity_id,operation,'pending',estimate,iso()))
            tx.execute('UPDATE discovery_runs SET reserved_cents=reserved_cents+? WHERE id=?',(estimate,run_id))
        try:result,cost=provider.call(kind,payload)
        except Exception:
            with self.db.transaction() as tx:tx.execute("UPDATE discovery_spend SET state='unknown' WHERE id=?",(id,))
            raise
        with self.db.transaction() as tx:
            tx.execute("UPDATE discovery_spend SET state='complete',actual_cents=?,result_json=? WHERE id=?",(cost,json.dumps(result),id))
            tx.execute('UPDATE discovery_runs SET reserved_cents=reserved_cents-?,spent_cents=spent_cents+? WHERE id=?',(estimate,cost,run_id))
        return result
