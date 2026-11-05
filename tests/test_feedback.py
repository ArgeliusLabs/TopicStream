"""Daily read estimates and evidence-report regressions. No paid requests."""
import tempfile
import unittest
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from topicstream import analyze as A, report
from topicstream.identity import account_key
from topicstream.monitor import alert_scope
from topicstream.sources import Post, X, iso, parse_time
from topicstream.store import Store
from topicstream.xsource import credit_delta
from test_investigations import ReplayHttp, row
from test_topicstream import NOW, x_search_page


class DailyReadTests(unittest.TestCase):
    def test_resource_markers_roll_back_with_failed_settlement(self):
        with Store(':memory:') as s:
            request=s.reserve_request('x','search','q',.05,1,iso(NOW))
            with self.assertRaises(ValueError):
                s.settle_resources(request,'scope','2026-11-04',[('post','1',.005),('invalid',)],iso(NOW))
            self.assertEqual(s.db.execute('SELECT count(*) FROM x_resource_reads').fetchone()[0],0)
            self.assertEqual(s.ledger()[0]['status'],'reserved')
            self.assertEqual(s.spent(),.05)

    def test_concurrent_responses_only_settle_an_id_once(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'concurrent.sqlite'
            with Store(path) as s:
                requests=[s.reserve_request('x','search','q',.05,1,iso(NOW)) for _ in range(2)]
            barrier=threading.Barrier(2); amounts=[]; errors=[]
            def settle(request):
                try:
                    with Store(path) as s:
                        barrier.wait(timeout=5)
                        amounts.append(s.settle_resources(request,'scope','2026-11-04',[('post','1',.005)],iso(NOW)))
                except Exception as exc: errors.append(exc)
            threads=[threading.Thread(target=settle,args=(r,)) for r in requests]
            for t in threads: t.start()
            for t in threads: t.join(timeout=10); self.assertFalse(t.is_alive())
            self.assertEqual(errors,[]); self.assertCountEqual(amounts,[0,.005])

    def read(self, store, ids, when=NOW, token='test', **kwargs):
        x=X(ReplayHttp(x_search_page(ids)),store=store,bearer=token,budget_usd=10,**kwargs)
        with patch('topicstream.xsource.utcnow',return_value=when):
            x._get(x._ep('search'),{'max_results':100,'expansions':'author_id'})
        return x.spent

    def test_restart_overlap_day_boundary_and_credential_scope(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'billing.sqlite'
            with Store(path) as s: self.assertEqual(self.read(s,[1,2]),.01)
            with Store(path) as s:
                self.assertEqual(self.read(s,[2,3]),.005)
                self.assertEqual(self.read(s,[1,2]),0)
                self.assertEqual(self.read(s,[1,2],NOW+timedelta(days=1)),.01)
                self.assertEqual(self.read(s,[1,2],token='other'),.01)
                self.assertAlmostEqual(s.spent(),.035)

    def test_cross_midnight_request_is_conservative_and_does_not_seed_reads(self):
        with Store(':memory:') as s:
            midnight=NOW.replace(hour=0,minute=0,second=0)
            x=X(ReplayHttp(x_search_page([1])),store=s,bearer='test',budget_usd=10)
            with patch('topicstream.xsource.utcnow',side_effect=[midnight-timedelta(seconds=1),midnight]):
                x._get(x._ep('search'),{'max_results':10})
            self.assertEqual(self.read(s,[1],midnight),.005)
            self.assertEqual(self.read(s,[1],midnight),0)

    def test_imports_and_uncertain_requests_do_not_establish_free_reads(self):
        with Store(':memory:') as s:
            s.add_posts([Post('x','x','1',iso(NOW),'a','imported')])
            x=X(ReplayHttp(TimeoutError()),store=s,bearer='test',budget_usd=10)
            with self.assertRaises(TimeoutError): x._get(x._ep('search'),{'max_results':10})
            self.assertEqual(self.read(s,[1]),.005)
            self.assertEqual(s.ledger()[0]['status'],'uncertain')
            self.assertAlmostEqual(s.spent(),.055)

    def test_opt_in_profile_charge_and_repeat_discount(self):
        with Store(':memory:') as s:
            self.assertEqual(self.read(s,[1,4],prices={'bill_author_expansions':True}),.02)
            self.assertEqual(self.read(s,[7],prices={'bill_author_expansions':True}),.005)

    def test_counts_are_charged_per_request_even_on_same_day(self):
        with Store(':memory:') as s:
            x=X(ReplayHttp({'data':[]},{'data':[]}),store=s,bearer='test',budget_usd=10)
            for _ in range(2): x._get(x._ep('counts'),{})
            self.assertEqual(s.spent(),.01)

    def test_balance_delta_clipping_topups_and_missing_values(self):
        self.assertEqual(credit_delta({'total_balance':10},{'total_balance':9}),1)
        self.assertEqual(credit_delta({'total_balance':10},{'total_balance':15}),-5)
        self.assertIsNone(credit_delta(None,{'total_balance':9}))
        self.assertIsNone(credit_delta({'total_balance':1},{'total_balance':0}))
        self.assertIsNone(credit_delta({'total_balance':float('nan')},{'total_balance':1}))
        self.assertEqual(credit_delta({'prepaid_balance':1,'free_balance':0},
                                     {'prepaid_balance':-2,'free_balance':0}),3)

    def test_credit_endpoint_failure_does_not_block_collection(self):
        messages=[]
        with Store(':memory:') as s:
            x=X(ReplayHttp(TimeoutError(),x_search_page([1]),TimeoutError()),store=s,bearer='test',budget_usd=1,log=messages.append)
            before=x.capture_credit(1,'before')
            x._get(x._ep('search'),{'max_results':10})
            self.assertIsNone(x.finish_credit(1,before))
            self.assertEqual(s.spent(),.005)
            self.assertIn('not a reconciled run charge',messages[-1])


class ReportPopulationTests(unittest.TestCase):
    def test_baseline_includes_unmatched_rows_but_selected_population_stays_scoped(self):
        matching=[dict(row('campaign',1,i),created_utc=iso(NOW.replace(hour=9)+timedelta(minutes=i))) for i in range(10)]
        background=[dict(row('background',1,i),matched=[],created_utc=iso(NOW.replace(hour=22)+timedelta(minutes=i))) for i in range(30)]
        comparison=A.hour_comparison(matching,{account_key(matching[0])},matching+background)
        self.assertEqual(comparison['band_share'],1)
        self.assertEqual(comparison['scoped_share'],1)
        self.assertEqual(comparison['all_share'],.25)
        self.assertEqual(comparison['baseline_posts'],40)

    def test_counts_keep_queries_separate_and_exclude_partial_hours(self):
        start=NOW.replace(hour=0,minute=30); end=start+timedelta(hours=3)
        rows=[dict(source='x',tag='a',query_hash='qa',start_utc=iso(start.replace(minute=0)+timedelta(hours=i)),uses=10) for i in range(4)]
        rows += [dict(rows[1],tag='b',query_hash='qb',uses=100)]
        rows += [dict(rows[2],query_hash='partial',end_utc=iso(start+timedelta(hours=2)))]
        profiles=A.count_hour_comparison(rows,1,start,end)
        self.assertEqual([(r['tag'],r['hours'],r['uses']) for r in profiles],[('a',2,20),('b',1,100)])

    def test_activity_uses_config_source_and_saved_provenance(self):
        posts=[row('a'+str(i),1,i) for i in range(3)]
        cfg={'terms':['water quality'],'tags':[],'alert':{'uses':3}}
        start=NOW-timedelta(days=10); end=NOW
        alerts=report.activity_rules(posts,[],[],cfg,start,end)
        self.assertEqual(len(alerts),1); self.assertEqual(alerts[0]['accounts'],3)
        old=dict(source='x',tag='water quality',start_utc=iso(start),minutes=30,payload={'uses':900,'accounts':1,'reasons':['stale']})
        self.assertEqual(report.activity_rules(posts,[],[old],cfg,start,end)[0]['uses'],3)
        old['payload']['scope_hash']=alert_scope(cfg,start,end)
        self.assertEqual(report.activity_rules(posts,[],[old],cfg,start,end)[0]['origin'],'Saved live monitor')
        self.assertEqual(report.activity_rules(posts,[],[],dict(cfg,alert={'uses':4}),start,end),[])

    def test_report_scope_counts_and_collapsed_evidence_are_complete(self):
        with Store(':memory:') as s:
            for day in (1,3,5):
                for i in range(9):
                    p=row('actor'+str(i),day,i//2); p.pop('key'); s.add_posts([Post(**p)])
            p=row('outside',0); p.pop('key'); s.add_posts([Post(**p)])
            p=row('unmatched',3); p.pop('key'); p['matched']=[]; s.add_posts([Post(**p)])
            cfg={'terms':['water quality'],'tags':[],'start_utc':row('s',1)['created_utc'],'end_utc':row('e',6)['created_utc']}
            text=report.render(s,cfg,now=NOW)
            self.assertIn('27 of 28 stored rows',text)
            self.assertIn('Show all pairs',text)
            self.assertEqual(text.count('class="post" id="post-'),27)
            self.assertIn('beforeprint',text); self.assertIn('hashchange',text)
            self.assertLess(text.index('Activity rules tripped'),text.index('id="groups"'))


if __name__=='__main__': unittest.main()
