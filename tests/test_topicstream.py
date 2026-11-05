"""Offline tests. Recorded Mastodon JSON shapes for the parsers; the Day 6 Ciap export for the analysis, when present."""
import json, os, sys, tempfile, unittest, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from topicstream.sources import Mastodon, Post, matches, tags_in, strip_html, iso, parse_time
from topicstream.store import Store
from topicstream import analyze as A, report as R
from topicstream.__main__ import import_csv

NOW = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)

def mast_status(i, acct, text, created, tags=(), card=None, reblog=False):
    s = dict(id=str(1000 + i), uri=f'https://ex.org/u/{acct}/{1000 + i}', url=f'https://ex.org/@{acct}/{1000 + i}', created_at=created, content=f'<p>{text}</p>',
             account=dict(id=str(i), acct=acct, created_at='2024-01-01T00:00:00.000Z', followers_count=10 + i), tags=[dict(name=t) for t in tags],
             language='en', reblogs_count=0, favourites_count=1, replies_count=0, card=dict(url=card) if card else None, reblog=None)
    if reblog: return dict(id=str(5000 + i), created_at=created, reblog=s, account=s['account'], content='', tags=[], uri=None)
    return s

class FakeHttp:
    def __init__(self, pages): self.pages = pages; self.requests = 0
    def get(self, url, headers=None):
        self.requests += 1
        if '/api/v1/tags/' in url:
            return dict(name='osint', history=[dict(day=str(int((NOW - timedelta(days=d)).replace(hour=0, minute=0, second=0).timestamp())), uses=str(100 + d), accounts=str(10 + d)) for d in range(7)]), {}
        if 'max_id=' not in url: return self.pages[0], {}
        return self.pages[1] if len(self.pages) > 1 else [], {}

class ParsingTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(strip_html('<p>hi <b>there</b><br>x &amp; y</p>'), 'hi there\nx & y')
        self.assertEqual(tags_in('go #OSINT and #Infosec'), ['osint', 'infosec'])
        self.assertEqual(matches('go #OSINT now', ['OSINT', 'infosec'], ['Go']), ['#osint', 'go'])
    def test_mastodon_pagination_and_dedupe(self):
        t = lambda m: (NOW - timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        p1 = [mast_status(1, 'a', 'one #osint', t(5), ['osint'], 'https://news.example/x'), mast_status(2, 'b', 'two #osint', t(10), ['osint']), mast_status(1, 'a', 'one #osint', t(5), ['osint'], reblog=True)]
        p2 = [mast_status(3, 'c', 'old #osint', (NOW - timedelta(days=9)).strftime('%Y-%m-%dT%H:%M:%S.000Z'), ['osint'])]
        m = Mastodon(['ex.org'], FakeHttp([p1, p2]), log=lambda *a: None)
        posts = m.posts(['osint'], [], NOW - timedelta(days=7), NOW)
        self.assertEqual([p.author for p in posts], ['a', 'b'])          # the reblog of post 1 de-duplicated on URI, the 9-day-old post cut by `since`
        self.assertEqual(posts[0].links, ['https://news.example/x']); self.assertEqual(posts[0].matched, ['#osint'])
        rows = m.tag_days(['osint'], NOW); self.assertEqual(len(rows), 7); self.assertEqual(rows[0][4], 100); self.assertEqual(rows[0][5], 10)
    def test_store_roundtrip_and_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / 'x.sqlite')
            p = Post(source='mastodon', instance='ex.org', post_id='u1', created_utc=iso(NOW), author='a', text='hi #osint', likes=1, matched=['#osint'], tags=['osint'], collected_utc=iso(NOW))
            self.assertEqual(s.add_posts([p]), 1); p.likes = 5; self.assertEqual(s.add_posts([p]), 0)
            self.assertEqual(s.posts()[0]['likes'], 5)

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.posts = []
        base = NOW - timedelta(days=2, hours=1)   # off the 3-hour background grid
        for i in range(60):  # a burst: 60 posts from 6 accounts in 20 minutes, same text
            self.posts.append(dict(source='m', author=f'bot{i % 6}', created_utc=iso(base + timedelta(seconds=20 * i)), text='Something is very wrong at the bay. Fishermen are pulling up dead catch. #campaign', tags=['campaign', 'osint'], matched=['#osint'], links=['https://site.example/a'], is_repost=0, likes=0, author_created_utc=iso(NOW - timedelta(days=5)), author_followers=3))
        for i in range(40):  # background: 40 posts from 40 people over the week
            self.posts.append(dict(source='m', author=f'person{i}', created_utc=iso(NOW - timedelta(hours=3 * i)), text=f'post number {i} about #osint things', tags=['osint'], matched=['#osint'], links=[], is_repost=0, likes=4, author_created_utc=iso(NOW - timedelta(days=900)), author_followers=200))
    def test_velocity_alerts_on_burst(self):
        v = A.velocity(self.posts, '#osint', 30, 200, 10, 5)
        self.assertEqual(v['uses'], 60); self.assertEqual(v['accounts'], 6); self.assertEqual(v['ratio'], 10.0)
        self.assertTrue(any('uses per account' in r for r in v['reasons'])); self.assertTrue(any('average' in r for r in v['reasons'])); self.assertEqual(v['first_trip']['start'], v['start'])
    def test_cooccurrence_and_domains_and_bursts(self):
        co = A.cooccurrence(self.posts, '#osint'); self.assertEqual(co[0]['tag'], '#campaign'); self.assertEqual(co[0]['accounts'], 6); self.assertAlmostEqual(co[0]['share'], 0.6)
        self.assertEqual(A.top_domains(self.posts, '#osint')[0], dict(domain='site.example', posts=60, accounts=6))
        b = A.bursts(self.posts, 10, 3); self.assertEqual(len(b), 2); self.assertEqual([len(x['accounts']) for x in b], [6, 6])   # 20 minutes of posting, two 10-minute windows
        acc = A.top_accounts(self.posts, '#osint', now=NOW); self.assertEqual(acc[0]['uses'], 10); self.assertEqual(acc[0]['age_days'], 5)
    def test_report_renders(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / 'x.sqlite')
            s.add_posts([Post(source='m', instance='ex', post_id=str(i), created_utc=p['created_utc'], author=p['author'], text=p['text'], matched=p['matched'], tags=p['tags'], links=p['links'], collected_utc=iso(NOW), author_created_utc=p['author_created_utc'], author_followers=p['author_followers'], likes=p['likes']) for i, p in enumerate(self.posts)])
            html = R.render(s, dict(name='t', tags=['osint'], days=7, alert={}), now=NOW)
            self.assertIn('ALERT', html); self.assertIn('#campaign', html); self.assertIn('site.example', html); self.assertNotIn('Traceback', html)

