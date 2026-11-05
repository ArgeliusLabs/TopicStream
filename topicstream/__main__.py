"""Command line.

  python -m topicstream collect  [--config config.json]      pull new posts and platform counts into the database
  python -m topicstream report   [--config config.json]      write the HTML report from what is stored
  python -m topicstream run      [--config config.json]      both
  python -m topicstream watch    [--config config.json] [--every 15]   collect+report on a loop, forever (Ctrl-C stops)
  python -m topicstream import-csv posts.csv --source ciap [--accounts profiles.csv]   load a posts export (Day 6 column names, see README), optionally joined to a profiles export
  python -m topicstream estimate [--config config.json]      what a run would cost on X, with live 7-day volumes if a token is present
  python -m topicstream usage    [--config config.json]      what X says the project has consumed this billing cycle
  python -m topicstream discover [--config config.json] [--add N]   tags riding along with what you track; --add N appends the top N to the config
  python -m topicstream peak [--hours N] [--at 2026-10-21T14:00] [--tag php2shell] [--dry-run]
                                       buy the busiest hour(s) COMPLETE on X, where the burst and account rules are trustworthy

"tags" are hashtags; "terms" are phrases, searched as quoted phrases on X and as text on Bluesky (Mastodon has no public phrase search).
Set discover.auto to true to let watch mode add co-occurring tags on its own, up to discover.max_tags, each one costing what any tag costs.
Set sources.x.read_mode to "on_alert" and watch buys nothing but counts until an hour trips a rule, then buys that hour complete.

Credentials come from the environment or from a .env file next to the config (X_BEARER_TOKEN=..., BSKY_HANDLE=..., BSKY_APP_PASSWORD=...).
"""
import argparse, json, sys, time, csv, traceback
from datetime import timedelta
from pathlib import Path
from .store import Store
from .sources import Http, build_sources, utcnow, iso, Post, matches, tags_in, parse_time, load_dotenv, X
from . import report as R
from . import analyze as A

