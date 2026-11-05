# Changes

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
