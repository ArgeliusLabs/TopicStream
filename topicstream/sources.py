"""Collectors. Each one turns a platform's own JSON into the same Post shape and, where the platform offers it,
its own per-day counts (TagDay). Read these top to bottom: the comments say what each endpoint costs and what it
leaves out, which is most of what you need to know before you trust a number from any social-listening dashboard.

Platform facts as of November 2026 (check before you budget; they change):
  Mastodon   GET /api/v1/tags/{name}            free, no auth: seven days of {day, uses, accounts} as that server saw them
             GET /api/v1/timelines/tag/{name}   free, no auth on most servers (some return 401/422: they require a token)
             Each server only knows what federated to it. Poll several and de-duplicate on the post URI.
  Bluesky    app.bsky.feed.searchPosts          free, but since 2025 the public AppView refuses it without a session,
             so sign in with an app password. Search returns original posts only: reposts are not "uses" here.
  X          GET /2/tweets/counts/recent        $0.005 per request, up to 7 days, minute/hour/day buckets (the cheap half)
             GET /2/tweets/search/recent        $0.005 per post returned (the expensive half), 7 days, 100 per page
             Pay-per-use since Feb 2026; the old Free/Basic/Pro tiers are gone. 3M reads a month before Enterprise.
"""
import json, re, time, html as H, os, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

UA = 'topicstream/0.1 (+research monitor; standard-library urllib)'   # say who you are; do not pretend to be a browser

@dataclass
class Post:
    source: str; instance: str; post_id: str; created_utc: str; author: str; text: str
    author_id: str = None; author_created_utc: str = None; author_followers: int = None; lang: str = None
    is_repost: bool = False; reposts: int = None; likes: int = None; replies: int = None; url: str = None
    matched: list = field(default_factory=list); tags: list = field(default_factory=list); links: list = field(default_factory=list)
    collected_utc: str = ''
    @property
    def key(self): return f'{self.source}:{self.post_id}'

def utcnow(): return datetime.now(timezone.utc).replace(microsecond=0)
def iso(dt): return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def parse_time(s):
    s = s.replace('Z', '+00:00')
    if '.' in s: s = re.sub(r'\.\d+', '', s)
    return datetime.fromisoformat(s).astimezone(timezone.utc)
def strip_html(s):
    s = re.sub(r'<br\s*/?>|</p>', '\n', s); s = re.sub(r'<[^>]+>', '', s); return H.unescape(s).strip()
def domain_of(url):
    try: return urllib.parse.urlparse(url).hostname or ''
    except Exception: return ''
def tags_in(text): return [t.lower() for t in re.findall(r'#(\w+)', text)]
def matches(text, tags, terms):
    """Which tracked tags/terms this post matches. Tags match as hashtags; terms match as case-insensitive substrings."""
    low = text.lower(); present = set(tags_in(text))
    return sorted({'#' + t.lower() for t in tags if t.lower() in present} | {t.lower() for t in terms if t.lower() in low})

def queries(tags, terms):
    """What to search for, with the label each hit is filed under: a hashtag as '#name', a phrase as the phrase itself (lower-case)."""
    return [('#' + t.lower(), 'tag', t) for t in tags] + [(t.lower(), 'term', t) for t in terms]

class Http:
    """Polite urllib wrapper: one request at a time, a pause between them, retries on 429/5xx with the server's Retry-After."""
    def __init__(self, pause=1.0, log=print): self.pause = pause; self.log = log; self.last = 0; self.requests = 0
    def get(self, url, headers=None, tries=4):
        for attempt in range(tries):
            wait = self.pause - (time.time() - self.last)
            if wait > 0: time.sleep(wait)
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json', **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    self.last = time.time(); self.requests += 1
                    return json.loads(r.read().decode('utf-8')), dict(r.headers)
            except urllib.error.HTTPError as e:
                self.last = time.time(); self.requests += 1
                if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                    delay = float(e.headers.get('Retry-After') or 2 ** (attempt + 1)); self.log(f'    {e.code} from {domain_of(url)}, waiting {delay:.0f}s'); time.sleep(delay); continue
                raise
    def post_json(self, url, body, headers=None):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST', headers={'User-Agent': UA, 'Content-Type': 'application/json', 'Accept': 'application/json', **(headers or {})})
        with urllib.request.urlopen(req, timeout=30) as r: self.requests += 1; return json.loads(r.read().decode('utf-8'))

