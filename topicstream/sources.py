"""Provider adapters normalize public records into Post.

Mastodon visibility is per server; Bluesky uses a bsky.social app-password
session and bounded search. X prices and request admission live in xsource.py.
Provider access, request shapes, and pricing must be verified operationally.
"""
import json, re, time, html as H, os, urllib.request, urllib.parse, urllib.error
from html.parser import HTMLParser
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

UA = 'topicstream/0.3 (+research monitor; standard-library urllib)'   # say who you are; do not pretend to be a browser

@dataclass
class Post:
    source: str; instance: str; post_id: str; created_utc: str; author: str; text: str
    author_id: str = None; author_created_utc: str = None; author_followers: int = None; lang: str = None
    is_repost: bool = False; reposts: int = None; likes: int = None; replies: int = None; url: str = None
    is_reply: bool = False; reply_to: str = None; author_posts: int = None   # reply_to = the account replied to, when the platform says
    author_uri: str = None; reference_type: str = None; referenced_post_id: str = None; original_author: str = None
    matched: list = field(default_factory=list); tags: list = field(default_factory=list); links: list = field(default_factory=list)
    collected_utc: str = ''
    @property
    def key(self): return f'{self.source}:{self.post_id}'

def utcnow(): return datetime.now(timezone.utc).replace(microsecond=0)
def iso(dt): return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def parse_time(s):
    s = s.strip().replace('Z', '+00:00')
    if '.' in s: s = re.sub(r'\.\d+', '', s)
    dt = datetime.fromisoformat(s)
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).astimezone(timezone.utc)

class LinkParser(HTMLParser):
    def __init__(self): super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            url = dict(attrs).get('href', '')
            if url.startswith(('https://', 'http://')): self.links.append(url)

