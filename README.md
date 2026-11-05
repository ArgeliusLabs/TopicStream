# TopicStream

A local investigation workspace for finding recurring coordination in public social-media activity. Enter a topic, review an editable search plan, collect or import posts, inspect account groups and their supporting evidence, and record an analyst assessment.

**Coordination is not proof of inauthenticity.** TopicStream identifies behavioral leads. It does not determine who controls an account, whether an identity is deceptive, or who sponsors an operation. An empty result with limited coverage is reported as **insufficient evidence**.

Choose the [CLI workflow](#cli-workflow) for exports, scripts, and repeatable reports, or [start the browser workspace](#start-the-workspace) for interactive investigations. Both use the same collection and analysis code.

## Live example: Singapore haze

[Read the public sample report](docs/examples/singapore-haze/report.md) from our November 5, 2026 X pilot. It shows the search scope, observed activity by day, detector settings, interpretation, coverage gaps, and estimated collection cost.

| Observed result | Value |
| --- | --- |
| Distinct posts retrieved | 285 |
| Posts analyzed / accounts | 284 / 238 |
| Brief repost clusters / recurring groups | 4 / 0 |
| Pilot cost inferred from reported account activity | About US$1.44 ($1.435 before cent rounding); not a separately verified debit |
| Historical 0.3.1 local estimate | US$4.02 initially; US$7.98 with verification, overstating the reported billing behavior |

**Upcoming X billing change:** an X notice supplied by the maintainer says expansions become billable from **November 22, 2026**. TopicStream 0.3.3 automatically includes author profiles at $0.010 per new user resource from that date and reserves for that cost in advance. The November 5 pilot remains a historical, pre-change example. See [pricing policy and source details](docs/x-costs.md).

**No strong recurring coordination was detected in this sample at the default thresholds.** This is a worked investigation example, not evidence that the wider topic is free of CIB or a benchmark of detection accuracy. The public report contains aggregate results; individual posts and account evidence remain local. See the [technical pilot notes](docs/live-pilot-2026-11-05.md) for collection fixes and billing caveats. To explore supporting evidence for a detected group without credentials or charges, use the synthetic example below.

## Start the workspace

Requires Python 3.9 or later. Runtime dependencies: Python standard library only. From this repository:

```console
python -m topicstream serve
```

Open http://127.0.0.1:8765 in your browser. Use `py` instead of `python` on Windows if that is your Python launcher. Stop with Ctrl+C.

Choose **Explore a synthetic example** for a complete demonstration without credentials, network collection, or charges. It contains invented accounts, repeated campaigns, and unrelated background activity.

The normal workflow is:

1. Describe a topic or situation; preview the search plan.
2. Edit phrases, hashtags, aliases, exclusions, languages, UTC dates, sources, and the X budget. The end date is exclusive.
3. Create the case. Choose **Collect data** or import a CSV under **Import data**. Creating a case alone makes no collection requests.
4. Inspect **Coverage**, then the recurring groups, graph, timeline, and individual supporting posts.
5. Record an explanation, benign alternatives, and selected evidence. Suspected inauthenticity requires selected evidence and an explanation; it remains an analyst assessment.
6. Export the case as JSON or open its self-contained HTML report.

The topic planner is a deterministic editable draft, not an LLM or automatic semantic research service. Add translations and alternative wording yourself. Exclusions and languages filter retrieved posts locally; they do not reduce the paid retrieval bill. Create another case to investigate a different scope.

```console
python -m topicstream serve --data-dir ./my-cases --port 8766
```

Cases are stored locally under `topicstream-cases/` by default. This is a single-user loopback server, not a hosted or multiuser service. Do not expose it through a public reverse proxy. Credentials stay in the environment or `.env`, outside exports.

## Sources

| Source | Collection in this release | Limits |
| --- | --- | --- |
| Mastodon | Public hashtag timelines on selected servers; HTML links and boost actors retained | Federation visibility and page caps; phrases only match inside collected hashtag results; servers may require authentication |
| Bluesky | Search through a `bsky.social` session; stable DIDs, facets, links, and reply targets | No firehose or repost-action collection; pagination does not establish complete topic coverage; this adapter currently supports accounts on `bsky.social` |
| X | Counts, bounded recent/archive search, resumable pages, amplification references | Requires accessible API endpoints and credit; cap, failure, or budget refusal leaves partial coverage |
| CSV | Existing public-data exports, with optional account-profile join | Completeness is unknown; stable IDs and provenance must come from the exporter |

For authenticated collection, create a local `.env` in the launch folder, or alongside a CLI config:

```dotenv
X_BEARER_TOKEN=your_token
BSKY_HANDLE=your_handle.bsky.social
BSKY_APP_PASSWORD=your_app_password
```

No credentials are required for the synthetic example or CSV imports. The UI shows unavailable sources. Provider capabilities, pricing, and permissions can change; consult [X search documentation](https://docs.x.com/x-api/posts/search-recent-posts), [Bluesky's canonical search schema](https://github.com/bluesky-social/bsky/blob/main/lexicons/app/bsky/feed/searchPosts.json), and [Mastodon timelines](https://docs.joinmastodon.org/methods/timelines/).

## What the detector does

It links accounts that repeatedly share normalized text, the same case-sensitive URL, or the same amplification target within a short interval. An edge must recur in at least three separate episodes on at least two UTC days by default. Connected groups need at least three accounts. Each edge retains its supporting events and posts.

Text/link observations from the same episode do not count as independent repetitions. Popular traces receive lower weight. Results include graph density, transparent ranking scores, and a reproducible within-day timing shuffle. These are exploratory diagnostics, **not calibrated CIB probabilities**. Open advocacy, syndication, emergency alerts, and legitimate campaigns can satisfy the same rules.

Also available: activity alerts, exact and near-text bursts, link matches, descriptive account observations, creation-date concentration, related hashtags, shared infrastructure, and cross-platform matches. Account age is measured at the event, and missing account data stays unknown. See [methodology](docs/methodology.md).

## Import CSV

Required columns: `timestamp_utc`, `handle`, `text`. Recommended: `post_id`, `author_id` (or `account_id`/`did`), `author_uri` for Mastodon, `link`, `content_type`, `referenced_post_id`, `lang`, `likes`, `reposts`, `replies`, and `in_reply_to`.

`content_type` may be `post`, `repost`, `reply`, or `quote`. `referenced_post_id` should identify the shared target for amplification analysis. `in_reply_to` can reference a post in the same CSV. Account profiles accept `handle`, `created_utc`, `followers`, `posts_total`, and optional stable IDs. Naive timestamps are interpreted as UTC; explicit offsets are converted to UTC. An absent post ID gets a deterministic content-based key, so edits without an ID appear as different records.

UI limits: 10 MB and 50,000 post rows; 1 MB profiles. Imports are validated before posts are stored. Only matching posts within the saved case interval appear in analysis. Try [synthetic-posts.csv](examples/synthetic-posts.csv) with phrase `water quality`, start `2026-10-29`, end `2026-11-05`. These nine invented posts demonstrate three recurring accounts; with no independent background, the shuffled timing comparison remains equally coordinated.

## CLI workflow

Copy `config.example.json` to `config.json`, edit its terms and sources, then:

```console
python -m topicstream run --config config.json
python -m topicstream report --config config.json
python -m topicstream watch --config config.json --every 15
python -m topicstream import-csv examples/synthetic-posts.csv --config config.json --source import
python -m topicstream import-csv posts.csv --accounts profiles.csv --config config.json
python -m topicstream discover --config config.json
python -m topicstream peak --config config.json --hours 1 --dry-run
```

`collect` collects without writing a report; `run` does both. `peak` attempts selected one-hour reads, keeping partial status until pagination ends. `estimate` may make paid counts requests when X credentials are present, guarded by the same budget. `usage` prints provider meter fields separately from the local ledger. `discover --add N` edits the config; automatic discovery is off in the examples.

For reproducible CLI reports, set `start_utc` and `end_utc`. Otherwise, collection uses a rolling `days` interval, while a retrospective report anchors its interval to the newest stored post. Use a new database when deliberately widening a rolling investigation into older history. See [migration](docs/migration.md).

## Budgets and interrupted work

Every X counts/search request reserves its maximum estimated cost before it is sent. A successful response settles against returned records. Interrupted or ambiguous calls retain the reservation. Completed X pages and their next token are saved in one transaction. Retry collection to resume a partial window; the newest observed ID never advances progress past uncollected pages.

The budget is **per database**, including other processes using that same database. Separate cases, tools, and applications have independent spending. It is not a provider-wide account cap or invoice guarantee. The default settlement estimate includes author-expansion charges from November 22, 2026, with full-page reservations covering them already. Successfully returned billable IDs are deduplicated within a UTC day, database, and credential scope. Before/after credit observations show account-wide movement separately. See [cost controls and reported measurements](docs/x-costs.md).

Reports show rows in analysis versus all stored rows in the interval, headline activity triggers, and posting-hour comparisons against both the full stored interval and each available X query's hourly counts. Detailed pair and post evidence is collapsible, with working evidence links, a light theme, and expanded light-background printing. See [current synthetic report screenshots](docs/report-examples.md).

## Development and validation

```console
python -m unittest discover -s tests -v
python -m compileall -q topicstream
```

Tests are offline, except for loopback HTTP used to test the local UI API. The optional course export test skips unless `TOPICSTREAM_SAMPLE_CSV` points to that dataset. CI checks Python 3.9 and 3.12 on Windows and Linux. See [validation](docs/validation.md), [architecture](docs/architecture.md), and [remaining work](docs/roadmap.md).

This release has synthetic validation, mocked API-shape tests, and a [live X pilot on Singapore haze](docs/live-pilot-2026-11-05.md). The pilot exercised authenticated counts/search, pagination resume, full-length posts, analysis, and reporting. It has not established real-world precision/recall. Provider billing reconciliation and live Bluesky/Mastodon acceptance remain to be checked.
