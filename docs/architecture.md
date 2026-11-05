# Architecture and local operations

## Components

| Module | Responsibility |
| --- | --- |
| `sources.py`, `xsource.py` | Provider normalization, pagination, request budgets, API compatibility |
| `store.py` | SQLite migrations, current posts, snapshots, checkpoints, coverage, ledger, analysis inputs, reviews |
| `identity.py`, `scope.py` | Shared identity, URL rules, explicit case interval and coverage checks |
| `monitor.py` | Closed-window alerts, including later episodes after an earlier alert |
| `analyze.py`, `detection.py` | Descriptive metrics, trace events, recurring edges/groups, shuffle comparison |
| `cases.py` | Saved case plans, local jobs, validation, exports, immutable analysis datasets |
| `web.py`, `static/` | Loopback JSON API and browser interface |
| `report.py`, `__main__.py` | Portable HTML evidence reports and CLI |

`python -m topicstream serve` binds only to `127.0.0.1`. A Host allowlist, per-session token, same-origin checks, JSON-only mutation requests, bounded request bodies, safe links, escaped content, and a restrictive content-security policy protect the local browser workflow. They are not multiuser authentication. Other processes running as the local user can access the workspace. Do not expose this server publicly.

## Case layout

Each random-ID case directory contains `case.json`, `config.json`, `job.json`, `evidence.sqlite`, and, after analysis, `analysis.json` and `report.html`. Imports retain the submitted `import.csv` and optional `profiles.csv`; a later import replaces those convenience files, while database snapshots/analysis inputs remain. Configs contain no credentials. Exported JSON omits internal database/report filesystem paths and includes the saved plan, analysis, source posts, review history, coverage, and request ledger.

Case plans are immutable through the UI. Create a new case for a changed scope. Stop the server before manually editing case files or backing up the directory. A copy of the entire case folder is the simplest backup. Removing a folder while the server is stopped removes that local case; there is no automatic retention policy or delete UI.

## Jobs and recovery

One worker performs collection/analysis jobs across the local case workspace. The UI can request cancellation and inspect the persisted log. Cancellation is cooperative between HTTP requests; an active request can take its 30-second timeout. Free-source retry waits are cancellable. CPU analysis finishes its bounded run before returning. On server restart, queued/running jobs become interrupted and may be retried.

X persists each page and continuation state atomically with SQLite FULL synchronization. A cap, interrupted request, repeated token, API error payload, or budget refusal leaves the interval partial. The next pass resumes its token. Progress advances to a later interval only when pagination ends. An expired continuation token can leave a case blocked; preserve its evidence and start a new case/database to retry the interval rather than deleting checkpoints silently.

Mastodon and Bluesky save successful pages as they arrive, but currently restart their search traversal on retry. They deduplicate stored posts and explicitly retain partial coverage. They do not offer the same durable continuation mechanism as X. Counts throttling is persisted after a completed query; interrupted counts may be requested again, with every attempt separately budgeted. Failed or partial source jobs appear in coverage even when analysis of available evidence succeeds.

## Storage transactions

Budget admission uses `BEGIN IMMEDIATE` against the same SQLite database. Pending and uncertain requests count toward the cap across process restarts and concurrent clients. No transaction spans an external network call. A crash after HTTP success but before persistence can result in a repeated request on retry; the unresolved reservation prevents silently losing its potential cost. Database migrations retain legacy tables and source rows, add conservative status defaults, and preserve distinct count/window query versions.

Analysis inputs are saved beside the result. Hashes include normalized data; a metric refresh can produce a new dataset version even without new text. Reports can be generated from those saved inputs. This release does not capture raw API bodies, sign exports, encrypt local case files, or coordinate budgets across databases.
