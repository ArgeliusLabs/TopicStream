"""Self-contained evidence report. All post content is escaped and scope is explicit."""
import html
import json
import base64
import hashlib
from datetime import datetime, timezone, timedelta
from . import analyze as A, detection
from .identity import account_key, post_key, safe_url
from .scope import selected_posts, labels, covers_burst, in_scope, analysis_scope
from .sources import parse_time, iso
from . import __version__ as VERSION

CSS = '''
:root{color-scheme:dark;--bg:#111923;--panel:#18232f;--line:#344350;--muted:#a9bac8;--ink:#edf3f6;--accent:#79d3b1}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,sans-serif}main{max-width:1250px;margin:auto;padding:42px 28px}h1{font-size:34px;line-height:1.2;margin:14px 0}h2{font-size:23px;margin:36px 0 12px}h3{font-size:17px}h4{font-size:14px;margin:18px 0 6px}.tok{white-space:nowrap}a{color:var(--accent)}p{max-width:100ch}.muted{color:var(--muted)}.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:12px;color:var(--accent)}.card{background:var(--panel);border:1px solid var(--line);padding:22px;border-radius:12px;margin:15px 0}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.metrics strong{display:block;font-size:28px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}td{overflow-wrap:anywhere}code{overflow-wrap:anywhere;color:var(--accent)}.notice{border-left:3px solid var(--accent);padding:12px 18px;background:#19312e}.bars{display:flex;align-items:end;gap:4px;height:150px}.bar{background:var(--accent);min-width:4px;max-width:72px;flex:1}.post{padding:15px 0;border-bottom:1px solid var(--line);scroll-margin-top:20px}summary{cursor:pointer;color:var(--accent)}.small{font-size:12px}nav{display:flex;gap:16px;flex-wrap:wrap}@media(max-width:650px){main{padding:20px 14px}.metrics{grid-template-columns:repeat(2,1fr)}h1{font-size:27px}}
'''
CSS += '''
:root[data-theme="light"]{color-scheme:light;--bg:#f7f9fb;--panel:#fff;--line:#c6d0d8;--muted:#465865;--ink:#14222e;--accent:#14634e}
:root[data-theme="light"] .notice{background:#e5f3ed}
button{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:8px 12px;cursor:pointer}
.report-head{display:flex;align-items:center;justify-content:space-between;gap:16px}.toolbar{display:flex;gap:8px}.card h2{margin:0 0 10px}.card p:last-child{margin-bottom:0}details{margin:12px 0}details>summary{padding:6px 0}
@media print{
 :root{color-scheme:light;--bg:#fff;--panel:#fff;--line:#aaa;--muted:#333;--ink:#000;--accent:#000}
 body,.notice{background:white!important;color:black!important}main{max-width:none;padding:0;font-size:10pt}
 .toolbar,nav{display:none}.scroll{overflow:visible}table{font-size:9pt}thead{display:table-header-group}
 .card{padding:10px;border-radius:0}.metrics{gap:6px}.metrics strong{font-size:18pt}
 details>*{display:block!important}details::details-content{display:block!important;content-visibility:visible!important}
 a,code,summary,.muted{color:black!important}h2,h3,h4,summary{break-after:avoid}.post,tr{break-inside:avoid}
}
'''

SCRIPT = '''
<script>
const themeButton=document.getElementById('theme-toggle');
themeButton.addEventListener('click',()=>{
 const light=document.documentElement.dataset.theme!=='light';
 document.documentElement.dataset.theme=light?'light':'dark';
 themeButton.textContent=light?'Dark theme':'Light theme';
 themeButton.setAttribute('aria-pressed',String(light));
});
function revealHash(){
 let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(e){return;}
 const target=document.getElementById(id);if(!target)return;
 for(let el=target;el;el=el.parentElement)if(el.tagName==='DETAILS')el.open=true;
 target.scrollIntoView({block:'start'});
}
addEventListener('hashchange',revealHash);revealHash();
document.addEventListener('click',event=>{
 const link=event.target.closest('a[href^="#"]');
 if(link && link.hash===location.hash)revealHash();
});
let closedBeforePrint=null;
addEventListener('beforeprint',()=>{
 if(closedBeforePrint!==null)return;
 closedBeforePrint=[...document.querySelectorAll('details:not([open])')];
 closedBeforePrint.forEach(el=>el.open=true);
});
addEventListener('afterprint',()=>{
 (closedBeforePrint||[]).forEach(el=>el.open=false);closedBeforePrint=null;
});
document.getElementById('print-report').addEventListener('click',()=>window.print());
</script>
'''
SCRIPT_HASH = 'sha256-' + base64.b64encode(hashlib.sha256(SCRIPT.split('<script>',1)[1].split('</script>',1)[0].encode('utf-8')).digest()).decode('ascii')