def load_cfg(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8')); cfg['_dir'] = str(Path(path).resolve().parent)
    cfg['_dotenv'] = load_dotenv([Path(cfg['_dir']) / '.env', Path('.env')])
    cfg.setdefault('tags', []); cfg.setdefault('terms', []); cfg.setdefault('days', 7); cfg.setdefault('db', 'topicstream.sqlite'); cfg.setdefault('report', 'topicstream_report.html')
    if not cfg['tags'] and not cfg['terms']: sys.exit('config needs at least one entry in "tags" or "terms"')
    return cfg

def tracked(cfg): return ['#' + t.lower() for t in cfg['tags']] + [t.lower() for t in cfg['terms']]

def collect(cfg, log=print):
    now = utcnow(); since = now - timedelta(days=int(cfg['days']))
    store = Store(cfg['db']); run_id = store.start_run(iso(now)); http = Http(pause=float(cfg.get('pause_seconds', 1.0)), log=log)
    notes = {}
    # X gets what it needs to stay cheap: the dollars already spent in this database, and where each tag's last read stopped
    xcfg = cfg.setdefault('sources', {}).setdefault('x', {})
    xcfg['_spent_before'] = store.spent('x'); xcfg['_cursors'] = store.cursors('x'); xcfg['_save_cursor'] = lambda tag, newest: store.set_cursor('x', tag, newest, iso(utcnow()))
    xcfg['_counts_fetched'] = store.cursors('x-counts'); xcfg['_save_counts_fetched'] = lambda tag, when: store.set_cursor('x-counts', tag, when, when)
    meter = None
    for src in build_sources(cfg, http, log):
        log(f'== {src.name}')
        if src.name == 'x' and src.available():
            try: meter = int(src.usage().get('data', {}).get('project_usage', 0)); notes['x_meter_before'] = meter; log(f'   X meter at start: {meter:,} unique post reads this billing cycle')
            except Exception as e: log(f'   (usage endpoint unavailable: {e!r})')
        try:
            rows = src.tag_days(cfg['tags'], now) if src.name != 'x' else src.tag_days(cfg['tags'], now, since, cfg['terms']); store.add_tag_days(rows)
            if getattr(src, 'hourly', None): store.add_counts('x', src.hourly, iso(now))
            if src.name == 'x' and xcfg.get('read_mode', 'always') == 'on_alert':
                posts, new = [], 0; log('   read_mode on_alert: posts are bought only for hours whose counts trip a rule (see below)')
            else:
                posts = src.posts(cfg['tags'], cfg['terms'], since, now); new = store.add_posts(posts)
            notes[src.name] = dict(posts=len(posts), new=new, tag_day_rows=len(rows))
            if getattr(src, 'spent', 0): notes[src.name]['spent_usd'] = round(src.spent, 4)
            log(f'   {len(posts)} posts seen, {new} new')
        except SystemExit as e:
            log(f'   {e}'); notes[src.name] = dict(error=str(e))
            if getattr(src, 'spent', 0): notes[src.name]['spent_usd'] = round(src.spent, 4)   # counts may have been bought before the guard stopped the reads
        except Exception as e:
            log(f'   failed: {e!r}'); notes[src.name] = dict(error=repr(e)); traceback.print_exc()
            if getattr(src, 'spent', 0): notes[src.name]['spent_usd'] = round(src.spent, 4)
    # evaluate alerts on what we now hold, and record new ones so `watch` can tell you only once
    al = cfg.get('alert', {}); posts = store.posts(since=iso(since))
    for t in tracked(cfg):
        v = A.velocity(posts, t, int(al.get('window_minutes', 30)), int(al.get('uses', 200)), float(al.get('ratio', 10)), float(al.get('uses_per_account', 5)), int(al.get('min_uses', 10)))
        f = v and v['first_trip']
        if f and store.add_alert(t, f['start'], v['window_min'], f['uses'], f['accounts'], v['baseline'], '; '.join(f['reasons']), iso(now)):
            log(f'!! ALERT {t}: {f["uses"]} uses / {f["accounts"]} accounts in {v["window_min"]} min from {f["start"]} ({"; ".join(f["reasons"])})')
    tripped = []
    for t in tracked(cfg):   # X counts are complete where sampled posts are not; alert on them separately
        v = A.velocity_from_counts(store.counts('x'), t, int(al.get('uses', 200)), float(al.get('ratio', 10)), int(al.get('min_uses', 10)))
        f = v and v['first_trip']
        if f and store.add_alert(t, f['start'], 60, f['uses'], 0, v['baseline'], 'X counts: ' + '; '.join(f['reasons']), iso(now)):
            log(f'!! ALERT (X counts, complete) {t}: {f["uses"]} posts in the hour from {f["start"]} ({"; ".join(f["reasons"])})'); tripped.append((t, f['start'], f['uses']))
    notes['http_requests'] = http.requests
    store.finish_run(run_id, iso(utcnow()), notes)
    if tripped and xcfg.get('read_mode', 'always') == 'on_alert':
        log(f'== x: buying {len(tripped)} alerted hour(s) complete'); buy_windows(cfg, store, tripped, log)
    return store

def buy_windows(cfg, store, wanted, log=print, dry=False):
    """Read the listed (label, start_utc) hours complete on X. `wanted` comes from the counts table, so each has an expected size.
    Refuses the whole batch if it could cross budget_usd. Records every window read in the windows table."""
    from .sources import queries
    xcfg = cfg.get('sources', {}).get('x', {}); spent = store.spent('x'); done = {(w['tag'], w['start_utc']) for w in store.windows()}
    by_label = {label: (kind, raw) for label, kind, raw in queries(cfg['tags'], cfg['terms'])}
    plan = []
    for label, start, expected in wanted:
        start = iso(parse_time(start))                       # the counts API writes ...T14:00:00.000Z; windows are stored as ...T14:00:00Z
        if (label, start) not in done and label in by_label and (label, start) not in [(l, st) for l, st, _ in plan]: plan.append((label, start, expected))
    if not plan: log('nothing to buy: every requested window is already complete in this database'); return 0
    est = sum(e for _, _, e in plan) * X.POST_READ
    log(f'plan: {len(plan)} window(s), {sum(e for _, _, e in plan):,} posts by the counts, up to ${est:.2f}; ${spent:.2f} already spent in this database, budget_usd {xcfg.get("budget_usd", 2.0):.2f}')
    for label, start, expected in plan: log(f'   {label:28s} {start[:16].replace("T", " ")} UTC  {expected:>6,} posts  ${expected * X.POST_READ:.2f}')
    if spent + est > float(xcfg.get('budget_usd', 2.0)): log('over budget: raise budget_usd or ask for fewer hours'); return 0
    if dry: return 0
    now = utcnow(); http = Http(pause=float(cfg.get('pause_seconds', 1.0)), log=log)
    x = X(http, log, budget_usd=xcfg.get('budget_usd', 2.0), query_extra=xcfg.get('query_extra', ''), archive=bool(xcfg.get('archive', False)), spent_before=spent)
    if not x.available(): log('No X_BEARER_TOKEN.'); return 0
    run_id = store.start_run(iso(now)); total = 0
    try: store_meter = int(x.usage().get('data', {}).get('project_usage', 0))
    except Exception: store_meter = None
    for label, start, expected in plan:
        kind, raw = by_label[label]; t0 = parse_time(start); t1 = t0 + timedelta(hours=1)
        posts = x.read_window(raw, kind, t0, t1, cfg['tags'], cfg['terms'], now, expected)
        new = store.add_posts(posts); store.add_window('x', label, iso(t0), iso(t1), expected, len(posts), iso(now)); total += len(posts)
        log(f'   stored {len(posts)} ({new} new) for {label} at {start[:16]}')
    notes = {'x': dict(windows=len(plan), posts=total, spent_usd=round(x.spent, 4)), 'peak': True}
    if store_meter is not None: notes['x_meter_before'] = store_meter
    store.finish_run(run_id, iso(utcnow()), notes); return total

def top_hours(store, labels, hours=1, at=None):
    """The busiest hours per label from the counts table, or the one hour named by `at` (an ISO time; snapped to the hour)."""
    counts = store.counts('x'); out = []
    for label in labels:
        rows = [c for c in counts if c['tag'] == label]
        if at:
            hour = at[:13] + ':00:00'
            rows = [c for c in rows if c['start_utc'][:13] == hour[:13]]
        for c in sorted(rows, key=lambda c: -c['uses'])[:hours]: out.append((label, c['start_utc'], c['uses']))
    return out

def peak(cfg, hours=1, at=None, label=None, dry=False, log=print):
    """Buy the busiest hour(s) complete. The counts series says which hours matter; this reads every post in them."""
    store = Store(cfg['db']); labels = [label] if label else tracked(cfg)
    wanted = top_hours(store, labels, hours, at)
    if not wanted: log('no counts stored for those terms yet: run collect (or estimate) first so the counts series exists'); return
    n = buy_windows(cfg, store, wanted, log, dry)
    if n: write_report(cfg, log)

def write_report(cfg, log=print):
    store = Store(cfg['db']); out = Path(cfg['report']); out.write_text(R.render(store, cfg), encoding='utf-8')
    log(f'report: {out} ({out.stat().st_size // 1024} KB, {len(store.posts()):,} posts)'); return out

def _pick(r, *names):
    for n in names:
        if r.get(n) not in (None, ''): return r[n]
    return None

def import_csv(cfg, path, source, log=print, accounts=None, now=None):
    """Load a posts CSV with the Day 6 export columns (timestamp_utc, handle, text, link, content_type, likes, reposts, replies, lang,
    post_id, in_reply_to). With --accounts, a profiles CSV (handle, created_utc, followers, posts_total; a few aliases accepted) fills
    account age, followers and lifetime posts, which the account signals and creation clusters need. `now` fixes the collected
    time (and the run record) for reproducible builds."""
    store = Store(cfg['db']); now = iso(now or utcnow()); rows = []; prof = {}; run_id = store.start_run(now)
    if accounts:
        with open(accounts, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                h = _pick(r, 'handle', 'username', 'screen_name', 'author')
                if h: prof[h.lstrip('@')] = r
        log(f'account profiles: {len(prof)} from {accounts}')
    def when(v): return iso(parse_time(v.replace(' ', 'T') + ('Z' if 'Z' not in v and '+' not in v else '')))
    with open(path, encoding='utf-8') as f: raw = list(csv.DictReader(f))
    by_id = {r['post_id']: r['handle'] for r in raw if r.get('post_id')}          # in_reply_to names a post; the signal wants the account
    for r in raw:
        text = r.get('text', ''); link = r.get('link') or ''; a = prof.get(r['handle'].lstrip('@'), {}); parent = r.get('in_reply_to') or ''
        replied = by_id.get(parent) or (parent.lstrip('@') if parent and not parent.startswith('P-') and ' ' not in parent else None)
        created = _pick(a, 'created_utc', 'created_at', 'account_created', 'joined'); followers = _pick(a, 'followers', 'followers_count'); total = _pick(a, 'posts_total', 'statuses_count', 'posts_count', 'post_count')
        rows.append(Post(source=source, instance=source, post_id=r.get('post_id') or f"{r['handle']}-{r['timestamp_utc']}", created_utc=when(r['timestamp_utc']),
                         author=r['handle'], text=text, lang=r.get('lang'), is_repost=r.get('content_type', 'post') == 'repost',
                         reposts=int(r['reposts']) if r.get('reposts') else None, likes=int(r['likes']) if r.get('likes') else None, replies=int(r['replies']) if r.get('replies') else None,
                         is_reply=bool(parent) or r.get('content_type') == 'reply', reply_to=replied,
                         author_created_utc=when(created) if created else None, author_followers=int(followers) if followers else None, author_posts=int(total) if total else None,
                         matched=matches(text, cfg['tags'], cfg['terms']), tags=tags_in(text), links=[link] if link else [], collected_utc=now))
    n = store.add_posts(rows); log(f'imported {len(rows)} rows, {n} new, from {path}')
    store.finish_run(run_id, now, {'import': dict(file=Path(path).name, rows=len(rows), new=n, source=source, accounts=len(prof) if accounts else None)})

def estimate(cfg, log=print):
    """What the configured X run would cost, worst case, and, with a token, the real 7-day volume of each tag from the counts endpoint
    (one request per tag, half a cent each) so you can see what reading everything would cost before you read anything."""
    xcfg = cfg.get('sources', {}).get('x', {}); tags = cfg['tags']; terms = cfg['terms']
    store = Store(cfg['db']); spent = store.spent('x')
    x = X(Http(pause=0.5, log=log), log, xcfg.get('max_posts_per_tag', 200), xcfg.get('budget_usd', 2.0), query_extra=xcfg.get('query_extra', ''), archive=bool(xcfg.get('archive', False)), spent_before=spent, cursors=store.cursors('x'), sample_per_day=xcfg.get('sample_per_day', 0), sample_windows_per_day=xcfg.get('sample_windows_per_day', 6))
    log(f'X pay-per-use: ${X.POST_READ} per post read, ${X.COUNT_RECENT} per counts/recent request, ${X.COUNT_ALL} per counts/all request. X meters UNIQUE posts per billing cycle (a post read twice counted once, observed Nov 2026), so these are upper bounds.')
    log(f'Config: {len(tags)} tag(s) + {len(terms)} term(s), max_posts_per_tag {x.max_posts}, query_extra "{x.query_extra}", archive {x.archive}, budget_usd {x.budget:.2f}; already spent in this database: ${spent:.2f}.')
    nq = len(tags) + len(terms)
    days = int(cfg['days']); reads = min(x.max_posts, max(10, x.sample_per_day // x.sample_windows) * x.sample_windows * (days + 1)) if x.sample_per_day else x.max_posts
    log(f'Worst case for one run: ${x.estimate(tags, terms, days):.2f}  (= {nq} queries x (counts requests + {reads} reads{" sampled " + str(x.sample_per_day) + " a day over " + str(days) + " days" if x.sample_per_day else ""})).')
    ce = int(xcfg.get('counts_every_minutes', 60))
    log(f'Watch mode reads only new posts (since_id) and refreshes counts every {ce} min, so a day of 15-minute runs costs ${nq * (1440 // max(1, ce)) * 2 * x.count_price():.2f} in counts plus at most {x.max_posts} reads per query per run (96 runs at that cap: ${96 * nq * x.max_posts * X.POST_READ:,.2f}, usually far less).')
    if not x.available(): log('No X_BEARER_TOKEN, so no live volumes. Put it in .env next to the config to see what each tag actually does in a week.'); return
    now = utcnow(); since = now - timedelta(days=int(cfg['days']))
    from .sources import queries
    log(f'Live volumes from the counts endpoint ({nq} request(s), ${nq * x.count_price():.3f}):')
    total = 0
    for label, kind, raw in queries(tags, terms):
        rows = x._counts(raw, 'day', since, kind); n = sum(r[2] for r in rows); total += n
        log(f'  {x.query(raw, kind):40s} {n:>9,} posts in {len(rows)} day(s)  -> reading all of them: ${n * X.POST_READ:,.2f}; your cap reads {min(n, x.max_posts)} for ${min(n, x.max_posts) * X.POST_READ:.2f}')
    log(f'  total {total:,} posts; reading everything once: ${total * X.POST_READ:,.2f}. This probe cost ${x.spent:.3f}.')
    run_id = store.start_run(iso(now)); store.finish_run(run_id, iso(utcnow()), {'x': dict(spent_usd=round(x.spent, 4), probe=True)})

def discover(cfg, add=0, log=print, path=None):
    """Print tags that co-occur with what we track and are not tracked yet; with add > 0, append the top ones to the config file."""
    store = Store(cfg['db']); posts = store.posts(); dc = cfg.get('discover', {})
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
    """X's own meter. Observed behaviour (November 2026): project_usage counts UNIQUE posts read in the billing cycle; reading a
    post again did not increase it. The tool's ledger counts every post returned, so the ledger is an upper bound and this is the number
    the invoice should follow. The meter lags a minute or two behind a run."""
    x = X(Http(log=log), log)
    if not x.available(): log('No X_BEARER_TOKEN.'); return
    u = x.usage().get('data', {}); reads = int(u.get('project_usage', 0))
    log(f'X meter: {reads:,} unique post reads this billing cycle (cap {int(u.get("project_cap", 0)):,}, resets on day {u.get("cap_reset_day")}) = ${reads * X.POST_READ:,.2f} at ${X.POST_READ} a read, before counts requests.')
    store = Store(cfg['db']); runs = [r for r in store.runs() if r['notes'] and 'x_meter_before' in json.loads(r['notes'])]
    if runs:
        first = json.loads(runs[0]['notes'])['x_meter_before']; ledger = sum(json.loads(r['notes']).get('x', {}).get('spent_usd', 0) for r in runs)
        log(f'Since {runs[0]["started_utc"][:16]} UTC, the first run here that recorded the meter (then {first:,}): {reads - first:,} unique reads = ${(reads - first) * X.POST_READ:,.2f}; the tool\'s own ledger for those runs says ${ledger:,.2f} (every post returned). The meter trails a run by minutes, longer after a large read.')

def main(argv=None):
    ap = argparse.ArgumentParser(prog='topicstream', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['collect', 'report', 'run', 'watch', 'import-csv', 'estimate', 'usage', 'discover', 'peak'])
    ap.add_argument('path', nargs='?', help='CSV path for import-csv')
    ap.add_argument('--config', default='config.json'); ap.add_argument('--every', type=int, default=15, help='minutes between collections in watch mode')
    ap.add_argument('--source', default='import', help='source label for import-csv'); ap.add_argument('--accounts', help='import-csv: a profiles CSV (handle, created_utc, followers, posts_total) to fill account age, followers and lifetime posts'); ap.add_argument('--add', type=int, default=0, help='discover: append the top N candidates to the config')
    ap.add_argument('--hours', type=int, default=1, help='peak: how many of the busiest hours per term to buy complete'); ap.add_argument('--at', help='peak: one specific hour, e.g. 2026-10-21T14:00')
    ap.add_argument('--tag', help='peak: only this term (as the report labels it, e.g. #php2shell or php2shell)'); ap.add_argument('--dry-run', action='store_true', help='peak: show the plan and cost, buy nothing')
    a = ap.parse_args(argv); cfg = load_cfg(a.config)
    if a.command == 'collect': collect(cfg)
    elif a.command == 'estimate': estimate(cfg)
    elif a.command == 'usage': usage(cfg)
    elif a.command == 'discover': discover(cfg, a.add, path=a.config)
    elif a.command == 'peak': peak(cfg, a.hours, a.at, a.tag, a.dry_run)
    elif a.command == 'report': write_report(cfg)
    elif a.command == 'run': collect(cfg); write_report(cfg)
    elif a.command == 'import-csv':
        if not a.path: sys.exit('import-csv needs a path');
        import_csv(cfg, a.path, a.source, accounts=a.accounts); write_report(cfg)
    elif a.command == 'watch':
        while True:
            try:
                collect(cfg); write_report(cfg)
                dc = cfg.get('discover', {})
                if dc.get('auto'): discover(cfg, int(dc.get('max_new_per_cycle', 1)), path=a.config)
            except KeyboardInterrupt: raise
            except Exception as e: print('run failed:', repr(e))
            print(f'sleeping {a.every} min'); time.sleep(a.every * 60)

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: print('\nstopped')
