# Upgrading from 0.2.x

Stop collectors and make a copy of existing SQLite files and configs before the first 0.3.0 run. The application migrates databases in place; no downgrade migration is supplied. Restoring the copied database/config is the rollback path.

Existing posts, metrics, tag-day rows, alerts, and run records remain. New columns retain canonical account identity and amplification references. New tables retain request reservations, page checkpoints, coverage, normalized snapshots, analysis inputs/results, and analyst reviews. Count/window uniqueness now includes query hash, so different query versions do not overwrite each other.

Legacy purchased windows become `unverified`, because older rows cannot prove that pagination ended. Legacy run spending is copied into the new request ledger once. It cannot reconstruct costs of old crashes that never saved a run. Old newest-ID cursors are retained for reference but no longer advance retrieval: a capped newest page may have skipped older data. The first upgraded X search can reread an interval, with its cost guarded by the remaining ledger budget.

Existing CLI commands remain. Fixed `start_utc`/`end_utc` are recommended for retrospective work. Explicit dates, query operators, and endpoint mode isolate new continuation state. A rolling CLI config deliberately widened into older history should use a new database. Imported timestamps without an offset are now UTC on every operating system.

Account counts may change because source-scoped stable IDs replace display handles. Mastodon boosts now represent amplification by the wrapper actor; old rows that discarded those actions cannot be reconstructed without recollection. Age is now evaluated at the event, rather than today. `peak_only` and `office_hours` are removed as suspicion signals; `dormant_then_active` becomes descriptive `low_lifetime_activity`.

The new report distinguishes partial, exhausted, and unverified intervals. The [report screenshots](report-examples.md) now show 0.3.2 with synthetic data. The historical changelog describes earlier behavior and should be read alongside the current methodology.

Version 0.3.2 adds daily resource-read records, private credit observations, and optional counts-bucket end times. Existing ledger estimates are not rewritten. Deduplication begins with successful reads recorded by the new version; imported rows and older reads cannot safely establish their billing day. `prices.bill_author_expansions` defaults to false even in older configs; set it true to retain the previous conservative author-expansion assumption. The UTC-day boundary is fixed by provider documentation, not the monthly account reset day. Back up databases before upgrading.

Version **0.3.3 supersedes that expansion default** following the X notice supplied by the maintainer. New configs use `"auto"`; existing `false` also follows the November 22, 2026 cutover. `true` estimates charges before that date too. The estimator uses midnight UTC because the notice does not supply a timezone. Every author-expanded page reserves the higher user-inclusive cost now, so some small budgets that previously allowed a request will refuse it. Successful settlements before the transition remain post-only. Upgrade collectors before November 22; merely leaving `false` in a 0.3.2 process does not gain this behavior. Restart the app on the new code. Historical ledger values remain unchanged and no paid recollection is required.

The browser workspace creates independent case folders. It does not automatically enroll an arbitrary existing CLI database. Continue reporting that database with the CLI, or import the original CSV into a case with an explicit scope. Never paste API credentials into a topic or CSV.