def html_links(value):
    parser = LinkParser(); parser.feed(value or ''); return parser.links
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
    def __init__(self, pause=1.0, log=print, cancelled=None):
        self.pause = pause; self.log = log; self.last = 0; self.requests = 0
        self.cancelled=cancelled or (lambda:False)
    def _wait(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if self.cancelled(): raise RuntimeError('Collection cancelled')
            time.sleep(min(.25,max(0,end-time.monotonic())))
    def get(self, url, headers=None, tries=4):
        for attempt in range(tries):
            if self.cancelled(): raise RuntimeError('Collection cancelled')
            wait = self.pause - (time.time() - self.last)
            if wait > 0: self._wait(wait)
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json', **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    self.last = time.time(); self.requests += 1
                    return json.loads(r.read().decode('utf-8')), dict(r.headers)
            except urllib.error.HTTPError as e:
                self.last = time.time(); self.requests += 1
                if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                    delay = min(60,float(e.headers.get('Retry-After') or 2 ** (attempt + 1))); self.log(f'    {e.code} from {domain_of(url)}, waiting {delay:.0f}s'); self._wait(delay); continue
                raise
    def post_json(self, url, body, headers=None):
        if self.cancelled(): raise RuntimeError('Collection cancelled')
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST', headers={'User-Agent': UA, 'Content-Type': 'application/json', 'Accept': 'application/json', **(headers or {})})
        with urllib.request.urlopen(req, timeout=30) as r: self.requests += 1; return json.loads(r.read().decode('utf-8'))

# ----------------------------------------------------------------------------------------------------------------------
class Mastodon:
    name = 'mastodon'
    def __init__(self, instances, http, log=print, max_pages=10, on_page=None):
        self.instances = instances; self.http = http; self.log = log; self.max_pages = max_pages
        self.on_page=on_page or (lambda posts:None)

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
                    page_start=len(out)
                    pages += 1
                    for s in j:
                        created = parse_time(s['created_at'])
                        if created < since: j = None; break
                        src = s['reblog'] or s
                        original_uri = src.get('uri') or src.get('url') or s['id']
                        # A boost is a separate action by the wrapper's actor at its own time.
                        uri = (s.get('uri') or s.get('url') or f'https://{inst}/statuses/{s["id"]}') if s.get('reblog') else original_uri
                        if uri in seen: continue
                        seen.add(uri); got += 1
                        text = strip_html(src.get('content', ''))
                        a = s['account']
                        out.append(Post(source=self.name, instance=inst, post_id=uri, created_utc=iso(created), author=a['acct'], author_id=str(a['id']),
                                        author_uri=a.get('uri') or a.get('url'),
                                        reference_type='repost' if s.get('reblog') else ('reply' if src.get('in_reply_to_id') else None),
                                        referenced_post_id=original_uri if s.get('reblog') else (f'https://{inst}/statuses/{src["in_reply_to_id"]}' if src.get('in_reply_to_id') else None),
                                        original_author=src['account'].get('acct') if s.get('reblog') else None,
                                        author_created_utc=iso(parse_time(a['created_at'])) if a.get('created_at') else None, author_followers=a.get('followers_count'),
                                        author_posts=a.get('statuses_count'), is_reply=bool(src.get('in_reply_to_id')), reply_to=(src.get('mentions') or [{}])[0].get('acct') if src.get('in_reply_to_id') else None,
                                        text=text, lang=src.get('language'), is_repost=bool(s.get('reblog')), reposts=src.get('reblogs_count'), likes=src.get('favourites_count'),
                                        replies=src.get('replies_count'), url=src.get('url'), matched=matches(text + ' ' + ' '.join('#' + t['name'] for t in src.get('tags', [])), tags, terms),
                                        tags=sorted({t['name'].lower() for t in src.get('tags', [])} | set(tags_in(text))),
                                        links=sorted(set([c['url'] for c in [src.get('card')] if c and c.get('url')] + html_links(src.get('content','')) + re.findall(r'https?://\S+', text))), collected_utc=iso(now)))
                    self.on_page(out[page_start:])
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
    def __init__(self, http, log=print, max_pages=10, handle=None, app_password=None, on_page=None, until=None):
        self.http = http; self.log = log; self.max_pages = max_pages
        self.handle = handle or os.environ.get('BSKY_HANDLE'); self.pw = app_password or os.environ.get('BSKY_APP_PASSWORD'); self.jwt = None
        self.on_page=on_page or (lambda posts:None); self.until=until
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
                q = {'q': '#'+raw if kind=='tag' else raw, 'sort': 'latest', 'limit': 100, 'since': iso(since)}
                if kind=='tag': q['tag']=raw
                if self.until: q['until']=iso(self.until)
                if cursor: q['cursor'] = cursor
                j, _ = self.http.get('https://bsky.social/xrpc/app.bsky.feed.searchPosts?' + urllib.parse.urlencode(q), headers={'Authorization': 'Bearer ' + self.jwt})
                pages += 1
                page_start=len(out)
                for p in j.get('posts', []):
                    rec = p['record']; text = rec.get('text', ''); a = p['author']
                    features = [ft for f in rec.get('facets', []) for ft in f.get('features', [])]
                    facet_tags = [f['tag'] for f in features if f.get('$type','').endswith('#tag') and f.get('tag')]
                    facet_links = [f['uri'] for f in features if f.get('$type','').endswith('#link') and f.get('uri')]
                    emb = p.get('embed') or {}; ext = emb.get('external', {}).get('uri') if isinstance(emb, dict) else None
                    out.append(Post(source=self.name, instance='bsky.social', post_id=p['uri'], created_utc=iso(parse_time(rec['createdAt'])), author=a['handle'], author_id=a['did'],
                                    author_created_utc=iso(parse_time(a['createdAt'])) if a.get('createdAt') else None, text=text, lang=(rec.get('langs') or [None])[0],
                                    is_reply=bool(rec.get('reply')), author_posts=a.get('postsCount'),
                                    reference_type='reply' if rec.get('reply') else None, referenced_post_id=(rec.get('reply') or {}).get('parent',{}).get('uri'),
                                    reposts=p.get('repostCount'), likes=p.get('likeCount'), replies=p.get('replyCount'),
                                    url=f"https://bsky.app/profile/{a['handle']}/post/{p['uri'].rsplit('/', 1)[-1]}", matched=matches(text, tags, terms),
                                    tags=sorted({t.lower() for t in facet_tags} | set(tags_in(text))), links=facet_links + ([ext] if ext else []), collected_utc=iso(now)))
                    got += 1
                self.on_page(out[page_start:])
                cursor = j.get('cursor')
                if not cursor or not j.get('posts'): break
            self.log(f'  bluesky {label}: {got} posts, {pages} pages (hitsTotal {j.get("hitsTotal", "?")})')
        return out

# ----------------------------------------------------------------------------------------------------------------------
from .xsource import X

def build_sources(cfg, http, log):
    s = cfg.get('sources', {}); out = []
    if s.get('mastodon', {}).get('enabled', True): out.append(Mastodon(s.get('mastodon', {}).get('instances', ['mastodon.social']), http, log, s.get('mastodon', {}).get('max_pages', 10),on_page=cfg.get('_on_page')))
    if s.get('bluesky', {}).get('enabled', True): out.append(Bluesky(http, log, s.get('bluesky', {}).get('max_pages', 10),on_page=cfg.get('_on_page'),until=cfg.get('_until')))
    if s.get('x', {}).get('enabled', True):
        x = s.get('x', {})
        out.append(X(http, log, x.get('max_posts_per_tag', 200), x.get('budget_usd', 2.0), query_extra=x.get('query_extra', ''), archive=bool(x.get('archive', False)),
                     spent_before=x.get('_spent_before', 0.0), cursors=x.get('_cursors'), save_cursor=x.get('_save_cursor'), sample_per_day=x.get('sample_per_day', 0), sample_windows_per_day=x.get('sample_windows_per_day', 6),
                     counts_every_minutes=x.get('counts_every_minutes', 60), counts_fetched=x.get('_counts_fetched'), save_counts_fetched=x.get('_save_counts_fetched'),
                     store=x.get('_store'), prices=x.get('prices'), cancelled=cfg.get('_cancelled'), until=cfg.get('_until'), scope_key=cfg.get('_scope_key','')))
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
