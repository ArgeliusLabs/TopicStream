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


# ---------------------------------------------------------------------------------------------------------------------- 0.2: the coordination layer
# Everything below is rule-based and explained. It ranks and shows evidence; it never says "bot" or "state actor". That call is the analyst's.

def _norm_link(u):
    u = u.strip().lower().split('#')[0]
    return u[:-1] if u.endswith('/') else u

def link_bursts(posts, window_min=10, minimum=3):
    """Same URL from several accounts inside the window: the second co-posting rule. The exact URL, tracking token included,
    is the fingerprint; a person retyping a link does not reproduce utm_campaign=rs9."""
    groups = collections.defaultdict(list)
    for p in posts:
        if p['is_repost']: continue
        for u in set(_norm_link(l) for l in p['links'] if l):
            groups[u].append((_t(p), p['author'], p))
    W = timedelta(minutes=window_min); out = []
    for u, rows in groups.items():
        rows.sort(key=lambda r: r[0]); i = 0
        while i < len(rows):
            inside = [r for r in rows if rows[i][0] <= r[0] <= rows[i][0] + W]; accounts = {r[1] for r in inside}
            if len(accounts) >= minimum:
                out.append(dict(start=inside[0][2]['created_utc'], accounts=sorted(accounts), uses=len(inside), link=u, sources=sorted({r[2]['source'] for r in inside})))
                i += len(inside)
            else: i += 1
    return sorted(out, key=lambda b: -len(b['accounts']))

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
def _tokens(text):
    s = re.sub(r'https?://\S+|@\S+|#\w+', ' ', text.lower()); return _WORD.findall(s)

def _shingles(tokens, n=3):
    if len(tokens) < n: return {' '.join(tokens)} if tokens else set()
    return {' '.join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}

def _distinct_samples(posts, n=3, width=140):
    """One sample per distinct wording, most common wording first, so a burst with one variant shows one line."""
    seen = collections.Counter(_norm_text(p['text']) for p in posts); out = []; done = set()
    for key, _ in seen.most_common():
        if key in done: continue
        done.add(key); out.append(next(p['text'] for p in posts if _norm_text(p['text']) == key)[:width])
        if len(out) >= n: break
    return out


def paraphrase_bursts(posts, window_min=60, minimum=3, threshold=0.35, min_tokens=8, ngram=2):
    """Same message in different words: the 2026 version of copy-paste, where a language model wrote every variant.
    Word bigram shingles, Jaccard similarity >= threshold (0.35: a light rewrite scores about 0.4, an unrelated post on the same
    topic about 0.1), clustered, then the same sliding window as the other burst rules.
    Exact duplicates fall in here too; `exact` on a burst says how many of its posts were word-for-word identical."""
    items = []
    for p in posts:
        if p['is_repost']: continue
        tok = _tokens(p['text'])
        if len(tok) >= min_tokens: items.append((p, _shingles(tok, ngram)))
    index = collections.defaultdict(list)
    for i, (p, sh) in enumerate(items):
        for s in sh: index[s].append(i)
    parent = list(range(len(items)))
    def find(a):
        while parent[a] != a: parent[a] = parent[parent[a]]; a = parent[a]
        return a
    seen = set()
    for s, ids in index.items():
        if len(ids) < 2 or len(ids) > 200: continue       # a shingle shared by hundreds of posts is the topic's vocabulary, not a copy
        for a in ids:
            for b in ids:
                if a < b and (a, b) not in seen:
                    seen.add((a, b)); sa, sb = items[a][1], items[b][1]
                    if len(sa & sb) / len(sa | sb) >= threshold: parent[find(a)] = find(b)
    clusters = collections.defaultdict(list)
    for i in range(len(items)): clusters[find(i)].append(items[i][0])
    W = timedelta(minutes=window_min); out = []
    for members in clusters.values():
        if len(members) < minimum: continue
        rows = sorted(members, key=lambda p: p['created_utc']); i = 0
        while i < len(rows):
            inside = [p for p in rows if _t(rows[i]) <= _t(p) <= _t(rows[i]) + W]; accounts = {p['author'] for p in inside}
            if len(accounts) >= minimum:
                texts = collections.Counter(_norm_text(p['text']) for p in inside)
                out.append(dict(start=inside[0]['created_utc'], end=inside[-1]['created_utc'], accounts=sorted(accounts), uses=len(inside), exact=max(texts.values()),
                                variants=len(texts), samples=_distinct_samples(inside, 3), sources=sorted({p['source'] for p in inside})))
                i += len(inside)
            else: i += 1
    return sorted(out, key=lambda b: (-len(b['accounts']), -b['uses']))

def hour_profile(posts):
    """Posts per UTC hour of day, and the tightest 8-hour band: what share of posting falls inside one working day somewhere on Earth."""
    h = [0] * 24
    for p in posts: h[int(p['created_utc'][11:13])] += 1
    n = sum(h) or 1; best = max(((sum(h[(s + k) % 24] for k in range(8)) / n, s) for s in range(24)))
    return dict(hours=h, band_share=best[0], band_start=best[1], band_end=(best[1] + 8) % 24)

