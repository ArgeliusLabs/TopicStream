"""Local case files, query planning, evidence exports, and durable job state."""
import csv
import io
import json
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .sources import Post, iso, utcnow, parse_time, matches, tags_in
from .identity import digest, normalized_url, post_key
from .store import Store
from .scope import selected_posts, collection_bounds, labels, analysis_scope
from . import detection


def save_json(path,value):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
    os.replace(temp,path)


def plan_topic(topic):
    topic=topic.strip()
    if not topic or len(topic)>1000: raise ValueError('Enter a topic of 1 to 1000 characters')
    tags=list(dict.fromkeys(t.lower() for t in re.findall(r'#(\w+)',topic)))[:8]
    quoted=re.findall(r'"([^"\n]+)"',topic)
    urls=re.findall(r'https?://\S+',topic)
    clean=re.sub(r'#\w+|https?://\S+',' ',topic)
    clean=re.sub(r'^(?:is there|investigate|look for|check|find|identify)\s+(?:(?:any|potential|coordinated|inauthentic|behavior|activity|around|about|on|the)\s+)*','',clean,flags=re.I).strip(' ?.!,')
    terms=quoted or ([normalized_url(urls[0])] if urls else ([clean] if clean else []))
    terms=[t[:120] for t in terms if t][:8]
    return {'topic':topic,'tags':tags,'terms':terms,'notes':['This is a deterministic draft, not an exhaustive topic search. Edit ambiguous wording and add aliases or translations.','X searches quoted phrases; Bluesky searches text; Mastodon collects hashtags and only matches phrases inside those results.'],
            'preview':{'x':['#'+t for t in tags]+['"'+t+'"' for t in terms], 'bluesky':tags+terms,'mastodon':['#'+t for t in tags]}}


def validated_config(body,folder):
    topic=str(body.get('topic','')).strip()
    plan=plan_topic(topic)
    def strings(key,default=()):
        values=body.get(key,list(default))
        if not isinstance(values,list) or len(values)>20 or any(not isinstance(v,str) or len(v)>200 for v in values): raise ValueError(f'Invalid {key}')
        return list(dict.fromkeys(v.strip() for v in values if v.strip()))
    tags=[t.lstrip('#').lower() for t in strings('tags',plan['tags'])]
    if any(not re.fullmatch(r'\w+',t) for t in tags): raise ValueError('Hashtags may contain letters, numbers, and underscores')
    terms=strings('terms',plan['terms'])
    if not tags and not terms: raise ValueError('Add at least one search term or hashtag')
    if any('"' in t or '\n' in t or '\r' in t for t in terms): raise ValueError('Terms cannot contain quotes or newlines')
    end=parse_time(body['end_utc']) if body.get('end_utc') else utcnow()
    start=parse_time(body['start_utc']) if body.get('start_utc') else end-timedelta(days=7)
    if start>=end or (end-start).days>366: raise ValueError('Choose a time range of up to 366 days, with start before end')
    sources=strings('sources',['mastodon','bluesky'])
    if any(s not in ('mastodon','bluesky','x') for s in sources): raise ValueError('Unsupported source')
    budget=float(body.get('budget_usd',2))
    if not 0<=budget<=10000: raise ValueError('Budget must be between 0 and 10000 USD')
    cfg={'name':topic,'case_id':folder.name,'tags':tags,'terms':terms,'exclude_terms':strings('exclude_terms'),
         'languages':strings('languages'),'start_utc':iso(start),'end_utc':iso(end),'days':max(1,(end-start).days+1),
         'db':str(folder/'evidence.sqlite'),'report':str(folder/'report.html'),'query_version':1,'pause_seconds':1,
         'sources':{'mastodon':{'enabled':'mastodon' in sources,'instances':['mastodon.social','infosec.exchange'],'max_pages':10},
                    'bluesky':{'enabled':'bluesky' in sources,'max_pages':10},
                    'x':{'enabled':'x' in sources,'max_posts_per_tag':200,'budget_usd':budget,'query_extra':'','archive':(utcnow()-start).days>=7,
                         'read_mode':'always','counts_every_minutes':60,'prices':{'post_read':.005,'counts_recent':.005,'counts_all':.010}}},
         'alert':{'window_minutes':30,'uses':200,'ratio':10,'uses_per_account':5,'min_uses':10},'detector':dict(detection.DEFAULTS)}
    cfg['query_fingerprint']=digest({k:cfg[k] for k in ('tags','terms','exclude_terms','languages','start_utc','end_utc','sources')})
    return cfg