# ----------------------------------------------------------------------------------------------------------------------
class Mastodon:
    name = 'mastodon'
    def __init__(self, instances, http, log=print, max_pages=10):
        self.instances = instances; self.http = http; self.log = log; self.max_pages = max_pages

    def tag_days(self, tags, now):
        """The platform's own numbers: seven days of uses and originating accounts per tag, per server."""
        rows = []
        for inst in self.instances:
            for tag in tags:
                try: j, _ = self.http.get(f'https://{inst}/api/v1/tags/{urllib.parse.quote(tag)}')
                except urllib.error.HTTPError as e: self.log(f'  {inst} tags/{tag}: HTTP {e.code}'); continue
                for h in j.get('history', []):
                    day = datetime.fromtimestamp(int(h['day']), timezone.utc).strftime('%Y-%m-%d')
                    rows.append((self.name, inst, '#' + tag.lower(), day, int(h['uses']), int(h['accounts']), iso(now)))
        return rows

    def posts(self, tags, terms, since, now):
        """Walk each server's public tag timeline back to `since`. 40 posts a page; the server decides what it has.
        Phrases (terms) cannot be searched here: Mastodon full-text search needs a user token and only covers what that server indexed."""
        out = []; seen = set()
        if terms: self.log(f'  mastodon: terms {terms} are matched inside collected posts only; hashtag timelines are the only public search')
        for inst in self.instances:
            for tag in tags:
                max_id = None; pages = 0; got = 0
                while pages < self.max_pages:
                    q = {'limit': 40}
                    if max_id: q['max_id'] = max_id
                    url = f'https://{inst}/api/v1/timelines/tag/{urllib.parse.quote(tag)}?' + urllib.parse.urlencode(q)
                    try: j, _ = self.http.get(url)
                    except urllib.error.HTTPError as e:
                        self.log(f'  {inst} timelines/tag/{tag}: HTTP {e.code}' + (' (this server wants a token for public timelines)' if e.code in (401, 422) else '')); break
                    if not j: break
                    pages += 1
                    for s in j:
                        created = parse_time(s['created_at'])
                        if created < since: j = None; break
                        src = s['reblog'] or s
                        uri = src.get('uri') or src.get('url') or s['id']
                        if uri in seen: continue
                        seen.add(uri); got += 1
                        text = strip_html(src.get('content', ''))
                        a = src['account']
                        out.append(Post(source=self.name, instance=inst, post_id=uri, created_utc=iso(created), author=a['acct'], author_id=str(a['id']),
                                        author_created_utc=iso(parse_time(a['created_at'])) if a.get('created_at') else None, author_followers=a.get('followers_count'),
                                        text=text, lang=src.get('language'), is_repost=bool(s.get('reblog')), reposts=src.get('reblogs_count'), likes=src.get('favourites_count'),
                                        replies=src.get('replies_count'), url=src.get('url'), matched=matches(text + ' ' + ' '.join('#' + t['name'] for t in src.get('tags', [])), tags, terms),
                                        tags=sorted({t['name'].lower() for t in src.get('tags', [])} | set(tags_in(text))),
                                        links=[c['url'] for c in [src.get('card')] if c and c.get('url')] + re.findall(r'https?://\S+', text), collected_utc=iso(now)))
                    if j is None: break
                    max_id = j[-1]['id']
                self.log(f'  {inst} #{tag}: {got} posts, {pages} pages')
        return out

