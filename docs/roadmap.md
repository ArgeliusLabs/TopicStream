# Remaining research and product work

0.3.0 provides a local topic-to-evidence workflow, acquisition safeguards, recurring groups, comparison diagnostics, and analyst review. It does not implement every longer-term recommendation from the review.

| Priority | Next work | Acceptance criterion |
| --- | --- | --- |
| 1 | Credentialed connector contract tests and operational checks | Confirm current API request/response behavior, access, pagination, and billing with bounded, documented test runs |
| 1 | Real-world labeled validation and matched controls | Publish held-out coordination precision/recall, coverage assumptions, threshold sensitivity, and analyst agreement without conflating deception labels |
| 1 | Workspace/provider-wide budget and reconciliation | Concurrent cases share an optional global ceiling; uncertain requests can be reconciled with evidence from provider records |
| 2 | Streaming acquisition and historical replay | Durable ingestion/checkpoints, lag and loss metrics, deduplication, deletion/tombstone handling, and tests across interruptions |
| 2 | Incremental free-source continuation and multiple Bluesky PDS hosts | Resume safely across servers and sessions with explicit visibility and auth behavior |
| 2 | Multilingual semantic and media matching | Evaluated language-aware matching, perceptual media traces, confidence/coverage disclosure, and linked source evidence |
| 2 | Richer temporal/null models | Matched account activity patterns, diurnal/weekly seasonality, multiple-comparison controls, and sensitivity by community/trace popularity |
| 2 | More sources through authorized APIs or imports | Per-connector provenance, limits, identity rules, and tests; no assumed cross-platform identity resolution |
| 3 | Multiuser review and case lifecycle | Auth, authorization, audit roles, backup/retention/deletion controls, and deployment hardening |
| 3 | Raw evidence archives and signed exports | Documented acquisition provenance, retention policy, content hashes, signatures, and tested restore/reverification |

The current connected-component graph is deliberately simple. More sophisticated community detection should be evaluated against analyst usefulness, not added merely because it is more complex. Near-text matching is lexical and bounded; it does not establish whether an LLM wrote a message. Actor attribution and intent require independent evidence beyond this application's public behavioral observations.
