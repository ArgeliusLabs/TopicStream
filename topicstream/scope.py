"""Explicit case bounds shared by reports, detectors and collection."""
from datetime import timedelta
from .sources import parse_time, iso, utcnow


def labels(cfg):
    return ['#' + t.lower().lstrip('#') for t in cfg.get('tags', [])] + [t.lower() for t in cfg.get('terms', [])]


def collection_bounds(cfg, now=None):
    now = now or utcnow()
    end = parse_time(cfg['end_utc']) if cfg.get('end_utc') else now
    start = parse_time(cfg['start_utc']) if cfg.get('start_utc') else end - timedelta(days=int(cfg.get('days',7)))
    if start >= end: raise ValueError('Start must be before end')
    return start, end


def selected_posts(store,cfg,now=None):
    start,end=collection_bounds(cfg,now)
    # Preserve useful retrospective CLI reports when no fixed case dates exist.
    if not cfg.get('start_utc') and not cfg.get('end_utc'):
        row=store.db.execute('SELECT MAX(created_utc) FROM posts').fetchone()[0]
        if row:
            end=parse_time(row).replace(hour=0,minute=0,second=0)+timedelta(days=1)
            start=end-timedelta(days=int(cfg.get('days',7)))
    wanted=set(labels(cfg)); excludes=[v.casefold() for v in cfg.get('exclude_terms',[]) if v]
    languages=set(cfg.get('languages',[]))
    posts=[p for p in store.posts(iso(start),iso(end)) if wanted.intersection(p['matched'])
           and not any(term in p['text'].casefold() for term in excludes)
           and (not languages or p['lang'] in languages)]
    return posts,start,end


def in_scope(row,start,end,label_set,time_key='start_utc'):
    return row.get('tag',row.get('label')) in label_set and start <= parse_time(row[time_key]) < end


def covers_burst(burst,windows,query_hashes=None):
    """Every contributing source and term, and the entire interval, must be covered."""
    start,end=parse_time(burst['start']),parse_time(burst.get('end') or burst['start'])
    sources=burst.get('sources',[]); terms=burst.get('matched',[])
    if not sources or not terms: return False
    for source in sources:
        if not all(any(w.get('status')=='exhausted' and w['source']==source and w['tag']==term
                   and parse_time(w['start_utc'])<=start and end<parse_time(w['end_utc'])
                   and (not query_hashes or w.get('query_hash') in query_hashes)
                   for w in windows) for term in terms): return False
    return True


def analysis_scope(cfg,start,end):
    from .xsource import X
    from .sources import queries
    xcfg=cfg.get('sources',{}).get('x',{})
    x=X(None,query_extra=xcfg.get('query_extra',''),archive=xcfg.get('archive',False))
    expected=[]
    for source,settings in cfg.get('sources',{}).items():
        if not settings.get('enabled'): continue
        for label,kind,raw in queries(cfg.get('tags',[]),cfg.get('terms',[])):
            expected.append({'source':source,'label':label,'query_hash':x.query_hash(raw,kind) if source=='x' else ''})
    return {'start_utc':iso(start),'end_utc':iso(end),'query_fingerprint':cfg.get('query_fingerprint'),
            'expected_queries':expected}


def complete_coverage(coverage,scope):
    """Require gap-free exhausted intervals for every enabled query in this scope."""
    if not scope or not scope.get('expected_queries'): return False
    start,end=parse_time(scope['start_utc']),parse_time(scope['end_utc'])
    for query in scope['expected_queries']:
        intervals=sorted((parse_time(c['start_utc']),parse_time(c['end_utc'])) for c in coverage
                         if all(c.get(k)==v for k,v in query.items())
                         and c.get('status')=='exhausted' and c.get('sampling')=='bounded search')
        cursor=start
        for a,b in intervals:
            if a>cursor: break
            cursor=max(cursor,b)
        if cursor<end: return False
    return True
