# Changes

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