def account_features(posts, now=None, windows=(), burst_accounts=(), min_posts=3, top=40):
    """One row per account with the facts a coordination analyst asks for first, and the signals those facts trip.
    Signals (each a plain rule, thresholds in the code): replies, no_audience, young, dormant_then_active, office_hours, one_domain,
    multilingual, peak_only, co_posted. More signals is a reason to look, not a conclusion.
    An X post whose text starts with @ counts as a reply even when the row predates the is_reply column (X puts the handles it
    replies to at the front of the text)."""
    now = now or datetime.now(timezone.utc); by = collections.defaultdict(list)
    for p in posts: by[p['author']].append(p)
    win = [(parse_time(w['start_utc']), parse_time(w['end_utc'])) for w in windows]
    def in_window(p): t = _t(p); return any(a <= t < b for a, b in win)
    rows = []
    for a, ps in by.items():
        if len(ps) < min_posts: continue
        n = len(ps); replies = sum(1 for p in ps if p.get('is_reply') or (p['source'] == 'x' and p['text'].lstrip().startswith('@'))); likes = [p['likes'] for p in ps if p['likes'] is not None]
        age = (now - parse_time(ps[0]['author_created_utc'])).days if ps[0]['author_created_utc'] else None
        followers = ps[0]['author_followers']; total = ps[0].get('author_posts')
        links = [l for p in ps for l in p['links']]; linked = sum(1 for p in ps if p['links']); doms = collections.Counter(domain_of(l) for l in links if domain_of(l))
        langs = collections.Counter(p['lang'] for p in ps if p['lang']); prof = hour_profile(ps)
        targets = collections.Counter(p.get('reply_to') for p in ps if p.get('reply_to'))
        sig = []
        if n >= 5 and replies / n >= 0.8: sig.append('replies')
        if n >= 5 and likes and statistics.median(likes) == 0 and (followers is not None and followers < 100): sig.append('no_audience')
        if age is not None and age < 30: sig.append('young')
        if age is not None and age > 365 and total is not None and total < 100 and n >= 5: sig.append('dormant_then_active')
        if n >= 10 and prof['band_share'] >= 0.9: sig.append('office_hours')
        if n >= 5 and linked / n >= 0.8 and doms and doms.most_common(1)[0][1] / len(links) >= 0.8: sig.append('one_domain')
        if sum(1 for l, c in langs.items() if c / n >= 0.1) >= 3: sig.append('multilingual')
        if win and all(in_window(p) for p in ps): sig.append('peak_only')
        if a in burst_accounts: sig.append('co_posted')
        rows.append(dict(account=a, source=ps[0]['source'], posts=n, reply_share=replies / n, reply_to=targets.most_common(1)[0][0] if targets else '', age_days=age, followers=followers,
                         total_posts=total, median_likes=statistics.median(likes) if likes else None, link_share=linked / n, top_domain=doms.most_common(1)[0][0] if doms else '',
                         langs=', '.join(l for l, _ in langs.most_common(3)), band=f"{prof['band_start']:02d}-{prof['band_end']:02d}", band_share=prof['band_share'], signals=sig,
                         first=min(p['created_utc'] for p in ps), last=max(p['created_utc'] for p in ps)))
    return sorted(rows, key=lambda r: (-len(r['signals']), -r['posts']))[:top]

def creation_clusters(posts, subset_accounts, min_accounts=3, ratio=3.0):
    """Weeks in which the subset's accounts were created far more often than accounts in general: a batch."""
    first = {}
    for p in posts:
        if p['author_created_utc'] and p['author'] not in first: first[p['author']] = p['author_created_utc'][:10]
    def week(d): y, w, _ = datetime.strptime(d, '%Y-%m-%d').isocalendar(); return f'{y}-W{w:02d}'
    allc = collections.Counter(week(d) for d in first.values()); subc = collections.Counter(week(first[a]) for a in subset_accounts if a in first)
    na, ns = sum(allc.values()) or 1, sum(subc.values()) or 1; out = []
    for w, c in subc.items():
        share_s, share_a = c / ns, allc[w] / na
        if c >= min_accounts and share_a and share_s / share_a >= ratio: out.append(dict(week=w, subset=c, subset_share=share_s, all=allc[w], all_share=share_a, lift=share_s / share_a))
    return sorted(out, key=lambda r: -r['subset'])

