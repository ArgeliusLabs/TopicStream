"""0.3.4: provider end-time clamp, 4xx error text, content-only dataset hash, lazy author profiles, originals-first windows,
sampled amplifiers and the amplified-originals table. Every request is faked; nothing here touches the network."""
import io, json, os, sys, unittest, urllib.error, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topicstream.sources import X, Post, iso
from topicstream.store import Store
from topicstream import analyze as A, detection, report as R
from test_topicstream import x_search_page, stored_directory

NOW = datetime(2026, 11, 23, 19, 0, tzinfo=timezone.utc)   # after the 22 November transition: author profiles bill at the user rate


def user(k, created='2020-03-01T00:00:00.000Z', followers=88, posts=9804):
    return dict(id=f'u{k}', username=f'user{k}', created_at=created, public_metrics=dict(followers_count=followers, post_count=posts))


class FakeHttp:
    """Counts, search (with or without the author expansion), users lookup, retweeted_by, usage, and a 400 on demand."""
    def __init__(self, fail_counts_once=False): self.calls = []; self.requests = 0; self.fail = fail_counts_once
    def get(self, url, headers=None, tries=4):
        self.calls.append(url); self.requests += 1; parsed = urllib.parse.urlparse(url); q = urllib.parse.parse_qs(parsed.query); path = parsed.path
        if '/usage/' in url: return dict(data=dict(prepaid_balance=10.0, free_balance=0.0, total_balance=10.0)), {}
        if '/counts/' in url:
            if self.fail:
                self.fail = False
                body = json.dumps(dict(detail='One or more parameters to your request was invalid.', errors=[dict(message="Invalid 'end_time'. 'end_time' must be a minimum of 10 seconds prior to the request time.")])).encode()
                raise urllib.error.HTTPError(url, 400, 'Bad Request', {}, io.BytesIO(body))
            return dict(data=[dict(start=f'2026-11-2{i % 3}T00:00:00.000Z', end=f'2026-11-2{i % 3}T01:00:00.000Z', post_count=50 + i) for i in range(3)], meta={}), {}
        if path.endswith('/users'):
            ids = q['ids'][0].split(','); return dict(data=[user(i[1:]) for i in ids if i != 'u9']), {}    # u9 does not exist: fewer returned than asked
        if path.endswith('/retweeted_by'):
            n = int(q['max_results'][0]); return dict(data=[user(f'r{i}', created='2026-11-20T00:00:00.000Z', followers=0, posts=3) for i in range(n)], meta={}), {}
        page = x_search_page([1001, 1002], next_token=None)
        if 'expansions' not in q: page.pop('includes')                                   # no author objects without the expansion
        return page, {}


class ClockAndErrorTests(unittest.TestCase):
    def test_counts_end_time_is_never_the_request_time(self):
        http = FakeHttp(); x = X(http, log=lambda *a: None, bearer='tok', budget_usd=1, until=NOW)
        with patch('topicstream.xsource.utcnow', return_value=NOW):
            x._counts('haze', 'hour', NOW - timedelta(days=6), 'term')
        q = urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[-1]).query)
        self.assertEqual(q['end_time'], [iso(NOW - X.MIN_END_LAG)])
        self.assertEqual(q['query'], ['"haze"'])

    def test_provider_error_text_is_logged(self):
        logs = []; http = FakeHttp(fail_counts_once=True); x = X(http, log=logs.append, bearer='tok', budget_usd=1)
        with self.assertRaises(urllib.error.HTTPError): x._counts('haze', 'hour', NOW - timedelta(days=6), 'term')
        self.assertTrue(any('HTTP 400' in l and 'minimum of 10 seconds' in l for l in logs), logs)


