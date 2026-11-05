# Live pilot: Singapore haze

[Read the public sample report](examples/singapore-haze/report.md) for a reader-facing walkthrough, daily activity table, and downloadable aggregate summary. This page records the collection process, fixes, and remaining validation work.

On November 5, 2026, TopicStream completed an authenticated X collection and analysis of the current Singapore haze discussion. The topic was selected using the [NEA November 4 advisory](https://www.nea.gov.sg/media/news/advisories/index/haze-situation-update-4-november-2026). This tests the workflow on real data; it does not establish detection accuracy.

## Scope and outcome

- Query: `"haze" (Singapore OR Singapura OR 新加坡)`.
- UTC interval: October 30, 2026, 17:26:08 through November 5, 2026, 17:26:08, end exclusive.
- Platform: X recent search only. No language filter; the English word `haze` remains required.
- Counts endpoint: 320 reported matches. Search pagination exhausted after 285 distinct posts. The discrepancy is unresolved and is not evidence of manipulation or deletion.
- Final analysis: 284 text-matching posts from 238 accounts, including 84 reposts. One URL-only result was retained in storage but excluded from text-based analysis.
- Four short-window co-amplification events, no recurring account-pair edges, and no group meeting the default threshold of three accounts, three independent episodes, and two UTC days.
- Five seeded timestamp shuffles each produced zero recurring edges. This is a diagnostic comparison, not a probability or significance test.

The supported conclusion is **no strong recurring coordination detected in the observed data at these settings**. A few users sharing the same news or travel post within ten minutes did not satisfy the recurrence requirement. Neither this result nor exhausted API pagination proves the absence of CIB across the wider topic.

## Collection and cost observations

The first pass stopped at 250 posts with partial coverage. A second pass resumed the saved token and retrieved the remaining 35. The cap was raised from US$5 to US$10; actual local estimates were below both the final cap and the authorized limit.

Initial collection was approximately US$4.02 under the conservative local resource model. A full-text verification reread brought the cumulative estimate to **US$7.98**, across nine paid-endpoint requests: two counts requests and seven search pages. Every ledger request settled. The total includes rereads and repeated author profiles without assuming X's daily deduplication. It is not an invoice; an ordinary first run with full text would not require the verification reread.

The post-usage meter updated asynchronously. Credit-balance readings immediately before and after the verification reread were unchanged. A balance baseline was not captured before the initial collection, so an exact debit attributable to the entire pilot cannot be established from these readings. Account identifiers, balances, credentials, raw posts, and analyst evidence are retained locally and are not published in this repository.

## Fixes prompted by the pilot

1. Before paid requests, account for author-profile expansions as well as posts in reservations and settlements.
2. Request X's full-length note text and entities. This increased text-matching posts from 267 to 284 without adding new post IDs. Both legacy and current field names have regression coverage.
3. Expose the documented credit-balance endpoint in `usage`, keeping it distinct from estimated costs.
4. Calculate resource charges with decimal arithmetic before micro-dollar settlement.
5. Include partial first/last UTC days in report charts; the initial render omitted the first date's 12 posts from the daily chart, while analysis totals were correct.

## Remaining limits

This was one narrow, primarily English search over six days. It does not cover all Chinese/Malay/Indonesian wording, private or deleted content, other platforms, image-only claims, semantic paraphrases, or activity outside the interval. Full-text retrieval does not expand referenced original posts behind every truncated repost. The mismatch between counts and retrieved posts also remains visible. A future evaluation needs independently annotated positive cases and benign controls before any accuracy or CIB-detection claims are made publicly.