# Point TOPICSTREAM_SAMPLE_CSV at a posts export with the import-csv column names to run the end-to-end analysis test.
CIAP = Path(os.environ.get('TOPICSTREAM_SAMPLE_CSV', Path(__file__).resolve().parents[2] / 'capstone/release/Evidence/1_Platform/exports/ciap_posts_2026-02-01_to_2026-03-08.csv'))
@unittest.skipUnless(CIAP.exists(), 'sample export not present (set TOPICSTREAM_SAMPLE_CSV)')
class ExerciseDataTests(unittest.TestCase):
    """The course exercise's dashboard is this code over that data: the alert fires on 3 February, the nine pushes show up as bursts."""
    def test_day6_export(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = dict(tags=['TelukRawah', 'TelukRawa', 'BuktiIndependen'], terms=[], days=40, db=str(Path(d) / 'c.sqlite'), report=str(Path(d) / 'r.html'), name='Teluk Rawa')
            import_csv(cfg, str(CIAP), 'ciap', log=lambda *a: None)
            s = Store(cfg['db']); posts = s.posts()
            self.assertGreater(len(posts), 800)
            v = A.velocity(posts, '#telukrawah', 30, 200, 10, 5)
            self.assertTrue(v['first_trip']['start'].startswith('2026-02-03T02:47'), v['first_trip']); self.assertGreaterEqual(v['first_trip']['uses'], 12)   # the alert the dossier shows
            self.assertTrue(v['start'].startswith('2026-02-05'), v['start'])                                                                       # the busiest push is the third
            b = A.bursts(posts, 10, 5); self.assertGreaterEqual(len(b), 8)        # the nine pushes, give or take the spelling split
            co = A.cooccurrence(posts, '#telukrawah'); self.assertIn('#sekawandeal', [c['tag'] for c in co])
            html = R.render(s, cfg, now=datetime(2026, 3, 9, tzinfo=timezone.utc)); self.assertIn('ALERT', html)
            self.assertIn('Imported export (ciap)', html); self.assertNotIn('<b>Mastodon.</b>', html)                              # platform notes follow what the database holds
            self.assertIn('Export: 2026-02-01 to 2026-03-08', html); self.assertIn('Export depth', html); self.assertNotIn('max_pages', html)
            prof = CIAP.parent / 'ciap_account_profiles_2026-03-09.csv'
            if prof.exists():
                cfg2 = dict(cfg, db=str(Path(d) / 'c2.sqlite')); import_csv(cfg2, str(CIAP), 'ciap', log=lambda *a: None, accounts=str(prof))
                rows = {r['account']: r for r in A.account_features(Store(cfg2['db']).posts(), now=datetime(2026, 3, 9, tzinfo=timezone.utc))}
                self.assertIsNotNone(rows['nurani_pesisir']['age_days']); self.assertIn('dormant_then_active', rows['nurani_pesisir']['signals'])
                self.assertEqual(rows['warga_rawa22']['reply_to'], 'ombak_merah')                                                  # in_reply_to resolved from a post id to its author

if __name__ == '__main__': unittest.main()


# ---------------------------------------------------------------------------------------------------------------------- X, offline
from topicstream.sources import X, load_dotenv
import urllib.parse

def x_search_page(ids, next_token=None, rt=False):
    return dict(data=[dict(id=str(i), text=f'post {i} #Election2026 https://t.co/x{i}', author_id=f'u{i % 3}', created_at='2026-11-04T12:00:00.000Z', lang='en',
                           public_metrics=dict(retweet_count=1, like_count=2, reply_count=0),
                           entities=dict(hashtags=[dict(tag='Election2026')], urls=[dict(expanded_url=f'https://news.example/{i}', unwound_url=f'https://news.example/{i}'), dict(expanded_url='https://x.com/u/status/1')]),
                           referenced_tweets=[dict(type='retweeted', id='9')] if rt else []) for i in ids],
                includes=dict(users=[dict(id=f'u{k}', username=f'user{k}', created_at='2026-10-01T00:00:00.000Z', public_metrics=dict(followers_count=10 * k)) for k in range(3)]),
                meta=dict(newest_id=str(max(ids)), oldest_id=str(min(ids)), result_count=len(ids), **({'next_token': next_token} if next_token else {})))

class XFakeHttp:
    def __init__(self): self.calls = []; self.requests = 0
    def get(self, url, headers=None):
        self.calls.append(url); self.requests += 1; q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert headers['Authorization'] == 'Bearer tok'
        if '/usage/' in url: return dict(data=dict(project_usage='2851', project_cap='3000000', cap_reset_day=26)), {}
        if '/counts/' in url:
            g = q['granularity'][0]; n = 7 if g == 'day' else 168
            return dict(data=[dict(start=f'2026-11-0{1 + i % 7}T00:00:00.000Z', end='x', post_count=100 + i) for i in range(n)], meta=dict(total_post_count=sum(100 + i for i in range(n)))), {}
        if 'since_id' in q: return x_search_page([2001, 2002]), {}
        if 'next_token' in q: return x_search_page([1003, 1004], rt=True), {}
        return x_search_page([1001, 1002], next_token='abc'), {}

class XTests(unittest.TestCase):
    def test_counts_and_posts_and_cursor(self):
        http = XFakeHttp(); saved = {}
        x = X(http, log=lambda *a: None, max_posts_per_tag=4, budget_usd=5, bearer='tok', query_extra='-is:retweet', save_cursor=lambda t, n: saved.__setitem__(t, n))
        rows = x.tag_days(['Election2026'], NOW, NOW - timedelta(days=7))
        self.assertEqual(len(rows), 7); self.assertEqual(rows[0][2], '#election2026'); self.assertEqual(len(x.hourly), 168)
        self.assertAlmostEqual(x.spent, 2 * 0.005)
        posts = x.posts(['Election2026'], [], NOW - timedelta(days=7), NOW)
        self.assertEqual(len(posts), 4); self.assertEqual(sum(p.is_repost for p in posts), 2)
        self.assertEqual(posts[0].links, ['https://news.example/1001']); self.assertEqual(posts[0].author, 'user2'); self.assertEqual(posts[0].author_followers, 20)
        self.assertEqual(posts[0].matched, ['#election2026']); self.assertEqual(saved, {'#election2026': '1004'})
        self.assertAlmostEqual(x.spent, 2 * 0.005 + 4 * 0.005)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[2]).query); self.assertEqual(q['query'], ['#Election2026 -is:retweet']); self.assertIn('start_time', q); self.assertNotIn('since_id', q)
    def test_incremental_uses_since_id_not_start_time(self):
        http = XFakeHttp(); x = X(http, log=lambda *a: None, max_posts_per_tag=10, budget_usd=5, bearer='tok', cursors={'#election2026': '1004'})
        posts = x.posts(['Election2026'], [], NOW - timedelta(days=7), NOW)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[0]).query); self.assertEqual(q['since_id'], ['1004']); self.assertNotIn('start_time', q)
        self.assertEqual([p.post_id for p in posts], ['2001', '2002']); self.assertEqual(x.cursors['#election2026'], '2002')
    def test_budget_counts_what_was_already_spent(self):
        x = X(XFakeHttp(), log=lambda *a: None, max_posts_per_tag=100, budget_usd=1.0, bearer='tok', spent_before=0.80)
        self.assertAlmostEqual(x.estimate(['a']), 0.01 + 0.5)
        with self.assertRaises(SystemExit): x.posts(['a'], [], NOW - timedelta(days=7), NOW)
        x2 = X(XFakeHttp(), log=lambda *a: None, max_posts_per_tag=100, budget_usd=1.0, bearer='tok', spent_before=0.0)
        x2.posts(['a'], [], NOW - timedelta(days=7), NOW)   # within budget: runs
    def test_dotenv(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / '.env').write_text('# comment\nX_BEARER_TOKEN="abc123"\nBSKY_HANDLE=me.bsky.social\n')
            os.environ.pop('X_BEARER_TOKEN', None); os.environ['BSKY_HANDLE'] = 'keep-me'
            self.assertTrue(load_dotenv([Path(d) / '.env'])); self.assertEqual(os.environ['X_BEARER_TOKEN'], 'abc123'); self.assertEqual(os.environ['BSKY_HANDLE'], 'keep-me')
            os.environ.pop('X_BEARER_TOKEN'); os.environ.pop('BSKY_HANDLE')
    def test_report_with_x_counts(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / 'x.sqlite'); s.add_counts('x', [('#election2026', f'2026-11-0{1 + i % 7}T{i % 24:02d}:00:00Z', 10 + i) for i in range(50)], iso(NOW))
            s.add_posts([Post(source='x', instance='api.x.com', post_id='1', created_utc=iso(NOW), author='a', text='x #election2026', matched=['#election2026'], tags=['election2026'], collected_utc=iso(NOW))])
            rid = s.start_run(iso(NOW)); s.finish_run(rid, iso(NOW), {'x': {'spent_usd': 0.123}})
            self.assertAlmostEqual(s.spent('x'), 0.123)
            html = R.render(s, dict(name='t', tags=['election2026'], days=7, alert={}), now=NOW)
            self.assertIn('X volume per hour', html); self.assertIn('$0.12', html)