class DatasetHashTests(unittest.TestCase):
    def rows(self, collected, likes, text='the same words'):
        return [dict(source='x', instance='api.x.com', post_id='1', key='x:1', created_utc='2026-11-18T13:00:00Z', author='a', author_id='u1', text=text, lang='in',
                     is_repost=0, is_reply=0, reply_to=None, reference_type=None, referenced_post_id=None, original_author=None, matched=['komdigi'], tags=[], links=[],
                     collected_utc=collected, likes=likes, reposts=0, replies=0, author_created_utc=None, author_followers=None, author_posts=None, url=None, author_uri=None)]
    def test_same_records_same_hash_whenever_imported(self):
        self.assertEqual(detection.dataset_hash(self.rows('2026-11-23T10:00:00Z', 0)), detection.dataset_hash(self.rows('2026-11-24T08:00:00Z', 13122)))
        self.assertNotEqual(detection.dataset_hash(self.rows('2026-11-23T10:00:00Z', 0)), detection.dataset_hash(self.rows('2026-11-23T10:00:00Z', 0, text='other words')))
    def test_analyze_uses_the_content_hash(self):
        a = detection.analyze(self.rows('2026-11-23T10:00:00Z', 0) * 1); b = detection.analyze(self.rows('2026-12-01T00:00:00Z', 5))
        self.assertEqual(a['dataset_hash'], b['dataset_hash'])


class LazyProfileTests(unittest.TestCase):
    def test_search_pages_carry_no_expansion_and_cost_the_post_rate_only(self):
        with Store(':memory:') as s, patch('topicstream.xsource.utcnow', return_value=NOW):
            http = FakeHttp(); x = X(http, log=lambda *a: None, store=s, bearer='tok', budget_usd=1, max_posts_per_tag=10)
            self.assertEqual(x.author_profiles, 'lazy'); self.assertAlmostEqual(x.search_unit_price(), 0.005)
            posts = x.posts(['t'], [], NOW - timedelta(days=1), NOW)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[-1]).query)
            self.assertNotIn('expansions', q); self.assertNotIn('user.fields', q)
            self.assertEqual(len(posts), 2); self.assertEqual(posts[0].author, 'u2')                    # the id stands in for the handle until a profile is bought
            self.assertIsNone(posts[0].author_created_utc)
            self.assertAlmostEqual(s.spent(), 0.01); self.assertEqual(s.ledger()[0]['reserved_micros'], 50000)   # ten posts reserved at $0.005, no author charge
    def test_always_mode_still_reserves_and_settles_authors(self):
        with Store(':memory:') as s, patch('topicstream.xsource.utcnow', return_value=NOW):
            x = X(FakeHttp(), log=lambda *a: None, store=s, bearer='tok', budget_usd=1, max_posts_per_tag=10, author_profiles='always')
            x.posts(['t'], [], NOW - timedelta(days=1), NOW)
            self.assertEqual(s.ledger()[0]['reserved_micros'], 150000); self.assertAlmostEqual(s.spent(), 0.01 + 0.02)   # two posts, two authors
    def test_profiles_are_bought_per_id_and_written_onto_posts(self):
        with Store(':memory:') as s, patch('topicstream.xsource.utcnow', return_value=NOW):
            http = FakeHttp(); x = X(http, log=lambda *a: None, store=s, bearer='tok', budget_usd=1, max_posts_per_tag=10)
            x.posts(['t'], [], NOW - timedelta(days=1), NOW)
            need = s.accounts_without_profile(['u1', 'u2', 'u9']); self.assertEqual(need, ['u1', 'u2', 'u9'])
            got = x.lookup_profiles(need); self.assertEqual([g['handle'] for g in got], ['user1', 'user2'])
            ledger = s.ledger()[-1]; self.assertEqual(ledger['reserved_micros'], 30000); self.assertEqual(ledger['charged_micros'], 20000)   # three asked, two returned
            n = s.apply_profiles(got, iso(NOW)); self.assertEqual(n, 2)
            by = {p['author_id']: p for p in s.posts()}                                        # the fake's two posts are by u2 and u0
            self.assertEqual(by['u2']['author'], 'user2'); self.assertEqual(by['u2']['author_followers'], 88); self.assertTrue(by['u2']['author_created_utc'].startswith('2020-03-01'))
            self.assertEqual(by['u0']['author'], 'u0')                                             # not asked for: still the id
            self.assertEqual(s.accounts_without_profile(['u1', 'u2']), [])
            x.lookup_profiles(['u1']); self.assertEqual(s.ledger()[-1]['charged_micros'], 0)                  # same profile, same UTC day: deduplicated
    def test_never_mode_refuses_nothing_but_buys_no_profile(self):
        x = X(FakeHttp(), log=lambda *a: None, bearer='tok', budget_usd=1, author_profiles='never')
        self.assertAlmostEqual(x.search_unit_price(), 0.005)
        with self.assertRaises(ValueError): X(FakeHttp(), bearer='tok', author_profiles='sometimes')


