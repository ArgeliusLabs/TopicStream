"""SQLite storage. One table of posts, one of tag-day counts the platforms report themselves, one of alerts.

Every source normalises its posts into the same row shape (see Post in sources.py), so the analysis never cares which
platform a post came from except where it has to (Bluesky search does not return reposts; X counts reposts as uses)."""
import sqlite3, json
from dataclasses import asdict
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from .identity import account_key, digest

SCHEMA = '''
CREATE TABLE IF NOT EXISTS posts (
  key TEXT PRIMARY KEY,            -- source:post_id, unique across everything we have ever stored
  source TEXT NOT NULL,            -- mastodon | bluesky | x
  instance TEXT,                   -- which server reported it (mastodon.social, bsky.social, api.x.com)
  post_id TEXT NOT NULL,
  created_utc TEXT NOT NULL,       -- ISO 8601, UTC, second precision
  author TEXT NOT NULL,            -- handle as the platform shows it
  author_id TEXT,
  author_created_utc TEXT,         -- when the account was created, if the platform tells us
  author_followers INTEGER,
  text TEXT NOT NULL,              -- plain text, HTML stripped
  lang TEXT,
  is_repost INTEGER NOT NULL DEFAULT 0,
  reposts INTEGER, likes INTEGER, replies INTEGER,
  url TEXT,
  matched TEXT NOT NULL,           -- JSON list of the tracked tags/terms this post matched
  tags TEXT NOT NULL,              -- JSON list of every hashtag in the post, lower-case, no '#'
  links TEXT NOT NULL,             -- JSON list of outbound URLs
  collected_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS posts_created ON posts(created_utc);
CREATE TABLE IF NOT EXISTS tag_days (
  source TEXT NOT NULL, instance TEXT NOT NULL, tag TEXT NOT NULL, day TEXT NOT NULL,   -- day = YYYY-MM-DD UTC
  uses INTEGER NOT NULL, accounts INTEGER,                                               -- accounts is NULL when the platform only gives a count
  fetched_utc TEXT NOT NULL,
  PRIMARY KEY (source, instance, tag, day)
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_utc TEXT NOT NULL, tag TEXT NOT NULL, window_start_utc TEXT NOT NULL,
  window_minutes INTEGER NOT NULL, uses INTEGER NOT NULL, accounts INTEGER NOT NULL, baseline REAL, reason TEXT NOT NULL,
  UNIQUE (tag, window_start_utc, window_minutes)
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_utc TEXT NOT NULL, finished_utc TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS cursors (                 -- where incremental collection left off, per source and tag (X: newest post id seen)
  source TEXT NOT NULL, tag TEXT NOT NULL, cursor TEXT NOT NULL, updated_utc TEXT NOT NULL, PRIMARY KEY (source, tag)
);
CREATE TABLE IF NOT EXISTS counts (                  -- platform-side counts at finer than a day (X counts endpoint, hourly)
  source TEXT NOT NULL, tag TEXT NOT NULL, start_utc TEXT NOT NULL, uses INTEGER NOT NULL, fetched_utc TEXT NOT NULL, PRIMARY KEY (source, tag, start_utc)
);
CREATE TABLE IF NOT EXISTS windows (                 -- time windows read COMPLETE (every post), where burst and account rules are trustworthy
  source TEXT NOT NULL, tag TEXT NOT NULL, start_utc TEXT NOT NULL, end_utc TEXT NOT NULL, expected INTEGER, got INTEGER NOT NULL, fetched_utc TEXT NOT NULL,
  PRIMARY KEY (source, tag, start_utc)
);
'''
# columns added after 0.1.0; existing databases get them in place
MIGRATIONS = [('posts', 'is_reply', 'INTEGER NOT NULL DEFAULT 0'), ('posts', 'reply_to', 'TEXT'), ('posts', 'author_posts', 'INTEGER'),
              ('posts', 'author_uri', 'TEXT'), ('posts', 'reference_type', 'TEXT'), ('posts', 'referenced_post_id', 'TEXT'),
              ('posts', 'original_author', 'TEXT'), ('posts', 'account_key', 'TEXT'),
              ('counts', 'query_hash', "TEXT NOT NULL DEFAULT ''"),
              ('windows', 'status', "TEXT NOT NULL DEFAULT 'unverified'"),
              ('windows', 'stop_reason', "TEXT NOT NULL DEFAULT 'legacy record without pagination evidence'"),
              ('windows', 'next_token', 'TEXT'), ('windows', 'query_hash', "TEXT NOT NULL DEFAULT ''")]

