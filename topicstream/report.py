"""Self-contained evidence report. All post content is escaped and scope is explicit."""
import html
import json
from datetime import datetime, timezone, timedelta
from . import analyze as A, detection
from .identity import account_key, post_key, safe_url
from .scope import selected_posts, labels, covers_burst, in_scope, analysis_scope
from .sources import parse_time, iso
from . import __version__ as VERSION

CSS = '''
:root{color-scheme:dark;--bg:#111923;--panel:#18232f;--line:#344350;--muted:#a9bac8;--ink:#edf3f6;--accent:#79d3b1}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,sans-serif}main{max-width:1250px;margin:auto;padding:42px 28px}h1{font-size:34px;line-height:1.2;margin:14px 0}h2{font-size:23px;margin:36px 0 12px}h3{font-size:17px}a{color:var(--accent)}p{max-width:100ch}.muted{color:var(--muted)}.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:12px;color:var(--accent)}.card{background:var(--panel);border:1px solid var(--line);padding:22px;border-radius:12px;margin:15px 0}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.metrics strong{display:block;font-size:28px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}td{overflow-wrap:anywhere}code{overflow-wrap:anywhere;color:var(--accent)}.notice{border-left:3px solid var(--accent);padding:12px 18px;background:#19312e}.bars{display:flex;align-items:end;gap:4px;height:150px}.bar{background:var(--accent);min-width:4px;max-width:72px;flex:1}.post{padding:15px 0;border-bottom:1px solid var(--line);scroll-margin-top:20px}summary{cursor:pointer;color:var(--accent)}.small{font-size:12px}nav{display:flex;gap:16px;flex-wrap:wrap}@media(max-width:650px){main{padding:20px 14px}.metrics{grid-template-columns:repeat(2,1fr)}h1{font-size:27px}}
'''

