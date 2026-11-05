"""X collection with request reservations and transactional, resumable pages.

Prices are configurable estimates, not a claim about a provider invoice.
All retrievable results means exhausted pagination for one query and interval.
"""
import os
import math
import re
import urllib.error
import urllib.parse
from datetime import timedelta
from decimal import Decimal
from .sources import Http, Post, iso, utcnow, parse_time, queries, matches, tags_in
from .identity import digest
from .store import BudgetExceeded


class CollectionCancelled(RuntimeError):
    pass


def credit_delta(before, after):
    """Positive means balance decreased. Prefer unclipped prepaid + free funds."""
    def valid(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if not isinstance(before, dict) or not isinstance(after, dict): return None
    keys = ('prepaid_balance', 'free_balance')
    if all(valid(b.get(k)) for b in (before,after) for k in keys):
        return float(sum(Decimal(str(before[k])) - Decimal(str(after[k])) for k in keys))
    # A clipped zero total cannot reveal a negative prepaid balance.
    if all(valid(b.get('total_balance')) and b['total_balance'] > 0 for b in (before,after)):
        return float(Decimal(str(before['total_balance'])) - Decimal(str(after['total_balance'])))
    return None


class X:
    name = 'x'
    COUNT_RECENT, COUNT_ALL, POST_READ, USER_READ = 0.005, 0.010, 0.005, 0.010
    FIELDS = 'created_at,entities,note_tweet,public_metrics,referenced_tweets,lang,author_id,in_reply_to_user_id'

    def __init__(self, http, log=print, max_posts_per_tag=200, budget_usd=2.0, bearer=None,
                 query_extra='', archive=False, spent_before=0.0, cursors=None, save_cursor=None,
                 sample_per_day=0, sample_windows_per_day=6, counts_every_minutes=60,
                 counts_fetched=None, save_counts_fetched=None, store=None, prices=None,
                 cancelled=None, until=None, scope_key=''):
        self.http, self.log, self.store = http, log, store
        self.max_posts, self.budget = int(max_posts_per_tag), float(budget_usd)
        self.bearer = bearer or os.environ.get('X_BEARER_TOKEN')
        self.query_extra, self.archive = query_extra.strip(), bool(archive)
        self.spent, self.spent_before = 0.0, spent_before
        self.cursors, self.save_cursor = dict(cursors or {}), save_cursor or (lambda *args: None)
        self.hourly, self.fields_param = [], 'tweet.fields'
        self.sample_per_day, self.sample_windows = int(sample_per_day or 0), max(1, int(sample_windows_per_day or 6))
        self.counts_every, self.counts_fetched = int(counts_every_minutes), dict(counts_fetched or {})
        self.save_counts_fetched = save_counts_fetched or (lambda *args: None)
        self.prices = {'post_read': self.POST_READ, 'user_read': self.USER_READ, 'counts_recent': self.COUNT_RECENT, 'counts_all': self.COUNT_ALL, 'bill_author_expansions': False}
        self.prices.update(prices or {})
        if not isinstance(self.prices['bill_author_expansions'], bool):
            raise ValueError('bill_author_expansions must be true or false')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for k,v in self.prices.items() if k != 'bill_author_expansions'):
            raise ValueError('X prices must be nonnegative numbers')
        if not math.isfinite(self.budget) or self.budget<0 or self.max_posts<1: raise ValueError('Invalid budget or post cap')
        self.cancelled = cancelled or (lambda: False)
        self.until = until
        self.scope_key = scope_key
        self.states, self.last_window, self.coverage_rows = {}, {}, []
        self._seen_resources = set()
        self._credential_scope = digest({'credential': self.bearer})

    def available(self): return bool(self.bearer)
    def _h(self): return {'Authorization': 'Bearer ' + self.bearer}
    def query(self, raw, kind='tag'):
        if '\n' in raw or '\r' in raw or (kind == 'term' and '"' in raw):
            raise ValueError('Search terms cannot contain quotes or newlines')
        core = '#' + raw if kind == 'tag' else '"' + raw + '"'
        return (core + ' ' + self.query_extra).strip()

    def query_hash(self, raw, kind='tag'):
        return digest({'query': self.query(raw, kind), 'archive': self.archive})

    def _ep(self, kind):
        return 'https://api.x.com/2/tweets/' + (('search/all' if self.archive else 'search/recent') if kind == 'search' else ('counts/all' if self.archive else 'counts/recent'))

    def count_price(self): return self.prices['counts_all' if self.archive else 'counts_recent']

    def search_unit_price(self):
        # Our only expansion is author_id: at most one user resource per post.
        return self.prices['post_read'] + (self.prices['user_read'] if self.prices['bill_author_expansions'] else 0)

    def resource_cost(self, posts, users=0):
        # Decimal multiplication avoids a binary-float tail becoming an extra
        # micro-dollar when Store conservatively rounds a reservation upward.
        return float(posts * Decimal(str(self.prices['post_read']))
                     + users * Decimal(str(self.prices['user_read'] if self.prices['bill_author_expansions'] else 0)))

    def capture_credit(self, run_id, phase):
        """Best-effort account observation, never an authoritative run charge."""
        if not self.available(): return None
        try:
            data = self.credits().get('data', {})
            balance = {k: data[k] for k in ('prepaid_balance','free_balance','total_balance') if k in data}
            if self.store: self.store.record_credit(run_id, phase, iso(utcnow()), balance)
            return balance
        except Exception as exc:
            self.log('  Credit observation unavailable: ' + type(exc).__name__)
            return None

    def finish_credit(self, run_id, before):
        after = self.capture_credit(run_id, 'after')
        delta = credit_delta(before, after)
        self.log(f'  Local run estimate: ${self.spent:.4f}; observed account balance decrease: ' +
                 ('unavailable' if delta is None else f'${delta:.4f}') +
                 '. Account-wide movement, not a reconciled run charge; delayed charges, other activity, grants or top-ups may affect it.')
        return delta

    def estimate(self, tags, terms=(), days=7):
        reads = max(10, self.max_posts)
        if self.sample_per_day:
            reads = min(reads, max(10, self.sample_per_day // self.sample_windows) * self.sample_windows * (days + 1))
        return (len(tags) + len(terms)) * ((2 + days * 24 // 500) * self.count_price() + reads * self.search_unit_price())

    def _get(self, url, q):
        if self.cancelled(): raise CollectionCancelled('Collection cancelled; completed pages are saved')
        counted = '/counts/' in url
        paid = counted or '/search/' in url
        expansions = set(q.get('expansions', '').split(',')) - {''}
        if paid and not counted and expansions - {'author_id'}:
            raise ValueError('Unpriced search expansion; only author_id is supported')
        limit = int(q.get('max_results', 0))
        price = self.count_price() if counted else self.resource_cost(limit, limit if 'author_id' in expansions else 0)
        reservation = None
        started = utcnow()
        if paid:
            if self.store:
                reservation = self.store.reserve_request('x', url, digest(q), price, self.budget, iso(started))
            elif self.spent_before + self.spent + price > self.budget + 1e-9:
                raise BudgetExceeded(f'x: budget_usd {self.budget:.2f} cannot cover the next request')
        try:
            full = url + '?' + urllib.parse.urlencode(q)
            # Retry at the job level. Hidden HTTP retries could issue unreserved paid requests.
            result = self.http.get(full, headers=self._h(), tries=1) if isinstance(self.http, Http) else self.http.get(full, headers=self._h())
        except BaseException as exc:
            if paid:
                self.spent += price
                if reservation: self.store.uncertain_request(reservation, type(exc).__name__, iso(utcnow()))
            if isinstance(exc,urllib.error.HTTPError) and exc.code==400 and 'tweet.fields' in q:
                body=exc.read().decode('utf-8','replace')[:1000]
                if 'fields' in body:
                    self.fields_param='post.fields'
                    retry=dict(q); retry['post.fields']=retry.pop('tweet.fields').replace('referenced_tweets','referenced_posts').replace('note_tweet','note_post')
                    # Compatibility retry is a separate, fully reserved request.
                    return self._get(url,retry)
            raise
        actual = 0; finished = utcnow()
        if paid:
            if counted:
                actual = self.count_price()
                if reservation: self.store.settle_request(reservation, actual, iso(finished))
            else:
                day = iso(started)[:10] if started.date() == finished.date() else None
                resources = [('post', p.get('id'), self.prices['post_read']) for p in result[0].get('data', [])]
                if self.prices['bill_author_expansions']:
                    resources += [('user', u.get('id'), self.prices['user_read']) for u in result[0].get('includes', {}).get('users', [])]
                if reservation:
                    actual = self.store.settle_resources(reservation, self._credential_scope, day, resources, iso(finished))
                else:
                    amount = Decimal(0)
                    for kind, resource_id, rate in resources:
                        key = (day, kind, resource_id)
                        if not day or not resource_id or key not in self._seen_resources: amount += Decimal(str(rate))
                        if day and resource_id: self._seen_resources.add(key)
                    actual = float(amount)
        self.spent += actual
        return result

    def _counts(self, raw, granularity, since, kind='tag'):
        rows, token, seen = [], None, set()
        while True:
            q = {'query': self.query(raw, kind), 'granularity': granularity, 'start_time': iso(since)}
            if self.until: q['end_time'] = iso(self.until)
            if token: q['next_token'] = token
            data, _ = self._get(self._ep('counts'), q)
            if data.get('errors'): raise RuntimeError('Counts API reported errors; query remains incomplete')
            rows.extend((b['start'], b['end'], int(b.get('post_count', b.get('tweet_count', 0)))) for b in data.get('data', []))
            token = data.get('meta', {}).get('next_token')
            if not token: return rows
            if token in seen: raise RuntimeError('Counts API repeated a continuation token')
            seen.add(token)

    def tag_days(self, tags, now, since=None, terms=()):
        if not self.available(): return []
        since = since or now - timedelta(days=7)
        rows = []
        for label, kind, raw in queries(tags, terms):
            fingerprint = self.query_hash(raw, kind)
            last = self.store.checkpoint('x-counts', fingerprint).get('fetched') if self.store else self.counts_fetched.get(label)
            if last and (now - parse_time(last)).total_seconds() < self.counts_every * 60: continue
            day = self._counts(raw, 'day', since, kind)
            hour = self._counts(raw, 'hour', since, kind)
            current = [('x','api.x.com',label,start[:10],n,None,iso(now)) for start, end, n in day]
            hours = [(label,iso(parse_time(start)),n) for start, end, n in hour]
            rows.extend(current); self.hourly.extend(hours)
            if self.store:
                self.store.add_tag_days(current)
                bounded_hours=[(label,iso(parse_time(a)),n,iso(parse_time(b))) for a,b,n in hour]
                self.store.add_counts('x', bounded_hours, iso(now), fingerprint)
                self.store.save_page('x-counts',fingerprint,{'fetched':iso(now)},[])
            else: self.save_counts_fetched(label,iso(now))
            self.log(f'  x {label}: {sum(n for _,_,n in hours):,} API-reported matches; counts refreshed')
        return rows

    def _state(self, key):
        return self.store.checkpoint('x-search', key) if self.store else dict(self.states.get(key, {}))

    def _persist(self, key, state, posts):
        if self.store: self.store.save_page('x-search',key,state,posts)
        self.states[key] = dict(state)

    def _coverage(self, key, label, state, now, sampling='bounded search'):
        status = state['status']
        reason = state.get('stop_reason','pagination exhausted' if status == 'exhausted' else 'post cap reached')
        args = ('x',state.get('query_hash',key),label,state['start'],state['end'],status,reason,state.get('got',0),sampling,iso(now))
        self.coverage_rows.append(args)
        if self.store: self.store.record_coverage(*args)

    def _page_window(self, raw, kind, start, end, tags, terms, now, cap, key, label, incremental=False):
        if cap<1: raise ValueError('Window cap must be positive')
        state = self._state(key)
        if not state or (state.get('status') == 'exhausted' and incremental):
            state = {'start':iso(start),'end':iso(end),'next_token':None,'newest':None,'got':0,'status':'pending','query_hash':self.query_hash(raw,kind)}
        if state.get('status') == 'exhausted':
            self.last_window = state
            return []
        out = []
        try:
            while len(out) < cap:
                # API minimum is ten. Budget reserves all ten even if the soft cap is lower.
                limit = max(10,min(500 if self.archive else 100,cap-len(out)))
                q = {'query':self.query(raw,kind),'max_results':limit,'start_time':state['start'],'end_time':state['end'],
                     self.fields_param:self.FIELDS.replace('referenced_tweets','referenced_posts').replace('note_tweet','note_post') if self.fields_param=='post.fields' else self.FIELDS,'expansions':'author_id','user.fields':'created_at,public_metrics,username'}
                if state.get('next_token'): q['next_token'] = state['next_token']
                j,_ = self._get(self._ep('search'),q)
                if j.get('errors'): raise RuntimeError('Search API reported partial errors; interval remains incomplete')
                page = self._parse(j,tags,terms,now)
                meta = j.get('meta',{})
                token = meta.get('next_token')
                if token and token == state.get('next_token'):
                    raise RuntimeError('API repeated its continuation token; window remains partial')
                candidate=dict(state)
                newest = meta.get('newest_id')
                if newest and (not candidate.get('newest') or int(newest)>int(candidate['newest'])): candidate['newest']=newest
                candidate.update(next_token=token,got=state.get('got',0)+len(page),status='partial' if token else 'exhausted',
                             stop_reason='post cap reached' if token else 'pagination exhausted')
                self._persist(key,candidate,page)
                state=candidate
                out.extend(page)
                if not token: break
                if not page: raise RuntimeError('API returned an empty page with a continuation token')
        except BaseException as exc:
            state.update(status='partial',stop_reason=type(exc).__name__)
            self._persist(key,state,[])
            self._coverage(key,label,state,now)
            self.last_window=dict(state)
            raise
        self._coverage(key,label,state,now)
        self.last_window=dict(state)
        return out

    def posts(self,tags,terms,since,now):
        if not self.available(): self.log('  x: skipped (X_BEARER_TOKEN missing)'); return []
        if self.sample_per_day: return self._sample(tags,terms,since,now)
        out=[]
        for label,kind,raw in queries(tags,terms):
            key=digest([self.query_hash(raw,kind),self.scope_key])
            state=self._state(key)
            end=min(self.until or now-timedelta(seconds=15),now-timedelta(seconds=15))
            # Advance by a fully exhausted time interval, never by a newest ID from a capped page.
            start=parse_time(state['end']) if state.get('status')=='exhausted' else since
            if start>=end: continue
            page=self._page_window(raw,kind,start,end,tags,terms,now,self.max_posts,key,label,incremental=True)
            out.extend(page)
            state=self.last_window
            if state['status']=='exhausted' and state.get('newest'):
                self.cursors[label]=state['newest']
                # Legacy callback is diagnostic only; durable progress lives beside posts.
                self.save_cursor(label,state['newest'])
            self.log(f'  x {label}: {len(page)} read; {state["status"]}; ${self.spent:.4f} this run')
        return out

    def _sample(self,tags,terms,since,now):
        out=[]; step=timedelta(days=1)/self.sample_windows
        for label,kind,raw in queries(tags,terms):
            got=0; start=since
            while start<min(self.until or now,now-timedelta(seconds=15)) and got<self.max_posts:
                end=min(start+step,self.until or now,now-timedelta(seconds=15))
                key=digest([self.query_hash(raw,kind),'sample',iso(start),iso(end)])
                cap=min(max(10,self.sample_per_day//self.sample_windows),self.max_posts-got)
                page=self._page_window(raw,kind,start,end,tags,terms,now,cap,key,label)
                # These deliberately selected windows are a quota sample even if one is exhausted.
                self._coverage(key,label,self.last_window,now,'newest-first quota sample')
                out.extend(page); got+=len(page); start=end
        return out

    def read_window(self,raw,kind,start,end,tags,terms,now,expected=None,cap=5000):
        previous=self.archive
        if now-start>=timedelta(days=7): self.archive=True
        try:
            key=digest([self.query_hash(raw,kind),'window',iso(start),iso(end)])
            posts=self._page_window(raw,kind,start,end,tags,terms,now,cap,key,('#'+raw.lower()) if kind=='tag' else raw.lower())
            self.last_window['query_hash']=self.query_hash(raw,kind)
            self.log(f'  x window {iso(start)}: {len(posts)} posts this pass; {self.last_window["status"]}')
            return posts
        finally: self.archive=previous

    def _parse(self,j,tags,terms,now):
        users={u['id']:u for u in j.get('includes',{}).get('users',[])}; out=[]
        for t in j.get('data',[]):
            u=users.get(t['author_id'],{}); ent=t.get('entities',{}); pm=t.get('public_metrics',{})
            note=t.get('note_post') or t.get('note_tweet') or {}
            text=note.get('text') or t['text']
            if note.get('text'): ent=note.get('entities') or ent
            refs=t.get('referenced_posts',t.get('referenced_tweets',[]))
            ref=next((r for r in refs if r.get('type')=='retweeted'),None) or next(iter(refs),{})
            rt=ref.get('type')=='retweeted'; reply=any(r.get('type')=='replied_to' for r in refs) or bool(t.get('in_reply_to_user_id'))
            links=[x.get('unwound_url') or x.get('expanded_url') for x in ent.get('urls',[]) if not re.match(r'https://(twitter|x)\.com/',x.get('expanded_url') or '')]
            out.append(Post(source='x',instance='api.x.com',post_id=t['id'],created_utc=iso(parse_time(t['created_at'])),author=u.get('username',t['author_id']),author_id=t['author_id'],
                author_created_utc=iso(parse_time(u['created_at'])) if u.get('created_at') else None,
                author_followers=(u.get('public_metrics') or {}).get('followers_count'),author_posts=(u.get('public_metrics') or {}).get('post_count',(u.get('public_metrics') or {}).get('tweet_count')),
                is_reply=reply,reply_to=t.get('in_reply_to_user_id'),reference_type={'retweeted':'repost','quoted':'quote','replied_to':'reply'}.get(ref.get('type')),referenced_post_id=ref.get('id'),
                text=text,lang=t.get('lang'),is_repost=rt,reposts=pm.get('repost_count',pm.get('retweet_count')),likes=pm.get('like_count'),replies=pm.get('reply_count'),
                url=f'https://x.com/i/status/{t["id"]}',matched=matches(text,tags,terms),tags=sorted({h['tag'].lower() for h in ent.get('hashtags',[])}|set(tags_in(text))),
                links=sorted(set(l for l in links if l)),collected_utc=iso(now)))
        return out

    def usage(self): return self._get('https://api.x.com/2/usage/tweets',{})[0]

    def credits(self): return self._get('https://api.x.com/2/usage/credits',{})[0]