class Cases:
    def __init__(self,root):
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='topicstream-case')
        self.lock=threading.RLock(); self.cancellations={}; self.futures={}
        for path in self.root.glob('*/job.json'):
            job=json.loads(path.read_text(encoding='utf-8'))
            if job['status'] in ('queued','running'):
                job.update(status='interrupted',message='Application restarted; completed pages are saved. Retry the job.'); save_json(path,job)

    def folder(self,case_id):
        if not re.fullmatch(r'[a-f0-9]{32}',case_id): raise ValueError('Invalid case ID')
        folder=self.root/case_id
        if not (folder/'config.json').is_file(): raise FileNotFoundError('Case not found')
        return folder

    def config(self,case_id): return json.loads((self.folder(case_id)/'config.json').read_text(encoding='utf-8'))

    def create(self,body):
        folder=self.root/uuid.uuid4().hex
        cfg=validated_config(body,folder)
        folder.mkdir(); save_json(folder/'config.json',cfg)
        save_json(folder/'case.json',{'id':folder.name,'topic':cfg['name'],'created_utc':iso(utcnow()),'synthetic':False})
        save_json(folder/'job.json',{'status':'idle','message':'Ready to import an export or collect from enabled sources','log':[]})
        with Store(cfg['db']): pass
        return self.detail(folder.name)

    def list(self):
        out=[]
        for path in self.root.glob('*/case.json'):
            meta=json.loads(path.read_text(encoding='utf-8')); job=json.loads((path.parent/'job.json').read_text(encoding='utf-8'))
            out.append(dict(meta,status=job['status']))
        return sorted(out,key=lambda x:x['created_utc'],reverse=True)

    def detail(self,case_id):
        folder=self.folder(case_id); cfg=self.config(case_id)
        meta=json.loads((folder/'case.json').read_text(encoding='utf-8')); job=json.loads((folder/'job.json').read_text(encoding='utf-8'))
        analysis=json.loads((folder/'analysis.json').read_text(encoding='utf-8')) if (folder/'analysis.json').exists() else None
        with Store(cfg['db']) as store:
            posts,start,end=selected_posts(store,cfg)
            reviews=store.reviews(); coverage=store.coverage(); spent=store.spent()
        public={k:v for k,v in cfg.items() if k not in ('db','report')}
        return {'case':meta,'config':public,'job':job,'analysis':analysis,'reviews':reviews,'coverage':coverage,'spent_usd':spent,'posts':len(posts)}

    def _log(self,folder,message,status='running'):
        with self.lock:
            job=json.loads((folder/'job.json').read_text(encoding='utf-8'))
            job.update(status=status,message=str(message),updated_utc=iso(utcnow()))
            job['log']=(job.get('log',[])+[str(message)])[-100:]; save_json(folder/'job.json',job)

    def _analyze(self,case_id):
        folder=self.folder(case_id); cfg=self.config(case_id)
        self._log(folder,'Analyzing recurring groups and comparison data')
        with Store(cfg['db']) as store:
            posts,start,end=selected_posts(store,cfg)
            result=detection.analyze(posts,store.coverage(),cfg.get('detector'),analysis_scope(cfg,start,end))
            store.save_analysis(result,iso(utcnow()),cfg.get('detector',{}),posts)
            save_json(folder/'analysis.json',result)
        from .__main__ import write_report
        write_report(cfg,log=lambda message:self._log(folder,message),result=result)
        return result

    def submit(self,case_id,kind):
        if kind not in ('collect','analyze'): raise ValueError('Unknown job type')
        folder=self.folder(case_id)
        with self.lock:
            existing=self.futures.get(case_id)
            if existing and not existing.done(): raise ValueError('A job is already running for this case')
            cancelled=threading.Event(); self.cancellations[case_id]=cancelled
            save_json(folder/'job.json',{'status':'queued','message':f'{kind.capitalize()} queued','kind':kind,'log':[]})
            future=self.executor.submit(self._run,case_id,kind,cancelled); self.futures[case_id]=future
        return {'status':'queued'}

    def _run(self,case_id,kind,cancelled):
        folder=self.folder(case_id); cfg=self.config(case_id)
        try:
            if cancelled.is_set(): self._log(folder,'Cancelled before starting','cancelled'); return
            if kind=='collect':
                from .__main__ import collect
                self._log(folder,'Collecting enabled sources; paid requests obey the case budget')
                cfg['_cancelled']=cancelled.is_set
                with collect(cfg,log=lambda m:self._log(folder,m)): pass
            if cancelled.is_set(): self._log(folder,'Cancelled; completed pages are saved','cancelled'); return
            self._analyze(case_id)
            self._log(folder,'Analysis ready. Review coverage and supporting evidence.','finished')
        except Exception as exc: self._log(folder,str(exc),'failed')

    def cancel(self,case_id):
        self.folder(case_id)
        if case_id in self.cancellations: self.cancellations[case_id].set()
        return {'status':'cancellation requested'}

    def import_text(self,case_id,text,source='import',profiles=None):
        with self.lock:
            return self._import_text(case_id,text,source,profiles)

    def _import_text(self,case_id,text,source='import',profiles=None):
        folder=self.folder(case_id)
        if source not in ('import','x','bluesky','mastodon'): raise ValueError('Invalid import source')
        if not isinstance(text,str) or len(text.encode('utf-8'))>10*1024*1024: raise ValueError('CSV must be text of at most 10 MB')
        if profiles is not None and (not isinstance(profiles,str) or len(profiles.encode('utf-8'))>1024*1024): raise ValueError('Profiles CSV must be text of at most 1 MB')
        if self.futures.get(case_id) and not self.futures[case_id].done(): raise ValueError('Wait for the current job before importing')
        reader=csv.DictReader(io.StringIO(text))
        if not {'timestamp_utc','handle','text'}.issubset(reader.fieldnames or []): raise ValueError('CSV requires timestamp_utc, handle, and text columns')
        if sum(1 for _ in reader)>50000: raise ValueError('Import at most 50000 rows per file')
        # Validate all rows before storing or changing case state.
        for index,row in enumerate(csv.DictReader(io.StringIO(text)),start=2):
            try:
                if not row['handle']: raise ValueError('missing handle')
                parse_time(row['timestamp_utc'])
                for metric in ('likes','reposts','replies'):
                    if row.get(metric) and int(row[metric])<0: raise ValueError('negative metric')
            except (ValueError,TypeError,KeyError) as exc: raise ValueError(f'CSV row {index}: {exc}') from exc
        path=folder/'import.csv'; path.write_text(text,encoding='utf-8')
        profile_path=None
        if profiles:
            profile_path=folder/'profiles.csv'; profile_path.write_text(profiles,encoding='utf-8')
        from .__main__ import import_csv
        try:
            import_csv(self.config(case_id),str(path),source,accounts=str(profile_path) if profile_path else None,log=lambda m:self._log(folder,m))
        except Exception as exc:
            self._log(folder,'Import failed: '+str(exc),'failed')
            raise
        self.submit(case_id,'analyze')
        return {'status':'queued'}

    def evidence(self,case_id,group_id):
        detail=self.detail(case_id); result=detail['analysis']
        group=next((g for g in (result or {}).get('groups',[]) if g['id']==group_id),None)
        if not group: raise FileNotFoundError('Group not found')
        keys=set(group['post_keys'])
        with Store(self.config(case_id)['db']) as store:
            posts=[p for p in store.analysis_posts(result['run_id']) if post_key(p) in keys]
        return {'group':group,'events':[e for e in result['events'] if e['id'] in group['event_ids']],'posts':posts,'dataset_hash':result['dataset_hash']}

    def review(self,case_id,body):
        if self.futures.get(case_id) and not self.futures[case_id].done(): raise ValueError('Wait for the current job before reviewing')
        result=self.detail(case_id)['analysis']
        if not result or body.get('dataset_hash')!=result['dataset_hash']: raise ValueError('The evidence changed; reopen this finding before saving a review')
        group_id=body.get('group_id')
        if group_id not in {g['id'] for g in result['groups']}: raise ValueError('Unknown group')
        assessment=body.get('assessment')
        if assessment not in ('unresolved','legitimate explanation','suspected inauthenticity','insufficient evidence'): raise ValueError('Unknown assessment')
        explanation=str(body.get('explanation','')).strip()
        if not explanation or len(explanation)>5000: raise ValueError('Add a review explanation of up to 5000 characters')
        evidence=body.get('evidence',[])
        if not isinstance(evidence,list) or any(k not in next(g['post_keys'] for g in result['groups'] if g['id']==group_id) for k in evidence): raise ValueError('Evidence must reference posts in this finding')
        if assessment=='suspected inauthenticity' and not evidence: raise ValueError('Select supporting evidence before recording suspected inauthenticity')
        with Store(self.config(case_id)['db']) as store: store.add_review(group_id,result['dataset_hash'],iso(utcnow()),assessment,explanation,evidence)
        from .__main__ import write_report
        write_report(self.config(case_id),log=lambda message:None,result=result)
        return {'status':'saved'}

    def export(self,case_id):
        detail=self.detail(case_id)
        with Store(self.config(case_id)['db']) as store:
            posts=store.analysis_posts(detail['analysis']['run_id']) if detail['analysis'] else selected_posts(store,self.config(case_id))[0]
            ledger=store.ledger()
        return dict(detail,evidence_posts=posts,request_ledger=ledger,exported_utc=iso(utcnow()),format_version=1)

    def demo(self):
        end=utcnow().replace(hour=0,minute=0,second=0); start=end-timedelta(days=7)
        detail=self.create({'topic':'Harbor water quality','terms':['harbor water'],'tags':[],'sources':[],'start_utc':iso(start),'end_utc':iso(end),'budget_usd':0})
        case_id=detail['case']['id']; cfg=self.config(case_id); rows=[]
        for day in range(1,6):
            for a in range(5):
                t=start+timedelta(days=day,hours=9,seconds=a*18)
                text=f'Harbor water quality public update for day {day}. Read the full environmental assessment and supporting evidence.'
                rows.append(Post('import','synthetic',f'group-{day}-{a}',iso(t),f'example_account_{a}',text,author_id=f'demo-{a}',links=[f'https://example.org/report/{day}?campaign=sample'],matched=['harbor water'],collected_utc=iso(end)))
            for a in range(32):
                t=start+timedelta(days=day,minutes=a*43)
                text=f'Harbor water observation {a} on day {day}; local discussion with independently worded notes number {a*day}.'
                rows.append(Post('import','synthetic',f'background-{day}-{a}',iso(t),f'public_example_{a}',text,author_id=f'public-{a}',matched=['harbor water'],collected_utc=iso(end)))
        with Store(cfg['db']) as store:
            store.add_posts(rows)
            store.record_coverage('import','demo','harbor water',iso(start),iso(end),'partial','synthetic demonstration; not real-world coverage',len(rows),'synthetic',iso(end))
        meta=detail['case']; meta['synthetic']=True; save_json(self.folder(case_id)/'case.json',meta)
        self.submit(case_id,'analyze')
        return {'id':case_id,'status':'queued'}

    def close(self):
        for event in self.cancellations.values(): event.set()
        self.executor.shutdown(wait=True,cancel_futures=True)
