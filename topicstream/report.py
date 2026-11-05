"""Render the report: one self-contained HTML file, laid out like the topic-stream dashboards students will meet at work,
with a method note under every panel saying exactly how its number was produced."""
import html, json, re
from datetime import datetime, timezone
from . import analyze as A
from .sources import parse_time
from . import __version__ as VERSION

CSS = '''
body{margin:0;background:#f3f4f6;font-family:Inter,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#1f2937;font-size:14px;line-height:1.5}
.db{display:grid;grid-template-columns:210px 1fr;min-height:100vh}
.tn{background:#0f172a;color:#cbd5e1;padding:14px 0;position:sticky;top:0;height:100vh;box-sizing:border-box}
.tn .brand{color:#fff;font-weight:800;font-size:17px;padding:4px 18px 18px;display:flex;align-items:center;gap:8px}.tn .brand i{width:22px;height:22px;border-radius:6px;background:linear-gradient(135deg,#f59e0b,#ef4444);display:inline-block}
.tn a{display:block;padding:8px 18px;color:#cbd5e1;text-decoration:none}.tn a:hover{background:#1e293b;color:#fff}.tn .meta{padding:16px 18px;font-size:11.5px;color:#94a3b8;border-top:1px solid #1e293b;margin-top:14px}
.tm{padding:22px 30px 60px;max-width:1180px}
h2{margin:0 0 4px;font-size:21px}.sub{color:#6b7280;margin-bottom:18px}h3{font-size:16px;margin:34px 0 10px;padding-bottom:6px;border-bottom:2px solid #e5e7eb}
.alert{background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px 14px;display:flex;gap:14px;align-items:flex-start;margin-bottom:10px}
.alert b{color:#991b1b}.pill{background:#991b1b;color:#fff;border-radius:4px;font-size:11px;padding:2px 7px;font-weight:700;white-space:nowrap;margin-top:3px}
.quiet{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:12px 14px;margin-bottom:10px}.quiet .pill{background:#166534}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}.tile{border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;background:#fff}.tile .k{font-size:11.5px;color:#6b7280;text-transform:uppercase;letter-spacing:.6px}.tile .v{font-size:24px;font-weight:700;margin-top:4px}.tile .d{font-size:12px;color:#6b7280}
.chart{border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;margin-bottom:14px;background:#fff}.chart h4{margin:0 0 10px;font-size:12px;letter-spacing:.8px;text-transform:uppercase;color:#374151}
.bars{display:flex;align-items:flex-end;gap:5px;height:150px;border-bottom:1px solid #e5e7eb}.bars div{flex:1;background:#f59e0b;position:relative;border-radius:3px 3px 0 0;min-height:1px}.bars div span{position:absolute;top:-16px;left:0;right:0;text-align:center;font-size:10px;color:#6b7280}.bars div.z{background:#e5e7eb}
.xl{display:flex;gap:5px;font-size:10px;color:#6b7280;margin-top:4px}.xl div{flex:1;text-align:center}.xl div small{display:block;color:#9ca3af}
table.tt{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff}table.tt th{text-align:left;background:#f9fafb;padding:8px 12px;color:#374151;font-weight:600;border-bottom:1px solid #e5e7eb;font-size:11.5px;letter-spacing:.5px;text-transform:uppercase}table.tt td{padding:6px 12px;border-bottom:1px solid #f3f4f6;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.3px;vertical-align:top;overflow-wrap:anywhere}table.tt td.t{white-space:nowrap}
.pan{border:1px solid #e5e7eb;border-radius:8px;overflow:auto;margin-bottom:14px;background:#fff}
table.tt.compact th,table.tt.compact td{padding:6px 8px;font-size:11.5px;white-space:nowrap}.pan h4{margin:0;background:#f9fafb;padding:9px 14px;font-size:12px;letter-spacing:.8px;text-transform:uppercase;color:#374151;border-bottom:1px solid #e5e7eb}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:900px){.grid2{grid-template-columns:1fr}.db{grid-template-columns:1fr}.tn{position:static;height:auto}}
.how{font-size:12px;color:#6b7280;padding:8px 14px;border-top:1px dashed #e5e7eb;background:#fafafa}.how b{color:#374151}
code{background:#eef1f5;padding:1px 5px;border-radius:4px;font-size:12px}
.tag{font-weight:700;color:#b45309}
'''
def esc(x): return html.escape(str(x)) if x is not None else ''
ORIG = {}   # lower-case label -> the term as the config spells it, filled by render()
def disp(t): return t if str(t).startswith('#') else '\u201c' + ORIG.get(str(t), str(t)) + '\u201d'   # a phrase shows in quotes, as spelled in the config
def pct(x): return f'{100 * x:.0f}%'
def num(x):
    if x is None: return ''
    if isinstance(x, float) and x.is_integer(): x = int(x)
    return f'{x:,}' if isinstance(x, int) else f'{x:.1f}'