# ----------------------------------------------------------------------------------------------------------------------
class Bluesky:
    """Needs BSKY_HANDLE and BSKY_APP_PASSWORD in the environment (Settings > Privacy and security > App passwords).
    Free. Search returns original posts; a repost is a separate record the search does not return, so 'uses' here
    undercounts relative to Mastodon and X. The report says so."""
    name = 'bluesky'
    def __init__(self, http, log=print, max_pages=10, handle=None, app_password=None):
        self.http = http; self.log = log; self.max_pages = max_pages
        self.handle = handle or os.environ.get('BSKY_HANDLE'); self.pw = app_password or os.environ.get('BSKY_APP_PASSWORD'); self.jwt = None
    def available(self): return bool(self.handle and self.pw)
    def login(self):
        j = self.http.post_json('https://bsky.social/xrpc/com.atproto.server.createSession', {'identifier': self.handle, 'password': self.pw})
        self.jwt = j['accessJwt']; self.log(f'  bluesky: signed in as {j.get("handle")}')
    def tag_days(self, tags, now): return []     # Bluesky has no per-tag daily counts endpoint; the report derives them from posts
    def posts(self, tags, terms, since, now):
        if not self.available(): self.log('  bluesky: skipped (set BSKY_HANDLE and BSKY_APP_PASSWORD)'); return []
        if not self.jwt: self.login()
        out = []
        for label, kind, raw in queries(tags, terms):
            cursor = None; pages = 0; got = 0; tag = raw
            while pages < self.max_pages:
                q = {('tag' if kind == 'tag' else 'q'): raw, 'sort': 'latest', 'limit': 100, 'since': iso(since)}
                if cursor: q['cursor'] = cursor
                j, _ = self.http.get('https://bsky.social/xrpc/app.bsky.feed.searchPosts?' + urllib.parse.urlencode(q), headers={'Authorization': 'Bearer ' + self.jwt})
                pages += 1
                for p in j.get('posts', []):
                    rec = p['record']; text = rec.get('text', ''); a = p['author']
                    facet_tags = [f['features'][0]['tag'] for f in rec.get('facets', []) for _ in [0] if f['features'][0]['$type'].endswith('#tag')]
                    facet_links = [f['features'][0]['uri'] for f in rec.get('facets', []) if f['features'][0]['$type'].endswith('#link')]
                    emb = p.get('embed') or {}; ext = emb.get('external', {}).get('uri') if isinstance(emb, dict) else None
                    out.append(Post(source=self.name, instance='bsky.social', post_id=p['uri'], created_utc=iso(parse_time(rec['createdAt'])), author=a['handle'], author_id=a['did'],
                                    author_created_utc=iso(parse_time(a['createdAt'])) if a.get('createdAt') else None, text=text, lang=(rec.get('langs') or [None])[0],
                                    reposts=p.get('repostCount'), likes=p.get('likeCount'), replies=p.get('replyCount'),
                                    url=f"https://bsky.app/profile/{a['handle']}/post/{p['uri'].rsplit('/', 1)[-1]}", matched=matches(text, tags, terms),
                                    tags=sorted({t.lower() for t in facet_tags} | set(tags_in(text))), links=facet_links + ([ext] if ext else []), collected_utc=iso(now)))
                    got += 1
                cursor = j.get('cursor')
                if not cursor or not j.get('posts'): break
            self.log(f'  bluesky {label}: {got} posts, {pages} pages (hitsTotal {j.get("hitsTotal", "?")})')
        return out

