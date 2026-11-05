# Detection and interpretation

## Two separate questions

Coordination asks whether accounts repeatedly act together. Inauthenticity asks whether identity, provenance, or control is deceptive. Shared content, timing, languages, or low engagement cannot answer the second question by themselves. The system returns coordination leads; an analyst records a separate explanation and supporting evidence.

The approach is informed by behavioral-trace networks described by [Pacheco et al.](https://arxiv.org/abs/2001.05658) and recurring coordination analysis by [Weber and Neumann](https://arxiv.org/abs/2103.03409). TopicStream does not claim to reproduce their evaluated systems or performance.

## Identity and evidence

X uses platform-scoped author IDs; Bluesky uses DIDs. Mastodon uses the actor URI when supplied, otherwise a full handle and instance, never an observing server's numeric ID alone. Handle fallbacks are explicitly counted as missing stable identity. Same-looking handles on different platforms are never automatically merged.

Mastodon boosts retain the wrapper actor and timestamp, plus the original target. X retains repost/reply/quote references when the API provides them. The Bluesky search adapter retains reply targets; repost actions require another acquisition method.

Normalized records retain source, post key, author identity, original text, timestamps, links, matches, and available metrics. Recollection records a normalized snapshot before later reports can change. Each analysis saves its actual input rows, dataset SHA-256, detector version, configuration, query scope, and coverage. Case evidence/export reads that saved analysis dataset, even if collection later refreshes current posts. These are reproducibility records, not signed forensic evidence or raw HTTP archives.

## Recurring groups (`recurrence-1`)

1. Use posts inside the saved UTC interval that match the case and local exclusions/languages.
2. Form behavioral traces: exact normalized text of at least 40 characters; normalized full URLs; and source/type/target triples for amplification. Reposts are excluded from copied-text/link families to avoid treating platform copying as manual copying.
3. Group trace occurrences into non-overlapping anchored windows, 10 minutes by default. Require at least two accounts for an event. Events above 100 accounts are excluded from pair expansion and reported as a limit. This greedy windowing can split boundary-spanning patterns.
4. For each account pair, merge events separated by at most 60 minutes into a single episode. Require at least three episodes on two UTC days. Multiple trace families in one episode do not count as multiple repetitions.
5. Weight evidence by `1 / log2(2 + distinct accounts using the trace)` and sum the strongest evidence per episode. Connected components with at least three accounts become leads. They need not be cliques, and do not establish common ownership. Density and edges make this visible.
6. Rank groups by summed edge weight divided by member count. The score is relative to this dataset and configuration, with no probability interpretation.

The default analysis limit is the earliest 20,000 in-scope posts (maximum configurable 50,000). Truncation is disclosed. The separate exploratory near-wording report uses the earliest 2,000 posts, complete-link word-shingle clusters, and the configured Jaccard threshold. It can miss translated or semantically rewritten narratives and does not infer AI authorship. URL normalization preserves path and query case; only scheme/host/default port and fragments are normalized.

## Comparison and negative findings

Five seeded permutations shuffle timestamps within each source and UTC day. They preserve account daily volume, content popularity, and the source/day timestamp multiset, while breaking individual within-day schedules. The UI shows each shuffled recurring-edge count. The comparison is diagnostic: no p-values, confidence percentages, or multiple-testing-adjusted significance are computed.

A negative observed-data assessment requires gap-free exhausted bounded-search intervals for every enabled query and the full requested interval, stable identities, and no analysis truncation or discarded high-volume events. Otherwise the result is insufficient evidence. Even an exhausted query is not complete platform or topic coverage: missing translations, deleted records, inaccessible content, and query selection remain limitations. CSV and non-X search coverage remain partial in this release.

## Analyst review

Inspect repeated pairs and individual posts, look for disclosed scheduling or syndication, inspect whether accounts explicitly belong to one organization, and consider breaking news and shared public sources. Record legitimate explanations as well as unresolved or suspected cases. Reviews retain dataset version, time, explanation, and evidence post keys; older dataset reviews remain labeled historical. A suspected-in-authenticity review requires at least one evidence reference but this validation cannot judge whether the analyst's evidence is sufficient.

Timing does not identify who originated a story. A content match does not identify an operator. A counts/search mismatch has no assumed cause. Low lifetime posting does not prove dormancy, and observed hour concentration does not establish location or office hours. Topic, ideology, or language alone is not a detector feature for deception.
