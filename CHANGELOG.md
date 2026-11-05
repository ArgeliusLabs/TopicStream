# Changes

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
