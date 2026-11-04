"""The numbers behind the dashboard, each one a few lines of plain Python.

Everything here works on the list of post dicts that Store.posts() returns, so you can run it over any export that
has the same columns, including the Ciap export from the Day 6 dossier (see README, "Running it on the exercise data")."""
import re, collections, statistics
from datetime import datetime, timedelta, timezone
from .sources import domain_of, parse_time

def _t(p): return parse_time(p['created_utc'])
def _for_tag(posts, tag): return [p for p in posts if tag in p['matched']]
def _day(p): return p['created_utc'][:10]

def end_day(posts):
    """The last day of the reporting window: the newest post in the store (today, for a live collection)."""
    return datetime.strptime(max(p['created_utc'] for p in posts)[:10], '%Y-%m-%d').date() if posts else datetime.now(timezone.utc).date()

def daily_series(posts, tag, days, end=None):
    """Uses and originating accounts per UTC day for the `days` days ending on `end`, zeros included: a zero day is information."""
    today = end or end_day(posts); out = []
    by = collections.defaultdict(list)
    for p in _for_tag(posts, tag): by[_day(p)].append(p['author'])
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat(); out.append((d, len(by[d]), len(set(by[d]))))
    return out

def platform_tag_days(tag_days, tag):
    """What the platforms themselves report, per server. Mastodon gives uses and accounts; X counts give uses only."""
    return [r for r in tag_days if r['tag'] == tag]

def first_seen(posts):
    out = {}
    for p in posts:
        for t in p['matched']:
            if t not in out or p['created_utc'] < out[t]: out[t] = p['created_utc']
    return out

def velocity(posts, tag, window_min=30, threshold_uses=200, threshold_ratio=10.0, min_accounts_ratio=5.0, min_uses=10):
    """Slide a window along the tag's timeline. Report the busiest window, its baseline, and whether it would alert.
    baseline = average uses per `window_min` across the whole collected period (crude, honest, and conservative).
    Alert reasons: absolute (uses >= threshold_uses), ratio (uses >= threshold_ratio * baseline, and at least min_uses, so one
    post in a quiet week never pages anyone), concentration (uses/accounts >= min_accounts_ratio with at least 2*min_uses uses)."""
    rows = sorted(_for_tag(posts, tag), key=lambda p: p['created_utc'])
    if not rows: return None
    W = timedelta(minutes=window_min); times = [_t(p) for p in rows]
    # baseline first: the average uses per window over the whole collected period, burst included (so the test is conservative).
    # A median would be zero for anything sparser than a firehose and the ratio rule could never fire.
    t0 = times[0].replace(minute=0, second=0); span = max(1, int((times[-1] - t0) / W) + 1)
    baseline = len(times) / span
    def judge(uses, accounts):
        reasons = []
        if uses >= threshold_uses: reasons.append(f"{uses} uses in {window_min} min (threshold {threshold_uses})")
        if uses >= min_uses and baseline > 0 and uses >= threshold_ratio * baseline: reasons.append(f"{uses / baseline:.0f}x the average window ({baseline:.2f})")
        ratio = uses / accounts if accounts else 0
        if ratio >= min_accounts_ratio and uses >= 2 * min_uses: reasons.append(f"{ratio:.1f} uses per account")
        return ratio, reasons
    best = None; first = None
    for i in range(len(rows)):
        j = i
        while j < len(rows) and times[j] - times[i] <= W: j += 1
        inside = rows[i:j]; uses = len(inside); accounts = len({p['author'] for p in inside}); ratio, reasons = judge(uses, accounts)
        win = dict(start=rows[i]['created_utc'], end=rows[j - 1]['created_utc'], uses=uses, accounts=accounts, ratio=ratio, reasons=reasons)
        if best is None or uses > best['uses']: best = win
        if reasons and first is None: first = win      # the moment a monitor would have paged someone
    best.update(window_min=window_min, baseline=baseline, span_windows=span, first_trip=first)
    return best

def cooccurrence(posts, tag, top=15):
    """Related tags are not a platform feature; they are co-occurrence. share = fraction of the tag's posts that also
    carry the other tag; lift = how much more often than in the whole collection (lift 1 = no relationship)."""
    mine = _for_tag(posts, tag); n = len(mine)
    if not n: return []
    base = collections.Counter(t for p in posts for t in set(p['tags'])); N = len(posts)
    co = collections.Counter(t for p in mine for t in set(p['tags']) if '#' + t != tag.lower())
    out = []
    for t, c in co.most_common(top):
        share = c / n; overall = base[t] / N; out.append(dict(tag='#' + t, count=c, share=share, lift=(share / overall) if overall else 0, accounts=len({p['author'] for p in mine if t in p['tags']})))
    return out

def top_domains(posts, tag=None, top=12):
    rows = _for_tag(posts, tag) if tag else posts; c = collections.Counter(); acc = collections.defaultdict(set)
    for p in rows:
        for u in p['links']:
            d = domain_of(u)
            if d: c[d] += 1; acc[d].add(p['author'])
    return [dict(domain=d, posts=n, accounts=len(acc[d])) for d, n in c.most_common(top)]

def top_accounts(posts, tag, top=15, now=None):
    now = now or datetime.now(timezone.utc); rows = _for_tag(posts, tag); n = len(rows)
    by = collections.defaultdict(list)
    for p in rows: by[p['author']].append(p)
    out = []
    for a, ps in sorted(by.items(), key=lambda kv: -len(kv[1]))[:top]:
        likes = [p['likes'] for p in ps if p['likes'] is not None]
        age = None
        if ps[0]['author_created_utc']: age = (now - parse_time(ps[0]['author_created_utc'])).days
        out.append(dict(account=a, source=ps[0]['source'], uses=len(ps), share=len(ps) / n, reposts=sum(1 for p in ps if p['is_repost']), age_days=age,
                        followers=ps[0]['author_followers'], median_likes=statistics.median(likes) if likes else None, first=min(p['created_utc'] for p in ps)))
    return out