class TermsAndDiscoveryTests(unittest.TestCase):
    def test_x_term_is_a_quoted_phrase_and_counts_both(self):
        http = XFakeHttp(); x = X(http, log=lambda *a: None, max_posts_per_tag=4, budget_usd=5, bearer='tok', query_extra='lang:en')
        self.assertEqual(x.query('Teluk Rawa', 'term'), '"Teluk Rawa" lang:en'); self.assertEqual(x.query('OSINT'), '#OSINT lang:en')
        self.assertAlmostEqual(x.estimate(['a'], ['b c']), 2 * (0.01 + 0.02))
        rows = x.tag_days(['Election2026'], NOW, NOW - timedelta(days=7), terms=['bilge water'])
        self.assertEqual({r[2] for r in rows}, {'#election2026', 'bilge water'})
        q = urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[2]).query); self.assertEqual(q['query'], ['"bilge water" lang:en'])
    def test_candidates(self):
        posts = [dict(author=f'a{i}', tags=['osint', 'campaign', 'threatintel'], matched=['#osint']) for i in range(6)] + [dict(author='bot', tags=['osint', 'spam'], matched=['#osint'])] * 9
        c = A.candidates(posts, ['#osint'], min_posts=3)
        self.assertEqual([r['tag'] for r in c][:2], ['#campaign', '#threatintel']); self.assertEqual(c[0]['accounts'], 6); self.assertEqual(c[0]['rides_with'], '#osint')
        spam = [r for r in c if r['tag'] == '#spam'][0]; self.assertEqual((spam['posts'], spam['accounts']), (9, 1))