def cross_platform(posts, window_min=30):
    """The same text or the same link on two or more platforms inside the window. Almost nobody can see this because almost nobody
    collects more than one platform; seeding the same message across platforms minutes apart is a hallmark of a run operation."""
    by_text = collections.defaultdict(list); by_link = collections.defaultdict(list)
    for p in posts:
        if p['is_repost']: continue
        k = _norm_text(p['text'])
        if len(k) >= 40: by_text[k].append(p)
        for l in set(_norm_link(x) for x in p['links'] if x): by_link[l].append(p)
    W = timedelta(minutes=window_min); out = []
    for kind, groups in (('text', by_text), ('link', by_link)):
        for k, rows in groups.items():
            if len({p['source'] for p in rows}) < 2: continue
            rows.sort(key=lambda p: p['created_utc'])
            for i, p in enumerate(rows):
                near = [q for q in rows[i:] if _t(q) - _t(p) <= W]
                srcs = {q['source'] for q in near}
                if len(srcs) >= 2:
                    out.append(dict(kind=kind, key=k[:120], start=p['created_utc'], sources=sorted(srcs), accounts=sorted({q['author'] + '@' + q['source'] for q in near}), posts=len(near)))
                    break
    return sorted(out, key=lambda r: (-len(r['sources']), -r['posts']))[:50]

GENERIC_PARAM_KEYS = {'feature', 'mid', 'bt', 'sub_rt', 'via', 'ref_src', 's', 'si', 'igshid', 'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid', 'twclid', 'ttclid', 'ref_url', 'cmpid'}
GENERIC_PARAM_VALUES = {'social', 'twitter', 'x', 'mastodon', 'bluesky', 'facebook', 'linkedin', 'reddit', 'threads', 'telegram', 'whatsapp', 'web', 'mobile', 'app', 'ios',
                        'android', 'other', 'share', 'sharing', 'organic_social', 'copy_link', 'copylink', 'link', 'email', 'rss', 'feed', 'none', 'null', 'true', 'false'}
SHORTENERS = {'bit.ly', 'tinyurl.com', 'ow.ly', 'buff.ly', 'is.gd', 't.ly', 'cutt.ly', 'rebrand.ly', 'shorturl.at', 'lnkd.in', 'dlvr.it', 'ift.tt', 'goo.gl', 'trib.al', 'tiny.cc', 'shorturl.com', 'rb.gy'}

def infrastructure(posts, min_accounts=3):
    """Shared link machinery across accounts: a query-string parameter and value that several accounts carry (a tracking token),
    link shorteners (which hide the destination), and domains linked by several accounts.
    Share-button boilerplate (utm_source=twitter, utm_medium=social, feature=youtu.be) is on every link anyone shares from a site's
    own button and says nothing about the accounts, so those keys and values are dropped; a campaign token (utm_campaign=rs9,
    ref=LLJIE, a shortCode) is kept. Parameters that always travel together on the same accounts are one row, not eight."""
    from urllib.parse import urlparse, parse_qsl
    params = collections.defaultdict(set); shorteners = collections.defaultdict(set); doms = collections.defaultdict(set)
    for p in posts:
        for l in p['links']:
            try: u = urlparse(l)
            except Exception: continue
            d = (u.hostname or '').lower()
            if not d: continue
            if d in SHORTENERS: shorteners[d].add(p['author'])
            else: doms[d].add(p['author'])
            for k, v in parse_qsl(u.query, keep_blank_values=True):
                kl, vl = k.lower(), v.lower()
                if kl in GENERIC_PARAM_KEYS or vl in GENERIC_PARAM_VALUES or not v: continue
                if kl.startswith(('utm_', 'ref', 'src', 'campaign', 'mc_', 'share', 'token', 'short', 'code', 'invite', 'aff', 'partner')) or len(v) >= 4: params[f'{k}={v}'].add(p['author'])
    kept = [(k, frozenset(v)) for k, v in params.items() if len(v) >= min_accounts]
    grouped = collections.defaultdict(list)
    for k, accts in kept: grouped[accts].append(k)
    rows = sorted([(' · '.join(sorted(ks)), sorted(accts)) for accts, ks in grouped.items()], key=lambda kv: -len(kv[1]))[:20]
    return dict(params=rows,
                shorteners=sorted([(d, sorted(v)) for d, v in shorteners.items() if len(v) >= 2], key=lambda kv: -len(kv[1])),
                domains=sorted([(d, len(v)) for d, v in doms.items() if len(v) >= min_accounts], key=lambda kv: -kv[1])[:20])

def leading_edge(posts, window, minutes=10):
    """Who posted in the first minutes of a complete window, before anyone could have organically seen it. Seeders post inside
    minutes of each other with the same link; organic uptake comes later from people who saw them."""
    a, b = parse_time(window['start_utc']), parse_time(window['end_utc'])
    inside = sorted((p for p in posts if a <= _t(p) < b and window['tag'] in p['matched']), key=lambda p: p['created_utc'])
    if not inside: return None
    t0 = _t(inside[0]); edge = [p for p in inside if _t(p) - t0 <= timedelta(minutes=minutes)]
    return dict(first=inside[0]['created_utc'], posts=len(inside), accounts=len({p['author'] for p in inside}), edge_posts=len(edge), edge_accounts=sorted({p['author'] for p in edge}),
                edge_links=collections.Counter(domain_of(l) for p in edge for l in p['links'] if domain_of(l)).most_common(5), per_account=len(inside) / max(1, len({p['author'] for p in inside})))