def activity_rules(posts, counts, stored_alerts, cfg, start, end):
    """First trigger per source/query, with the rule's distinct provenance."""
    from .monitor import count_alerts, alert_scope
    al=cfg.get('alert',{}); minutes=int(al.get('window_minutes',30)); candidates=[]
    for source in sorted({p['source'] for p in posts}):
        source_posts=[p for p in posts if p['source']==source]
        for tag in labels(cfg):
            v=A.velocity(source_posts,tag,minutes,int(al.get('uses',200)),float(al.get('ratio',10)),float(al.get('uses_per_account',5)),int(al.get('min_uses',10)))
            if v and v['first_trip']:
                candidates.append(dict(v['first_trip'],source=source,tag=tag,minutes=minutes,origin='Retrospective sliding window'))
    for a in count_alerts(counts,end,int(al.get('uses',200)),float(al.get('ratio',10)),int(al.get('min_uses',10))):
        candidates.append(dict(a,source='x-counts',minutes=60,origin='Stored API counts / closed hour'))
    # Legacy alerts do not carry query provenance; recompute from current evidence.
    hashes={r['query_hash'] for r in counts}
    for a in stored_alerts:
        p=a['payload']
        provenance=(a['source']=='x-counts' and p.get('query_hash') in hashes) or p.get('scope_hash')==alert_scope(cfg,start,end)
        if a['tag'] in labels(cfg) and start<=parse_time(a['start_utc'])<end and provenance:
            candidates.append(dict(p,source=a['source'],tag=a['tag'],start=a['start_utc'],minutes=a['minutes'],origin='Saved live monitor'))
    first={}
    for a in sorted(candidates,key=lambda r:r['start']): first.setdefault((a['source'],a['tag']),a)
    return list(first.values())

def esc(value): return html.escape(str(value)) if value is not None else 'Unknown'
def num(value): return f'{value:,}' if isinstance(value,(int,float)) else 'Unknown'
def med(value): return f'{value:g}' if isinstance(value,(int,float)) else 'Unknown'      # a median: 1 and 0.5, never 1.0
# One line per account signal, in the order analyze.account_features applies them. Keep the two in step: tests compare them.
SIGNAL_RULES={
 'replies':'at least 5 posts, and 8 in 10 of them are replies',
 'no_audience':'at least 5 posts with a median of 0 likes, from an account with fewer than 100 followers',
 'young':'the account was less than 30 days old at its first post here',
 'low_lifetime_activity':'the account was more than a year old at its first post here, has fewer than 100 posts in its whole life, and has at least 5 posts here',
 'observed_hour_concentration':'at least 10 posts on 3 or more days, with 9 in 10 of them inside one eight-hour band',
 'one_domain':'at least 5 posts, 8 in 10 of them carry a link, and 8 in 10 of those links go to one domain',
 'multilingual':'three or more languages, each on at least 1 in 10 of the account\'s posts',
 'co_posted':'the account appears in a Same text, Same link or Similar wording match above',
}