EXTRA_SCHEMA = '''
CREATE TABLE IF NOT EXISTS checkpoints (source TEXT, query_hash TEXT, state TEXT NOT NULL, PRIMARY KEY(source, query_hash));
CREATE TABLE IF NOT EXISTS coverage (
  source TEXT, query_hash TEXT, label TEXT, start_utc TEXT, end_utc TEXT,
  status TEXT NOT NULL, stop_reason TEXT, retrieved INTEGER NOT NULL DEFAULT 0,
  sampling TEXT NOT NULL, fetched_utc TEXT, PRIMARY KEY(source, query_hash, label, start_utc, end_utc)
);
CREATE TABLE IF NOT EXISTS request_ledger (
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, endpoint TEXT NOT NULL, query_hash TEXT,
  started_utc TEXT NOT NULL, finished_utc TEXT, status TEXT NOT NULL,
  reserved_micros INTEGER NOT NULL, charged_micros INTEGER, detail TEXT
);
CREATE TABLE IF NOT EXISTS post_snapshots (
  post_key TEXT, collected_utc TEXT, content_hash TEXT, record TEXT NOT NULL,
  PRIMARY KEY(post_key, collected_utc, content_hash)
);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY, group_id TEXT NOT NULL, dataset_hash TEXT NOT NULL,
  created_utc TEXT NOT NULL, assessment TEXT NOT NULL, explanation TEXT NOT NULL, evidence TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS detector_runs (
  id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, dataset_hash TEXT NOT NULL,
  config TEXT NOT NULL, result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_posts (
  run_id TEXT, post_key TEXT, record TEXT NOT NULL, PRIMARY KEY(run_id,post_key)
);
CREATE TABLE IF NOT EXISTS monitor_alerts (
  source TEXT, tag TEXT, start_utc TEXT, minutes INTEGER, payload TEXT NOT NULL, created_utc TEXT NOT NULL,
  PRIMARY KEY(source, tag, start_utc, minutes)
);
'''


class BudgetExceeded(RuntimeError):
    pass


def micros(value):
    return int((Decimal(str(value)) * 1000000).to_integral_value(rounding=ROUND_CEILING))

