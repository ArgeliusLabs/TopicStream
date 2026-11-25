# Changes

## 0.3.13 (November 25, 2026)

- **Text and link matches** says how texts are compared: hashtags, links and mentions are taken out and capitals ignored, and reposts are left out. A reader who had never seen the tool found thirteen "identical" posts ending in three different sets of hashtags and could not tell why they matched.
- No change to any number.

## 0.3.12 (November 25, 2026)

- Timestamps in the report's tables stay on one line. With the columns 0.3.11 added, the start time in the match tables was being broken across three lines (`2026-02-` / `03T02:47` / `:12Z`). Same fix for the activity rules, purchased windows, cross-platform matches and run details.
- An example text that is shortened for a table ends with an ellipsis, so a clipped hashtag (`#TelukRaw` for `#TelukRawah`) is not read as a different tag.
- No change to any number.

## 0.3.11 (November 25, 2026)

The rest of what the report showed up to 0.2.5 is back. A 0.2.5 report and a current one were rendered on the same data and compared panel by panel and column by column; everything below was still being computed and no longer printed.

In each tag card:

- **First post, peak day, typical day, empty days**, in a sentence beside the daily bars (the old overview tiles, said per tag).
- **Busiest window and account concentration**: the busiest stretch for the tag with posts, accounts, posts per account and the average window, and how many of the tag's accounts were under 30 and 90 days old. The alert table at the top still shows the first window that tripped a rule; this is the biggest one, which can be different.
- **X volume per hour** as bars again, above the table.
- **What the platforms report for this tag**: the per-day uses and accounts each Mastodon server (or X) reports itself. The collector never stopped storing these.

In the tables:

- **Text and link matches** show how many accounts and posts each match holds; Similar wording also shows how many wordings and the largest identical group.
- **Account observations** has Replies (with who the account replies to most), Links (with the domain it links most), Languages and each account's own Tightest 8 hours with the share of its posts inside. Rows are still ordered by number of signals, then posts.
- **Observed posting-hour comparison** has its chart again, now with both groups: 24 hours, the selected accounts beside all stored posts, each as a share of its own posts, the tightest eight hours marked. The sentence and the table stay.
- **Purchased X windows** shows accounts and posts per account for each hour; **Early observed participants** shows the posts and linked domains of the first ten minutes.
- **Creation-date concentration** shows both shares beside the ratio; **Cross-platform matches** shows posts and accounts.
- **Other tags that travel with the tracked ones** has Posts per account and Travels with.

One behaviour change: when several eight-hour bands hold the same number of posts, the band shown is the one centred on them (posts from 01:00 to 06:59 read as 00:00 to 08:00, where they used to read as 23:00 to 07:00). The share inside the band does not change, and no signal depends on which band is shown. A comparison between a group and all stored posts can move only where the group's own band was tied.

`tests/test_report_panels.py` is new: it lists every panel the report prints and every analysis it is expected to show, and fails by name if one goes missing. That is the check that would have caught 0.3.0.

Nothing here makes a request or costs anything. No change to collection, detection or pricing.

## 0.3.10 (November 25, 2026)

0.3.9 put the per-tag account table back shorter than it used to be. Checked against a 0.2.5 report on the same data, and brought into line with it:

- **Top originating accounts** lists up to 15 accounts (0.3.9 stopped at 10) and has its **Reposts** column again: how many of an account's posts with the tag are reposts. The order is unchanged, most posts with the tag first.
- Each tag card's heading carries the tag's totals again: `#tag · 158 posts from 17 accounts`.
- **Related hashtags** shows **Share** and **Lift** again, with a line saying what each is. The analysis never stopped computing them.
- No change to collection, detection, pricing or any existing number in a report.

## 0.3.9 (November 25, 2026)

Three panels are back in the report. They were in every version up to 0.2.5 and did not come across when the report was rebuilt around recurring groups in 0.3.0. The analysis never stopped computing them.

