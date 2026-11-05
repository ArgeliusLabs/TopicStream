"""Explainable recurring coordination leads, not an authenticity classifier.

Edges retain their supporting events. Recurrence is required across independent
time episodes; correlated text/link observations do not count as two episodes.
The shuffled comparison is a sensitivity diagnostic, not a calibrated p-value.
"""
import collections
import itertools
import math
import random
from datetime import timedelta
from . import analyze as A
from .identity import account_key, post_key, digest, normalized_url
from .sources import parse_time, iso
from .scope import complete_coverage

VERSION = 'recurrence-1'
DEFAULTS = {'window_minutes':10,'episode_gap_minutes':60,'min_episodes':3,'min_days':2,
            'min_accounts':3,'max_event_accounts':100,'max_posts':20000,'baseline_repeats':5}


def _traces(p):
    if not p['is_repost']:
        text=A._norm_text(p['text'])
        if len(text)>=40: yield 'text',text
        for url in sorted({normalized_url(u) for u in p['links']} - {''}): yield 'link',url
    if p.get('referenced_post_id') and p.get('reference_type') in ('repost','reply','quote'):
        yield 'amplification',p['source']+':'+p['reference_type']+':'+p['referenced_post_id']


def _events(posts,settings):
    traces=collections.defaultdict(list)
    for p in posts:
        for trace in _traces(p): traces[trace].append(p)
    events=[]; ignored=0
    window=timedelta(minutes=settings['window_minutes'])
    for (family,trace),rows in sorted(traces.items()):
        rows.sort(key=lambda p:(p['created_utc'],post_key(p)))
        popularity=len({account_key(p) for p in rows})
        i=0
        while i<len(rows):
            start=parse_time(rows[i]['created_utc']); j=i+1
            while j<len(rows) and parse_time(rows[j]['created_utc'])-start<=window: j+=1
            inside=rows[i:j]; accounts=sorted({account_key(p) for p in inside})
            if len(accounts)>settings['max_event_accounts']:
                ignored+=1; i=j; continue
            if len(accounts)>=2:
                keys=sorted({post_key(p) for p in inside})
                events.append({'id':digest([family,trace,keys])[:20],'family':family,'trace':trace,
                               'start':inside[0]['created_utc'],'end':inside[-1]['created_utc'],
                               'accounts':accounts,'post_keys':keys,'specificity':1/math.log2(2+popularity)})
                i=j
            else: i+=1
    return sorted(events,key=lambda e:(e['start'],e['id'])),ignored


def _edges(events,settings):
    pairs=collections.defaultdict(list)
    for e in events:
        for pair in itertools.combinations(e['accounts'],2): pairs[pair].append(e)
    out=[]; gap=timedelta(minutes=settings['episode_gap_minutes'])
    for (a,b),support in sorted(pairs.items()):
        episodes=[]
        for event in sorted(support,key=lambda e:e['start']):
            timestamp=parse_time(event['start'])
            if not episodes or timestamp-episodes[-1]['last']>gap:
                episodes.append({'start':timestamp,'last':timestamp,'events':[event]})
            else:
                episodes[-1]['last']=timestamp; episodes[-1]['events'].append(event)
        days={ep['start'].date().isoformat() for ep in episodes}
        if len(episodes)<settings['min_episodes'] or len(days)<settings['min_days']: continue
        score=sum(max(e['specificity'] for e in ep['events']) for ep in episodes)
        out.append({'a':a,'b':b,'episodes':len(episodes),'days':len(days),
                    'families':sorted({e['family'] for e in support}),'weight':round(score,4),
                    'event_ids':sorted({e['id'] for e in support})})
    return out


def _components(edges,min_accounts):
    adjacent=collections.defaultdict(set)
    for e in edges: adjacent[e['a']].add(e['b']); adjacent[e['b']].add(e['a'])
    seen=set(); groups=[]
    for node in sorted(adjacent):
        if node in seen: continue
        stack=[node]; members=set()
        while stack:
            current=stack.pop()
            if current in members: continue
            members.add(current); stack.extend(adjacent[current]-members)
        seen.update(members)
        if len(members)>=min_accounts: groups.append(sorted(members))
    return groups


