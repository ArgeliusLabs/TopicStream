"""SQLite storage. One table of posts, one of tag-day counts the platforms report themselves, one of alerts.

Every source normalises its posts into the same row shape (see Post in sources.py), so the analysis never cares which
platform a post came from except where it has to (Bluesky search does not return reposts; X counts reposts as uses)."""
import sqlite3, json
from pathlib import Path

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
'''

class Store:
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path)); self.db.row_factory = sqlite3.Row
        # No separate journal file: friendlier to synced folders (OneDrive, Dropbox) and to mounted filesystems that cannot lock one.
        # The database is small and single-writer; a crash mid-run costs at most that run, which the next collection repeats for free.
        self.db.execute('PRAGMA journal_mode=MEMORY')
        self.db.executescript(SCHEMA)

    def add_posts(self, posts):
        """Insert or refresh. Returns how many were new. Engagement numbers are refreshed on re-collection because they grow."""
        new = 0
        for p in posts:
            cur = self.db.execute('SELECT matched FROM posts WHERE key = ?', (p.key,)).fetchone()
            if cur is None:
                new += 1; matched = p.matched
            else:
                matched = sorted(set(json.loads(cur['matched'])) | set(p.matched))
            self.db.execute('''INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET reposts=excluded.reposts, likes=excluded.likes, replies=excluded.replies,
                author_followers=excluded.author_followers, matched=excluded.matched, collected_utc=excluded.collected_utc''',
                (p.key, p.source, p.instance, p.post_id, p.created_utc, p.author, p.author_id, p.author_created_utc, p.author_followers,
                 p.text, p.lang, int(p.is_repost), p.reposts, p.likes, p.replies, p.url, json.dumps(matched), json.dumps(sorted(set(p.tags))),
                 json.dumps(p.links), p.collected_utc))
        self.db.commit(); return new

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
        """Dollars this database has already recorded for a source, summed over every finished run."""
        total = 0.0
        for r in self.db.execute('SELECT notes FROM runs WHERE notes IS NOT NULL'):
            n = json.loads(r['notes']); total += float(n.get(source, {}).get('spent_usd', 0) or 0)
        return total
    def cursors(self, source): return {r['tag']: r['cursor'] for r in self.db.execute('SELECT tag, cursor FROM cursors WHERE source = ?', (source,))}
    def set_cursor(self, source, tag, cursor, now):
        self.db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?,?)', (source, tag, cursor, now)); self.db.commit()
    def add_counts(self, source, rows, now):
        self.db.executemany('INSERT OR REPLACE INTO counts VALUES (?,?,?,?,?)', [(source, tag, start, n, now) for tag, start, n in rows]); self.db.commit()
    def counts(self, source='x'): return [dict(r) for r in self.db.execute('SELECT * FROM counts WHERE source = ? ORDER BY tag, start_utc', (source,))]
