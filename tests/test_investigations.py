"""Offline behavior, storage-failure, and HTTP workflow regressions."""
import copy
import csv
import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from topicstream import analyze as A, detection, report
from topicstream.cases import Cases, plan_topic, validated_config
from topicstream.identity import account_key, digest, normalized_url, post_key
from topicstream.monitor import count_alerts
from topicstream.scope import complete_coverage, covers_burst, selected_posts
from topicstream.sources import Post, X, iso, parse_time, Mastodon, Bluesky, Http, html_links
from topicstream.store import Store, BudgetExceeded, SCHEMA
from topicstream.web import make_server
from test_topicstream import x_search_page, NOW, mast_status, FakeHttp


def row(account, day, minute=0, text=None, source='x'):
    p=Post(source,source,f'{account}-{day}-{minute}',iso(NOW-timedelta(days=7)+timedelta(days=day,minutes=minute)),
           account,text or f'Public water quality briefing day {day}; the full assessment and supporting source documents are available.',
           author_id=account,matched=['water quality'],links=[f'https://example.org/{day}'],collected_utc=iso(NOW))
    return dict(asdict(p),key=p.key)


def coordinated(): return [row(f'a{i}',day,i) for day in (1,3,5) for i in range(4)]


class ReplayHttp:
    def __init__(self,*pages): self.pages=list(pages); self.calls=[]
    def get(self,url,headers=None):
        self.calls.append(url); result=self.pages.pop(0)
        if isinstance(result,Exception): raise result
        return result,{}


class IdentityAndScopeTests(unittest.TestCase):
    def test_identity_separates_platforms_and_preserves_handle_changes(self):
        p=row('a',1); changed=dict(p,author='renamed')
        self.assertEqual(account_key(p),account_key(changed))
        self.assertNotEqual(account_key(p),account_key(dict(p,source='bluesky')))
        m=dict(p,source='mastodon',author='alice',author_id='1',instance='one.example')
        self.assertNotEqual(account_key(m),account_key(dict(m,instance='two.example')))
        self.assertEqual(account_key(dict(m,author_uri='https://origin/users/a')),account_key(dict(m,instance='two',author_id='99',author_uri='https://origin/users/a')))

    def test_url_case_is_not_lost(self):
        self.assertEqual(normalized_url('HTTPS://EXAMPLE.COM:443/Case?Token=AB#x'),'https://example.com/Case?Token=AB')
        self.assertNotEqual(normalized_url('https://x/a?c=A'),normalized_url('https://x/a?c=a'))
        self.assertEqual(normalized_url('javascript:alert(1)'),'')
        self.assertEqual(normalized_url('https://user:password@x/a'),'')

    def test_naive_csv_times_are_utc_and_offsets_preserved(self):
        self.assertEqual(iso(parse_time('2026-01-01 01:00:00')),'2026-01-01T01:00:00Z')
        self.assertEqual(iso(parse_time('2026-01-01T01:00:00-07:00')),'2026-01-01T08:00:00Z')

    def test_mastodon_boost_actor_and_original_target_are_separate(self):
        original=mast_status(1,'original','Read #t',iso(NOW))
        boost=dict(original,id='500',uri='https://one/boost/500',reblog=original,
                   account=dict(id='55',acct='amplifier',uri='https://one/users/amplifier'))
        source=Mastodon(['one'],FakeHttp([[boost]]),max_pages=1,log=lambda *a:None)
        post=source.posts(['t'],[],NOW-timedelta(days=1),NOW)[0]
        self.assertEqual(post.author,'amplifier'); self.assertEqual(post.original_author,'original')
        self.assertEqual(post.referenced_post_id,original['uri']); self.assertNotEqual(post.post_id,original['uri'])
        self.assertEqual(html_links('<a href="https://x/Case">truncated...</a>'),['https://x/Case'])

    def test_selected_posts_obey_time_topic_exclusion_language(self):
        with Store(':memory:') as store:
            for p in [row('a',1),row('b',3),row('c',5),dict(row('d',3),text='excluded water quality'),dict(row('e',3),lang='es')]:
                p.pop('key'); p['lang']=p['lang'] or 'en'; store.add_posts([Post(**p)])
            cfg={'tags':[],'terms':['water quality'],'start_utc':row('x',2)['created_utc'],'end_utc':row('x',4)['created_utc'],'exclude_terms':['excluded'],'languages':['en']}
            rows,_,_=selected_posts(store,cfg)
            self.assertEqual([p['author'] for p in rows],['b'])

    def test_complete_coverage_needs_all_queries_and_no_gaps(self):
        scope={'start_utc':iso(NOW-timedelta(hours=2)),'end_utc':iso(NOW),'expected_queries':[{'source':'x','label':'q','query_hash':'current'}]}
        c={'source':'x','label':'q','query_hash':'current','start_utc':scope['start_utc'],'end_utc':scope['end_utc'],'status':'exhausted','sampling':'bounded search'}
        self.assertTrue(complete_coverage([c],scope))
        for change in ({'query_hash':'old'},{'status':'partial'},{'sampling':'newest-first quota sample'},{'start_utc':iso(NOW-timedelta(hours=1))}):
            self.assertFalse(complete_coverage([dict(c,**change)],scope))
        self.assertFalse(complete_coverage([c],dict(scope,expected_queries=scope['expected_queries']+[{'source':'bluesky','label':'q','query_hash':''}])))

    def test_burst_coverage_checks_full_interval_source_and_term(self):
        b={'start':iso(NOW),'end':iso(NOW+timedelta(minutes=12)),'sources':['x'],'matched':['q']}
        w={'source':'x','tag':'q','start_utc':iso(NOW),'end_utc':iso(NOW+timedelta(minutes=10)),'status':'exhausted','query_hash':'v1'}
        self.assertFalse(covers_burst(b,[w]))
        w['end_utc']=iso(NOW+timedelta(hours=1)); self.assertTrue(covers_burst(b,[w],{'v1'}))
        self.assertFalse(covers_burst(b,[w],{'v2'})); self.assertFalse(covers_burst(dict(b,sources=['x','bluesky']),[w]))