class SamplingTests(unittest.TestCase):
    def test_sample_per_day_walks_the_window_with_start_and_end_time(self):
        http = XFakeHttp(); x = X(http, log=lambda *a: None, max_posts_per_tag=10000, budget_usd=500, bearer='tok', sample_per_day=60, archive=True, sample_windows_per_day=6)
        posts = x.posts(['PHP2Shell'], [], NOW - timedelta(days=7), NOW)
        qs = [urllib.parse.parse_qs(urllib.parse.urlparse(u).query) for u in http.calls]
        self.assertTrue(all('start_time' in q and 'end_time' in q and 'since_id' not in q for q in qs))
        self.assertGreaterEqual(len({q['start_time'][0][:10] for q in qs}), 7)                       # every day covered
        self.assertEqual(sorted({q['start_time'][0][11:13] for q in qs}), ['00', '04', '08', '12', '16', '20'])   # six 4-hour windows from midnight
        self.assertTrue(all('search/all' in u for u in http.calls))
        self.assertGreaterEqual(len(posts), 7 * 6 * 4); self.assertAlmostEqual(x.spent, len(posts) * 0.005)
        self.assertAlmostEqual(x.estimate(['a'], [], 21), (1 + (1 + 21 * 24 // 500)) * 0.01 + min(10000, 10 * 6 * 22) * 0.005)
    def test_velocity_from_counts(self):
        counts = [dict(tag='#t', start_utc=f'2026-10-{14 + i // 24:02d}T{i % 24:02d}:00:00Z', uses=5) for i in range(200)]
        counts[170]['uses'] = 784; counts[150]['uses'] = 120
        v = A.velocity_from_counts(counts, '#t', 200, 10, 10)
        self.assertEqual(v['uses'], 784); self.assertEqual(v['first_trip']['uses'], 120); self.assertTrue(any('average hour' in r for r in v['first_trip']['reasons']))


class CollectWiringTests(unittest.TestCase):
    """collect() end to end against the recorded X shapes: meter recorded, cursor saved, spend accumulated, budget enforced."""
    def test_collect_records_meter_cursor_and_spend(self):
        import topicstream.sources as S
        from topicstream.__main__ import collect
        fake = XFakeHttp(); orig = S.Http.get
        S.Http.get = lambda self, url, headers=None, tries=4: fake.get(url, headers)
        try:
            with tempfile.TemporaryDirectory() as d:
                os.environ['X_BEARER_TOKEN'] = 'tok'
                cfg = dict(tags=['Election2026'], terms=[], days=7, db=str(Path(d) / 'c.sqlite'), report=str(Path(d) / 'r.html'), pause_seconds=0,
                           sources=dict(mastodon=dict(enabled=False), bluesky=dict(enabled=False), x=dict(enabled=True, max_posts_per_tag=4, budget_usd=0.07, query_extra='', counts_every_minutes=60)), alert={})
                store = collect(cfg, log=lambda *a: None); n = json.loads(store.runs()[-1]['notes'])
                self.assertEqual(n['x_meter_before'], 2851); self.assertEqual(n['x']['posts'], 4); self.assertAlmostEqual(n['x']['spent_usd'], 0.01 + 0.02)   # counts (day + hour) + 4 reads
                self.assertEqual(store.cursors('x'), {'#election2026': '1004'}); self.assertIn('#election2026', store.cursors('x-counts'))
                collect(cfg, log=lambda *a: None); n2 = json.loads(store.runs()[-1]['notes'])
                self.assertEqual(n2['x']['posts'], 2); self.assertAlmostEqual(n2['x']['spent_usd'], 0.01); self.assertAlmostEqual(store.spent('x'), 0.04)   # counts kept (bought minutes ago), 2 new reads
                collect(cfg, log=lambda *a: None); n3 = json.loads(store.runs()[-1]['notes']); self.assertNotIn('error', n3['x'])   # 0.04 + worst case 0.03 = 0.07, allowed
                collect(cfg, log=lambda *a: None); n4 = json.loads(store.runs()[-1]['notes'])
                self.assertIn('error', n4['x']); self.assertIn('budget_usd', n4['x']['error']); self.assertNotIn('spent_usd', n4['x'])   # 0.05 + 0.03 > 0.07: nothing bought
        finally:
            S.Http.get = orig; os.environ.pop('X_BEARER_TOKEN', None)

class CountsThrottleTests(unittest.TestCase):
    def test_counts_not_rebought_inside_the_interval(self):
        http = XFakeHttp(); saved = {}
        x = X(http, log=lambda *a: None, max_posts_per_tag=10, budget_usd=5, bearer='tok', counts_every_minutes=60, counts_fetched={'#election2026': iso(NOW - timedelta(minutes=20))}, save_counts_fetched=lambda l, w: saved.__setitem__(l, w))
        rows = x.tag_days(['Election2026'], NOW, NOW - timedelta(days=7)); self.assertEqual(rows, []); self.assertEqual(http.requests, 0); self.assertEqual(x.spent, 0)
        x2 = X(http, log=lambda *a: None, max_posts_per_tag=10, budget_usd=5, bearer='tok', counts_every_minutes=60, counts_fetched={'#election2026': iso(NOW - timedelta(minutes=61))}, save_counts_fetched=lambda l, w: saved.__setitem__(l, w))
        rows = x2.tag_days(['Election2026'], NOW, NOW - timedelta(days=7)); self.assertEqual(len(rows), 7); self.assertEqual(saved, {'#election2026': iso(NOW)}); self.assertAlmostEqual(x2.spent, 0.01)

class ImportJoinTests(unittest.TestCase):
    def test_accounts_join_and_reply_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            posts = Path(d) / 'p.csv'; prof = Path(d) / 'a.csv'
            posts.write_text('post_id,handle,timestamp_utc,content_type,lang,text,link,in_reply_to,likes,reposts,replies\n'
                             'P-1,alice,2026-02-03 02:47:00,post,en,hello #t,https://e.example/x,,1,0,0\n'
                             'P-2,bob,2026-02-03 02:48:00,reply,en,@alice hi,,P-1,0,0,0\n'
                             'P-3,carol,2026-02-03 02:49:00,reply,en,hey,,@dave,0,0,0\n', encoding='utf-8')
            prof.write_text('handle,created_utc,followers,posts_total\nalice,2024-01-01 00:00:00,12,30\nbob,2026-02-01 00:00:00,0,3\n', encoding='utf-8')
            cfg = dict(tags=['t'], terms=[], days=7, db=str(Path(d) / 'c.sqlite'), report=str(Path(d) / 'r.html')); import_csv(cfg, str(posts), 'ex', log=lambda *a: None, accounts=str(prof))
            P = {p['author']: p for p in Store(cfg['db']).posts()}
            self.assertEqual(P['alice']['author_followers'], 12); self.assertEqual(P['alice']['author_posts'], 30); self.assertTrue(P['alice']['author_created_utc'].startswith('2024-01-01'))
            self.assertTrue(P['bob']['is_reply']); self.assertEqual(P['bob']['reply_to'], 'alice'); self.assertEqual(P['carol']['reply_to'], 'dave'); self.assertIsNone(P['carol']['author_followers'])

class PeakTests(unittest.TestCase):
    def _cfg(self, d, **x):
        xd = dict(enabled=True, max_posts_per_tag=4, budget_usd=5.0, query_extra=''); xd.update(x)
        return dict(tags=['Election2026'], terms=[], days=7, db=str(Path(d) / 'c.sqlite'), report=str(Path(d) / 'r.html'), pause_seconds=0,
                    sources=dict(mastodon=dict(enabled=False), bluesky=dict(enabled=False), x=xd), alert=dict(uses=200, ratio=10, min_uses=10))
    def test_read_window_is_complete_and_recorded(self):
        import topicstream.sources as S
        from topicstream.__main__ import collect, peak, buy_windows, top_hours
        fake = XFakeHttp(); orig = S.Http.get; S.Http.get = lambda self, url, headers=None, tries=4: fake.get(url, headers)
        try:
            with tempfile.TemporaryDirectory() as d:
                os.environ['X_BEARER_TOKEN'] = 'tok'; cfg = self._cfg(d); logs = []
                store = collect(cfg, log=logs.append)                                   # stores the hourly counts
                top = top_hours(store, ['#election2026'], 2); self.assertEqual(len(top), 2); self.assertTrue(top[0][2] >= top[1][2])
                self.assertEqual(buy_windows(cfg, store, top, log=logs.append, dry=True), 0)      # dry run buys nothing
                self.assertEqual(len(store.windows()), 0)
                n = buy_windows(cfg, store, top, log=logs.append); self.assertGreater(n, 0)
                w = store.windows(); self.assertEqual(len(w), 2); self.assertEqual(w[0]['got'], 4); self.assertEqual(w[0]['end_utc'][11:13], f"{(int(w[0]['start_utc'][11:13]) + 1) % 24:02d}")
                calls = [u for u in fake.calls if 'search' in u]; q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[-1]).query)
                self.assertIn('start_time', q); self.assertIn('end_time', q); self.assertNotIn('since_id', q)
                self.assertEqual(buy_windows(cfg, store, top, log=logs.append), 0)        # already complete: nothing re-bought
                self.assertTrue(any('peak' in json.loads(r['notes'] or '{}') for r in store.runs()))
                html = R.render(store, cfg, now=NOW); self.assertIn('Hours read complete on X', html); self.assertIn('First 10 minutes', html)
        finally: S.Http.get = orig; os.environ.pop('X_BEARER_TOKEN', None)
    def test_windows_section_before_any_peak(self):
        import topicstream.sources as S
        from topicstream.__main__ import collect
        fake = XFakeHttp(); orig = S.Http.get; S.Http.get = lambda self, url, headers=None, tries=4: fake.get(url, headers)
        try:
            with tempfile.TemporaryDirectory() as d:
                os.environ['X_BEARER_TOKEN'] = 'tok'; cfg = self._cfg(d); store = collect(cfg, log=lambda m: None)
                html = R.render(store, cfg, now=NOW); self.assertIn('No hour has been read complete yet', html); self.assertIn('to read in full', html)
                s2 = Store(':memory:')                                                  # an import-only database: no X counts series at all
                html = R.render(s2, dict(name='t', tags=['x'], days=7, alert={}), now=NOW); self.assertIn('This database has no X counts series', html)
        finally: S.Http.get = orig; os.environ.pop('X_BEARER_TOKEN', None)
    def test_budget_refuses_the_batch(self):
        import topicstream.sources as S
        from topicstream.__main__ import collect, buy_windows, top_hours
        fake = XFakeHttp(); orig = S.Http.get; S.Http.get = lambda self, url, headers=None, tries=4: fake.get(url, headers)
        try:
            with tempfile.TemporaryDirectory() as d:
                os.environ['X_BEARER_TOKEN'] = 'tok'; cfg = self._cfg(d, budget_usd=0.05); logs = []
                store = collect(cfg, log=logs.append); top = top_hours(store, ['#election2026'], 1)
                self.assertEqual(buy_windows(cfg, store, top, log=logs.append), 0); self.assertTrue(any('over budget' in l for l in logs))
        finally: S.Http.get = orig; os.environ.pop('X_BEARER_TOKEN', None)
    def test_on_alert_mode_reads_nothing_until_a_rule_trips(self):
        import topicstream.sources as S
        from topicstream.__main__ import collect
        fake = XFakeHttp(); orig = S.Http.get; S.Http.get = lambda self, url, headers=None, tries=4: fake.get(url, headers)
        try:
            with tempfile.TemporaryDirectory() as d:
                os.environ['X_BEARER_TOKEN'] = 'tok'; cfg = self._cfg(d, read_mode='on_alert'); logs = []
                store = collect(cfg, log=logs.append)
                n = json.loads(store.runs()[0]['notes']); self.assertEqual(n['x']['posts'], 0); self.assertAlmostEqual(n['x']['spent_usd'], 0.01)   # counts only
                # the fake's hourly series is flat (100..267 per hour, average ~183): no hour is 10x the average, none >= 200 by the first-trip rule? 267 >= 200 trips
                self.assertTrue(len(store.windows()) >= 1); self.assertTrue(any('buying' in l for l in logs))
        finally: S.Http.get = orig; os.environ.pop('X_BEARER_TOKEN', None)

class CoordinationLayerTests(unittest.TestCase):
    def mk(self, author, minutes, text, links=(), lang='en', created_days=400, followers=50, likes=0, reply=False, source='x', total=None):
        return dict(source=source, author=author, created_utc=iso(NOW + timedelta(minutes=minutes)), text=text, tags=[], matched=['#t'], links=list(links), is_repost=0, likes=likes,
                    author_created_utc=iso(NOW - timedelta(days=created_days)), author_followers=followers, lang=lang, is_reply=reply, reply_to='bigaccount' if reply else None, author_posts=total)
    def test_link_bursts_use_the_exact_url(self):
        P = [self.mk(f'a{i}', i, f'post {i}', ['https://Site.example/page?utm_campaign=rs9#x']) for i in range(4)] + [self.mk('z', 2, 'other', ['https://site.example/page'])]
        b = A.link_bursts(P, 10, 3); self.assertEqual(len(b), 1); self.assertEqual(len(b[0]['accounts']), 4); self.assertIn('utm_campaign=rs9', b[0]['link'])
    def test_paraphrase_bursts_merge_variants_and_report_exact_copies(self):
        base = 'the water in the bay has turned brown and the fishermen are reporting dead fish along the shoreline this morning'
        variants = [base, base, base.replace('this morning', 'today'), base.replace('turned brown', 'gone brown'), 'the water in the bay turned brown and fishermen report dead fish along the shoreline today']
        P = [self.mk(f'a{i}', i * 3, v) for i, v in enumerate(variants)] + [self.mk('q', 1, 'completely unrelated post about football scores and the weather tonight in town')]
        pb = A.paraphrase_bursts(P, 60, 3); self.assertEqual(len(pb), 1); self.assertEqual(len(pb[0]['accounts']), 5); self.assertEqual(pb[0]['exact'], 2); self.assertGreaterEqual(pb[0]['variants'], 3)
    def test_account_features_and_signals(self):
        P = [self.mk('replybot', i * 7, f'@x reply number {i} about the thing', reply=True, created_days=10, followers=20) for i in range(12)]
        P += [self.mk('poly', i * 90, f'post {i}', lang=['en', 'ja', 'es'][i % 3], created_days=800, followers=5000, likes=30, total=50) for i in range(9)]
        rows = {r['account']: r for r in A.account_features(P, now=NOW, burst_accounts={'poly'})}
        self.assertEqual(set(rows['replybot']['signals']), {'replies', 'no_audience', 'young', 'office_hours'})
        self.assertEqual(set(rows['poly']['signals']), {'multilingual', 'dormant_then_active', 'co_posted'})
        self.assertEqual(rows['replybot']['reply_to'], 'bigaccount')
    def test_hour_profile_band(self):
        P = [self.mk('a', 60 * h, 'x') for h in [1, 2, 3, 4, 5, 6, 7, 8, 20]]   # NOW is 20:00 UTC, so minutes shift the hour
        prof = A.hour_profile(P); self.assertEqual(sum(prof['hours']), 9); self.assertGreaterEqual(prof['band_share'], 8 / 9 - 1e-9)
    def test_creation_clusters(self):
        P = [self.mk(f'c{i}', i, 'x', created_days=100) for i in range(5)] + [self.mk(f'o{i}', i, 'x', created_days=100 + 30 * i) for i in range(1, 30)]
        cc = A.creation_clusters(P, {f'c{i}' for i in range(5)}); self.assertEqual(len(cc), 1); self.assertEqual(cc[0]['subset'], 5); self.assertGreater(cc[0]['lift'], 3)
    def test_cross_platform_and_infrastructure(self):
        P = [self.mk('a', 0, 'a long enough identical message to be matched across the two platforms here', source='x'),
             self.mk('b@m', 5, 'a long enough identical message to be matched across the two platforms here', source='mastodon'),
             self.mk('c', 0, 'x', ['https://site.example/p?utm_campaign=rs9'], source='x'), self.mk('d', 1, 'y', ['https://site.example/q?utm_campaign=rs9'], source='bluesky'),
             self.mk('e', 1, 'z', ['https://bit.ly/abc', 'https://site.example/r?utm_campaign=rs9'], source='x'), self.mk('f', 1, 'w', ['https://bit.ly/def'], source='x')]
        xp = A.cross_platform(P, 30); self.assertEqual(xp[0]['kind'], 'text'); self.assertEqual(xp[0]['sources'], ['mastodon', 'x'])
        inf = A.infrastructure(P); self.assertEqual(inf['params'][0][0], 'utm_campaign=rs9'); self.assertEqual(len(inf['params'][0][1]), 3); self.assertEqual(inf['shorteners'][0][0], 'bit.ly')
        self.assertNotIn('bit.ly', [d for d, _ in inf['domains']])                        # a shortener is not a destination
    def test_infrastructure_drops_share_buttons_and_groups_tokens(self):
        P = [self.mk(f'u{i}', i, 'v', [f'https://news.example/{i}?utm_source=twitter&utm_medium=social&feature=youtu.be']) for i in range(6)]      # six people, six share buttons
        P += [self.mk(f'r{i}', i, 'w', ['https://ex.example/token/abc?shortCode=3CaPbHA&ref=LLJIE&t=1792570550730&utm_source=okx_share']) for i in range(4)]
        inf = A.infrastructure(P); keys = [k for k, _ in inf['params']]
        self.assertEqual(len(keys), 1, keys)                                             # boilerplate gone; the four token parameters are one row
        self.assertIn('ref=LLJIE', keys[0]); self.assertIn('shortCode=3CaPbHA', keys[0]); self.assertIn('utm_source=okx_share', keys[0]); self.assertEqual(len(inf['params'][0][1]), 4)
    def test_link_share_and_reply_fallback(self):
        P = [self.mk('two', i * 60, f'post {i}', ['https://a.example/1', 'https://a.example/2']) for i in range(5)]           # two links per post is still one linking post
        P += [self.mk('legacy', i * 60, f'@someone reply {i} stored before is_reply existed') for i in range(6)]
        rows = {r['account']: r for r in A.account_features(P, now=NOW)}
        self.assertEqual(rows['two']['link_share'], 1.0); self.assertIn('one_domain', rows['two']['signals'])
        self.assertEqual(rows['legacy']['reply_share'], 1.0); self.assertIn('replies', rows['legacy']['signals'])
    def test_leading_edge(self):
        P = [self.mk(f's{i}', i, 'seed', ['https://seed.example/x']) for i in range(3)] + [self.mk(f'o{i}', 20 + i, 'organic') for i in range(10)]
        for p in P: p['matched'] = ['#t']
        le = A.leading_edge(P, dict(tag='#t', start_utc=iso(NOW), end_utc=iso(NOW + timedelta(hours=1))), 10)
        self.assertEqual(le['edge_accounts'], ['s0', 's1', 's2']); self.assertEqual(le['posts'], 13); self.assertEqual(le['edge_links'][0][0], 'seed.example')