class Store:
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=30); self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:
            if col not in {r['name'] for r in self.db.execute(f'PRAGMA table_info({table})')}: self.db.execute(f'ALTER TABLE {table} ADD COLUMN {col} {decl}')
        self.db.executescript(EXTRA_SCHEMA)
        # Preserve distinct query versions at the same label and timestamp.
        for table in ('counts','windows'):
            info=list(self.db.execute(f'PRAGMA table_info({table})'))
            if not next(r for r in info if r['name']=='query_hash')['pk']:
                columns=','.join(r['name'] for r in info)
                definitions=','.join(r['name']+' '+r['type'] for r in info)
                with self.db:
                    self.db.execute(f'CREATE TABLE {table}_v3 ({definitions}, PRIMARY KEY(source,tag,start_utc,query_hash))')
                    self.db.execute(f'INSERT INTO {table}_v3({columns}) SELECT {columns} FROM {table}')
                    self.db.execute(f'DROP TABLE {table}')
                    self.db.execute(f'ALTER TABLE {table}_v3 RENAME TO {table}')
        if not self.db.execute("SELECT 1 FROM metadata WHERE key='ledger_migrated'").fetchone():
            old = sum(float(json.loads(r['notes']).get('x', {}).get('spent_usd', 0) or 0)
                      for r in self.db.execute('SELECT notes FROM runs WHERE notes IS NOT NULL'))
            if old:
                self.db.execute("INSERT INTO request_ledger(source,endpoint,started_utc,status,reserved_micros,charged_micros) VALUES ('x','legacy runs','','settled',?,?)", (micros(old), micros(old)))
            self.db.execute("INSERT INTO metadata VALUES ('ledger_migrated','1')")
        for row in self.db.execute('SELECT * FROM posts WHERE account_key IS NULL').fetchall():
            self.db.execute('UPDATE posts SET account_key=? WHERE key=?', (account_key(dict(row)), row['key']))
        self.db.commit()

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()

    def add_posts(self, posts, commit=True):
        """Insert or refresh. Returns how many were new. Engagement numbers are refreshed on re-collection because they grow."""
        new = 0
        for p in posts:
            cur = self.db.execute('SELECT matched FROM posts WHERE key = ?', (p.key,)).fetchone()
            if cur is None:
                new += 1; matched = p.matched
            else:
                matched = sorted(set(json.loads(cur['matched'])) | set(p.matched))
            self.db.execute('''INSERT INTO posts (key, source, instance, post_id, created_utc, author, author_id, author_created_utc, author_followers, text, lang, is_repost,
                reposts, likes, replies, url, matched, tags, links, collected_utc, is_reply, reply_to, author_posts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET reposts=excluded.reposts, likes=excluded.likes, replies=excluded.replies,
                text=excluded.text, tags=excluded.tags, links=excluded.links, url=excluded.url, lang=excluded.lang,
                author_created_utc=COALESCE(excluded.author_created_utc,posts.author_created_utc),
                author_followers=excluded.author_followers, author_posts=excluded.author_posts, matched=excluded.matched, collected_utc=excluded.collected_utc''',
                (p.key, p.source, p.instance, p.post_id, p.created_utc, p.author, p.author_id, p.author_created_utc, p.author_followers,
                 p.text, p.lang, int(p.is_repost), p.reposts, p.likes, p.replies, p.url, json.dumps(matched), json.dumps(sorted(set(p.tags))),
                 json.dumps(p.links), p.collected_utc, int(p.is_reply), p.reply_to, p.author_posts))
            record = asdict(p)
            self.db.execute('UPDATE posts SET author=?,author_id=COALESCE(?,author_id),author_uri=COALESCE(?,author_uri),reference_type=?,referenced_post_id=?,original_author=?,account_key=? WHERE key=?',
                            (p.author,p.author_id,p.author_uri,p.reference_type,p.referenced_post_id,p.original_author,account_key(record),p.key))
            identity=dict(self.db.execute('SELECT * FROM posts WHERE key=?',(p.key,)).fetchone())
            self.db.execute('UPDATE posts SET account_key=? WHERE key=?',(account_key(identity),p.key))
            self.db.execute('INSERT OR IGNORE INTO post_snapshots VALUES (?,?,?,?)', (p.key,p.collected_utc,digest(record),json.dumps(record,ensure_ascii=False)))
        if commit: self.db.commit()
        return new

    def add_tag_days(self, rows):
        self.db.executemany('INSERT OR REPLACE INTO tag_days VALUES (?,?,?,?,?,?,?)', rows); self.db.commit()

    def add_alert(self, tag, window_start, minutes, uses, accounts, baseline, reason, now):
        cur = self.db.execute('INSERT OR IGNORE INTO alerts (created_utc, tag, window_start_utc, window_minutes, uses, accounts, baseline, reason) VALUES (?,?,?,?,?,?,?,?)',
                              (now, tag, window_start, minutes, uses, accounts, baseline, reason))
        self.db.commit(); return cur.rowcount == 1

    def posts(self, since=None, until=None):
        q = 'SELECT * FROM posts'; args = []; conds = []
        if since: conds.append('created_utc >= ?'); args.append(since)
        if until: conds.append('created_utc < ?'); args.append(until)
        if conds: q += ' WHERE ' + ' AND '.join(conds)
        q += ' ORDER BY created_utc'
        out = []
        for r in self.db.execute(q, args):
            d = dict(r); d['matched'] = json.loads(d['matched']); d['tags'] = json.loads(d['tags']); d['links'] = json.loads(d['links']); out.append(d)
        return out

    def tag_days(self): return [dict(r) for r in self.db.execute('SELECT * FROM tag_days ORDER BY tag, day, source, instance')]
    def alerts(self): return [dict(r) for r in self.db.execute('SELECT * FROM alerts ORDER BY window_start_utc')]
    def start_run(self, now):
        cur = self.db.execute('INSERT INTO runs (started_utc) VALUES (?)', (now,)); self.db.commit(); return cur.lastrowid
    def finish_run(self, run_id, now, notes):
        self.db.execute('UPDATE runs SET finished_utc = ?, notes = ? WHERE id = ?', (now, json.dumps(notes), run_id)); self.db.commit()
    def runs(self): return [dict(r) for r in self.db.execute('SELECT * FROM runs ORDER BY id')]
    def spent(self, source='x'):
        """Conservative local ledger, including unresolved requests after a crash."""
        row = self.db.execute('SELECT COALESCE(SUM(COALESCE(charged_micros,reserved_micros)),0) FROM request_ledger WHERE source=?', (source,)).fetchone()
        return row[0] / 1000000
    def cursors(self, source): return {r['tag']: r['cursor'] for r in self.db.execute('SELECT tag, cursor FROM cursors WHERE source = ?', (source,))}
    def set_cursor(self, source, tag, cursor, now):
        self.db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?,?)', (source, tag, cursor, now)); self.db.commit()
    def add_counts(self, source, rows, now, query_hash=''):
        self.db.executemany('INSERT OR REPLACE INTO counts(source,tag,start_utc,uses,fetched_utc,query_hash) VALUES (?,?,?,?,?,?)', [(source, tag, start, n, now, query_hash) for tag, start, n in rows]); self.db.commit()
    def counts(self, source='x'): return [dict(r) for r in self.db.execute('SELECT * FROM counts WHERE source = ? ORDER BY tag, start_utc', (source,))]
    def add_window(self, source, tag, start, end, expected, got, now, status='unverified', stop_reason='', next_token=None, query_hash=''):
        self.db.execute('INSERT OR REPLACE INTO windows(source,tag,start_utc,end_utc,expected,got,fetched_utc,status,stop_reason,next_token,query_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (source,tag,start,end,expected,got,now,status,stop_reason,next_token,query_hash)); self.db.commit()
    def windows(self): return [dict(r) for r in self.db.execute('SELECT * FROM windows ORDER BY tag, start_utc')]

    def checkpoint(self, source, query_hash):
        row = self.db.execute('SELECT state FROM checkpoints WHERE source=? AND query_hash=?', (source,query_hash)).fetchone()
        return json.loads(row['state']) if row else {}

    def save_page(self, source, query_hash, state, posts):
        """One transaction: either both the page and its resume state persist, or neither."""
        with self.db:
            self.add_posts(posts, commit=False)
            self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?,?)', (source,query_hash,json.dumps(state)))

    def record_coverage(self, source, query_hash, label, start, end, status, reason, retrieved, sampling, now):
        self.db.execute('INSERT OR REPLACE INTO coverage VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (source,query_hash,label,start,end,status,reason,retrieved,sampling,now)); self.db.commit()

    def coverage(self): return [dict(r) for r in self.db.execute('SELECT * FROM coverage ORDER BY source,label,start_utc')]

    def reserve_request(self, source, endpoint, query_hash, amount, budget, now):
        amount = micros(amount)
        try:
            self.db.execute('BEGIN IMMEDIATE')
            used = self.db.execute('SELECT COALESCE(SUM(COALESCE(charged_micros,reserved_micros)),0) FROM request_ledger WHERE source=?', (source,)).fetchone()[0]
            if used + amount > micros(budget):
                raise BudgetExceeded(f'{source}: budget_usd {budget:.2f} cannot cover the next request; {used/1000000:.4f} already reserved or spent')
            cur = self.db.execute("INSERT INTO request_ledger(source,endpoint,query_hash,started_utc,status,reserved_micros) VALUES (?,?,?,?,'reserved',?)", (source,endpoint,query_hash,now,amount))
            self.db.commit(); return cur.lastrowid
        except BaseException:
            self.db.rollback(); raise

    def settle_request(self, request_id, amount, now):
        self.db.execute("UPDATE request_ledger SET charged_micros=?,finished_utc=?,status='settled' WHERE id=?", (micros(amount),now,request_id)); self.db.commit()

    def uncertain_request(self, request_id, detail, now):
        self.db.execute("UPDATE request_ledger SET status='uncertain',detail=?,finished_utc=? WHERE id=?", (str(detail)[:500],now,request_id)); self.db.commit()

    def ledger(self): return [dict(r) for r in self.db.execute('SELECT * FROM request_ledger ORDER BY id')]

    def add_monitor_alert(self, source, tag, start, minutes, payload, now):
        cur = self.db.execute('INSERT OR IGNORE INTO monitor_alerts VALUES (?,?,?,?,?,?)', (source,tag,start,minutes,json.dumps(payload),now)); self.db.commit()
        return cur.rowcount == 1

    def monitor_alerts(self):
        return [dict(r, payload=json.loads(r['payload'])) for r in self.db.execute('SELECT * FROM monitor_alerts ORDER BY start_utc')]

    def add_review(self, group_id, dataset_hash, now, assessment, explanation, evidence):
        self.db.execute('INSERT INTO reviews(group_id,dataset_hash,created_utc,assessment,explanation,evidence) VALUES (?,?,?,?,?,?)', (group_id,dataset_hash,now,assessment,explanation,json.dumps(evidence))); self.db.commit()

    def reviews(self): return [dict(r, evidence=json.loads(r['evidence'])) for r in self.db.execute('SELECT * FROM reviews ORDER BY id')]

    def save_analysis(self, result, now, config, posts=()):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO detector_runs VALUES (?,?,?,?,?)', (result['run_id'],now,result['dataset_hash'],json.dumps(config,sort_keys=True),json.dumps(result,ensure_ascii=False)))
            self.db.executemany('INSERT OR REPLACE INTO analysis_posts VALUES (?,?,?)',[(result['run_id'],p['key'],json.dumps(p,ensure_ascii=False)) for p in posts])

    def analysis_posts(self,run_id):
        return [json.loads(r['record']) for r in self.db.execute('SELECT record FROM analysis_posts WHERE run_id=? ORDER BY post_key',(run_id,))]
