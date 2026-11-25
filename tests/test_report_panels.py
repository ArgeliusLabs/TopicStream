"""A tripwire. The report was rebuilt once (0.3.0) and a dozen panels did not come across, though the analysis kept computing them;
nobody noticed for three weeks. Every panel the report prints is listed here with a string that only that panel writes. If one
goes missing the test names it. Removing a panel on purpose means removing its line here and saying so in CHANGELOG.md."""
import inspect, unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from topicstream import report as R, analyze as A

PANELS = [
    ('headline assessment', 'result["assessment"]'),
    ('activity rules tripped: the first window that met a rule', "'Source / query','First window UTC','Posts or API matches','Accounts','Reasons / rule'"),
    ('recurring account groups, with their pairs', 'Account pairs · '),
    ('amplified originals', "'Original','Platform reposts','Captured here','Reposting accounts','Hours','Reposter profile'"),
    ('collection coverage', "'Source / query','Interval UTC','Status','Records','Method / stop reason'"),
    ('purchased X windows, with accounts and posts per account', "'Query','Hour UTC','Status','Counts said','Returned','Accounts','Posts per account','Stop reason'"),
    ('tag card heading with the tag\'s totals', 'from {tag_accounts:,} account'),
    ('daily bars and the day table', "'UTC day','Observed posts','Originating accounts'"),
    ('first post, peak day, typical day, empty days', 'Peak day: '),
    ('busiest window and account concentration', "'Busiest window (UTC)','Posts','Accounts','Posts per account','Average window'"),
    ('account ages under 30 and 90 days', 'under 30 days old at the first post with this tag'),
    ('top originating accounts: 15 rows, reposts, age, followers, likes', "'Account','Posts with this tag','Share of the tag','Reposts','Age at first post (days)','Followers','Median likes'"),
    ('related hashtags with share and lift', "'Hashtag','Posts','Share','Lift','Accounts'"),
    ('domains linked from the tag', "'Domain','Posts','Accounts'"),
    ('X volume per hour as bars', 'X volume per {unit}, from the counts API'),
    ('X volume per hour as a table', "'Hour UTC','API-reported matches'"),
    ('what the platforms report per day', 'What the platforms report for this tag'),
    ('text and link matches with account and post counts', "['Start UTC','Accounts','Posts']"),
    ('similar wording: wordings and largest identical group', "['Wordings','Largest identical group']"),
    ('the key to the account signals', 'What each signal in this table counts'),
    ('account table: signals, age, followers, lifetime posts, likes, replies, links, languages, hour band',
     "'Account','Posts','Observed signals','Age at event','Followers','Lifetime posts','Median likes','Replies','Links','Languages','Tightest 8 hours (UTC)'"),
    ('posting-hour comparison, in words', 'Their tightest eight-hour band starts at'),
    ('posting-hour chart', 'class="hours"'),
    ('posting-hour table', "'UTC hour','Selected accounts / matching posts','All stored posts in the interval'"),
    ('X query volume in the same band', "'Source / query','Query fingerprint','Stored hours','API matches','Share in band'"),
    ('creation-date concentration with both shares', "'Creation week','Matched accounts','Share of matched','All observed accounts','Share of all','Relative share'"),
    ('cross-platform matches with posts and accounts', "'Time UTC','Type','Sources','Posts','Accounts','Match'"),
    ('early participants in complete windows, with their links', "'Query / hour','Early accounts','Posts in the first 10 minutes','Domains linked in those minutes','Posts in window'"),
    ('tracking tokens carried by several accounts', "'Token on the shared links','Distinct accounts','Accounts'"),
    ('domains and link shorteners by accounts', "'Domain','Distinct accounts'"),
    ('candidate tags with posts per account and what they travel with', "'Candidate tag','Posts','Accounts','Posts per account','Travels with'"),
    ('supporting evidence', 'Evidence posts · '),
    ('run details', "'Started','Finished','Notes'"),
]
# Every analysis the report is expected to print. A function that is computed and never shown is how the panels were lost.
PRINTED = ['velocity', 'account_age_mix', 'top_accounts', 'cooccurrence', 'top_domains', 'daily_series', 'bursts', 'link_bursts', 'paraphrase_bursts', 'account_features',
           'hour_comparison', 'count_hour_comparison', 'creation_clusters', 'cross_platform', 'infrastructure', 'leading_edge', 'candidates', 'amplified_originals']

class ReportPanels(unittest.TestCase):
    def test_every_panel_is_still_printed(self):
        source = inspect.getsource(R)
        missing = [name for name, marker in PANELS if marker not in source]
        self.assertEqual(missing, [], 'the report no longer prints: ' + '; '.join(missing))
    def test_every_listed_analysis_reaches_the_report(self):
        source = inspect.getsource(R)
        unused = [f for f in PRINTED if f'A.{f}(' not in source]
        self.assertEqual(unused, [], 'computed by analyze.py and not printed by report.py: ' + ', '.join(unused))
        for f in PRINTED: self.assertTrue(callable(getattr(A, f, None)), f)

if __name__ == '__main__': unittest.main()