- **Tracking tokens carried by several accounts**, under Shared links and related tags: each campaign or referral token found on the links in the posts (`utm_campaign=…`, a referral code, a short code), how many distinct accounts carry it, and which. Share-button boilerplate is left out and tokens that always travel together are one row, as before. The note under the table says what a shared token does and does not show: it ties posts to one source of links, and anyone who copies or forwards a post carries the token along.
- **Top originating accounts**, in each tag's card: the ten accounts that used the tag most, with posts, share of the tag, age at first post, followers and median likes. (Fifteen, with reposts, from 0.3.10.)
- **Followers and Lifetime posts** columns in Account observations, beside each account's signals, so the facts behind `no_audience` and `low_lifetime_activity` are on the page.
- Medians print as 1 or 0.5, not 1.0.
- Where a section has nothing to list (no shared domain, no candidate tag), the report says so in a sentence in place of an empty table.
- `examples/build_report_demo.py`: the demo links carry a made-up token, so the demo report shows the table. `docs/report-examples.md` has two new screenshots.
- None of this makes a request or costs anything: the tokens come from links already collected and the account facts from profiles already held. "Unknown" is shown where a profile was not collected.
- No change to collection, detection, pricing, or any existing number in a report.

## 0.3.8 (November 25, 2026)

The report explains itself. Two people who had never seen the tool read its report cold; these are the places where they had to guess.

- **Recurring account groups** now states the rule in words under the heading: two accounts become a pair when they post the same text, link or repost target within the window, on at least `min_episodes` occasions across at least `min_days` UTC days. The numbers come from the run's own settings.
- **Text and link matches** states the settings each table used (accounts, minutes), so a reader can compare a table with their own count.
- **Account observations** has a key, "What each signal in this table counts", with the threshold behind each signal that appears, and says which posts are counted. `report.SIGNAL_RULES` holds the wording; a test keeps it in step with `analyze.account_features`.
- **Timing comparison** says "recurring account pairs" (it said "edges") and describes what a shuffled copy keeps and what it reassigns.
- No change to collection, detection, pricing or any number in a report.

## 0.3.7 (November 25, 2026)

- Explorer: the menu reads as a sentence, "Find accounts that posted: the same text (hashtags ignored) / the same text, exactly / the same link / any link containing…", and the box for the last one says what it is for (a tracking token, for example) and that no time window applies. The two tables stay side by side in a frame as narrow as 700 px.
- `examples/explorer-demo.csv`: a made-up sample for the co-posting explorer (96 posts, 24 accounts), with `examples/build_explorer_demo.py`, which writes it and lists what each setting shows.

## 0.3.6 (November 25, 2026)

Collect, export, explore: a collection now opens in the co-posting explorer in one step.

- New: `export-csv posts.csv` writes the posts the report analyses (stored posts inside the configured interval) as CSV, reading the local database and making no requests. `--accounts profiles.csv` also writes the profile facts held for their authors. The layout is the one `import-csv` reads back, so a collection round-trips, and the one the explorer maps without help. Reposts, replies and quotes are marked in `content_type`.
- Workspace: **Explore bursts** opens the explorer on a case's posts (`/explorer?case=<id>`), and **Posts CSV** downloads them (`/api/cases/<id>/posts.csv`).
- Explorer: tick which kinds of post to include when the file has a `content_type` column (reposts and replies start unticked); **Pin this list**, change a setting, and it names the accounts that joined and left; click a burst to list its accounts in posting order; long lists are cut at 60 names.
- `import-csv` reads files with or without a byte-order mark, so CSVs saved by Excel import cleanly.
- Tried on a real collection (three hours of one Indonesian topic on X, 3,045 posts): no same-text burst among the 134 originals, quotes and replies at any setting, and with reposts ticked in, the two reposted originals that dominate the hour appear as waves of several hundred to a thousand accounts. No change to collection, detection, pricing or the report.

## 0.3.5 (November 24, 2026)

- New: the co-posting explorer, `topicstream/static/coposting_explorer.html`. One self-contained page (no dependencies, no network requests) that loads any CSV of posts, lets you map the time, account, text and link columns, and shows bursts and candidate accounts as you move the window and the minimum number of accounts. Groups by text with hashtags removed, exact text, exact link, or any link containing a string. Copy or download the candidate list. `python -m topicstream explorer` opens it (`--dry-run` prints its path), and the workspace serves it at `/explorer`, with its one inline script allowed by hash under the existing content security policy.
- It is the tool to use before writing a config: the two numbers it helps you choose are `burst.window_minutes` and `burst.minimum`.
- No change to collection, detection, pricing or the report. A database and a config from 0.3.4 work unchanged.

## 0.3.4 (November 23, 2026)

