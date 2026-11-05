# Validation

## Automated checks

Run `python -m unittest discover -s tests -v`. The suite uses invented posts, recorded API shapes, SQLite databases, and a temporary localhost HTTP server. It sends no requests to social platforms and needs no credentials. One optional test uses `TOPICSTREAM_SAMPLE_CSV`; it is skipped when the external course export is unavailable.

Regression coverage includes identity separation and handle changes; Mastodon amplification attribution and HTML links; URL case; UTC import parsing; time/topic/language filters; whole-interval coverage; pre-request budgets and concurrent reservations; crash-persistent uncertain charges; atomic page/checkpoint rollback; capped and interrupted pagination after restart; query/scope changes; legacy migration; immutable evidence exports; recurring text/link/amplification groups; one-off viral and independent-post negatives; correlated-family episode merging; deterministic shuffles; analysis limits; 201 exact-copy posts; later monitoring alerts; case/import/review workflows; and HTTP session/origin validation.

GitHub Actions runs the suite on Windows and Ubuntu with Python 3.9 and 3.12. Runtime remains standard-library-only. Windows tests explicitly close SQLite handles before deleting temporary folders.

## Browser acceptance checks

Use synthetic data only during development:

1. Start `python -m topicstream serve` and open its local URL.
2. Open the synthetic example. Expect 185 posts, 37 accounts, one five-account recurring group, and $0 spending. Inspect the graph, timeline, source evidence, and comparison runs.
3. Save a review explanation. Close/reopen the finding and verify the history; verify the HTML report includes the review.
4. Create a new import-only case for `water quality`, UTC 2026-10-29 through 2026-11-05 (exclusive).
5. Import `examples/synthetic-posts.csv`. Expect nine posts, three accounts, one group, and partial import coverage. Inspect findings and export JSON.
6. Check browser console errors, empty/failed/unavailable states, narrow-screen layout, and report links. Do not click live collection merely to test a button.

During implementation on Windows, automated checks and manual case creation, demo graph/evidence, review saving, and CSV import were exercised. Browser diagnostics showed no application console errors in those flows. Live credentialed X/Bluesky collection and provider billing were not exercised.

## What these tests do not establish

Synthetic positives demonstrate expected mechanics, not real-world precision or recall. A legitimate recurring campaign is intentionally a coordination lead. Strong evaluation needs independently annotated cases, matched benign controls, held-out topics/time periods, missing-data stress tests, threshold sensitivity, and analyst agreement. Keep labels for coordination separate from labels for deceptive identity/control. Do not turn these tests into a public CIB accuracy percentage.