def _baseline(posts,settings,seed):
    """Shuffle timestamps within each source and UTC day, preserving daily volume.

    Account daily activity, content popularity and source-wide timestamp sets
    remain fixed. Within-day individual schedules do not: disclose this limit.
    """
    buckets=collections.defaultdict(list)
    for i,p in enumerate(posts): buckets[(p['source'],p['created_utc'][:10])].append(i)
    samples=[]; rng=random.Random(seed)
    for _ in range(settings['baseline_repeats']):
        shuffled=[dict(p) for p in posts]
        for indices in buckets.values():
            times=[posts[i]['created_utc'] for i in indices]; rng.shuffle(times)
            for i,t in zip(indices,times): shuffled[i]['created_utc']=t
        events,_=_events(shuffled,settings)
        samples.append(len(_edges(events,settings)))
    return {'method':'timestamps shuffled within source and UTC day','repeats':len(samples),
            'recurring_edges_per_shuffle':samples,
            'median_edges':sorted(samples)[len(samples)//2] if samples else None,
            'limitation':'Diagnostic only: breaks individual within-day schedules and cannot model every benign organizer. Not a p-value or CIB probability.'}


def analyze(posts,coverage=(),config=None,scope=None):
    settings=dict(DEFAULTS); settings.update(config or {})
    for key in DEFAULTS:
        if not isinstance(settings[key],int) or settings[key]<1: raise ValueError(f'{key} must be a positive integer')
    if settings['window_minutes']>settings['episode_gap_minutes']: raise ValueError('Episode gap must be at least the match window')
    if settings['max_event_accounts']>200 or settings['max_posts']>50000 or settings['baseline_repeats']>20:
        raise ValueError('Detector limits exceed local safety bounds')
    rows=sorted(posts,key=lambda p:(p['created_utc'],post_key(p)))
    dataset=digest(rows); truncated=len(rows)>settings['max_posts']; rows=rows[:settings['max_posts']]
    events,ignored=_events(rows,settings); edges=_edges(events,settings)
    event_map={e['id']:e for e in events}; groups=[]
    for members in _components(edges,settings['min_accounts']):
        member_set=set(members); relevant=[e for e in edges if e['a'] in member_set and e['b'] in member_set]
        ids=sorted({eid for e in relevant for eid in e['event_ids']})
        support=[event_map[eid] for eid in ids]
        density=2*len(relevant)/(len(members)*(len(members)-1))
        groups.append({'id':digest(members)[:20],'accounts':members,'edges':relevant,'event_ids':ids,
                       'post_keys':sorted({key for e in support for key in e['post_keys']}),
                       'first':min(e['start'] for e in support),'last':max(e['end'] for e in support),
                       'families':sorted({e['family'] for e in support}),'density':round(density,3),
                       'ranking_score':round(sum(e['weight'] for e in relevant)/len(members),3),
                       'assessment':'Coordination lead; authenticity unresolved',
                       'alternatives':['Breaking news or a shared published source','Open advocacy, syndication, or disclosed organizing','Accounts operated by the same publicly identified organization'],
                       'explanation':f'{len(relevant)} account pairs recur in at least {settings["min_episodes"]} episodes across {settings["min_days"]} days. Connected members need not all coordinate with each other.'})
    groups.sort(key=lambda g:(-g['ranking_score'],g['id']))
    identity={account_key(p):{'id':account_key(p),'handle':p['author'],'source':p['source'],'stable_id_available':bool(p.get('author_uri') if p['source']=='mastodon' else p.get('author_id'))} for p in rows}
    sufficient=(bool(rows) and complete_coverage(coverage,scope) and not truncated and not ignored
                and all(a['stable_id_available'] for a in identity.values()))
    if groups: assessment='Coordination leads found; authenticity unresolved'
    elif sufficient: assessment='No strong recurring coordination detected in the observed data'
    else: assessment='Insufficient evidence for a negative assessment'
    baseline=_baseline(rows,settings,dataset) if len(rows)>1 else {'method':'unavailable','repeats':0,'recurring_edges_per_shuffle':[],'median_edges':None,'limitation':'Too few posts'}
    run_id=digest([dataset,VERSION,settings,scope,coverage])
    return {'run_id':run_id,'version':VERSION,'dataset_hash':dataset,'settings':settings,'scope':scope or {},
            'assessment':assessment,'authenticity':'Unresolved; public behavior alone does not establish deception',
            'posts_observed':len(posts),'posts_analyzed':len(rows),'accounts':identity,'groups':groups,
            'events':events,'recurring_edges':len(edges),'baseline':baseline,'coverage':list(coverage),
            'limits':{'truncated_posts':truncated,'high_volume_events_not_compared':ignored,
                      'missing_stable_id_accounts':sum(not a['stable_id_available'] for a in identity.values()),
                      'coverage_complete_for_observed_queries':sufficient},
            'interpretation':'Ranking scores are not probabilities. Review supporting posts and benign alternatives before assessing inauthenticity.'}