# ----------------------------------------------------------------------------------------------------------------------
class X:
    """Needs X_BEARER_TOKEN (an app's OAuth 2.0 app-only bearer token from the developer console).
    Pay-per-use since February 2026: $0.005 per post returned, $0.005 per counts/recent request, $0.010 per counts/all request.
    What keeps the bill honest here:
      - counts first: one request per tag per granularity gives the whole 7-day volume series, for half a cent;
      - incremental reads: after the first run, search uses since_id so only posts newer than the last one stored are billed;
      - caps: max_posts_per_tag per run, and budget_usd across ALL runs stored in the database, not just this one;
      - query_extra: e.g. "-is:retweet lang:en" roughly halves what comes back on a busy tag.
    With `archive: true` and `days` > 7 it uses the full-archive endpoints (search/all, counts/all), which pay-per-use can call."""
    name = 'x'
    COUNT_RECENT, COUNT_ALL, POST_READ = 0.005, 0.010, 0.005
    FIELDS = 'created_at,entities,public_metrics,referenced_tweets,lang,author_id'
    def __init__(self, http, log=print, max_posts_per_tag=200, budget_usd=2.0, bearer=None, query_extra='', archive=False, spent_before=0.0, cursors=None, save_cursor=None, sample_per_day=0, sample_windows_per_day=6, counts_every_minutes=60, counts_fetched=None, save_counts_fetched=None):
        self.http = http; self.log = log; self.max_posts = max_posts_per_tag; self.budget = budget_usd
        self.bearer = bearer or os.environ.get('X_BEARER_TOKEN'); self.spent = 0.0; self.spent_before = spent_before
        self.query_extra = query_extra.strip(); self.archive = archive; self.cursors = cursors or {}; self.save_cursor = save_cursor or (lambda tag, newest: None)
        self.hourly = []; self.fields_param = 'tweet.fields'; self.sample_per_day = int(sample_per_day or 0); self.sample_windows = max(1, int(sample_windows_per_day or 1))
        self.counts_every = int(counts_every_minutes or 0); self.counts_fetched = counts_fetched or {}; self.save_counts_fetched = save_counts_fetched or (lambda label, when: None)
    def available(self): return bool(self.bearer)
    def _h(self): return {'Authorization': 'Bearer ' + self.bearer}
    def query(self, raw, kind='tag'):
        """The X search query for one tracked thing: a hashtag as #name, a phrase quoted so word order counts, plus query_extra."""
        core = f'#{raw}' if kind == 'tag' else f'"{raw}"'
        return (core + ' ' + self.query_extra).strip()
    def _ep(self, kind):
        base = 'https://api.x.com/2/tweets/'
        return base + ('search/all' if self.archive else 'search/recent') if kind == 'search' else base + ('counts/all' if self.archive else 'counts/recent')
    def count_price(self): return self.COUNT_ALL if self.archive else self.COUNT_RECENT
    def estimate(self, tags, terms=(), days=7):
        """Worst case for one run: counts requests per query (day and hour; the hour series paginates on long windows), then reads
        up to max_posts per query, or sample_per_day x days when sampling, whichever is smaller."""
        reads = min(self.max_posts, max(10, self.sample_per_day // self.sample_windows) * self.sample_windows * (days + 1)) if self.sample_per_day else self.max_posts
        count_pages = 1 + (1 + days * 24 // 500)
        return (len(tags) + len(terms)) * (count_pages * self.count_price() + reads * self.POST_READ)
    def _get(self, url, q):
        try: return self.http.get(url + '?' + urllib.parse.urlencode(q), headers=self._h())
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')[:300]
            if e.code == 400 and self.fields_param == 'tweet.fields' and 'fields' in body:   # the docs now call it post.fields; accept either
                self.fields_param = 'post.fields'; q['post.fields'] = q.pop('tweet.fields', self.FIELDS); return self._get(url, q)
            raise RuntimeError(f'x {e.code}: {body}') from None
    def _counts(self, raw, granularity, since, kind='tag'):
        """All buckets for the query at this granularity; follows next_token (each page is one billed request)."""
        rows = []; token = None
        while True:
            q = {'query': self.query(raw, kind), 'granularity': granularity}
            if self.archive: q['start_time'] = iso(since)
            if token: q['next_token'] = token
            j, _ = self._get(self._ep('counts'), q); self.spent += self.count_price()
            for b in j.get('data', []): rows.append((b['start'], b['end'], int(b.get('post_count', b.get('tweet_count', 0)))))
            token = j.get('meta', {}).get('next_token')
            if not token: break
        return rows
    def tag_days(self, tags, now, since=None, terms=()):
        """Buys the day and hour series for every query, unless a series younger than counts_every_minutes is already stored
        (watch mode would otherwise re-buy the same curve every cycle: a cent a term a run adds up to a dollar a term a day at 15 minutes)."""
        if not self.available(): return []
        since = since or (now - timedelta(days=7)); rows = []
        for label, kind, raw in queries(tags, terms):
            last = self.counts_fetched.get(label)
            if last and (now - parse_time(last)).total_seconds() < self.counts_every * 60:
                self.log(f'  x {self.query(raw, kind)}: counts bought {int((now - parse_time(last)).total_seconds() // 60)} min ago, kept (counts_every_minutes {self.counts_every})'); continue
            for start, end, n in self._counts(raw, 'day', since, kind): rows.append((self.name, 'api.x.com', label, start[:10], n, None, iso(now)))   # counts give no account number
            for start, end, n in self._counts(raw, 'hour', since, kind): self.hourly.append((label, start, n))
            total = sum(n for t, _, n in self.hourly if t == label); self.save_counts_fetched(label, iso(now))
            self.log(f'  x {self.query(raw, kind)}: {total:,} posts in the window by the counts endpoint (${self.spent:.3f} so far)')
        return rows
    def posts(self, tags, terms, since, now):
        if not self.available(): self.log('  x: skipped (set X_BEARER_TOKEN in the environment or in .env)'); return []
        est = self.estimate(tags, terms, max(1, (now - since).days))
        if self.spent_before + est > self.budget:
            raise SystemExit(f'x: skipped. ${self.spent_before:.2f} already spent in this database and this run could add up to ${est:.2f}; budget_usd is {self.budget:.2f}. Raise budget_usd or lower max_posts_per_tag.')
        out = []
        if self.sample_per_day: return self._sample(tags, terms, since, now)
        for label, kind, raw in queries(tags, terms):
            tag = label; got = 0; token = None; newest = self.cursors.get(tag); mode = f'since_id {newest}' if newest else f'start_time {iso(since)}'
            while got < self.max_posts:
                q = {'query': self.query(raw, kind), 'max_results': max(10, min(100 if not self.archive else 500, self.max_posts - got)),
                     self.fields_param: self.FIELDS, 'expansions': 'author_id', 'user.fields': 'created_at,public_metrics,username'}
                if newest: q['since_id'] = newest            # since_id and start_time are mutually exclusive
                else: q['start_time'] = iso(since)
                if token: q['next_token'] = token
                j, _ = self._get(self._ep('search'), q)
                data = j.get('data', []); self.spent += len(data) * self.POST_READ
                out.extend(self._parse(j, tags, terms, now)); got += len(data)
                meta = j.get('meta', {})
                if meta.get('newest_id') and (not self.cursors.get(tag) or int(meta['newest_id']) > int(self.cursors[tag])): self.cursors[tag] = meta['newest_id']
                token = meta.get('next_token')
                if not token or not data: break
            if self.cursors.get(tag): self.save_cursor(tag, self.cursors[tag])
            self.log(f'  x {self.query(raw, kind)}: {got} posts read ({mode}), ${self.spent:.2f} this run, ${self.spent_before + self.spent:.2f} in this database')
        return out
    def _parse(self, j, tags, terms, now):
        users = {u['id']: u for u in j.get('includes', {}).get('users', [])}; out = []
        for t in j.get('data', []):
            u = users.get(t['author_id'], {}); ent = t.get('entities', {}); pm = t.get('public_metrics', {})
            is_rt = any(r.get('type') == 'retweeted' for r in t.get('referenced_tweets', []))
            links = [x.get('unwound_url') or x.get('expanded_url') for x in ent.get('urls', []) if not re.match(r'https://(twitter|x)\.com/', x.get('expanded_url') or '')]
            out.append(Post(source=self.name, instance='api.x.com', post_id=t['id'], created_utc=iso(parse_time(t['created_at'])), author=u.get('username', t['author_id']), author_id=t['author_id'],
                            author_created_utc=iso(parse_time(u['created_at'])) if u.get('created_at') else None, author_followers=(u.get('public_metrics') or {}).get('followers_count'),
                            text=t['text'], lang=t.get('lang'), is_repost=is_rt, reposts=pm.get('retweet_count'), likes=pm.get('like_count'), replies=pm.get('reply_count'),
                            url=f"https://x.com/{u.get('username', 'i')}/status/{t['id']}", matched=matches(t['text'], tags, terms),
                            tags=sorted({h['tag'].lower() for h in ent.get('hashtags', [])} | set(tags_in(t['text']))), links=[l for l in links if l], collected_utc=iso(now)))
        return out
    def _sample(self, tags, terms, since, now):
        """Stratified sample: each UTC day is split into sample_windows_per_day equal windows (six by default, four hours each) and
        the newest posts in each window are read, sample_per_day / windows of them (never fewer than 10, the API minimum), so a
        three-week event is covered end to end and across the clock instead of the last two days swallowing the cap. Ignores since_id.
        Timing analysis on a sample is still approximate; the counts endpoint is the complete record and the report uses it for X velocity."""
        out = []; day = timedelta(days=1); per_window = max(10, self.sample_per_day // self.sample_windows); step = day / self.sample_windows
        for label, kind, raw in queries(tags, terms):
            got = 0; start = since.replace(hour=0, minute=0, second=0, microsecond=0)
            while start < now and got < self.max_posts:
                end = min(start + step, now - timedelta(seconds=15))
                if end > start:
                    want = min(per_window, self.max_posts - got); token = None; w_got = 0
                    while w_got < want:
                        q = {'query': self.query(raw, kind), 'max_results': max(10, min(100 if not self.archive else 500, want - w_got)), 'start_time': iso(start), 'end_time': iso(end),
                             self.fields_param: self.FIELDS, 'expansions': 'author_id', 'user.fields': 'created_at,public_metrics,username'}
                        if token: q['next_token'] = token
                        j, _ = self._get(self._ep('search'), q); data = j.get('data', []); self.spent += len(data) * self.POST_READ
                        out.extend(self._parse(j, tags, terms, now)); w_got += len(data); token = j.get('meta', {}).get('next_token')
                        if not token or not data: break
                    got += w_got
                start += step
            self.log(f'  x {self.query(raw, kind)}: {got} posts sampled, {per_window} per {24 // self.sample_windows}-hour window, ${self.spent:.2f} this run, ${self.spent_before + self.spent:.2f} in this database')
        return out
    def usage(self):
        """GET /2/usage/tweets: what X says the project has consumed this billing cycle (project-level, not per run)."""
        j, _ = self._get('https://api.x.com/2/usage/tweets', {}); return j

def build_sources(cfg, http, log):
    s = cfg.get('sources', {}); out = []
    if s.get('mastodon', {}).get('enabled', True): out.append(Mastodon(s.get('mastodon', {}).get('instances', ['mastodon.social']), http, log, s.get('mastodon', {}).get('max_pages', 10)))
    if s.get('bluesky', {}).get('enabled', True): out.append(Bluesky(http, log, s.get('bluesky', {}).get('max_pages', 10)))
    if s.get('x', {}).get('enabled', True):
        x = s.get('x', {})
        out.append(X(http, log, x.get('max_posts_per_tag', 200), x.get('budget_usd', 2.0), query_extra=x.get('query_extra', ''), archive=bool(x.get('archive', False)),
                     spent_before=x.get('_spent_before', 0.0), cursors=x.get('_cursors'), save_cursor=x.get('_save_cursor'), sample_per_day=x.get('sample_per_day', 0), sample_windows_per_day=x.get('sample_windows_per_day', 6),
                     counts_every_minutes=x.get('counts_every_minutes', 60), counts_fetched=x.get('_counts_fetched'), save_counts_fetched=x.get('_save_counts_fetched')))
    return out

def load_dotenv(paths):
    """KEY=VALUE lines from the first .env found; never overrides a variable already in the environment; no quoting rules beyond stripping matching quotes."""
    for p in paths:
        p = Path(p)
        if p.is_file():
            for line in p.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line: continue
                k, v = line.split('=', 1); k = k.strip(); v = v.strip().strip('"').strip("'")
                if k and k not in os.environ: os.environ[k] = v
            return str(p)
    return None