class OriginalsFirstTests(unittest.TestCase):
    def test_window_read_excludes_reposts_by_default_and_records_its_own_fingerprint(self):
        with Store(':memory:') as s, patch('topicstream.xsource.utcnow', return_value=NOW):
            http = FakeHttp(); x = X(http, log=lambda *a: None, store=s, bearer='tok', budget_usd=1, reposts='exclude')
            t0 = NOW - timedelta(hours=3); posts = x.read_window('komdigi', 'term', t0, t0 + timedelta(hours=1), [], ['komdigi'], NOW)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[-1]).query)
            self.assertEqual(q['query'], ['"komdigi" -is:retweet']); self.assertEqual(x.query_extra, '')        # the extra is only for the window
            self.assertEqual(x.last_window['reposts'], 'exclude'); self.assertEqual(s.coverage()[-1]['sampling'], 'originals only')
            self.assertNotEqual(x.window_fingerprint('komdigi', 'term', t0, NOW), X(None, reposts='include').window_fingerprint('komdigi', 'term', t0, NOW))
            inc = X(http, log=lambda *a: None, store=s, bearer='tok', budget_usd=1, reposts='include')
            inc.read_window('komdigi', 'term', t0, t0 + timedelta(hours=1), [], ['komdigi'], NOW)
            self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlparse(http.calls[-1]).query)['query'], ['"komdigi"'])
    def test_sample_caps_the_read_and_says_so(self):
        with Store(':memory:') as s, patch('topicstream.xsource.utcnow', return_value=NOW):
            x = X(FakeHttp(), log=lambda *a: None, store=s, bearer='tok', budget_usd=1)
            t0 = NOW - timedelta(hours=3); posts = x.read_window('komdigi', 'term', t0, t0 + timedelta(hours=1), [], ['komdigi'], NOW, sample=1)
            self.assertEqual(len(posts), 2)                                                    # the API minimum page is ten; the sample label is what changes
            self.assertEqual(s.coverage()[-1]['sampling'], 'originals only, first 1 (sample)')
    def test_amplifiers_are_sampled_priced_and_stored(self):
        with Store(':memory:') as s, patch('topicstream.xsource.utcnow', return_value=NOW):
            x = X(FakeHttp(), log=lambda *a: None, store=s, bearer='tok', budget_usd=1)
            got = x.amplifiers('555', sample=5); self.assertEqual(len(got), 5)
            self.assertEqual(s.ledger()[-1]['reserved_micros'], 50000); self.assertEqual(s.ledger()[-1]['charged_micros'], 50000)
            s.add_amplifiers('555', got, 5, iso(NOW)); amp = s.amplifiers(); self.assertEqual(len(amp['555']), 5); self.assertEqual(amp['555'][0]['followers'], 0)
            with self.assertRaises(Exception): X(FakeHttp(), log=lambda *a: None, store=s, bearer='tok', budget_usd=0.01).amplifiers('555', sample=5)   # the cap holds here too


