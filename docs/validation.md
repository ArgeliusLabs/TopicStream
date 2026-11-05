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

During implementation on Windows, automated checks and manual case creation, demo graph/evidence, review saving, and CSV import were exercised. Browser diagnostics showed no application console errors in those flows. A subsequent [live X pilot](live-pilot-2026-11-05.md) exercised authenticated collection and exposed the long-post preview issue fixed in 0.3.1. Provider billing is not reconciled, and live Bluesky/Mastodon acceptance has not been exercised.

The 0.3.2 feedback regressions cover same-UTC-day deduplication across restarts, day rollover and midnight-crossing requests, credential isolation, conservative failure reservations, optional author charges, unchanged per-request counts charges, credit failures/top-ups/clipping, stored-row comparison populations, separate query-hour profiles, configured activity rules, and preserved collapsed evidence. The workspace report route allows only the known report script hash; post content remains escaped.

The 0.3.3 pricing regressions use mocked clocks and responses to exercise the November 22 transition, a collector surviving the cutover, historical-post reads at current prices, legacy `false` configs, in-flight requests spanning the transition, repeated author IDs, next-day charges, and budget refusal before HTTP. Existing historical fixtures pin their pricing clock so CI remains stable after the change. These tests validate the estimator against the supplied notice, not the provider's future production billing implementation.

Manual browser checks on the [synthetic report](report-examples.md) verified light/dark controls, 25 initially disclosed pair rows with all 210 retained, links opening event and nested post details, and a white-background print preview with expanded pair references. No console warnings or errors were reported. These checks make no paid API requests. The private classroom dataset was not available for a fresh run; its reported 21-of-22 result has not been independently remeasured. Detector defaults and their existing regression tests are unchanged.

## What these tests do not establish

Synthetic positives demonstrate expected mechanics, not real-world precision or recall. A legitimate recurring campaign is intentionally a coordination lead. Strong evaluation needs independently annotated cases, matched benign controls, held-out topics/time periods, missing-data stress tests, threshold sensitivity, and analyst agreement. Keep labels for coordination separate from labels for deceptive identity/control. Do not turn these tests into a public CIB accuracy percentage.