def render(store, cfg, now=None):
    now = now or datetime.now(timezone.utc)
    terms = cfg.get('terms', []); tags = ['#' + t.lower() for t in cfg['tags']] + [t.lower() for t in terms]; days = int(cfg.get('days', 7))
    ORIG.clear(); ORIG.update({t.lower(): t for t in terms})
    slug = lambda t: ('tag-' if t.startswith('#') else 'phrase-') + (re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-') or 'x')   # a hashtag and a phrase with the same word get different anchors
    posts = store.posts(); tds = store.tag_days(); runs = store.runs(); name = cfg.get('name', 'Topic stream'); xcounts = store.counts('x'); xspent = store.spent('x'); wins = store.windows()
    al = cfg.get('alert', {}); win = int(al.get('window_minutes', 30))
    sources = sorted({p['source'] for p in posts}); by_source = {s: sum(1 for p in posts if p['source'] == s) for s in sources}
    out = []
    w = out.append
    w(f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(name)}: topic stream</title><style>{CSS}</style></head><body><div class="db">')
    w('<div class="tn"><div class="brand"><i></i>topicstream</div>')
    for sec, label in [('alerts', 'alerts'), ('overview', 'overview')] + [(slug(t), disp(t)) for t in tags] + [('windows', 'complete windows'), ('bursts', 'bursts'), ('accounts', 'accounts'), ('infrastructure', 'infrastructure'), ('candidates', 'candidates'), ('sources', 'sources')]: w(f'<a href="#{esc(sec)}">{esc(label)}</a>')
    spend_line = f'X spend recorded: ${xspent:.2f}<br>' if xspent else ''
    w(f'<div class="meta">{len(posts):,} posts stored<br>{", ".join(f"{s} {n:,}" for s, n in by_source.items()) or "no sources ran"}<br>{len(runs)} collection run(s)<br>{spend_line}generated {now.strftime("%Y-%m-%d %H:%M")} UTC</div></div>')
    w(f'<div class="tm"><h2>Topic stream: {esc(name)}</h2><div class="sub">Window: {days} days ending {esc(A.end_day(posts).isoformat())} · tags {esc(", ".join("#" + t for t in cfg["tags"]) or "none")}' + (f' · phrases {esc(", ".join(chr(34) + t + chr(34) for t in terms))}' if terms else '') + f' · sources: {esc(", ".join(sources) or "none")} · alert window {win} min</div>')

    # ---- alerts
    w('<h3 id="alerts">Velocity alerts</h3>')
    vel = {t: A.velocity(posts, t, win, int(al.get('uses', 200)), float(al.get('ratio', 10)), float(al.get('uses_per_account', 5)), int(al.get('min_uses', 10))) for t in tags}
    fired = False
    for t, v in vel.items():
        if v and v['first_trip']:
            fired = True; f = v['first_trip']
            w(f'<div class="alert"><span class="pill">ALERT</span><div><b>{esc(disp(t))}, first tripped {esc(f["start"].replace("T", " ")[:16])} UTC.</b> {f["uses"]} uses from {f["accounts"]} originating accounts within {win} minutes ({f["ratio"]:.1f} per account); average {win}-minute window in this collection {v["baseline"]:.2f}. Rule: {esc("; ".join(f["reasons"]))}.' + (f' Busiest window later: {v["uses"]} uses from {v["accounts"]} accounts from {esc(v["start"].replace("T", " ")[:16])}.' if v["start"] != f["start"] else '') + '</div></div>')
    xs = cfg.get('sources', {}).get('x', {}); sampled = bool(xs.get('sample_per_day'))
    for t in tags:
        v = A.velocity_from_counts(xcounts, t, int(al.get('uses', 200)), float(al.get('ratio', 10)), int(al.get('min_uses', 10)))
        if v and v['first_trip']:
            fired = True; f = v['first_trip']
            w(f'<div class="alert"><span class="pill">X COUNTS</span><div><b>{esc(disp(t))} on X, first tripped in the hour starting {esc(f["start"].replace("T", " ")[:16])} UTC.</b> {f["uses"]:,} posts that hour against an average of {v["baseline"]:.1f} an hour over {v["hours"]} hours ({v["total"]:,} posts in all). Rule: {esc("; ".join(f["reasons"]))}.' + (f' Peak hour: {v["uses"]:,} posts from {esc(v["start"].replace("T", " ")[:16])}.' if v["start"] != f["start"] else '') + ' From the counts endpoint, which is complete; accounts are not counted there.</div></div>')
    if not fired: w('<div class="quiet"><span class="pill">QUIET</span> No tag crossed an alert rule in the collected period. Busiest windows are listed per tag below.</div>')
    if sampled: w(f'<div class="how"><b>Sampling caveat:</b> X posts in this database are a stratified sample ({xs.get("sample_per_day")} a day in {xs.get("sample_windows_per_day", 6)} windows), so the post-based windows above understate X volume and can be skewed within a window; the X COUNTS alerts and the hourly chart are the complete record for X.</div>')
    w(f'<div class="how"><b>How:</b> for each tag, sort its posts by time and slide a {win}-minute window; the alert is the first window that trips a rule (what a monitor would have paged on), and the busiest window is shown with it. Rules: absolute uses &ge; {al.get("uses", 200)}; or uses &ge; {al.get("ratio", 10)}&times; the average {win}-minute window over the whole collection; (with at least {al.get("min_uses", 10)} uses); or &ge; {al.get("uses_per_account", 5)} uses per originating account (with at least {2 * int(al.get("min_uses", 10))} uses). Change these in the config; there is no correct setting, only a documented one.</div>')

    # ---- overview tiles
    end = A.end_day(posts); T = A.tiles(posts, tags, days, end)
    w('<h3 id="overview">Overview</h3><div class="tiles">')
    xtotal = sum(c['uses'] for c in xcounts)
    w(f'<div class="tile"><div class="k">Posts collected</div><div class="v">{T["total_uses"]:,}</div><div class="d">{days} days to {esc(end.isoformat())}' + (f' · X counted {xtotal:,} in all' if xtotal else '') + '</div></div>')
    if xcounts:   # the complete record beats the collected posts for the peak
        byday = {}
        for c in xcounts: byday[(c['tag'], c['start_utc'][:10])] = byday.get((c['tag'], c['start_utc'][:10]), 0) + c['uses']
        (ptag, pday), puses = max(byday.items(), key=lambda kv: kv[1])
        w(f'<div class="tile"><div class="k">Peak day (X counts)</div><div class="v">{esc(pday[5:])}</div><div class="d">{esc(ptag)} {puses:,} posts, complete</div></div>')
    else:
        w(f'<div class="tile"><div class="k">Peak day</div><div class="v">{esc(T["peak_day"][5:] if T["peak_day"] else "–")}</div><div class="d">{esc(T["peak_tag"])} {T["peak_uses"]:,}</div></div>')
    w(f'<div class="tile"><div class="k">Originating accounts, median</div><div class="v">{num(T["median_accounts"])}</div><div class="d">per tag-day with activity</div></div>')
    if xcounts:   # complete record: a zero day on X is a real zero, not a sampling gap
        zd = {}
        for c in xcounts: zd[(c['tag'], c['start_utc'][:10])] = zd.get((c['tag'], c['start_utc'][:10]), 0) + c['uses']
        zero = sorted((t_, d_) for (t_, d_), n_ in zd.items() if n_ == 0)
        w(f'<div class="tile"><div class="k">Zero days (X counts)</div><div class="v">{len(zero)}</div><div class="d">{esc(", ".join(d[5:] + " " + t for t, d in zero[:3]))}{"…" if len(zero) > 3 else ""}{"" if zero else "every tracked day had posts"}</div></div></div>')
    else:
        w(f'<div class="tile"><div class="k">Zero days</div><div class="v">{len(T["zero_days"])}</div><div class="d">{esc(", ".join(d[5:] + " " + t for t, d in T["zero_days"][:3]))}{"…" if len(T["zero_days"]) > 3 else ""}</div></div></div>')
    w('<div class="how"><b>Read these carefully:</b> "posts" are what this collection holds (Mastodon and X include reposts; Bluesky search returns originals only), "originating accounts" is distinct authors, and a zero day is zero <em>observed by this collection</em>, which is a statement about the collector before it is a statement about the world.</div>')

    # ---- per tag
    for t in tags:
        tid = slug(t); series = A.daily_series(posts, t, days, end); mx = max([u for d, u, a in series] + [1])
        mine = [p for p in posts if t in p['matched']]
        kind = '' if t.startswith('#') else ' <small style="color:#6b7280;font-weight:500">(phrase)</small>'
        w(f'<h3 id="{esc(tid)}"><span class="tag">{esc(disp(t))}</span>{kind} · {len(mine):,} posts from {len({p["author"] for p in mine}):,} accounts</h3>')
        w(f'<div class="chart"><h4>{esc(disp(t))} · daily uses (accounts underneath)</h4><div class="bars">')
        for d, u, a in series: w(f'<div class="{"z" if not u else ""}" style="height:{int(u / mx * 138)}px"><span>{u}</span></div>')
        w('</div><div class="xl">');
        for d, u, a in series: w(f'<div>{d[5:]}<small>{a} acct</small></div>')
        w('</div>')
        if mine:
            oldest = min(p['created_utc'] for p in mine); depth = (now - parse_time(oldest)).total_seconds() / 86400
            w(f'<div class="how"><b>Collection depth:</b> the oldest post collected for this tag is from {esc(oldest.replace("T", " ")[:16])} UTC, {depth:.1f} days back. Days before that are blank because the collector stopped paginating (<code>max_pages</code>), not because nobody posted; the platform-reported table on the left goes back further.</div>')
        w('</div>')
        # platform-reported
        xh = sorted((c for c in xcounts if c['tag'] == t), key=lambda c: c['start_utc'])
        if xh:
            step = max(1, -(-len(xh) // 168)); xt = sum(c['uses'] for c in xh)          # bucket to at most 168 bars: 1 h for a week, 3 h for three weeks
            buckets = [dict(start=xh[i]['start_utc'], end=xh[min(i + step, len(xh)) - 1]['start_utc'], uses=sum(c['uses'] for c in xh[i:i + step])) for i in range(0, len(xh), step)]
            xm = max([b['uses'] for b in buckets] + [1]); peak = max(buckets, key=lambda b: b['uses']); unit = 'hour' if step == 1 else f'{step}-hour bucket'
            w(f'<div class="chart"><h4>{esc(disp(t))} · X volume per {esc(unit)}, from the counts endpoint ({xt:,} posts over {len(xh)} hours; peak {peak["uses"]:,} at {esc(peak["start"].replace("T", " ")[:16])} UTC)</h4><div class="bars" style="gap:1px">')
            for b in buckets: w(f'<div class="{"z" if not b["uses"] else ""}" style="height:{int(b["uses"] / xm * 138)}px" title="{esc(b["start"].replace("T", " ")[:16])} UTC: {b["uses"]:,}"></div>')
            per_label = max(1, len(buckets) // 10)
            w('</div><div class="xl">' + ''.join(f'<div>{esc(b["start"][5:10])}</div>' for b in buckets[::per_label]) + '</div>')
            w(f'<div class="how"><b>How:</b> <code>GET /2/tweets/counts/{"all" if len(xh) > 170 else "recent"}?query={esc(t)}&granularity=hour</code>, one request per 500 hours, and it counts every post whether or not we paid to read it. Hover a bar for its time. This is the cheap half of X; the posts in this report are the expensive half.</div></div>')
        pt = A.platform_tag_days(tds, t); fs = A.first_seen(posts).get(t)
        w('<div class="pan"><h4>What the platforms report for this tag (uses / accounts)</h4>')
        if pt:
            cols = sorted({(r['source'], r['instance']) for r in pt}); days_ = sorted({r['day'] for r in pt}, reverse=True)[:31]
            cell = {(r['day'], r['source'], r['instance']): r for r in pt}
            w('<table class="tt compact"><tr><th>Day</th>' + ''.join(f'<th>{esc(inst)}</th>' for src, inst in cols) + '</tr>')
            for d in days_:
                w(f'<tr><td>{esc(d[5:])}</td>' + ''.join((lambda r: f'<td>{r["uses"]:,} / {num(r["accounts"]) if r["accounts"] is not None else "n/a"}</td>' if r else '<td>–</td>')(cell.get((d, src, inst))) for src, inst in cols) + '</tr>')
        else: w('<table class="tt"><tr><td>No platform-side counts for this tag (Bluesky has none; X counts need a token).</td></tr>')
        w(f'</table><div class="how"><b>How:</b> Mastodon <code>GET /api/v1/tags/{esc(t.lstrip("#"))}</code> returns seven days of uses and accounts as <em>that server</em> saw them; different servers see different slices of the fediverse, so rows do not add. X <code>GET /2/tweets/counts/recent</code> gives counts only. First observation in our own store: {esc(fs or "none")}.</div></div>')
        # velocity detail
        v = vel.get(t)
        w('<div class="pan"><h4>Busiest window and account concentration (collected posts)</h4>')
        if v:
            w(f'<table class="tt"><tr><th>Window</th><th>Uses</th><th>Accounts</th><th>Per account</th><th>Average window</th></tr><tr><td class="t">{esc(v["start"][5:16])} to {esc(v["end"][5:16])}</td><td>{v["uses"]}</td><td>{v["accounts"]}</td><td>{v["ratio"]:.1f}</td><td>{v["baseline"]:.2f}</td></tr></table>')
            mix = A.account_age_mix(posts, t)
            if mix: w(f'<div style="padding:8px 14px;font-size:12.5px">Account ages known for {mix["accounts_with_age"]} accounts: {mix["under_30"]} created in the last 30 days, {mix["under_90"]} in the last 90.</div>')
        else: w('<div style="padding:10px 14px">No posts collected for this tag.</div>')
        w('<div class="how"><b>How:</b> the same sliding window the co-posting detector uses, applied to one tag instead of one message. Uses per account is the number to watch: 412 uses from 19 accounts is a different thing from 412 uses from 300 accounts.</div></div>')
        # related tags + accounts
        co = A.cooccurrence(posts, t); acc = A.top_accounts(posts, t, now=now)
        w('<div class="grid2"><div class="pan"><h4>Related tags (co-occurrence)</h4><table class="tt"><tr><th>Tag</th><th>Posts</th><th>Share</th><th>Lift</th><th>Accounts</th></tr>')
        for r in co: w(f'<tr><td>{esc(r["tag"])}</td><td>{r["count"]}</td><td>{pct(r["share"])}</td><td>{r["lift"]:.1f}</td><td>{r["accounts"]}</td></tr>')
        if not co: w('<tr><td colspan="5">No co-occurring tags.</td></tr>')
        w('</table><div class="how"><b>How:</b> no platform has a "related hashtags" endpoint; every tool derives it from co-occurrence. Share = fraction of this tag\'s posts that also carry the other tag. Lift = share divided by the other tag\'s frequency in everything collected; 1.0 means no relationship. A high-lift tag carried by few accounts is a candidate campaign tag; a high-share, low-lift tag is just the topic\'s vocabulary.</div></div>')
        dom = A.top_domains(posts, t)
        w('<div class="pan"><h4>Domains linked from this tag\'s posts</h4><table class="tt"><tr><th>Domain</th><th>Posts</th><th>Accounts</th></tr>')
        for r in dom: w(f'<tr><td>{esc(r["domain"])}</td><td>{r["posts"]}</td><td>{r["accounts"]}</td></tr>')
        if not dom: w('<tr><td colspan="3">No outbound links.</td></tr>')
        w('</table><div class="how"><b>How:</b> link cards and URLs in the text, reduced to hostnames. Many posts, few accounts, one domain: that is the pivot from accounts to infrastructure, and the domain is where you go next (WHOIS, certificates, what else is on the host).</div></div></div>')
        w('<div class="pan"><h4>Top originating accounts</h4><table class="tt"><tr><th>Account</th><th>Uses</th><th>Share</th><th>Reposts</th><th>Age (d)</th><th>Followers</th><th>Med. likes</th></tr>')
        for r in acc: w(f'<tr><td>{esc(r["account"])}<br><small style="color:#9ca3af">{esc(r["source"])}</small></td><td>{r["uses"]}</td><td>{pct(r["share"])}</td><td>{r["reposts"]}</td><td>{num(r["age_days"])}</td><td>{num(r["followers"])}</td><td>{num(r["median_likes"])}</td></tr>')
        if not acc: w('<tr><td colspan="7">No accounts.</td></tr>')
        w('</table><div class="how"><b>How:</b> straight counts. Volume without an audience (many posts, single-digit likes, few followers, young account) is visible here if it exists; one account matching it is a Tuesday, a cluster matching it is a lead.</div></div>')

    # ---- complete windows (peak)
    w('<h3 id="windows">Complete windows</h3>')
    if wins:
        w('<div class="pan"><h4>Hours read complete on X: every post, every account</h4><table class="tt"><tr><th>Term</th><th>Hour (UTC)</th><th>Counts said</th><th>Read</th><th>Accounts</th><th>Per account</th><th>First 10 minutes</th></tr>')
        for wn in wins:
            le = A.leading_edge(posts, wn, 10)
            gap = (f'<br><small>{wn["expected"] - wn["got"]:,} counted, not returned</small>' if wn["expected"] and wn["expected"] > wn["got"] else '')
            if le: w(f'<tr><td class="t">{esc(disp(wn["tag"]))}</td><td class="t">{esc(wn["start_utc"][5:16].replace("T", " "))}</td><td>{num(wn["expected"])}</td><td>{wn["got"]}{gap}</td><td>{le["accounts"]}</td><td>{le["per_account"]:.1f}</td><td>{le["edge_posts"]} posts from {len(le["edge_accounts"])} accounts: {esc(", ".join(le["edge_accounts"][:8]))}{"…" if len(le["edge_accounts"]) > 8 else ""}' + (f'<br><small>links: {esc(", ".join(f"{d} ({n})" for d, n in le["edge_links"]))}</small>' if le["edge_links"] else '') + '</td></tr>')
            else: w(f'<tr><td class="t">{esc(disp(wn["tag"]))}</td><td class="t">{esc(wn["start_utc"][5:16].replace("T", " "))}</td><td>{num(wn["expected"])}</td><td>{wn["got"]}{gap}</td><td colspan="3">no posts stored for this window</td></tr>')
        w('</table><div class="how"><b>How:</b> <code>python -m topicstream peak</code> reads the busiest hour(s) from the counts series complete, so the burst and account rules below run on the full record instead of a sample. The first ten minutes are the leading edge: who posted before anyone could have organically seen it. Seeders post inside minutes of each other with the same link; organic uptake comes later from people who saw them. Uses per account inside the hour: 206 posts from 190 accounts is a story breaking, 206 from 19 is a push. When the counts said more than the read returned, the difference is posts the index still counts but search no longer serves: deleted, or from accounts suspended or protected since. On a topic with bot traffic that can be a fifth of the hour, and it is itself worth knowing.</div></div>')
    else:
        if xcounts:
            busiest = max(xcounts, key=lambda c: c['uses'])
            w(f'<div class="pan"><div style="padding:10px 14px;font-size:13px">No hour has been read complete yet. The counts series says which hours matter: the busiest is {esc(busiest["start_utc"][5:16].replace("T", " "))} UTC with {num(busiest["uses"])} posts, ${busiest["uses"] * 0.005:.2f} to read in full. <code>python -m topicstream peak --hours 2</code> buys the top hours, and the burst and account rules then run on the whole record for those hours.</div></div>')
        else:
            w('<div class="pan"><div style="padding:10px 14px;font-size:13px">Complete windows come from X: <code>python -m topicstream peak</code> reads the busiest hours of the counts series in full, so the burst and account rules run on the whole record for those hours instead of a sample. This database has no X counts series.</div></div>')

    # ---- bursts: exact text, link, paraphrase
    bw = int(cfg.get('burst', {}).get('window_minutes', 10)); bm = int(cfg.get('burst', {}).get('minimum', 3))
    in_win = lambda start: any(wn['start_utc'] <= start < wn['end_utc'] for wn in wins)
    cth = '<th>Complete?</th>' if wins else ''; ctd = (lambda start: f'<td>{"yes" if in_win(start) else "sample"}</td>') if wins else (lambda start: '')
    B = A.bursts(posts, bw, bm); L = A.link_bursts(posts, bw, bm); PB = A.paraphrase_bursts(posts, int(cfg.get('burst', {}).get('paraphrase_window_minutes', 60)), bm, float(cfg.get('burst', {}).get('paraphrase_threshold', 0.35)))
    burst_accounts = {a for b in B + L + PB for a in b['accounts']}
    w('<h3 id="bursts">Bursts: the co-posting rules</h3>')
    w(f'<div class="pan"><h4>Same text, several accounts, inside the window</h4><table class="tt"><tr><th>Start</th><th>Accounts</th><th>Uses</th>{cth}<th>Text</th></tr>')
    for b in B[:25]: w(f'<tr><td class="t">{esc(b["start"][5:16])}</td><td>{len(b["accounts"])}<br><small>{esc(", ".join(b["accounts"][:6]))}{"…" if len(b["accounts"]) > 6 else ""}</small></td><td>{b["uses"]}</td>{ctd(b["start"])}<td>{esc(b["text"])}</td></tr>')
    if not B: w('<tr><td colspan="5">None at this window and minimum.' + (' X posts here are a sample, and a sparse sample rarely catches two copies inside ten minutes even when the copying is real; <code>peak</code> buys the hour that matters complete.' if sampled and not wins else '') + '</td></tr>')
    w(f'</table><div class="how"><b>How:</b> strip links, hashtags and mentions, group by the remaining text, slide a {bw}-minute window, report groups with at least {bm} distinct accounts. Reposts excluded.' + (' "Complete?" says whether the burst falls in an hour that was read in full.' if wins else '') + '</div></div>')
    w(f'<div class="pan"><h4>Same link, several accounts, inside the window</h4><table class="tt"><tr><th>Start</th><th>Accounts</th><th>Uses</th>{cth}<th>Link</th></tr>')
    for b in L[:25]: w(f'<tr><td class="t">{esc(b["start"][5:16])}</td><td>{len(b["accounts"])}<br><small>{esc(", ".join(b["accounts"][:6]))}{"…" if len(b["accounts"]) > 6 else ""}</small></td><td>{b["uses"]}</td>{ctd(b["start"])}<td>{esc(b["link"][:160])}</td></tr>')
    if not L: w('<tr><td colspan="5">None at this window and minimum.</td></tr>')
    w('</table><div class="how"><b>How:</b> the exact URL, tracking parameters included, is the key. A person retyping a link does not reproduce <code>utm_campaign=rs9</code>; a tool pasting one does. Same window and minimum as the text rule.</div></div>')
    w(f'<div class="pan"><h4>Same message in different words (paraphrase)</h4><table class="tt"><tr><th>Start</th><th>Accounts</th><th>Uses</th><th>Variants</th><th>Exact copies</th>{cth}<th>Samples</th></tr>')
    for b in PB[:25]: w(f'<tr><td class="t">{esc(b["start"][5:16])}</td><td>{len(b["accounts"])}<br><small>{esc(", ".join(b["accounts"][:6]))}{"…" if len(b["accounts"]) > 6 else ""}</small></td><td>{b["uses"]}</td><td>{b["variants"]}</td><td>{b["exact"]}</td>{ctd(b["start"])}<td>{"<br>".join(esc(x) for x in b["samples"][:2])}</td></tr>')
    if not PB: w('<tr><td colspan="7">None.</td></tr>')
    w(f'</table><div class="how"><b>How:</b> word-pair shingles, Jaccard similarity of at least {cfg.get("burst", {}).get("paraphrase_threshold", 0.35)} (a light rewrite scores about 0.4, an unrelated post on the same topic about 0.1), clustered, then a {cfg.get("burst", {}).get("paraphrase_window_minutes", 60)}-minute window. This is the 2026 version of copy-paste: a language model writes every variant, so the exact-text rule sees nothing and this one sees the cluster. "Variants" is how many distinct wordings; "exact copies" is the size of the largest identical group inside it. A shingle shared by more than 200 posts is treated as the topic\'s vocabulary and ignored.</div></div>')

    # ---- accounts with signals
    AF = A.account_features(posts, now=now, windows=wins, burst_accounts=burst_accounts, min_posts=int(cfg.get('accounts', {}).get('min_posts', 3)), top=int(cfg.get('accounts', {}).get('top', 40)))
    w('<h3 id="accounts">Accounts, with signals</h3>')
    flagged = [p for p in posts if p['author'] in {r['account'] for r in AF if len(r['signals']) >= 2}]
    if flagged:
        prof = A.hour_profile(flagged); hm = max(prof['hours'] + [1]); allp = A.hour_profile(posts)
        w(f'<div class="chart"><h4>Posting hour, UTC, accounts with 2+ signals · {len(flagged):,} posts · tightest 8-hour band {prof["band_start"]:02d}:00 to {prof["band_end"]:02d}:00 holds {pct(prof["band_share"])}; all posts {pct(allp["band_share"])}</h4><div class="bars">')
        for h, n in enumerate(prof['hours']): w(f'<div class="{"z" if not n else ""}" style="height:{int(n / hm * 138)}px" title="{h:02d}:00 UTC: {n}"><span>{n or ""}</span></div>')
        w('</div><div class="xl">' + ''.join(f'<div>{h:02d}</div>' for h in range(24)) + '</div><div class="how"><b>How:</b> a run operation posts during its operators\' working hours and goes quiet on their holidays; a real audience is spread across its own time zones. If the tightest eight-hour band holds most of the flagged accounts\' posting and the topic\'s audience is somewhere else, ask what time zone that band is nine to five in. Compare the two shares: an hour bought complete adds posts to that hour for everyone, so the flagged accounts\' band only means something when it is well above the all-posts share.</div></div>')
    w('<div class="pan"><h4>Ranked by number of signals, then volume</h4><table class="tt"><tr><th>Account</th><th>Posts</th><th>Signals</th><th>Replies</th><th>Med. likes</th><th>Links</th><th>Langs</th><th>8-h band</th></tr>')
    for r in AF:
        facts = ' · '.join(x for x in [f'{num(r["age_days"])} d old' if r['age_days'] is not None else '', f'{num(r["followers"])} followers' if r['followers'] is not None else '', f'{num(r["total_posts"])} posts lifetime' if r['total_posts'] is not None else ''] if x)
        w(f'<tr><td>{esc(r["account"])}<br><small style="color:#9ca3af">{esc(r["source"])}{(" · " + esc(facts)) if facts else ""}</small></td><td>{r["posts"]}</td><td>{esc(", ".join(r["signals"])) or "–"}</td><td>{pct(r["reply_share"])}{("<br><small>→ " + esc(r["reply_to"]) + "</small>") if r["reply_to"] else ""}</td><td>{num(r["median_likes"])}</td><td>{pct(r["link_share"])}{("<br><small>" + esc(r["top_domain"]) + "</small>") if r["top_domain"] else ""}</td><td>{esc(r["langs"])}</td><td>{esc(r["band"])}<br><small>{pct(r["band_share"])}</small></td></tr>')
    if not AF: w('<tr><td colspan="8">No account has enough posts yet.</td></tr>')
    w('</table><div class="how"><b>Signals, each a plain rule:</b> <code>replies</code> 80%+ of posts are replies (reply hijacking); <code>no_audience</code> median likes zero and under 100 followers; <code>young</code> account under 30 days old; <code>dormant_then_active</code> account over a year old with under 100 lifetime posts, now busy here; <code>office_hours</code> 90%+ of posts inside one 8-hour band; <code>one_domain</code> 80%+ of posts carry a link and 80%+ of links go to one domain; <code>multilingual</code> three or more languages at 10%+ each; <code>peak_only</code> every post falls inside an hour read complete; <code>co_posted</code> in at least one burst above. More signals is a reason to look, not a conclusion: a vulnerability feed trips four of these and is exactly what it looks like.</div></div>')
    CC = A.creation_clusters(posts, {r['account'] for r in AF if len(r['signals']) >= 2})
    if CC:
        w('<div class="pan"><h4>Account creation weeks over-represented among flagged accounts</h4><table class="tt"><tr><th>ISO week</th><th>Flagged accounts created</th><th>Share of flagged</th><th>All accounts created</th><th>Share of all</th><th>Lift</th></tr>')
        for c in CC: w(f'<tr><td>{esc(c["week"])}</td><td>{c["subset"]}</td><td>{pct(c["subset_share"])}</td><td>{c["all"]}</td><td>{pct(c["all_share"])}</td><td>{c["lift"]:.1f}</td></tr>')
        w('</table><div class="how"><b>How:</b> accounts created in a batch wake up for the same topic. A week where the flagged accounts\' creation dates are three or more times over-represented, with at least three of them, is worth a look at the accounts themselves.</div></div>')
    XP = A.cross_platform(posts, int(cfg.get('burst', {}).get('cross_platform_minutes', 30)))
    w('<div class="pan"><h4>Cross-platform seeding: the same text or link on two or more platforms inside the window</h4><table class="tt"><tr><th>Start</th><th>Kind</th><th>Platforms</th><th>Posts</th><th>Accounts</th><th>Key</th></tr>')
    for r in XP[:20]: w(f'<tr><td class="t">{esc(r["start"][5:16])}</td><td>{esc(r["kind"])}</td><td>{esc(", ".join(r["sources"]))}</td><td>{r["posts"]}</td><td><small>{esc(", ".join(r["accounts"][:6]))}{"…" if len(r["accounts"]) > 6 else ""}</small></td><td>{esc(r["key"][:100])}</td></tr>')
    if not XP: w('<tr><td colspan="6">None' + (' (only one platform in this database).' if len(sources) < 2 else '.') + '</td></tr>')
    w('</table><div class="how"><b>How:</b> normalized text and exact links, matched across sources within the window. Almost nobody can see this because almost nobody collects more than one platform. A message seeded on three platforms minutes apart was placed, not shared.</div></div>')

    # ---- infrastructure
    INF = A.infrastructure(posts)
    w('<h3 id="infrastructure">Shared link infrastructure</h3><div class="grid2"><div class="pan"><h4>Tracking parameters carried by several accounts</h4><table class="tt"><tr><th>Parameter</th><th>Accounts</th></tr>')
    for k, accts in INF['params']: w(f'<tr><td class="t">{esc(k[:40])}</td><td>{len(accts)}<br><small>{esc(", ".join(accts[:6]))}{"…" if len(accts) > 6 else ""}</small></td></tr>')
    if not INF['params']: w('<tr><td colspan="2">None shared by three or more accounts.</td></tr>')
    w('</table><div class="how"><b>How:</b> query-string parameters on the links in posts, grouped by name and value. A campaign\'s links carry its tracking token (<code>utm_campaign=…</code>, a referral code, a short code); people pasting from the same source share it, people typing a URL do not. Share-button boilerplate (<code>utm_source=twitter</code>, <code>utm_medium=social</code>) is dropped, and parameters that always travel together on the same accounts are one row.</div></div>')
    w('<div class="pan"><h4>Shorteners and domains by number of accounts</h4><table class="tt"><tr><th>Domain</th><th>Accounts</th></tr>')
    for d, accts in INF['shorteners']: w(f'<tr><td>{esc(d)} <small>(shortener)</small></td><td>{len(accts)}</td></tr>')
    for d, n in INF['domains'][:15]: w(f'<tr><td>{esc(d)}</td><td>{n}</td></tr>')
    w('</table><div class="how"><b>How:</b> shorteners hide the destination and are worth expanding by hand; a domain linked by many accounts is the pivot to WHOIS, certificates and hosting.</div></div></div>')

    # ---- candidates (snowball)
    C = A.candidates(posts, tags, top=int(cfg.get('discover', {}).get('show', 25)), min_posts=int(cfg.get('discover', {}).get('min_posts', 3)))
    w('<h3 id="candidates">Candidate tags not yet tracked</h3><div class="pan"><h4>Tags riding along with what you track</h4><table class="tt"><tr><th>Tag</th><th>Posts</th><th>Accounts</th><th>Per account</th><th>Rides with</th></tr>')
    for c in C: w(f'<tr><td>{esc(c["tag"])}</td><td>{c["posts"]}</td><td>{c["accounts"]}</td><td>{c["per_account"]:.1f}</td><td>{esc(c["rides_with"])}</td></tr>')
    if not C: w('<tr><td colspan="5">Nothing beyond the tracked tags yet.</td></tr>')
    w('</table><div class="how"><b>How:</b> every hashtag in the collected posts that is not already tracked, ranked by how many distinct accounts carry it. Many accounts means the topic has spread and the tag is worth tracking; many posts from few accounts means someone is pushing it, which is a different reason to track it. <code>python -m topicstream discover --add 2</code> appends the top two to the config; <code>discover.auto</code> lets watch mode do it on its own, capped by <code>discover.max_tags</code>, because every added tag costs what any tag costs on X.</div></div>')

    # ---- sources
    w(f'<h3 id="sources">Sources, costs and what each one leaves out</h3><div class="pan"><h4>Collection runs · X spend recorded in this database: ${xspent:.2f}</h4><table class="tt"><tr><th>Started</th><th>Finished</th><th>Notes</th></tr>')
    for r in runs[-10:]: w(f'<tr><td class="t">{esc(r["started_utc"])}</td><td class="t">{esc(r["finished_utc"] or "running")}</td><td>{esc(json.dumps(json.loads(r["notes"]) if r["notes"] else {}, ensure_ascii=False))}</td></tr>')
    meters = [json.loads(r['notes'])['x_meter_before'] for r in runs if r['notes'] and 'x_meter_before' in json.loads(r['notes'])]
    w('</table>' + (f'<div class="how"><b>Two ledgers:</b> the tool\'s ledger above counts every post X returned, ${xspent:.2f}. X\'s own meter (<code>GET /2/usage/tweets</code>) counts unique posts per billing cycle; it read {meters[0]:,} at the first run here that recorded it and {meters[-1]:,} at the latest, so re-reads between runs cost nothing. The invoice follows the meter.</div>' if meters else '') + '</div>')
    present = {p['source'] for p in posts} | {r['source'] for r in tds} | ({'x'} if xcounts or xspent else set()) | ({'mastodon'} if any('mastodon' in (r['notes'] or '') for r in runs) else set()) | ({'bluesky'} if any('bluesky' in (r['notes'] or '') for r in runs) else set())
    imported = sorted(src for src in present if src not in ('mastodon', 'bluesky', 'x'))
    notes = []
    if 'mastodon' in present: notes.append('''<p><b>Mastodon.</b> No credentials. <code>/api/v1/tags/{name}</code> gives seven days of uses and accounts; <code>/api/v1/timelines/tag/{name}</code> gives the posts, 40 a page. Each server reports only what federated to it, so poll several and de-duplicate on the post URI (this tool does). Some servers require a token for public timelines and answer 401 or 422; the run log says which.</p>''')
    if 'bluesky' in present: notes.append('''<p><b>Bluesky.</b> Free app password required since the public AppView stopped serving <code>app.bsky.feed.searchPosts</code> unauthenticated. Search returns original posts only, so uses are undercounted relative to the other two; <code>hitsTotal</code> is approximate. For a true live stream, the Jetstream firehose is public and free (websocket), and is the next feature to add.</p>''')
    if 'x' in present: notes.append('''<p><b>X.</b> Pay-per-use since February 2026: $0.005 per post read, $0.005 per counts request, 3 million reads a month before Enterprise. Counting is cheap (a seven-day daily series for one tag is half a cent); reading posts is where the money goes, which is why the config has a budget guard and a per-tag post cap. Uses include reposts unless <code>-is:retweet</code> is in the query.</p>''')
    if imported: notes.append(f'<p><b>Imported export{"s" if len(imported) > 1 else ""} ({esc(", ".join(imported))}).</b> Loaded with <code>import-csv</code>: the posts are whatever the export holds, nothing was collected live, and the platform\'s own counts (uses and originating accounts per day, as the platform reports them) are not in it unless the export carried them. Account age, followers and lifetime posts come from a profiles file joined on handle when one was given; without it the account signals that need them stay quiet.</p>')
    notes.append('''<p><b>Everything else.</b> Reddit (free OAuth API, 100 requests a minute), YouTube Data API (free quota), Telegram (Telethon, your own account) are the natural next collectors; TikTok's Research API and Meta's Content Library are for approved researchers only. The commercial dashboards (Brandwatch, Talkwalker, Meltwater) are these same calls plus licensed firehoses plus a sales team.</p>''')
    w('<div class="pan"><h4>Platform notes</h4><div style="padding:10px 14px;font-size:13px">' + '\n'.join(notes) + '</div></div>')
    w(f'<div class="how" style="margin-top:30px;border:0;background:none;text-align:center">Generated by topicstream {esc(VERSION)} · <a href="https://github.com/ArgeliusLabs/TopicStream">github.com/ArgeliusLabs/TopicStream</a> · standard-library Python, every number explained above it</div>')
    w('</div></div></body></html>')
    return ''.join(out)