Cost and correctness changes from the first live run of 0.3.3 after X began billing author profiles (measured 23 November: three complete hours of one topic, 3,045 posts, $43.85 on the account against $43.855 in the ledger; two thirds of it author profiles).

- Author profiles are no longer requested with every search page. `author_profiles` (`lazy` by default, `always` for the 0.3.3 behaviour, `never`) buys profiles afterwards, only for the accounts a report shows: recurring-group members, accounts in text, link or similar-wording matches, accounts with enough posts for the account table, authors of the most reposted originals. One users lookup per 100 ids, priced per profile returned, deduplicated per UTC day in the same ledger, capped by `profile_cap` (300). `profiles` runs it on demand; collection and `peak` run it at the end. Until a profile is bought an X account appears by its numeric id and carries no age or audience signal; the report says how many are known.
- `peak` reads an hour's originals and replies by default (`reposts: "exclude"`, `-is:retweet`), which is where the text, the links and the authors are, at a fraction of the price of the hour; the originals' own repost counts come back with them. `--reposts include` reads everything as before. Such a window is recorded under the query's `-is:retweet` fingerprint and marked "originals only"; the counts still count reposts.
- `amplifiers --post <id> --sample N`: a bounded, newest-first sample of the accounts that reposted one post (each a profile read), stored and used for the cohort line below.
- Report: an "Amplified originals" section, the most reposted originals in scope with reposts captured, the platform's total, distinct reposting accounts, hours, and the reposters' age and follower profile from collected or sampled profiles; originals over the detector's comparison limit are marked. The posts behind "insufficient evidence" in a repost-dominated window are now on the first screen.
- `peak --sample N` reads the first N posts of an hour and records the read as a sample, not a complete window.
- Fixed: rolling-window `collect` and `run` sent `end_time` equal to the request time, which X rejects ("must be a minimum of 10 seconds prior to the request time"); every such live collection in 0.3.2 and 0.3.3 failed with a bare HTTP 400. The provider end bound is now clamped to thirty seconds before the request, and a 4xx response's own message is logged.
- Fixed: windows read from the archive endpoint (hours older than seven days) were recorded under an archive fingerprint the report never expected and were missing from "Purchased X windows"; the scope now lists each query's fingerprint aliases (archive, recent, with and without `-is:retweet`), and completeness is still judged on the configured query alone.
- The dataset hash is computed over content fields only (not collection time, engagement counts or bought profiles), so the same records imported twice give the same hash, the same review binding and the same shuffle median.
- Tests pinned against the clock and the fixtures' dates (the suite had rotted past the 22 November transition); 112 tests.

## 0.3.3 (November 5, 2026)

- Follow the X PPU notice supplied by the maintainer: expanded author objects become billable at the configured user-resource rate from November 22, 2026. Use request time, including for historical searches and collectors already running at the transition.
- Default expansion billing to `auto`; legacy `false` follows the same scheduled transition, while `true` includes user charges immediately. The notice specifies no timezone; the estimator uses midnight UTC.
- Reserve full post-plus-author page cost in advance, including before the transition; settle requests spanning the cutover conservatively. Preserve daily user deduplication, unknown-outcome reservations, and all historical ledger entries.
- Clarify the pre-change Singapore pilot figures, future pricing, and migration behavior. Add offline transition/budget tests and freeze historical pricing fixtures so CI does not depend on today's date. No new paid API test was performed.

## 0.3.2 (November 5, 2026)

- Default search author-expansion charges to zero, with an opt-in conservative price setting. Settle repeated resource IDs once per UTC day within a database and credential scope; retain full reservations for uncertain calls and preserve historical entries.
- Capture before/after credit observations for collection and peak reads. Report account balance movement separately from local estimates; do not claim automatic invoice reconciliation.
- Correct the public pilot's billing interpretation: approximately $1.44 inferred from operator-reported account activity, alongside the original $4.02/$7.98 estimates and the unresolved half-cent whole-account discrepancy.
- Compare posting hours against all stored rows inside the bounds and, separately, each matching X query's stored complete hourly buckets. Show analysis versus stored-row counts and headline activity triggers using configured thresholds.
- Collapse pair and post reference material without removing evidence. Hash links open their targets; a light-theme toggle and print controls work in standalone and workspace reports under a script-hash CSP.
- Refresh synthetic report screenshots and make CLI navigation prominent. Detector defaults, descriptive account labels, authenticity language, and shuffle limitations are unchanged.