def esc(value): return html.escape(str(value)) if value is not None else 'Unknown'
def num(value): return f'{value:,}' if isinstance(value,(int,float)) else 'Unknown'
def _table(headers,rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def _link(url,label):
    url=safe_url(url)
    return f'<a href="{esc(url)}" rel="noopener noreferrer">{esc(label)}</a>' if url else esc(label)


def render(store,cfg,now=None,result=None):
    now=now or datetime.now(timezone.utc)
    posts,start,end=selected_posts(store,cfg,now); tags=labels(cfg); wanted=set(tags)
    if result: posts=store.analysis_posts(result['run_id']) or posts
    scope=analysis_scope(cfg,start,end)
    hashes={q['query_hash'] for q in scope['expected_queries'] if q['source']=='x'}
    counts=[r for r in store.counts() if in_scope(r,start,end,wanted) and r.get('query_hash') in hashes]
    windows=[r for r in store.windows() if in_scope(r,start,end,wanted) and r.get('query_hash') in hashes]
    coverage=[r for r in store.coverage() if r['label'] in wanted and parse_time(r['start_utc'])<end and parse_time(r['end_utc'])>=start]
    result=result or detection.analyze(posts,coverage,cfg.get('detector'),scope)
    run_notes=[json.loads(r['notes']) for r in store.runs() if r['notes']]
    import_only=bool(posts) and (any('import' in n for n in run_notes) or all(p['source'] not in ('x','bluesky','mastodon') for p in posts)) and not any(any(s in n for s in ('x','bluesky','mastodon')) for n in run_notes)
    names={account_key(p):p['author']+' ('+p['source']+')' for p in posts}
    out=[]; w=out.append
    w(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(cfg.get("name","TopicStream"))} — TopicStream</title><style>{CSS}</style></head><body><main>')
    w('<div class="eyebrow">TopicStream / Investigation report</div>')
    if any(c.get('sampling')=='synthetic' for c in coverage): w('<p class="notice"><strong>Synthetic demonstration — invented accounts and posts. This report describes no real-world operation.</strong></p>')
    w(f'<h1>{esc(cfg.get("name","Topic investigation"))}</h1><p class="muted">{esc(iso(start))} to {esc(iso(end))} · UTC · end exclusive</p>')
    if import_only:
        w('<p class="muted">Export: '+esc(min(p['created_utc'] for p in posts)[:10])+' to '+esc(max(p['created_utc'] for p in posts)[:10])+' · observed rows within this report scope.</p><p>Export depth: posts are rows included in the export. Zero observed days do not establish that nobody posted. No platform-side counts in the export are assumed.</p>')
    w('<nav><a href="#groups">Recurring groups</a><a href="#coverage">Coverage</a><a href="#activity">Activity</a><a href="#bursts">Matches</a><a href="#accounts">Accounts</a><a href="#evidence">Evidence</a></nav>')
    w(f'<div class="card"><h2>{esc(result["assessment"])}</h2><p>{esc(result["interpretation"])}</p><p class="muted">This report does not establish deceptive identity, common control, automation, or sponsorship.</p></div>')
    w('<div class="metrics">'+''.join(f'<div class="card"><strong>{esc(v)}</strong>{esc(k)}</div>' for k,v in [('Observed posts',len(posts)),('Distinct accounts',len(names)),('Recurring groups',len(result['groups'])),('Reserved or spent',f'${store.spent():.4f}')])+'</div>')
    w('<h2 id="groups">Recurring account groups</h2>')
    if not result['groups']: w('<p>No group meets the configured recurrence thresholds. Check coverage before drawing a negative conclusion.</p>')
    for index,g in enumerate(result['groups'],1):
        w(f'<section class="card" id="group-{g["id"]}"><h3>Group {index} · {len(g["accounts"])} accounts</h3><p>{esc(g["explanation"])}</p><p>Signals: {esc(", ".join(g["families"]))} · graph density {g["density"]:.2f} · ranking score {g["ranking_score"]:.2f} (not a probability)</p><p>'+esc(', '.join(names.get(a,a) for a in g['accounts']))+'</p>')
        w(_table(['Account pair','Episodes','Days','Evidence'],[(esc(names.get(e['a'],e['a'])+' / '+names.get(e['b'],e['b'])),e['episodes'],e['days'],', '.join(f'<a href="#event-{eid}">{eid[:8]}</a>' for eid in e['event_ids'])) for e in g['edges']]))
        w('<p>Review alternatives: '+esc('; '.join(g['alternatives']))+'</p></section>')
    baseline=result['baseline']
    w(f'<div class="notice">Timing comparison: {result["recurring_edges"]} recurring edges observed; median {esc(baseline["median_edges"])} across {baseline["repeats"]} shuffled datasets. {esc(baseline["limitation"])}</div>')
    if any(result['limits'][k] for k in ('truncated_posts','high_volume_events_not_compared','missing_stable_id_accounts')): w('<p class="notice">Analysis limits: '+esc(json.dumps(result['limits']))+'</p>')
    if store.reviews():
        w('<h3>Analyst review history</h3>')
        w(_table(['Date','Group','Assessment','Explanation','Evidence version'],[(esc(r['created_utc']),esc(r['group_id']),esc(r['assessment']),esc(r['explanation']),esc(r['dataset_hash'][:12])+(' (current)' if r['dataset_hash']==result['dataset_hash'] else ' (older dataset)')) for r in store.reviews()]))
    w('<h2 id="coverage">Collection coverage</h2><p>Exhausted means pagination ended for one retrievable query and interval. It does not mean the whole topic or platform was observed. Missing results and count/search differences have no assumed cause.</p>')
    source_notes={'mastodon':'Selected servers and federated hashtag visibility; phrase-only search is unavailable. Boosts retain their own actor.',
                  'bluesky':'Authenticated search results. Search does not collect repost actions, deleted records, or the full firehose.',
                  'x':'Results accessible to the configured API account and query. Counts and search can differ; a cap or error leaves coverage partial.'}
    w(_table(['Source','Visibility'],[(esc('Imported export ('+source+')' if import_only else source),esc('Export completeness, provenance, and missing posts require external verification.' if import_only else source_notes.get(source,'Imported export; completeness, provenance, and missing posts require external verification.'))) for source in sorted({p['source'] for p in posts}|{c['source'] for c in coverage})]))
    if coverage: w(_table(['Source / query','Interval UTC','Status','Records','Method / stop reason'],[(esc(r['source']+' / '+r['label']),esc(r['start_utc']+' → '+r['end_utc']),esc(r['status']),r['retrieved'],esc(r['sampling']+' / '+r['stop_reason'])) for r in coverage]))
    else: w('<p class="notice">No collection-coverage records are available. Legacy and imported data cannot establish complete coverage.</p>')
    w('<h3>Purchased X windows</h3>')
    if windows: w(_table(['Query','Hour UTC','Status','Counts said','Returned','Stop reason'],[(esc(r['tag']),esc(r['start_utc']),esc(r['status']),num(r['expected']),r['got'],esc(r['stop_reason'])) for r in windows]))
    else: w('<p>No purchased windows. '+('This database has no X counts series.' if not counts else 'Use peak --dry-run to inspect a targeted read.')+'</p>')
    w('<h2 id="activity">Observed activity and alerts</h2>')
    alerts=[r for r in store.monitor_alerts() if r['tag'] in wanted and start<=parse_time(r['start_utc'])<end]
    if alerts: w(_table(['Source','Query','Interval','ALERT reasons'],[(esc(r['source']),esc(r['tag']),esc(r['start_utc']),esc('; '.join(r['payload']['reasons']))) for r in alerts]))
    for tag in tags:
        last_day=(end-timedelta(seconds=1)).date()
        calendar_days=(last_day-start.date()).days+1
        series=A.daily_series(posts,tag,calendar_days,end=last_day); maximum=max([u for _,u,_ in series]+[1])
        w(f'<section class="card"><h3>{esc(tag)}</h3><div class="bars" role="img" aria-label="Observed posts per UTC day">'+''.join(f'<div class="bar" style="height:{max(1,int(145*u/maximum))}px" title="{esc(d)}: {u} posts from {a} accounts"></div>' for d,u,a in series)+'</div>')
        w(_table(['UTC day','Observed posts','Originating accounts'],[(esc(d),u,a) for d,u,a in series]))
        w('<details><summary>Related hashtags and linked domains</summary>'+_table(['Hashtag','Posts','Accounts'],[(esc(c['tag']),c['count'],c['accounts']) for c in A.cooccurrence(posts,tag)])+_table(['Domain','Posts','Accounts'],[(esc(c['domain']),c['posts'],c['accounts']) for c in A.top_domains(posts,tag)])+'</details>')
        v=A.velocity(posts,tag)
        if v and v['first_trip']: w('<p>Retrospective activity rule: '+esc('; '.join(v['first_trip']['reasons']))+'. This is not a CIB verdict.</p>')
        if counts: w('<details><summary>X volume per hour from the counts API</summary>'+_table(['Hour UTC','API-reported matches'],[(esc(c['start_utc']),c['uses']) for c in counts if c['tag']==tag])+'</details>')
        w('</section>')
    bc=cfg.get('burst',{}); window=int(bc.get('window_minutes',10)); minimum=int(bc.get('minimum',3))
    exact=A.bursts(posts,window,minimum); links=A.link_bursts(posts,window,minimum)
    near=A.paraphrase_bursts(posts[:2000],int(bc.get('paraphrase_window_minutes',60)),minimum,float(bc.get('paraphrase_threshold',.35)))
    if len(posts)>2000: w('<p class="notice">Exploratory similar-wording matches use the earliest 2,000 posts. Recurring groups use their separately stated analysis limit.</p>')
    w('<h2 id="bursts">Text and link matches</h2><p>Matching content may come from a common public source or legitimate organizing. Similar wording does not establish AI authorship.</p>')
    for title,items,field in [('Same text',exact,'text'),('Same link',links,'link'),('Similar wording',near,'samples')]:
        w('<h3>'+title+'</h3>')
        w(_table(['Start UTC','Accounts','Query interval exhausted','Example'],[(esc(b['start']),esc(', '.join(names.get(a,a) for a in b['accounts'])), 'yes' if covers_burst(b,windows) else 'not established',esc(' / '.join(b[field]) if isinstance(b[field],list) else b[field])) for b in items[:50]]) if items else '<p>None at these settings.</p>')
    burst_accounts={a for b in exact+links+near for a in b['accounts']}
    accounts=A.account_features(posts,now=now,burst_accounts=burst_accounts,min_posts=cfg.get('accounts',{}).get('min_posts',3),top=cfg.get('accounts',{}).get('top',40))
    w('<h2 id="accounts">Account observations</h2><p>Age is measured at first observed activity in this case. Low lifetime activity does not establish dormancy. Hour concentration requires at least three observed days and does not establish location or working hours. Flag counts are not probabilities.</p>')
    w(_table(['Account','Posts','Observed signals','Age at event','Median likes'],[(esc(r['account']+' ('+r['source']+')'),r['posts'],esc(', '.join(r['signals'])),num(r['age_days']),num(r['median_likes'])) for r in accounts]))
    hours=A.hour_comparison(posts,{r['account_id'] for r in accounts if len(r['signals'])>=2})
    if hours:
        w('<h3>Observed posting-hour comparison</h3><p>Accounts with at least two descriptive signals: '+str(hours['selected_posts'])+' posts. Their tightest eight-hour band starts at '+f'{hours["band_start"]:02d}:00 UTC'+f' and contains {hours["band_share"]:.1%} of their posts. The same band contains {hours["all_share"]:.1%} of all observed posts. Sampling and ordinary schedules can explain this pattern; it does not establish location, intent, or office hours.</p>')
        w(_table(['UTC hour','Selected accounts','All observed posts'],[(f'{h:02d}:00',hours['hours'][h],hours['all_hours'][h]) for h in range(24)]))
    clusters=A.creation_clusters(posts,burst_accounts)
    if clusters:
        w('<h3>Creation-date concentration</h3><p>Comparison is against accounts in this dataset, not a representative platform population.</p>')
        w(_table(['Creation week','Matched accounts','All observed accounts','Relative share'],[(esc(c['week']),c['subset'],c['all'],round(c['lift'],2)) for c in clusters]))
    cross=A.cross_platform(posts)
    if cross:
        w('<h3>Cross-platform matches</h3><p>Matching posts do not establish that accounts on different platforms belong to the same person.</p>')
        w(_table(['Time UTC','Type','Sources','Match'],[(esc(c['start']),esc(c['kind']),esc(', '.join(c['sources'])),esc(c['key'])) for c in cross]))
    early=[(win,A.leading_edge(posts,win)) for win in windows if win['status']=='exhausted']
    if any(edge for _,edge in early):
        w('<h3>Early observed participants in exhausted query windows</h3><p>This is relative timing in collected evidence, not identification of who originated a narrative.</p>')
        w(_table(['Query / hour','Early accounts','Posts in window'],[(esc(win['tag']+' / '+win['start_utc']),esc(', '.join(names.get(a,a) for a in edge['edge_accounts'])),edge['posts']) for win,edge in early if edge]))
    infra=A.infrastructure(posts)
    w('<h3>Shared links and related tags</h3><p>Tracking tokens and domains are leads. Ordinary copying and publisher links can produce the same pattern.</p>')
    w(_table(['Domain','Distinct accounts'],[(esc(domain),n) for domain,n in infra['domains']]))
    w(_table(['Candidate tag','Posts','Accounts'],[(esc(c['tag']),c['posts'],c['accounts']) for c in A.candidates(posts,tags)]))
    w('<h2 id="evidence">Supporting evidence</h2>'); used={eid for g in result['groups'] for eid in g['event_ids']}; evidence_keys=set()
    for e in result['events']:
        if e['id'] not in used: continue
        evidence_keys.update(e['post_keys'])
        w(f'<details id="event-{e["id"]}" class="card"><summary>{esc(e["family"])} match · {esc(e["start"])} · {len(e["accounts"])} accounts</summary><p>{esc(e["trace"])}</p><p>'+', '.join(f'<a href="#post-{esc(key)}">{esc(key)}</a>' for key in e['post_keys'])+'</p></details>')
    for post in posts:
        if post_key(post) not in evidence_keys: continue
        w(f'<article class="post" id="post-{esc(post_key(post))}"><strong>{esc(post["author"])} · {esc(post["source"])}</strong><div class="muted small">{esc(post["created_utc"])} · {_link(post.get("url"),post_key(post))}</div><p>{esc(post["text"])}</p><p>'+', '.join(_link(url,url) for url in post['links'])+'</p></article>')
    w('<h2>Run details</h2><p>Dataset hash: <code>'+esc(result['dataset_hash'])+'</code></p><p>Detector: '+esc(result['version'])+' · configuration: <code>'+esc(json.dumps(result['settings'],sort_keys=True))+'</code></p><p>Configured X prices are estimates. The request ledger retains unresolved reservations after interrupted calls and does not promise provider-level billing accuracy.</p>')
    w(_table(['Started','Finished','Notes'],[(esc(r['started_utc']),esc(r['finished_utc']),esc(r['notes'])) for r in store.runs()[-10:]]))
    w(f'<p class="muted small">Generated by TopicStream {esc(VERSION)} · {esc(iso(now))}. Findings apply only to the stated queries, period, and collected evidence.</p></main></body></html>')
    return ''.join(out)
