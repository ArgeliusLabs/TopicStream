"""Provider-announced expansion billing transition; all requests are mocked."""
import unittest
from datetime import timedelta
from unittest.mock import patch

from topicstream.sources import X
from topicstream.store import Store, BudgetExceeded
from test_investigations import ReplayHttp
from test_topicstream import x_search_page


class ExpansionPricingTests(unittest.TestCase):
    cutoff=X.AUTHOR_EXPANSIONS_BILL_FROM
    query={'max_results':10,'expansions':'author_id'}

    def test_long_lived_collector_reprices_when_request_date_changes(self):
        with Store(':memory:') as s:
            x=X(ReplayHttp(x_search_page([1]),x_search_page([1])),store=s,bearer='test',budget_usd=1)
            with patch('topicstream.xsource.utcnow',return_value=self.cutoff-timedelta(seconds=1)):
                self.assertEqual(x.search_unit_price(),.005)
                x._get(x._ep('search'),self.query)
            with patch('topicstream.xsource.utcnow',return_value=self.cutoff):
                self.assertEqual(x.search_unit_price(),.015)
                x._get(x._ep('search'),self.query)
            # The fixture's post dates precede the cutover; request time sets pricing.
            self.assertEqual([r['charged_micros'] for r in s.ledger()],[5000,15000])
            self.assertEqual([r['reserved_micros'] for r in s.ledger()],[150000,150000])

    def test_legacy_false_cannot_disable_announced_user_charges(self):
        for mode in ('auto',False):
            with self.subTest(mode=mode), Store(':memory:') as s, patch('topicstream.xsource.utcnow',return_value=self.cutoff):
                x=X(ReplayHttp(x_search_page([1,4])),store=s,bearer='test',budget_usd=1,prices={'bill_author_expansions':mode})
                x._get(x._ep('search'),self.query)
                self.assertEqual(s.spent(),.02)  # two posts, one author

    def test_pre_cutover_settlement_is_free_for_authors_but_reservation_covers_transition(self):
        with Store(':memory:') as s, patch('topicstream.xsource.utcnow',return_value=self.cutoff-timedelta(days=1)):
            x=X(ReplayHttp(x_search_page([1,4])),store=s,bearer='test',budget_usd=1)
            x._get(x._ep('search'),self.query)
            self.assertEqual(s.spent(),.01)
            self.assertEqual(s.ledger()[0]['reserved_micros'],150000)
            self.assertEqual(s.db.execute("SELECT count(*) FROM x_resource_reads WHERE kind='user'").fetchone()[0],0)

    def test_transition_spanning_request_settles_with_fully_reserved_user_charge(self):
        with Store(':memory:') as s:
            x=X(ReplayHttp(x_search_page([1])),store=s,bearer='test',budget_usd=1)
            with patch('topicstream.xsource.utcnow',side_effect=[self.cutoff-timedelta(seconds=1),self.cutoff]):
                x._get(x._ep('search'),self.query)
            self.assertEqual(s.spent(),.015)
            self.assertEqual(s.db.execute('SELECT count(*) FROM x_resource_reads').fetchone()[0],0)

    def test_user_deduplication_across_new_posts_and_next_day(self):
        with Store(':memory:') as s:
            x=X(ReplayHttp(x_search_page([1]),x_search_page([4]),x_search_page([4])),store=s,bearer='test',budget_usd=1)
            with patch('topicstream.xsource.utcnow',return_value=self.cutoff):
                x._get(x._ep('search'),dict(self.query,query='one'))
                x._get(x._ep('search'),dict(self.query,query='two'))
            with patch('topicstream.xsource.utcnow',return_value=self.cutoff+timedelta(days=1)):
                x._get(x._ep('search'),self.query)
            self.assertEqual([r['charged_micros'] for r in s.ledger()],[15000,5000,15000])

    def test_budget_refusal_precedes_http_on_both_sides_of_transition(self):
        for when in (self.cutoff-timedelta(days=1),self.cutoff):
            with self.subTest(when=when), Store(':memory:') as s, patch('topicstream.xsource.utcnow',return_value=when):
                http=ReplayHttp(); x=X(http,store=s,bearer='test',budget_usd=.10)
                with self.assertRaises(BudgetExceeded): x._get(x._ep('search'),self.query)
                self.assertEqual(http.calls,[])

    def test_explicit_true_can_estimate_paid_authors_before_cutover(self):
        with patch('topicstream.xsource.utcnow',return_value=self.cutoff-timedelta(days=1)):
            self.assertEqual(X(None,prices={'bill_author_expansions':True}).resource_cost(10,6),.11)

    def test_invalid_modes_are_rejected(self):
        for value in ('false','never',None,0,1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                X(None,prices={'bill_author_expansions':value})


if __name__=='__main__': unittest.main()