class LedgerAndResumeTests(unittest.TestCase):
    def test_author_expansion_budget_is_checked_before_http(self):
        with Store(':memory:') as store:
            http=ReplayHttp()
            x=X(http,store=store,bearer='tok',budget_usd=.10,max_posts_per_tag=10)
            with self.assertRaises(BudgetExceeded): x.posts(['t'],[],NOW-timedelta(days=1),NOW)
            self.assertEqual(http.calls,[]); self.assertEqual(store.spent(),0)

    def test_search_settles_returned_posts_and_author_profiles(self):
        page=x_search_page([1,4])  # Two posts by one author, one expanded profile.
        with Store(':memory:') as store:
            x=X(ReplayHttp(page),store=store,bearer='tok',budget_usd=1,max_posts_per_tag=10,log=lambda *a:None)
            x.posts(['t'],[],NOW-timedelta(days=1),NOW)
            self.assertAlmostEqual(store.spent(),.02)
            self.assertEqual(store.ledger()[0]['reserved_micros'],150000)

    def test_uncertain_search_retains_post_and_profile_reservation(self):
        with Store(':memory:') as store:
            x=X(ReplayHttp(TimeoutError('network')),store=store,bearer='tok',budget_usd=1,max_posts_per_tag=10)
            with self.assertRaises(TimeoutError): x.posts(['t'],[],NOW-timedelta(days=1),NOW)
            self.assertAlmostEqual(store.spent(),.15)

    def test_unpriced_expansions_are_rejected_before_http(self):
        http=ReplayHttp(); x=X(http,bearer='tok')
        with self.assertRaises(ValueError): x._get(x._ep('search'),{'max_results':10,'expansions':'referenced_tweets.id'})
        self.assertEqual(http.calls,[])

    def test_store_failure_does_not_save_advanced_cursor_without_posts(self):
        with Store(':memory:') as store:
            original=store.save_page
            def fail_data_page(source,key,state,posts):
                if posts: raise sqlite3.OperationalError('disk failure')
                original(source,key,state,posts)
            with patch.object(store,'save_page',fail_data_page):
                x=X(ReplayHttp(x_search_page([1,2],'older')),store=store,bearer='tok',budget_usd=1,max_posts_per_tag=2,log=lambda *a:None)
                with self.assertRaises(sqlite3.OperationalError): x.posts(['Election2026'],[],NOW-timedelta(days=1),NOW)
            self.assertEqual(store.posts(),[])
            state=json.loads(store.db.execute("SELECT state FROM checkpoints WHERE source='x-search'").fetchone()[0])
            self.assertIsNone(state['next_token']); self.assertEqual(state['got'],0); self.assertIsNone(state['newest'])

    def test_field_compatibility_retry_is_separately_reserved(self):
        error=urllib.error.HTTPError('https://api.x.com',400,'Bad Request',{},io.BytesIO(b'Use post.fields'))
        with Store(':memory:') as store:
            http=ReplayHttp(error,x_search_page([1]))
            x=X(http,store=store,bearer='tok',budget_usd=1,max_posts_per_tag=10,log=lambda *a:None)
            x.posts(['Election2026'],[],NOW-timedelta(days=1),NOW)
            self.assertEqual(len(store.ledger()),2); self.assertEqual(store.ledger()[0]['status'],'uncertain')
            self.assertIn('post.fields=',http.calls[-1]); self.assertAlmostEqual(store.spent(),.165)

    def test_api_error_payload_never_exhausts_coverage(self):
        with Store(':memory:') as store:
            x=X(ReplayHttp({'errors':[{'detail':'partial response'}]}),store=store,bearer='tok',budget_usd=2,log=lambda *a:None)
            with self.assertRaises(RuntimeError): x.posts(['Election2026'],[],NOW-timedelta(days=1),NOW)
            self.assertEqual(store.coverage()[0]['status'],'partial')

    def test_current_x_reference_names_are_retained(self):
        page=x_search_page([1],rt=True); p=page['data'][0]
        p['referenced_posts']=p.pop('referenced_tweets'); p['public_metrics']['repost_count']=8
        parsed=X(None)._parse(page,['Election2026'],[],NOW)[0]
        self.assertTrue(parsed.is_repost); self.assertEqual(parsed.reference_type,'repost'); self.assertEqual(parsed.reposts,8)

    def test_reservation_survives_restart_and_guards_before_http(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'c.sqlite'
            with Store(db) as s: s.reserve_request('x','counts','q',.01,.01,iso(NOW))
            with Store(db) as s:
                http=ReplayHttp(); x=X(http,store=s,bearer='tok',budget_usd=.01)
                with self.assertRaises(BudgetExceeded): x._counts('q','hour',NOW-timedelta(days=1))
                self.assertEqual(http.calls,[]); self.assertEqual(s.spent(),.01)

    def test_concurrent_reservations_cannot_exceed_budget(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'c.sqlite'
            with Store(db): pass
            results=[]; barrier=threading.Barrier(2)
            def reserve():
                with Store(db) as store:
                    barrier.wait()
                    try: store.reserve_request('x','search','q',.05,.05,iso(NOW)); results.append('reserved')
                    except BudgetExceeded: results.append('refused')
            threads=[threading.Thread(target=reserve) for _ in range(2)]
            for t in threads: t.start()
            for t in threads: t.join(timeout=5); self.assertFalse(t.is_alive())
            self.assertCountEqual(results,['reserved','refused'])

    def test_failed_request_retains_uncertain_charge(self):
        with Store(':memory:') as store:
            x=X(ReplayHttp(TimeoutError('network')),store=store,bearer='tok',budget_usd=1)
            with self.assertRaises(TimeoutError): x._counts('q','hour',NOW)
            self.assertEqual(store.ledger()[0]['status'],'uncertain'); self.assertEqual(store.spent(),.005)

    def test_page_and_checkpoint_rollback_together(self):
        with Store(':memory:') as store:
            p=row('a',1); p.pop('key')
            with self.assertRaises(AttributeError): store.save_page('x','q',{'next_token':'next'},[Post(**p),object()])
            self.assertEqual(store.posts(),[]); self.assertEqual(store.checkpoint('x','q'),{})

    def test_capped_window_resumes_after_restart_without_advancing(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'c.sqlite'; start=NOW-timedelta(days=1); end=NOW-timedelta(hours=1)
            with Store(db) as store:
                x=X(ReplayHttp(x_search_page([1,2],'older')),store=store,bearer='tok',budget_usd=2,log=lambda *a:None)
                x.read_window('Election2026','tag',start,end,['Election2026'],[],NOW,cap=2)
                self.assertEqual(x.last_window['status'],'partial'); self.assertEqual(store.coverage()[0]['status'],'partial')
            with Store(db) as store:
                http=ReplayHttp(x_search_page([3,4])); x=X(http,store=store,bearer='tok',budget_usd=2,log=lambda *a:None)
                x.read_window('Election2026','tag',start,end,['Election2026'],[],NOW,cap=2)
                self.assertIn('next_token=older',http.calls[0]); self.assertEqual(len(store.posts()),4)
                self.assertEqual(x.last_window['status'],'exhausted'); self.assertEqual(x.last_window['got'],4)
                self.assertEqual(store.coverage()[0]['status'],'exhausted')

    def test_failure_on_second_page_preserves_first_page_and_retry_token(self):
        with Store(':memory:') as store:
            http=ReplayHttp(x_search_page([1,2],'older'),TimeoutError('interrupted'))
            x=X(http,store=store,bearer='tok',budget_usd=2,log=lambda *a:None,max_posts_per_tag=10)
            with self.assertRaises(TimeoutError): x.posts(['Election2026'],[],NOW-timedelta(days=1),NOW)
            self.assertEqual(len(store.posts()),2); self.assertEqual(x.last_window['next_token'],'older')
            self.assertEqual(x.cursors,{})

    def test_changed_query_and_fixed_scope_do_not_reuse_old_checkpoint(self):
        with Store(':memory:') as store:
            for extra,scope in [('', 'one'),('lang:en','one'),('lang:en','two')]:
                http=ReplayHttp(x_search_page([1,2]))
                x=X(http,store=store,bearer='tok',budget_usd=3,log=lambda *a:None,query_extra=extra,scope_key=scope)
                x.posts(['Election2026'],[],NOW-timedelta(days=1),NOW)
                self.assertEqual(len(http.calls),1)
            self.assertEqual(store.db.execute("SELECT count(*) FROM checkpoints WHERE source='x-search'").fetchone()[0],3)

    def test_legacy_windows_and_spend_migrate_conservatively(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'legacy.sqlite'
            with sqlite3.connect(db) as con:
                con.executescript(SCHEMA)
                con.execute('INSERT INTO windows VALUES (?,?,?,?,?,?,?)',('x','#t',iso(NOW),iso(NOW+timedelta(hours=1)),100,100,iso(NOW)))
                con.execute('INSERT INTO runs(started_utc,notes) VALUES (?,?)',(iso(NOW),json.dumps({'x':{'spent_usd':.5}})))
            con.close()
            with Store(db) as store:
                self.assertEqual(store.windows()[0]['status'],'unverified'); self.assertEqual(store.spent(),.5)
            with Store(db) as store: self.assertEqual(store.spent(),.5)

    def test_query_versions_are_retained_and_edits_snapshotted(self):
        with Store(':memory:') as store:
            store.add_counts('x',[('t',iso(NOW),1)],iso(NOW),'old')
            store.add_counts('x',[('t',iso(NOW),2)],iso(NOW),'new')
            self.assertEqual(len(store.counts()),2)
            p=row('a',1); p.pop('key'); obj=Post(**p); store.add_posts([obj]); obj.text='edited'; store.add_posts([obj])
            self.assertEqual(store.posts()[0]['text'],'edited')
            self.assertEqual(store.db.execute('SELECT count(*) FROM post_snapshots').fetchone()[0],2)


class DetectionTests(unittest.TestCase):
    def test_hour_comparison_uses_same_band_for_both_populations(self):
        early=[dict(row('early',1,i),created_utc=iso(NOW.replace(hour=1)+timedelta(minutes=i))) for i in range(10)]
        late=[dict(row('late',1,i),created_utc=iso(NOW.replace(hour=13)+timedelta(minutes=i))) for i in range(90)]
        comparison=A.hour_comparison(early+late,{'x:id:early'})
        self.assertEqual(comparison['band_share'],1)
        self.assertEqual(comparison['all_share'],.1)
        self.assertEqual(A.hour_profile(early+late)['band_share'],.9)

    def test_recurring_group_retains_edge_and_post_evidence(self):
        result=detection.analyze(coordinated())
        self.assertEqual(len(result['groups']),1); group=result['groups'][0]
        self.assertEqual(len(group['accounts']),4); self.assertEqual(len(group['edges']),6)
        self.assertTrue(all(e['episodes']==3 for e in group['edges']))
        self.assertEqual(set(group['post_keys']),{p['key'] for p in coordinated()})
        self.assertEqual(result['authenticity'],'Unresolved; public behavior alone does not establish deception')

    def test_one_viral_event_is_not_recurring_coordination(self):
        result=detection.analyze([row(f'a{i}',1,i) for i in range(50)])
        self.assertEqual(result['groups'],[]); self.assertIn('Insufficient evidence',result['assessment'])

    def test_independent_daily_posts_do_not_form_group(self):
        posts=[row(f'a{i}',day,90*i,text=f'Independent topic number {i} author-specific wording day {day}') for day in (1,3,5) for i in range(10)]
        self.assertEqual(detection.analyze(posts)['groups'],[])

    def test_text_and_link_at_same_time_are_one_episode(self):
        result=detection.analyze([row(f'a{i}',day,i) for day in (1,3) for i in range(4)])
        self.assertEqual(result['groups'],[])

    def test_repeated_amplification_is_an_independent_trace(self):
        posts=[dict(p,is_repost=True,reference_type='repost',referenced_post_id='target-'+p['created_utc'][:10]) for p in coordinated()]
        result=detection.analyze(posts)
        self.assertEqual(result['groups'][0]['families'],['amplification'])

    def test_shuffled_comparison_is_deterministic(self):
        a=detection.analyze(coordinated()); b=detection.analyze(list(reversed(coordinated())))
        self.assertEqual(a['dataset_hash'],b['dataset_hash']); self.assertEqual(a['baseline'],b['baseline'])
        self.assertIn('Not a p-value',a['baseline']['limitation'])

    def test_truncation_and_high_volume_are_disclosed(self):
        a=detection.analyze(coordinated(),config={'max_posts':5})
        self.assertTrue(a['limits']['truncated_posts']); self.assertIn('Insufficient evidence',a['assessment'])
        a=detection.analyze(coordinated(),config={'max_event_accounts':3})
        self.assertGreater(a['limits']['high_volume_events_not_compared'],0)

    def test_201_exact_copies_remain_visible(self):
        posts=[row(f'a{i}',1,0) for i in range(201)]
        bursts=A.paraphrase_bursts(posts,60,3)
        self.assertEqual(len(bursts),1); self.assertEqual(len(bursts[0]['accounts']),201)

    def test_monitor_alerts_later_episodes(self):
        rows=[{'source':'x','tag':'t','start_utc':iso(NOW-timedelta(hours=24-i)),'uses':500 if i in (9,19) else 1} for i in range(24)]
        alerts=count_alerts(rows,NOW,200,10,10)
        self.assertEqual([a['uses'] for a in alerts],[500,500])


class CaseTests(unittest.TestCase):
    def test_bluesky_has_required_query_and_persists_page_before_failure(self):
        page={'posts':[{'uri':'at://did:plc:a/app.bsky.feed.post/1','author':{'did':'did:plc:a','handle':'a.bsky.social'},'record':{'text':'water quality #harbor','createdAt':iso(NOW),'facets':[{'features':[{'$type':'app.bsky.richtext.facet#link','uri':'https://example.org/Case'}]}]}}],'cursor':'next'}
        saved=[]; http=ReplayHttp(page,TimeoutError('interrupted'))
        b=Bluesky(http,handle='a',app_password='test',on_page=lambda rows:saved.extend(rows),until=NOW,log=lambda *a:None); b.jwt='mock'
        with self.assertRaises(TimeoutError): b.posts(['harbor'],[],NOW-timedelta(days=1),NOW)
        self.assertIn('q=%23harbor',http.calls[0]); self.assertIn('until=',http.calls[0]); self.assertEqual(len(saved),1)
        self.assertEqual(saved[0].links,['https://example.org/Case'])

    def test_cancellation_prevents_another_http_request(self):
        with patch('urllib.request.urlopen') as opened:
            with self.assertRaises(RuntimeError): Http(cancelled=lambda:True).get('https://example.org')
            opened.assert_not_called()

    def test_topic_plan_keeps_phrases_alongside_hashtags(self):
        plan=plan_topic('Investigate #Harbor water quality')
        self.assertEqual(plan['tags'],['harbor']); self.assertEqual(plan['terms'],['water quality'])

    def test_demo_review_and_immutable_export(self):
        with tempfile.TemporaryDirectory() as d:
            cases=Cases(d)
            try:
                case_id=cases.demo()['id']; cases.futures[case_id].result(timeout=15)
                detail=cases.detail(case_id); self.assertEqual(detail['job']['status'],'finished',detail['job'])
                self.assertTrue(detail['case']['synthetic']); self.assertEqual(detail['spent_usd'],0)
                self.assertIn('invented accounts and posts',(cases.folder(case_id)/'report.html').read_text(encoding='utf-8'))
                result=detail['analysis']; self.assertEqual(len(result['groups']),1)
                group=result['groups'][0]; evidence=cases.evidence(case_id,group['id'])
                body={'dataset_hash':result['dataset_hash'],'group_id':group['id'],'assessment':'suspected inauthenticity','explanation':'Synthetic test','evidence':[]}
                with self.assertRaises(ValueError): cases.review(case_id,body)
                body.update(assessment='legitimate explanation',explanation='Known synthetic example',evidence=[group['post_keys'][0]])
                cases.review(case_id,body)
                self.assertIn('Known synthetic example',(cases.folder(case_id)/'report.html').read_text(encoding='utf-8'))
                with Store(cases.config(case_id)['db']) as store:
                    store.db.execute("UPDATE posts SET text='changed later'"); store.db.commit()
                self.assertNotIn('changed later',[p['text'] for p in cases.evidence(case_id,group['id'])['posts']])
                export=cases.export(case_id); self.assertEqual(len(export['evidence_posts']),185)
                self.assertEqual(len(export['reviews']),1)
                body['dataset_hash']='old'
                with self.assertRaises(ValueError): cases.review(case_id,body)
            finally: cases.close()

    def test_csv_validation_scope_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            cases=Cases(d)
            try:
                detail=cases.create({'topic':'water quality','sources':[],'start_utc':'2026-01-01','end_utc':'2026-01-03'})
                case_id=detail['case']['id']
                with self.assertRaises(ValueError): cases.import_text(case_id,'timestamp_utc,handle,text\nbad,a,water quality')
                self.assertEqual(cases.detail(case_id)['posts'],0)
                cases.import_text(case_id,'timestamp_utc,handle,text,author_id\n2026-01-02,a,water quality,stable\n2026-02-01,b,water quality,other\n')
                cases.futures[case_id].result(timeout=10)
                self.assertEqual(cases.detail(case_id)['posts'],1)
                self.assertIn('Insufficient evidence',cases.detail(case_id)['analysis']['assessment'])
                with self.assertRaises(ValueError): cases.folder('../escape')
                (cases.folder(case_id)/'job.json').write_text(json.dumps({'status':'running'}),encoding='utf-8')
            finally: cases.close()
            reopened=Cases(d)
            try: self.assertEqual(reopened.detail(case_id)['job']['status'],'interrupted')
            finally: reopened.close()

    def test_report_escapes_untrusted_content(self):
        with Store(':memory:') as store:
            for p in coordinated():
                p.pop('key'); p['text']='<script>alert(1)</script> water quality repeating same sufficiently long content'; p['url']='javascript:alert(1)'; store.add_posts([Post(**p)])
            html=report.render(store,{'name':'<img onerror=bad>','tags':[],'terms':['water quality'],'days':7},now=NOW)
            self.assertNotIn('<script>',html); self.assertNotIn('href="javascript:',html); self.assertIn('&lt;script&gt;',html)

    def test_report_preserves_export_wording_and_bar_width(self):
        with Store(':memory:') as store:
            for p in coordinated():
                p.pop('key'); p['source']='import'; store.add_posts([Post(**p)])
            html=report.render(store,{'name':'Imported example','tags':[],'terms':['water quality'],'days':7},now=NOW)
            self.assertIn('Imported export (import)',html); self.assertIn('Export: 2026-10-29 to 2026-11-02',html)
            self.assertIn('Export depth',html); self.assertIn('max-width:72px',html); self.assertNotIn('max_pages',html)

    def test_http_case_flow_and_cross_origin_protection(self):
        with tempfile.TemporaryDirectory() as d:
            server=make_server(d,0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def get(path):
                with urllib.request.urlopen(base+path,timeout=5) as r: return json.load(r)
            def post(path,body,token='',origin=None):
                headers={'Content-Type':'application/json','X-TopicStream-Token':token}
                if origin: headers['Origin']=origin
                req=urllib.request.Request(base+path,json.dumps(body).encode(),headers,method='POST')
                with urllib.request.urlopen(req,timeout=5) as r: return json.load(r)
            try:
                token=get('/api/session')['token']
                with self.assertRaises(urllib.error.HTTPError) as error: post('/api/cases',{'topic':'test'})
                self.assertEqual(error.exception.code,403)
                with self.assertRaises(urllib.error.HTTPError) as error: post('/api/plan',{'topic':'test'},token,'https://evil.example')
                self.assertEqual(error.exception.code,403)
                plan=post('/api/plan',{'topic':'Investigate #Harbor'},token); self.assertEqual(plan['tags'],['harbor'])
                case=post('/api/cases',{'topic':'water quality','sources':[]},token); case_id=case['case']['id']
                self.assertEqual(get('/api/cases')[0]['id'],case_id)
                self.assertEqual(get('/api/cases/'+case_id+'/export')['format_version'],1)
                for path in ('/app.js','/app.css','/'):
                    with urllib.request.urlopen(base+path) as response: self.assertEqual(response.status,200)
            finally: server.shutdown(); thread.join(timeout=5); server.server_close(); server.cases.close()


if __name__=='__main__': unittest.main()
