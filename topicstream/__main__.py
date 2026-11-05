"""TopicStream: local investigations into recurring coordinated public activity.

Start the browser workspace: python -m topicstream serve
CLI: collect / report / run / watch / import-csv / estimate / usage / discover / peak.
Search coverage and behavior patterns do not establish inauthenticity.
Credentials come from environment variables or a local .env file.
"""
import argparse, json, sys, time, csv, traceback
from datetime import timedelta
from pathlib import Path
from .store import Store
from .sources import Http, build_sources, utcnow, iso, Post, matches, tags_in, parse_time, load_dotenv, X
from . import report as R
from . import analyze as A
from .scope import collection_bounds, selected_posts, labels
from .monitor import count_alerts, post_alerts
from .identity import digest
from .store import BudgetExceeded

def load_cfg(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8')); cfg['_dir'] = str(Path(path).resolve().parent)
    cfg['_dotenv'] = load_dotenv([Path(cfg['_dir']) / '.env', Path('.env')])
    cfg.setdefault('tags', []); cfg.setdefault('terms', []); cfg.setdefault('days', 7); cfg.setdefault('db', 'topicstream.sqlite'); cfg.setdefault('report', 'topicstream_report.html')
    if not cfg['tags'] and not cfg['terms']: sys.exit('config needs at least one entry in "tags" or "terms"')
    return cfg

def tracked(cfg): return ['#' + t.lower() for t in cfg['tags']] + [t.lower() for t in cfg['terms']]

def collect(cfg, log=print):
    now=utcnow(); since,until=collection_bounds(cfg,now)
    store=Store(cfg['db']); run_id=store.start_run(iso(now))
    notes={}; local=dict(cfg); local['sources']={k:dict(v) for k,v in cfg.get('sources',{}).items()}
    local['_until']=until
    local['_on_page']=lambda posts:store.add_posts([p for p in posts if since<=parse_time(p.created_utc)<until])
    local['_scope_key']=digest([cfg.get('start_utc'),cfg.get('end_utc')]) if cfg.get('start_utc') or cfg.get('end_utc') else ''
    xcfg=local['sources'].setdefault('x',{})
    xcfg.update(_store=store,_spent_before=store.spent('x'))
    http=Http(pause=float(cfg.get('pause_seconds',1.0)),log=log,cancelled=cfg.get('_cancelled'))
    try:
        for src in build_sources(local,http,log):
            if cfg.get('_cancelled',lambda:False)(): break
            log(f'Collecting {src.name}')
            before=len(store.posts()); entry={}
            try:
                if hasattr(src,'available') and not src.available():
                    entry['status']='unavailable'; entry['error']='Credentials missing'
                    for tag in tracked(cfg): store.record_coverage(src.name,'',tag,iso(since),iso(until),'unavailable','credentials missing',0,'search',iso(now))
                    continue
                if src.name=='x':
                    src.tag_days(cfg['tags'],now,since,cfg['terms'])
                    if xcfg.get('read_mode','always')!='on_alert': src.posts(cfg['tags'],cfg['terms'],since,now)
                    else: log('  Counts-only monitoring; qualifying hours are queued below')
                else:
                    store.add_tag_days(src.tag_days(cfg['tags'],now))
                    posts=[p for p in src.posts(cfg['tags'],cfg['terms'],since,now) if parse_time(p.created_utc)<until]
                    store.add_posts(posts)
                    for tag in tracked(cfg):
                        store.record_coverage(src.name,'',tag,iso(since),iso(until),'partial','search or server visibility limits',sum(tag in p.matched for p in posts),'bounded search',iso(now))
                entry.update(status='finished',new=len(store.posts())-before,posts=len(store.posts())-before)
            except (Exception,SystemExit) as exc:
                entry.update(status='interrupted',error=str(exc)); log(f'  {src.name}: {exc}')
                if src.name!='x' or not src.coverage_rows:
                    for tag in tracked(cfg): store.record_coverage(src.name,'',tag,iso(since),iso(until),'failed',type(exc).__name__,0,'search',iso(now))
            finally:
                if getattr(src,'spent',0): entry['spent_usd']=round(src.spent,6)
                notes[src.name]=entry
        al=cfg.get('alert',{}); posts,_,_=selected_posts(store,cfg,now)
        for alert in post_alerts(posts,now,int(al.get('window_minutes',30)),int(al.get('uses',200)),float(al.get('ratio',10)),float(al.get('uses_per_account',5)),int(al.get('min_uses',10))):
            if store.add_monitor_alert(alert['source'],alert['tag'],alert['start'],int(al.get('window_minutes',30)),alert,iso(now)):
                log(f'ALERT {alert["tag"]}: {"; ".join(alert["reasons"])}')
        x=X(http,log,store=store,budget_usd=xcfg.get('budget_usd',2),query_extra=xcfg.get('query_extra',''),archive=xcfg.get('archive',False),prices=xcfg.get('prices'))
        fingerprints={x.query_hash(raw,kind) for _,kind,raw in __import__('topicstream.sources',fromlist=['queries']).queries(cfg['tags'],cfg['terms'])}
        counts=[r for r in store.counts() if r['tag'] in tracked(cfg) and since<=parse_time(r['start_utc'])<until and r.get('query_hash') in fingerprints]
        tripped=count_alerts(counts,now,int(al.get('uses',200)),float(al.get('ratio',10)),int(al.get('min_uses',10)))
        for alert in tripped:
            if store.add_monitor_alert('x-counts',alert['tag'],alert['start'],60,alert,iso(now)):
                log(f'ALERT {alert["tag"]}: {"; ".join(alert["reasons"])}')
        if tripped and xcfg.get('read_mode')=='on_alert' and not cfg.get('_cancelled',lambda:False)():
            buy_windows(cfg,store,[(a['tag'],a['start'],a['uses']) for a in tripped],log)
    except BaseException:
        store.finish_run(run_id,iso(utcnow()),notes); store.close(); raise
    store.finish_run(run_id,iso(utcnow()),notes)
    return store


def buy_windows(cfg,store,wanted,log=print,dry=False):
    from .sources import queries
    xcfg=cfg.get('sources',{}).get('x',{}); now=utcnow()
    x=X(Http(pause=float(cfg.get('pause_seconds',1)),log=log),log,store=store,budget_usd=xcfg.get('budget_usd',2),
        query_extra=xcfg.get('query_extra',''),archive=xcfg.get('archive',False),prices=xcfg.get('prices'),cancelled=cfg.get('_cancelled'))
    by_label={label:(kind,raw) for label,kind,raw in queries(cfg['tags'],cfg['terms'])}
    plan=[]
    for label,start,expected in wanted:
        start=iso(parse_time(start))
        if label not in by_label or any(label==l and start==st for l,st,_ in plan): continue
        kind,raw=by_label[label]; previous=x.archive
        if now-parse_time(start)>=timedelta(days=7): x.archive=True
        fingerprint=x.query_hash(raw,kind); x.archive=previous
        if any(w['tag']==label and w['start_utc']==start and w['status']=='exhausted' and w['query_hash']==fingerprint for w in store.windows()): continue
        plan.append((label,start,expected))
    if not plan: log('No unfinished requested windows'); return 0
    estimate=sum(expected for _,_,expected in plan)*x.prices['post_read']
    log(f'{len(plan)} window(s), estimated ${estimate:.4f}; requests also reserve their full page cost before reading')
    if dry or not x.available(): return 0
    run=store.start_run(iso(now)); total=0; errors=[]
    try:
        for label,start,expected in plan:
            kind,raw=by_label[label]; t0=parse_time(start); t1=t0+timedelta(hours=1)
            try:
                posts=x.read_window(raw,kind,t0,t1,cfg['tags'],cfg['terms'],now,expected,cap=int(xcfg.get('window_cap',5000)))
                total+=len(posts)
            except (Exception,SystemExit) as exc:
                errors.append(str(exc)); log(f'Window remains partial: {exc}')
            state=x.last_window
            if state:
                prev=x.archive
                if now-t0>=timedelta(days=7): x.archive=True
                fingerprint=x.query_hash(raw,kind); x.archive=prev
                store.add_window('x',label,start,iso(t1),expected,state.get('got',0),iso(now),state.get('status','partial'),state.get('stop_reason',''),state.get('next_token'),fingerprint)
            if errors: break
    finally:
        store.finish_run(run,iso(utcnow()),{'x':{'windows':len(plan),'posts':total,'spent_usd':round(x.spent,6),'errors':errors},'peak':True})
    return total


def top_hours(store, labels, hours=1, at=None, cfg=None):
    """The busiest hours per label from the counts table, or the one hour named by `at` (an ISO time; snapped to the hour)."""
    counts = store.counts('x'); out = []
    if cfg:
        from .scope import analysis_scope
        start,end=collection_bounds(cfg)
        hashes={q['query_hash'] for q in analysis_scope(cfg,start,end)['expected_queries'] if q['source']=='x'}
        counts=[c for c in counts if start<=parse_time(c['start_utc'])<end and c.get('query_hash') in hashes]
    for label in labels:
        rows = [c for c in counts if c['tag'] == label]
        if at:
            hour = at[:13] + ':00:00'
            rows = [c for c in rows if c['start_utc'][:13] == hour[:13]]
        for c in sorted(rows, key=lambda c: -c['uses'])[:hours]: out.append((label, c['start_utc'], c['uses']))
    return out

def peak(cfg, hours=1, at=None, label=None, dry=False, log=print):
    """Read selected hours up to the budget/page cap; retain partial pagination state."""
    store = Store(cfg['db']); labels = [label] if label else tracked(cfg)
    wanted = top_hours(store, labels, hours, at, cfg)
    if not wanted: log('no counts stored for those terms yet: run collect first'); store.close(); return
    try: n = buy_windows(cfg, store, wanted, log, dry)
    finally: store.close()
    if n: write_report(cfg, log)

def write_report(cfg, log=print, result=None):
    out = Path(cfg['report']); out.parent.mkdir(parents=True,exist_ok=True)
    with Store(cfg['db']) as store:
        out.write_text(R.render(store,cfg,result=result),encoding='utf-8')
    log(f'report: {out}'); return out

def _pick(r, *names):
    for n in names:
        if r.get(n) not in (None, ''): return r[n]
    return None

def import_csv(cfg, path, source, log=print, accounts=None, now=None):
    """Load a posts CSV with the Day 6 export columns (timestamp_utc, handle, text, link, content_type, likes, reposts, replies, lang,
    post_id, in_reply_to). With --accounts, a profiles CSV (handle, created_utc, followers, posts_total; a few aliases accepted) fills
    account age, followers and lifetime posts, which the account signals and creation clusters need. `now` fixes the collected
    time (and the run record) for reproducible builds."""
    now = iso(now or utcnow()); rows = []; prof = {}
    if accounts:
        with open(accounts, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                h = _pick(r, 'handle', 'username', 'screen_name', 'author')
                if h: prof[h.lstrip('@')] = r
        log(f'account profiles: {len(prof)} from {accounts}')
    def when(v): return iso(parse_time(v))
    with open(path, encoding='utf-8') as f: raw = list(csv.DictReader(f))
    by_id = {r['post_id']: r['handle'] for r in raw if r.get('post_id')}          # in_reply_to names a post; the signal wants the account
    for r in raw:
        text = r.get('text', ''); link = r.get('link') or ''; a = prof.get(r['handle'].lstrip('@'), {}); parent = r.get('in_reply_to') or ''
        replied = by_id.get(parent) or (parent.lstrip('@') if parent and not parent.startswith('P-') and ' ' not in parent else None)
        created = _pick(a, 'created_utc', 'created_at', 'account_created', 'joined'); followers = _pick(a, 'followers', 'followers_count'); total = _pick(a, 'posts_total', 'statuses_count', 'posts_count', 'post_count')
        rows.append(Post(source=source, instance=source, post_id=r.get('post_id') or digest([r['handle'],r['timestamp_utc'],text,link]), created_utc=when(r['timestamp_utc']),
                         author=r['handle'], author_id=_pick(r,'author_id','account_id','did') or _pick(a,'author_id','account_id','did'), author_uri=_pick(r,'author_uri') or _pick(a,'author_uri'), text=text, lang=r.get('lang'), is_repost=r.get('content_type', 'post') == 'repost',
                         reposts=int(r['reposts']) if r.get('reposts') else None, likes=int(r['likes']) if r.get('likes') else None, replies=int(r['replies']) if r.get('replies') else None,
                         is_reply=bool(parent) or r.get('content_type') == 'reply', reply_to=replied, reference_type=r.get('content_type') if r.get('content_type') in ('repost','reply','quote') else None, referenced_post_id=_pick(r,'referenced_post_id','in_reply_to'),
                         author_created_utc=when(created) if created else None, author_followers=int(followers) if followers else None, author_posts=int(total) if total else None,
                         matched=matches(text, cfg['tags'], cfg['terms']), tags=tags_in(text), links=[link] if link else [], collected_utc=now))
    store = Store(cfg['db'])
    try:
        run_id = store.start_run(now)
        n = store.add_posts(rows); log(f'imported {len(rows)} rows, {n} new, from {path}')
        store.finish_run(run_id, now, {'import': dict(file=Path(path).name, rows=len(rows), new=n, source=source, accounts=len(prof) if accounts else None)})
        if rows:
            for label in tracked(cfg): store.record_coverage(source,'',label,min(p.created_utc for p in rows),max(p.created_utc for p in rows),'partial','export coverage unknown',sum(label in p.matched for p in rows),'import',now)
    finally: store.close()


def estimate(cfg,log=print):
    xcfg=cfg.get('sources',{}).get('x',{})
    with Store(cfg['db']) as store:
        x=X(Http(pause=float(cfg.get('pause_seconds',1)),log=log),log,store=store,max_posts_per_tag=xcfg.get('max_posts_per_tag',200),budget_usd=xcfg.get('budget_usd',2),query_extra=xcfg.get('query_extra',''),archive=xcfg.get('archive',False),prices=xcfg.get('prices'))
        log(f'Configured price estimates: {x.prices}; verify against your provider account. Ledger reserved/spent: ${store.spent():.4f}')
        log(f'Approximate capped run: ${x.estimate(cfg["tags"],cfg["terms"],int(cfg.get("days",7))):.4f}. Paid probes obey budget_usd.')
        if not x.available(): return
        now=utcnow(); since,until=collection_bounds(cfg,now); x.until=until
        from .sources import queries
        for label,kind,raw in queries(cfg['tags'],cfg['terms']):
            try:
                rows=x._counts(raw,'day',since,kind)
                log(f'{label}: {sum(row[2] for row in rows):,} API-reported matches')
            except Exception as exc: log(str(exc)); break


def discover(cfg, add=0, log=print, path=None):
    """Print tags that co-occur with what we track and are not tracked yet; with add > 0, append the top ones to the config file."""
    with Store(cfg['db']) as store: posts,_,_=selected_posts(store,cfg)
    dc = cfg.get('discover', {})
    cands = [c for c in A.candidates(posts, tracked(cfg), top=int(dc.get('show', 25)), min_posts=int(dc.get('min_posts', 3))) if c['accounts'] >= int(dc.get('min_accounts', 1))]
    log(f'{len(cands)} candidate tag(s) riding along with {", ".join(tracked(cfg))}:')
    log(f'  {"tag":28s} {"posts":>6s} {"accts":>6s} {"per acct":>9s}  rides with')
    for c in cands: log(f'  {c["tag"]:28s} {c["posts"]:>6d} {c["accounts"]:>6d} {c["per_account"]:>9.1f}  {c["rides_with"]}')
    if add and cands and path:
        room = int(dc.get('max_tags', 12)) - len(cfg['tags']); chosen = [c['tag'].lstrip('#') for c in cands[:max(0, min(add, room))]]
        if not chosen: log(f'  nothing added: discover.max_tags is {dc.get("max_tags", 12)} and the config already tracks {len(cfg["tags"])} tags'); return cands
        raw = json.loads(Path(path).read_text(encoding='utf-8')); raw['tags'] = raw.get('tags', []) + chosen
        Path(path).write_text(json.dumps(raw, indent=2, ensure_ascii=False) + '\n', encoding='utf-8'); cfg['tags'] += chosen
        log(f'  added to {path}: {", ".join("#" + c for c in chosen)}. Each one now costs what any tag costs on X; run estimate again.')
    return cands

def usage(cfg, log=print):
    """Print provider meter fields separately from local estimates."""
    x = X(Http(log=log), log)
    if not x.available(): log('No X_BEARER_TOKEN.'); return
    log('Provider usage response: ' + json.dumps(x.usage().get('data', {}),sort_keys=True))
    with Store(cfg['db']) as store:
        log(f'Local reserved or spent estimate: ${store.spent():.4f}. Meter fields are not a verified invoice.')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='topicstream', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['serve', 'collect', 'report', 'run', 'watch', 'import-csv', 'estimate', 'usage', 'discover', 'peak'])
    ap.add_argument('path', nargs='?', help='CSV path for import-csv')
    ap.add_argument('--config', default='config.json'); ap.add_argument('--every', type=int, default=15, help='minutes between collections in watch mode')
    ap.add_argument('--source', default='import', help='source label for import-csv'); ap.add_argument('--accounts', help='import-csv: a profiles CSV (handle, created_utc, followers, posts_total) to fill account age, followers and lifetime posts'); ap.add_argument('--add', type=int, default=0, help='discover: append the top N candidates to the config')
    ap.add_argument('--hours', type=int, default=1, help='peak: how many of the busiest hours per term to read with recorded coverage'); ap.add_argument('--at', help='peak: one specific hour, e.g. 2026-10-21T14:00')
    ap.add_argument('--tag', help='peak: only this term (as the report labels it, e.g. #php2shell or php2shell)'); ap.add_argument('--dry-run', action='store_true', help='peak: show the plan and cost, buy nothing')
    ap.add_argument('--data-dir', default='topicstream-cases', help='serve: folder for saved cases')
    ap.add_argument('--port', type=int, default=8765, help='serve: localhost port')
    a = ap.parse_args(argv)
    if a.command == 'serve':
        from .web import serve
        serve(a.data_dir,a.port); return
    cfg = load_cfg(a.config)
    if a.command == 'collect': collect(cfg).close()
    elif a.command == 'estimate': estimate(cfg)
    elif a.command == 'usage': usage(cfg)
    elif a.command == 'discover': discover(cfg, a.add, path=a.config)
    elif a.command == 'peak': peak(cfg, a.hours, a.at, a.tag, a.dry_run)
    elif a.command == 'report': write_report(cfg)
    elif a.command == 'run': collect(cfg).close(); write_report(cfg)
    elif a.command == 'import-csv':
        if not a.path: sys.exit('import-csv needs a path');
        import_csv(cfg, a.path, a.source, accounts=a.accounts); write_report(cfg)
    elif a.command == 'watch':
        while True:
            try:
                collect(cfg).close(); write_report(cfg)
                dc = cfg.get('discover', {})
                if dc.get('auto'): discover(cfg, int(dc.get('max_new_per_cycle', 1)), path=a.config)
            except KeyboardInterrupt: raise
            except Exception as e: print('run failed:', repr(e))
            print(f'sleeping {a.every} min'); time.sleep(a.every * 60)

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: print('\nstopped')