## 0.3.1 (November 5, 2026)

- Live Singapore haze pilot: 285 retrieved posts; 284 text-matching posts from 238 accounts; no recurring group at the default thresholds. This is an operational check, not an accuracy benchmark. See `docs/live-pilot-2026-11-05.md`.
- Request and retain full-length X note text and entities, supporting both `note_tweet` and `note_post`. The pilot recovered 17 posts otherwise excluded because their previews lacked the term.
- `usage` also reports the provider's credit balance when available. Balance readings and conservative local estimates remain distinct.
- Avoid binary floating-point tails adding a micro-dollar to resource-cost settlements.
- Daily report charts include partial first/last UTC days; a six-day interval starting at midday spans seven calendar dates.

## 0.3.0 (November 2026)

- Local browser workspace: editable topic plans, saved cases, source status, imports, jobs/cancellation, group graph/timeline/evidence, reviews, JSON exports, and standalone reports.
- Recurring text/link/amplification groups with independent episodes, transparent pair evidence, popularity weighting, and deterministic timing comparisons. Coordination remains separate from authenticity.
- X search budgets include expanded author profiles as well as posts; pricing checked against public X documentation on November 5, 2026.
- Transactional X pages/checkpoints, request-level budget reservations, crash-persistent uncertain charges, query-version isolation, and explicit partial/exhausted/unverified coverage. Free-source pages are saved as they arrive.
- Stable platform-scoped identities, distinct Mastodon boost actors, canonical links, event-time account age, full-interval report scope, later-episode alerts, and removal of unsupported suspicion/causality labels.
- Immutable analysis inputs, review history, migration guidance, conservative budget documentation, synthetic regression tests, and Windows/Linux CI.
- Earlier descriptions of complete windows, costs, or suspicion flags below are historical; use the current methodology and cost-control documentation.

## 0.2.5 (November 2026)

- The posting-hour chart compares the flagged accounts' band with the share of all posts in that same band (it used to show all posts' own tightest band, which is a different number).

## 0.2.4 (November 2026)

- Daily bars stop at 72px wide, so a three-day database does not draw three slabs.

## 0.2.3 (November 2026)

- Import-only databases read as what they are: the header shows the export's span, the depth note and the platform-counts panel say "export" rather than "collector", and the posts caveat describes export rows.

## 0.2.2 (November 2026)

- `import-csv` records a run (file, rows, new, profiles joined) so the report's sources panel shows where imported posts came from; `import_csv(now=…)` for reproducible builds.

## 0.2.1 (November 2026)

- `import-csv --accounts profiles.csv`: join account age, followers and lifetime posts from a profiles export, so the account signals and creation clusters work on imported data; `in_reply_to` is resolved to the replied account when it names a post in the same file.
- The report's platform notes describe only the sources the database holds, and say so for imported exports.

## 0.2.0 (November 2026)

The coordination layer, and a cheaper way to pay for it.

- `peak`: buy the busiest hour(s) of the X counts series complete, so the burst and account rules run on every post in the hour instead of a sample. `--dry-run`, `--at`, `--tag`. Windows are recorded and never bought twice; hours older than seven days use the archive endpoint on their own.
- `read_mode: "on_alert"`: `watch` buys only counts until an hour trips a rule, then buys that hour complete. Three terms around the clock are $0.72 a day.
- Two more burst rules beside same-text: same link (tracking parameters included) and same message in different words (word-pair shingles, Jaccard, clustered; `burst.paraphrase_threshold`).
- Accounts with signals: `replies`, `no_audience`, `young`, `dormant_then_active`, `office_hours`, `one_domain`, `multilingual`, `peak_only`, `co_posted`; a posting-hour chart for the accounts with two or more.
- Creation clusters, cross-platform matches, shared link infrastructure (tracking parameters, shorteners, domains by accounts), and the leading edge of every complete window.
- Reply status, reply target and lifetime post count are now stored for every post; existing databases are migrated in place.
- Report: the complete-windows, bursts, accounts and infrastructure sections; a data-driven note on what the next `peak` would cost; version and repository in the footer.
- 29 offline tests.

## 0.1.0 (November 2026)

Mastodon, Bluesky and X collectors; counts-based velocity; stratified sampling; budget cap; `estimate`, `usage`, `discover`, `import-csv`; the first report.
