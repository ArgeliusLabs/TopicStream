# Sample investigation report: Singapore haze

**TopicStream by Argelius Labs · Early research release · November 5, 2026**

> **Finding:** No strong recurring coordination detected in the observed data at the selected settings. Inauthenticity remains unresolved; public behavior alone does not establish deception.

This public report summarizes a real X collection analyzed with TopicStream 0.3.1 and detector `recurrence-1`. It is an edited, aggregate walkthrough, not the application's complete evidence export. It demonstrates how to read a result, including one where no group passes the detector's thresholds.

## Investigation scope

The question was whether accounts repeatedly acted together in the collected discussion of Singapore's haze situation. The [NEA November 4 advisory](https://www.nea.gov.sg/media/news/advisories/index/haze-situation-update-4-november-2026) supplied the topic context; it did not allege an influence operation.

| Setting | Value |
| --- | --- |
| Source | X recent search |
| Query | `"haze" (Singapore OR Singapura OR 新加坡)` |
| Start, inclusive | October 30, 2026 at 17:26:08 UTC |
| End, exclusive | November 5, 2026 at 17:26:08 UTC |
| Duration | Six days, spanning seven UTC calendar dates |
| Language filter | None; the query still requires the English word `haze` |

## What was collected and analyzed

| Measure | Result |
| --- | ---: |
| Matches reported by X's counts endpoint | 320 |
| Distinct posts retrieved | 285 |
| Text-matching posts analyzed | 284 |
| Accounts in the analysis | 238 |
| Reposts among analyzed posts | 84 |
| Other analyzed posts | 200 |
| Short-window co-amplification events | 4 |
| Recurring account-pair edges | 0 |
| Groups meeting the recurring-group thresholds | 0 |

Search pagination ended after 285 distinct posts. The difference from the 320 reported matches remains unresolved. Exhausted pagination describes the requests made; it does not establish complete coverage of the topic. One retrieved result matched through a URL rather than its text and was excluded by the local text filter.

### Observed activity over time

These are analyzed posts per UTC date, including reposts. They measure activity in this dataset, not the prevalence of coordination.

| UTC date | Analyzed posts | Portion of date within scope |
| --- | ---: | --- |
| October 30 | 12 | From 17:26:08 |
| October 31 | 31 | Full day |
| November 1 | 36 | Full day |
| November 2 | 47 | Full day |
| November 3 | 76 | Full day |
| November 4 | 49 | Full day |
| November 5 | 33 | Before 17:26:08 |
| **Total** | **284** | |

The busiest observed date was November 3. The first and last dates cover fewer hours, so their raw totals should not be compared as equal-duration daily rates. An activity peak alone is not a finding of coordination.

## Why four brief clusters did not become a recurring group

The detector searched for shared normalized text, URLs, and amplification targets within **10-minute windows**. Its episode-gap setting was **60 minutes**. A qualifying account-pair edge had to appear in at least **three independent episodes** across **two UTC days**; a connected group needed at least **three accounts**. See the [methodology](../../methodology.md) for the exact rules.

The four co-amplification events show people reposting the same targets close together in time. No account pair met the recurrence requirements. Consequently, there are no recurring groups or recurring-network edges to display for this run. The individual events should not be presented as four influence operations: ordinary news sharing or openly organized activity can produce similar observations.

Five seeded timestamp shuffles also produced zero recurring edges. That comparison is an exploratory diagnostic, not a significance test, CIB probability, or accuracy measurement. This pilot provides no independently labeled ground truth with which to classify the result as a true negative.

## Cost and workflow observations

The initial collection's local estimate was approximately **US$4.02**. A verification reread to recover full-length text brought the cumulative estimate to **US$7.98**, across two counts requests and seven search pages. These estimates include returned author profiles and repeated resources without assuming provider deduplication. They are not a reconciled X invoice or a price guarantee for another run.

Requesting full text recovered **17 relevant posts** that shortened previews had excluded, without adding new post IDs. The pilot also led to fixes for author-profile cost accounting and the report's partial first-day chart. The [technical pilot notes](../../live-pilot-2026-11-05.md) explain these changes and the incomplete billing reconciliation.

## Interpretation and next steps

This result supports only the finding stated at the top, for this query, time interval, platform, dataset, and configuration. It does not show that Singapore's haze discussion is free of coordinated inauthentic behavior. The search did not comprehensively cover other languages, other platforms, private or deleted material, image-only content, or activity outside the interval. It also leaves the counts/search discrepancy unresolved.

A broader investigation could review additional local-language terminology, expand the period and source coverage, and compare findings against legitimate campaigns and independently annotated coordination cases. These are suggested follow-up investigations; they have not been run as part of this example.

## Public summary and reproducibility

The [aggregate summary JSON](summary.json) contains the published counts, daily totals, settings, and rounded cost estimates. It is a documentation companion, not an importable case or a substitute for the underlying evidence. Raw posts, account identifiers, credentials, provider balances, and analyst evidence are not included. The full case stays local, so readers cannot independently reproduce the account-level analysis from this summary alone. A later API query may return different data or require archive access.

To explore a detected group and follow its supporting evidence yourself, start TopicStream and choose **Explore a synthetic example**. That uses explicitly invented data without API credentials or charges. See [getting started](../../../README.md#start-the-workspace).