class AmplifiedOriginalsTests(unittest.TestCase):
    def mk(self, pid, author, text, minutes, rt_of=None, reposts=0, created='2020-01-01T00:00:00Z', followers=50, author_id=None):
        return dict(source='x', instance='api.x.com', post_id=pid, key='x:' + pid, created_utc=iso(NOW + timedelta(minutes=minutes)), author=author, author_id=author_id or 'id_' + author,
                    text=text, lang='in', is_repost=bool(rt_of), reposts=reposts, likes=0, replies=0, matched=['komdigi'], tags=[], links=[], is_reply=0, reply_to=None,
                    reference_type='repost' if rt_of else None, referenced_post_id=rt_of, original_author=None, author_created_utc=created, author_followers=followers, author_posts=100, url=None, author_uri=None)
    def test_table_from_reposts_and_from_originals(self):
        posts = [self.mk('1', 'IDLIXsupport', 'DOMAIN BARU IDLIX', 0, reposts=13122)]
        posts += [self.mk(f'r{i}', f'fan{i}', 'RT @IDLIXsupport: DOMAIN BARU IDLIX', i, rt_of='1', reposts=13122, created='2026-11-20T00:00:00Z' if i < 2 else '2019-05-05T00:00:00Z', followers=0 if i < 3 else 88) for i in range(12)]
        posts += [self.mk('2', 'foolinsights', 'KOMDIGI SIALAN', 5, reposts=23341)]
        posts += [self.mk('x', 'someone', 'quiet post', 9, reposts=1)]
        rows = A.amplified_originals(posts, {}, max_event_accounts=10)
        self.assertEqual([r['author'] for r in rows][:2], ['foolinsights', 'IDLIXsupport'])                 # ranked by the platform's own repost count
        idlix = rows[1]; self.assertEqual(idlix['captured'], 12); self.assertEqual(idlix['accounts'], 12); self.assertTrue(idlix['skipped_by_detector'])
        self.assertEqual(idlix['cohort']['known'], 12); self.assertEqual(idlix['cohort']['under_30_days'], 2); self.assertEqual(idlix['cohort']['zero_followers'], 3)
        self.assertEqual(rows[0]['captured'], 0); self.assertTrue(rows[0]['in_scope'])
        self.assertFalse(any(r['author'] == 'someone' for r in rows))
    def test_report_renders_the_section_with_sampled_profiles(self):
        with stored_directory() as d:
            cfg = dict(name='t', tags=[], terms=['komdigi'], days=7, start_utc=iso(NOW - timedelta(days=1)), end_utc=iso(NOW + timedelta(days=1)), db=str(Path(d) / 'c.sqlite'), report=str(Path(d) / 'r.html'),
                       sources=dict(mastodon=dict(enabled=False), bluesky=dict(enabled=False), x=dict(enabled=True)))
            with Store(cfg['db']) as s:
                s.add_posts([Post(source='x', instance='api.x.com', post_id='1', created_utc=iso(NOW), author='IDLIXsupport', author_id='o1', author_created_utc='2018-01-01T00:00:00Z', text='DOMAIN BARU IDLIX komdigi', reposts=13122, matched=['komdigi'], collected_utc=iso(NOW)),
                             Post(source='x', instance='api.x.com', post_id='2', created_utc=iso(NOW), author='9876', author_id='9876', text='RT @IDLIXsupport: DOMAIN BARU IDLIX komdigi', is_repost=True, reference_type='repost', referenced_post_id='1', reposts=13122, matched=['komdigi'], collected_utc=iso(NOW))])
                s.add_amplifiers('1', [dict(author_id=f'r{i}', handle=f'fan{i}', created_utc='2019-05-05T00:00:00Z', followers=88, posts_total=9804) for i in range(3)], 3, iso(NOW))
                html = R.render(s, cfg, now=NOW + timedelta(hours=1))
            self.assertIn('Amplified originals', html); self.assertIn('@IDLIXsupport', html); self.assertIn('13,122', html)
            self.assertIn('3 profiles', html); self.assertIn('3 sampled', html); self.assertIn('Sampled reposters: post 1: 3 of 3 asked', html)
            self.assertIn('Author profiles are known for 1 of 2 X accounts', html)


if __name__ == '__main__': unittest.main()