def _norm_text(s):
    s = re.sub(r'https?://\S+', '', s); s = re.sub(r'#\w+', '', s); s = re.sub(r'@\S+', '', s); return re.sub(r'\s+', ' ', s).strip().lower()

def bursts(posts, window_min=10, minimum=3, min_chars=40):
    """Same text, several accounts, short window: the co-posting rule from Day 6, applied to live data.
    Reposts are excluded (a repost is the platform copying, not an account retyping)."""
    groups = collections.defaultdict(list)
    for p in posts:
        if p['is_repost']: continue
        k = _norm_text(p['text'])
        if len(k) >= min_chars: groups[k].append((_t(p), p['author'], p))
    W = timedelta(minutes=window_min); out = []
    for k, rows in groups.items():
        rows.sort(key=lambda r: r[0]); i = 0
        while i < len(rows):
            inside = [r for r in rows if rows[i][0] <= r[0] <= rows[i][0] + W]; accounts = {r[1] for r in inside}
            if len(accounts) >= minimum:
                out.append(dict(start=inside[0][2]['created_utc'], accounts=sorted(accounts), uses=len(inside), text=inside[0][2]['text'][:160], sources=sorted({r[2]['source'] for r in inside})))
                i += len(inside)
            else: i += 1
    return sorted(out, key=lambda b: -len(b['accounts']))

def tiles(posts, tags, days, end=None):
    """The four numbers at the top of the dashboard, computed the same way the fictional one defined them."""
    end = end or end_day(posts); start = (end - timedelta(days=days - 1)).isoformat()
    total = sum(1 for t in tags for p in _for_tag(posts, t) if p['created_utc'][:10] >= start)
    peak = ('', 0, ''); medians = []; zero_days = []
    for t in tags:
        s = daily_series(posts, t, days, end)
        for d, u, a in s:
            if u > peak[1]: peak = (d, u, t)
            if u == 0: zero_days.append((t, d))
        acc = [a for d, u, a in s if u]
        if acc: medians.append(statistics.median(acc))
    return dict(total_uses=total, peak_day=peak[0], peak_uses=peak[1], peak_tag=peak[2], median_accounts=statistics.median(medians) if medians else 0, zero_days=zero_days)

def account_age_mix(posts, tag, now=None):
    """Share of the tag's originating accounts created in the last 30 / 90 days. Young accounts are not proof of anything; a spike of them is a question."""
    now = now or datetime.now(timezone.utc); ages = {}
    for p in _for_tag(posts, tag):
        if p['author_created_utc']: ages[p['author']] = (now - parse_time(p['author_created_utc'])).days
    n = len(ages)
    return dict(accounts_with_age=n, under_30=sum(1 for a in ages.values() if a < 30), under_90=sum(1 for a in ages.values() if a < 90)) if n else None

def candidates(posts, tracked, top=25, min_posts=3):
    """Tags that ride along with what we track but are not tracked themselves: the snowball step.
    For each: posts, distinct accounts, posts per account, and which tracked thing it mostly appears with.
    Breadth (many accounts) says the topic has spread; concentration (many posts, few accounts) says someone is pushing it.
    Both are reasons to add a tag; the report shows both and leaves the choice to the analyst (or to discover.auto, bounded)."""
    tracked = {t.lower() for t in tracked}; stats = {}
    for p in posts:
        for t in set(p['tags']):
            if '#' + t in tracked: continue
            d = stats.setdefault(t, dict(posts=0, accounts=set(), with_=collections.Counter()))
            d['posts'] += 1; d['accounts'].add(p['author']); d['with_'].update(p['matched'])
    out = []
    for t, d in stats.items():
        if d['posts'] < min_posts: continue
        rides, n = d['with_'].most_common(1)[0] if d['with_'] else ('', 0)
        out.append(dict(tag='#' + t, posts=d['posts'], accounts=len(d['accounts']), per_account=d['posts'] / len(d['accounts']), rides_with=rides))
    return sorted(out, key=lambda r: (-r['accounts'], -r['posts'], r['tag']))[:top]

def velocity_from_counts(counts, tag, threshold_uses=200, threshold_ratio=10.0, min_uses=10):
    """The X velocity alert from the counts endpoint: complete, hourly, no accounts. baseline = average posts per hour over the
    whole series (zeros included). first_trip = first hour that meets a rule; busiest = the biggest hour."""
    rows = sorted((c for c in counts if c['tag'] == tag), key=lambda c: c['start_utc'])
    if not rows: return None
    baseline = sum(c['uses'] for c in rows) / len(rows)
    def judge(n):
        r = []
        if n >= threshold_uses: r.append(f"{n} posts in an hour (threshold {threshold_uses})")
        if n >= min_uses and baseline > 0 and n >= threshold_ratio * baseline: r.append(f"{n / baseline:.0f}x the average hour ({baseline:.1f})")
        return r
    best = max(rows, key=lambda c: c['uses']); first = next((c for c in rows if judge(c['uses'])), None)
    return dict(start=best['start_utc'], uses=best['uses'], reasons=judge(best['uses']), baseline=baseline, hours=len(rows), total=sum(c['uses'] for c in rows),
                first_trip=dict(start=first['start_utc'], uses=first['uses'], reasons=judge(first['uses'])) if first else None)