def _table(headers,rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def _link(url,label):
    url=safe_url(url)
    return f'<a href="{esc(url)}" rel="noopener noreferrer">{esc(label)}</a>' if url else esc(label)


def render(store,cfg,now=None,result=None):
    now=now or datetime.now(timezone.utc)
    posts,start,end=selected_posts(store,cfg,now); tags=labels(cfg); wanted=set(tags)
    if result: posts=store.analysis_posts(result['run_id']) or posts
    stored_posts=store.posts(iso(start),iso(end))
    scope=analysis_scope(cfg,start,end)
    hashes={q['query_hash'] for q in scope['expected_queries'] if q['source']=='x'}|{a for q in scope['expected_queries'] if q['source']=='x' for a in q.get('aliases',[])}
    counts=[r for r in store.counts() if in_scope(r,start,end,wanted) and r.get('query_hash') in hashes]
    windows=[r for r in store.windows() if in_scope(r,start,end,wanted) and r.get('query_hash') in hashes]
    coverage=[r for r in store.coverage() if r['label'] in wanted and parse_time(r['start_utc'])<end and parse_time(r['end_utc'])>=start]
    result=result or detection.analyze(posts,coverage,cfg.get('detector'),scope)
    run_notes=[json.loads(r['notes']) for r in store.runs() if r['notes']]
    import_only=bool(posts) and (any('import' in n for n in run_notes) or all(p['source'] not in ('x','bluesky','mastodon') for p in posts)) and not any(any(s in n for s in ('x','bluesky','mastodon')) for n in run_notes)
    names={account_key(p):p['author']+' ('+p['source']+')' for p in posts}
    out=[]; w=out.append
    w(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(cfg.get("name","TopicStream"))} — TopicStream</title><style>{CSS}</style></head><body><main>')
    w('<div class="report-head"><div class="eyebrow">TopicStream / Investigation report</div><div class="toolbar"><button id="theme-toggle" type="button" aria-pressed="false">Light theme</button><button id="print-report" type="button">Print report</button></div></div>')
    if any(c.get('sampling')=='synthetic' for c in coverage): w('<p class="notice"><strong>Synthetic demonstration — invented accounts and posts. This report describes no real-world operation.</strong></p>')
    w(f'<h1>{esc(cfg.get("name","Topic investigation"))}</h1><p class="muted">{esc(iso(start))} to {esc(iso(end))} · UTC · end exclusive</p>')
    if import_only:
        w('<p class="muted">Export: '+esc(min(p['created_utc'] for p in posts)[:10])+' to '+esc(max(p['created_utc'] for p in posts)[:10])+' · observed rows within this report scope.</p><p>Export depth: posts are rows included in the export. Zero observed days do not establish that nobody posted. No platform-side counts in the export are assumed.</p>')
    w('<nav><a href="#groups">Recurring groups</a><a href="#amplified">Amplified</a><a href="#coverage">Coverage</a><a href="#activity">Activity</a><a href="#bursts">Matches</a><a href="#accounts">Accounts</a><a href="#evidence">Evidence</a></nav>')
    w(f'<div class="card"><h2>{esc(result["assessment"])}</h2><p>{esc(result["interpretation"])}</p><p class="muted">This report does not establish deceptive identity, common control, automation, or sponsorship.</p></div>')
    matching=sum(bool(wanted.intersection(p['matched'])) for p in stored_posts)
    w(f'<p><strong>{len(posts):,} of {len(stored_posts):,} stored rows in the interval are included in analysis.</strong> {matching:,} match the case tags or terms before language and exclusion filters. Rows outside the interval are not counted here.</p>')
    alerts=activity_rules(posts,counts,store.monitor_alerts(),cfg,start,end)
    w('<h2 id="activity-alerts">Activity rules tripped</h2><p>Volume and concentration alerts are investigation leads, not a CIB verdict. Retrospective sliding windows use a full-period baseline; live rules use preceding observed intervals.</p>')
    w(_table(['Source / query','First window UTC','Posts or API matches','Accounts','Reasons / rule'],[(esc(a['source']+' / '+a['tag']),esc(a['start'])+f' · {a["minutes"]} min',a['uses'],num(a['accounts']),esc('; '.join(a['reasons']))+'<br><span class="muted">'+esc(a['origin'])+'</span>') for a in alerts]) if alerts else '<p>No activity rule tripped at the configured thresholds.</p>')
    w('<div class="metrics">'+''.join(f'<div class="card"><strong>{esc(v)}</strong>{esc(k)}</div>' for k,v in [('Rows in analysis / interval',f'{len(posts):,} / {len(stored_posts):,}'),('Distinct accounts',len(names)),('Recurring groups',len(result['groups'])),('Local estimate / reserved',f'${store.spent():.4f}')])+'</div>')
    st=result['settings']
    w('<h2 id="groups">Recurring account groups</h2>')
    w(f'<p class="muted">The rule: two accounts become a pair when they post the same text, the same link or a repost of the same post within {st["window_minutes"]} minutes of each other, on at least {st["min_episodes"]} separate occasions (episodes) across at least {st["min_days"]} UTC days. Pairs that connect at least {st["min_accounts"]} accounts make a group.</p>')
    if not result['groups']: w('<p>No group meets the configured recurrence thresholds. Check coverage before drawing a negative conclusion.</p>')
    for index,g in enumerate(result['groups'],1):
        w(f'<section class="card" id="group-{g["id"]}"><h3>Group {index} · {len(g["accounts"])} accounts</h3><p>{esc(g["explanation"])}</p><p>Signals: {esc(", ".join(g["families"]))} · graph density {g["density"]:.2f} · ranking score {g["ranking_score"]:.2f} (not a probability)</p><p>'+esc(', '.join(names.get(a,a) for a in g['accounts']))+'</p>')
        edges=sorted(g['edges'],key=lambda e:(-e['episodes'],-e['days'],e['a'],e['b']))
        pair_rows=[(esc(names.get(e['a'],e['a'])+' / '+names.get(e['b'],e['b'])),e['episodes'],e['days'],', '.join(f'<a href="#event-{eid}">{eid[:8]}</a>' for eid in e['event_ids'])) for e in edges]
        headers=['Account pair','Episodes','Days','Evidence']
        w(f'<details><summary>Account pairs · {len(edges)} total · top {min(25,len(edges))} by episodes</summary>'+_table(headers,pair_rows[:25]))
        if len(edges)>25: w(f'<details><summary>Show all pairs · {len(edges)-25} additional rows</summary>'+_table(headers,pair_rows[25:])+'</details>')
        w('</details>')
        w('<p>Review alternatives: '+esc('; '.join(g['alternatives']))+'</p></section>')
    baseline=result['baseline']
    w(f'<div class="notice">Timing comparison: {result["recurring_edges"]} recurring account pairs observed; a median of {esc(baseline["median_edges"])} across {baseline["repeats"]} shuffled copies of the data. Each copy keeps every post, its account and its UTC day, and hands the times of day out at random among the posts of that day. {esc(baseline["limitation"])}</div>')
    if any(result['limits'][k] for k in ('truncated_posts','high_volume_events_not_compared','missing_stable_id_accounts')): w('<p class="notice">Analysis limits: '+esc(json.dumps(result['limits']))+'</p>')
    amplified=A.amplified_originals(posts,store.amplifiers() if hasattr(store,'amplifiers') else {},max_event_accounts=result['settings'].get('max_event_accounts'))
    w('<h2 id="amplified">Amplified originals</h2><p>The posts in this interval that were reposted most: originals ranked by the repost count the platform returns with them, and the originals behind any reposts collected. A thousand accounts reposting one post inside an hour is coordination in the loose sense; the age and follower profile of the reposters is what separates a public from a purchase, and it needs their profiles (collected with the reposts, or sampled with <code>amplifiers</code>).</p>')
    if amplified:
        def cohort_cell(r):
            c=r['cohort']
            if not c: return 'no profiles yet'+(f' · {r["accounts"]} reposters captured' if r['accounts'] else '')
            return (f'{c["known"]:,} profiles: median age {c["median_age_days"]:,} days, median followers {num(c["median_followers"])}, '
                    f'{c["under_30_days"]} under 30 days ({c["under_30_share"]:.0%}), {c["zero_followers"]} with no followers'+(f' · {r["sampled"]} sampled' if r['sampled'] else ''))
        w(_table(['Original','Platform reposts','Captured here','Reposting accounts','Hours','Reposter profile'],
                 [(esc('@'+(r['author'] or 'unknown'))+': '+esc(r['text'][:110])+(' <span class="muted">(outside the detector\'s comparison limit)</span>' if r['skipped_by_detector'] else ''),num(r['total']),r['captured'],r['accounts'],r['hours'],cohort_cell(r)) for r in amplified]))
    else: w('<p>No reposted originals in scope at these settings.</p>')
    samples=store.amplifier_samples() if hasattr(store,'amplifier_samples') else []
    if samples: w('<p class="muted small">Sampled reposters: '+esc('; '.join(f'post {s["post_id"]}: {s["returned"]} of {s["requested"]} asked ({s["fetched_utc"]})' for s in samples))+'. A sample is the provider\'s newest reposters first, not a random draw.</p>')
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
    if windows:
        w(_table(['Query','Hour UTC','Status','Counts said','Returned','Stop reason'],[(esc(r['tag']),esc(r['start_utc']),esc(r['status']),num(r['expected']),r['got'],esc(r['stop_reason'])) for r in windows]))
        originals_only=[c for c in coverage if c.get('sampling','').startswith('originals')]
        if originals_only: w('<p class="muted small">Windows read with reposts excluded (<code>-is:retweet</code>) return the originals and replies of the hour; "Counts said" still counts reposts, so the two columns differ by design.</p>')
    else: w('<p>No purchased windows. '+('This database has no X counts series.' if not counts else 'Use peak --dry-run to inspect a targeted read.')+'</p>')
    w('<h2 id="activity">Observed activity and alerts</h2>')
    w('<p><a href="#activity-alerts">View the first activity triggers above.</a></p>')
    for tag in tags:
        last_day=(end-timedelta(seconds=1)).date()
        calendar_days=(last_day-start.date()).days+1
        series=A.daily_series(posts,tag,calendar_days,end=last_day); maximum=max([u for _,u,_ in series]+[1])
        w(f'<section class="card"><h3>{esc(tag)}</h3><div class="bars" role="img" aria-label="Observed posts per UTC day">'+''.join(f'<div class="bar" style="height:{max(1,int(145*u/maximum))}px" title="{esc(d)}: {u} posts from {a} accounts"></div>' for d,u,a in series)+'</div>')
        w(_table(['UTC day','Observed posts','Originating accounts'],[(esc(d),u,a) for d,u,a in series]))
        top_accounts=A.top_accounts(posts,tag,top=10,now=now)
        if top_accounts:
            w('<h4>Top originating accounts</h4>')
            w(_table(['Account','Posts with this tag','Share of the tag','Age at first post (days)','Followers','Median likes'],[(esc(r['account']+' ('+r['source']+')'),r['uses'],f'{r["share"]:.0%}',num(r['age_days']),num(r['followers']),med(r['median_likes'])) for r in top_accounts]))
            w('<p class="muted">Straight counts for the accounts that used this tag most, with what the platform says about each. "Unknown" means that profile fact was not collected. Many posts, few likes and few followers on one account is ordinary. The same picture across several accounts at once is a reason to look at them, not a conclusion.</p>')
        w('<details><summary>Related hashtags and linked domains</summary>'+_table(['Hashtag','Posts','Accounts'],[(esc(c['tag']),c['count'],c['accounts']) for c in A.cooccurrence(posts,tag)])+_table(['Domain','Posts','Accounts'],[(esc(c['domain']),c['posts'],c['accounts']) for c in A.top_domains(posts,tag)])+'</details>')
        if counts: w('<details><summary>X volume per hour from the counts API</summary>'+_table(['Hour UTC','API-reported matches'],[(esc(c['start_utc']),c['uses']) for c in counts if c['tag']==tag])+'</details>')
        w('</section>')
    bc=cfg.get('burst',{}); window=int(bc.get('window_minutes',10)); minimum=int(bc.get('minimum',3))
    exact=A.bursts(posts,window,minimum); links=A.link_bursts(posts,window,minimum)
    near=A.paraphrase_bursts(posts[:2000],int(bc.get('paraphrase_window_minutes',60)),minimum,float(bc.get('paraphrase_threshold',.35)))
    if len(posts)>2000: w('<p class="notice">Exploratory similar-wording matches use the earliest 2,000 posts. Recurring groups use their separately stated analysis limit.</p>')
    w('<h2 id="bursts">Text and link matches</h2><p>Matching content may come from a common public source or legitimate organizing. Similar wording does not establish AI authorship.</p>')
    w(f'<p class="muted">Settings used: Same text and Same link list at least {minimum} accounts posting the identical text or link within {window} minutes. Similar wording lists at least {minimum} accounts posting closely matching text within {int(bc.get("paraphrase_window_minutes",60))} minutes.</p>')
    for title,items,field in [('Same text',exact,'text'),('Same link',links,'link'),('Similar wording',near,'samples')]:
        w('<h3>'+title+'</h3>')
        w(_table(['Start UTC','Accounts','Query interval exhausted','Example'],[(esc(b['start']),esc(', '.join(names.get(a,a) for a in b['accounts'])), 'yes' if covers_burst(b,windows) else 'not established',esc(' / '.join(b[field]) if isinstance(b[field],list) else b[field])) for b in items[:50]]) if items else '<p>None at these settings.</p>')
    burst_accounts={a for b in exact+links+near for a in b['accounts']}
    accounts=A.account_features(posts,now=now,burst_accounts=burst_accounts,min_posts=cfg.get('accounts',{}).get('min_posts',3),top=cfg.get('accounts',{}).get('top',40))
    w('<h2 id="accounts">Account observations</h2><p>Age is measured at first observed activity in this case. Low lifetime activity does not establish dormancy. Hour concentration requires at least three observed days and does not establish location or working hours. Flag counts are not probabilities.</p>')
    x_accounts={p['author_id'] for p in posts if p['source']=='x' and p.get('author_id')}
    if x_accounts:
        profiled={p['author_id'] for p in posts if p['source']=='x' and p.get('author_created_utc')}
        if len(profiled)<len(x_accounts): w(f'<p class="muted">Author profiles are known for {len(profiled):,} of {len(x_accounts):,} X accounts in scope; the rest appear by numeric id and carry no age or audience signal. Profiles are bought separately (<code>author_profiles</code>), once per account per UTC day.</p>')
    present=[k for k in SIGNAL_RULES if any(k in r['signals'] for r in accounts)]
    if present: w('<details open><summary>What each signal in this table counts</summary><ul>'+''.join(f'<li><code>{k}</code>: {esc(SIGNAL_RULES[k])}</li>' for k in present)+'</ul><p class="muted">"Posts" means posts in this analysis, not everything the account has posted; "Lifetime posts" is the platform\'s own count for the account. Age is in days. Followers and lifetime posts are as reported when the profile was collected, and "Unknown" means that profile fact was not collected. Accounts with fewer than '+str(cfg.get('accounts',{}).get('min_posts',3))+' posts here are not listed.</p></details>')
    w(_table(['Account','Posts','Observed signals','Age at event','Followers','Lifetime posts','Median likes'],[(esc(r['account']+' ('+r['source']+')'),r['posts'],esc(', '.join(r['signals'])),num(r['age_days']),num(r['followers']),num(r['total_posts']),med(r['median_likes'])) for r in accounts]))
    hours=A.hour_comparison(posts,{r['account_id'] for r in accounts if len(r['signals'])>=2},stored_posts)
    if hours:
        w('<h3>Observed posting-hour comparison</h3><p>Accounts with at least two descriptive signals: '+str(hours['selected_posts'])+' matching posts. Their tightest eight-hour band starts at '+f'{hours["band_start"]:02d}:00 UTC'+f' and contains {hours["band_share"]:.1%} of those posts. The same band contains {hours["all_share"]:.1%} of all stored posts in the interval ({hours["baseline_posts"]:,} rows), regardless of tags or other case filters, and {hours["scoped_share"]:.1%} of posts in analysis. Sampling and ordinary schedules can explain this pattern; it does not establish location, intent, or office hours.</p>')
        profiles=A.count_hour_comparison(counts,hours['band_start'],start,end)
        if profiles:
            w('<p>X query volume in the same band, using stored complete hourly buckets only. Each query is separate because results may overlap. Missing or partial hours are excluded; this is the topic\'s own profile, not an independent control population. No extra API requests were made.</p>')
            w(_table(['Source / query','Query fingerprint','Stored hours','API matches','Share in band'],[(esc(r['source']+' / '+r['tag']),esc(r['query_hash'][:12]),r['hours'],r['uses'],f'{r["share"]:.1%}') for r in profiles]))
        w('<details><summary>Hourly comparison data</summary>'+_table(['UTC hour','Selected accounts / matching posts','All stored posts in the interval'],[(f'{h:02d}:00',hours['hours'][h],hours['all_hours'][h]) for h in range(24)])+'</details>')
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
    w('<h4>Tracking tokens carried by several accounts</h4>')
    if infra['params']:
        w(_table(['Token on the shared links','Distinct accounts','Accounts'],[(' · '.join('<span class="tok">'+esc(t)+'</span>' for t in token.split(' · ')),len(accts),esc(', '.join(sorted((names.get(a,a) for a in accts),key=str.lower)[:30]))+(f' and {len(accts)-30} more' if len(accts)>30 else '')) for token,accts in infra['params']]))
    else: w('<p>No tracking token is carried by three or more accounts.</p>')
    w('<p class="muted">A tracking token is something a sharing or campaign tool adds to the end of a link so its owner can count clicks (<code>utm_campaign=…</code>, a referral code, a short code). Accounts that paste from one source carry the same token. So does anyone who copies or forwards one of their posts, so a shared token ties posts to one source of links and does not by itself make an account part of a group. Share-button boilerplate such as <code>utm_source=twitter</code> is left out, and tokens that always travel together are one row.</p>')
    w('<h4>Domains and link shorteners by number of accounts</h4>')
    domain_rows=[(esc(domain)+' (link shortener)',len(accts)) for domain,accts in infra['shorteners']]+[(esc(domain),n) for domain,n in infra['domains']]
    w(_table(['Domain','Distinct accounts'],domain_rows) if domain_rows else '<p>No linked domain is shared by several accounts.</p>')
    candidate_tags=A.candidates(posts,tags)
    if candidate_tags: w('<h4>Other tags that travel with the tracked ones</h4>'+_table(['Candidate tag','Posts','Accounts'],[(esc(c['tag']),c['posts'],c['accounts']) for c in candidate_tags]))
    else: w('<p class="muted">No untracked tag travels with the tracked ones often enough to list.</p>')
    w('<h2 id="evidence">Supporting evidence</h2>'); used={eid for g in result['groups'] for eid in g['event_ids']}; evidence_keys=set()
    for e in result['events']:
        if e['id'] not in used: continue
        evidence_keys.update(e['post_keys'])
        w(f'<details id="event-{e["id"]}" class="card"><summary>{esc(e["family"])} match · {esc(e["start"])} · {len(e["accounts"])} accounts</summary><p>{esc(e["trace"])}</p><p>'+', '.join(f'<a href="#post-{esc(key)}">{esc(key)}</a>' for key in e['post_keys'])+'</p></details>')
    w(f'<details><summary>Evidence posts · {len(evidence_keys)} referenced records</summary>')
    for post in posts:
        if post_key(post) not in evidence_keys: continue
        w(f'<details class="post" id="post-{esc(post_key(post))}"><summary>{esc(post["author"])} · {esc(post["source"])} · {esc(post["created_utc"])}</summary><div class="muted small">{_link(post.get("url"),post_key(post))}</div><p>{esc(post["text"])}</p><p>'+', '.join(_link(url,url) for url in post['links'])+'</p></details>')
    w('</details>')
    w('<h2>Run details</h2><p>Dataset hash: <code>'+esc(result['dataset_hash'])+'</code></p><p>Detector: '+esc(result['version'])+' · configuration: <code>'+esc(json.dumps(result['settings'],sort_keys=True))+'</code></p><p>Configured X prices are estimates. The request ledger retains unresolved reservations after interrupted calls and does not promise provider-level billing accuracy.</p>')
    w(_table(['Started','Finished','Notes'],[(esc(r['started_utc']),esc(r['finished_utc']),esc(r['notes'])) for r in store.runs()[-10:]]))
    w(f'<p class="muted small">Generated by TopicStream {esc(VERSION)} · {esc(iso(now))}. Findings apply only to the stated queries, period, and collected evidence.</p></main>{SCRIPT}</body></html>')
    return ''.join(out)
