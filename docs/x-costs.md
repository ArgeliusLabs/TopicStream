# X costs and collection coverage

`budget_usd` limits the accumulated local estimate in one database, including prior runs, pending reservations, and unresolved requests. It is not an account-wide cap or an authoritative provider invoice. Old ledger entries are retained unchanged when upgrading.

## Pricing assumptions in 0.3.3

Default rates are `post_read: 0.005`, `user_read: 0.010`, `counts_recent: 0.005`, and `counts_all: 0.010` USD, with **`bill_author_expansions: "auto"`**. Automatic settlement estimates omit author-expansion charges before November 22, 2026 and include them from that date. The policy is evaluated for each request, including in a running collector; the post's creation date and the case's historical dates do not determine its read price.

The published post/user/count rates come from [X pricing](https://docs.x.com/x-api/getting-started/pricing), checked November 5, 2026. The project maintainer also supplied an X PPU notice stating that expanded objects are currently unbilled but become billable at their standard resource rate **from November 22**. That notice is the source for the transition date; the public pricing/expansions pages checked on November 5 did not state that date. The notice does not specify a timezone, so midnight UTC is an estimation convention, not a claim about the provider's exact cutover instant. Reservations already cover the higher rate.

The notice lists expanded posts at $0.005, users at $0.010, and media, polls, and places at $0.005 each. TopicStream requests **only `author_id` expansions**; it makes no explicit users-endpoint calls and requests no media, poll, place, or referenced-post expansions. Its existing daily resource tracking also deduplicates billable authors within the same local scope. Reducing `user.fields` alone does not remove the returned user object; the current fields supply account age, display name, and public metrics used in investigation. [X expansion mechanics](https://docs.x.com/x-api/fundamentals/expansions).

Set `bill_author_expansions: true` to estimate author charges immediately. Legacy `false` from 0.3.2 now follows the automatic date policy too: it cannot silently disable charges after the announced change. Custom numeric rates remain configurable. No historical ledger entries or pilot totals are retroactively repriced.

```json
{
  "enabled": true,
  "budget_usd": 2.0,
  "max_posts_per_tag": 100,
  "query_extra": "",
  "archive": false,
  "read_mode": "always",
  "prices": {
    "post_read": 0.005,
    "user_read": 0.010,
    "counts_recent": 0.005,
    "counts_all": 0.010,
    "bill_author_expansions": "auto"
  }
}
```

Search reserves the full requested page price before HTTP, without assuming duplicate results. **Reservations include author charges even before November 22**, so an in-flight request crossing the transition is covered. At the default rates, a 100-post page with author expansions needs $1.50 available. Ten new posts with six new author profiles settle to $0.05 before the change and $0.11 from it; `true` uses the latter estimate immediately. A request spanning the cutover settles at the higher rate, without seeding daily deduplication across midnight. Unsupported expansion types are rejected. Recent search's minimum page size is 10, so a smaller cap remains a soft limit and the reservation covers all 10. [X search parameters](https://docs.x.com/x-api/posts/search-recent-posts).

For scale, 100 new posts by 100 new authors cost an estimated $0.50 before the change versus $1.50 after it, excluding counts. Repeated authors can lower that total through daily deduplication; three times the post-only rate is an illustrative worst case for this one-author-per-post expansion, not a universal multiplier for every investigation.

Successful search responses settle only newly observed resource IDs within the **same UTC calendar day**, across queries and restarts in the same database and credential scope. The resource record and settlement are atomic. This implements X's documented daily deduplication, which X describes as a soft guarantee. It resets at midnight UTC, **not on the monthly billing day**. Monthly usage reset fields do not define the deduplication interval.

This is a local approximation: another database, another credential, or another tool may already have read the same resource. Those reads are unknown here, so the estimate can be higher. Token rotation starts a new local scope. Imported rows and pre-0.3.2 ledger entries do not establish when the provider billed a resource. Missing IDs and requests crossing UTC midnight are conservatively charged without seeding daily deduplication. Counts remain charged per request. No raw credential is stored in the resource ledger or evidence export.

An ambiguous failure retains the full reservation. Hidden paid HTTP retries are disabled; a field-name compatibility retry reserves separately. A zero rate is allowed for explicit mock/free use but cannot protect a paid account from an incorrect configuration. Keep provider spending controls enabled independently.

## Measured account observations — November 4–5, 2026

These are **operator-reported developer-console totals and request inventories**, supplied in feedback on November 5. They are useful evidence, but the underlying invoice has not been independently inspected here.

| UTC date | Reported activity | Arithmetic at the post/count rates | Reported console total |
| --- | --- | --- | --- |
| November 4 | 2,865 new posts; 13 archive counts; 10 recent counts; author expansions | `2865 × $0.005 + 13 × $0.010 + 10 × $0.005 = $14.505` | $14.51 |
| November 5 | 820 archive posts plus 285 distinct haze posts; same-day reread of those 285; 2 recent counts; author expansions | `(820 + 285) × $0.005 + 2 × $0.005 = $5.535` | $5.53 |

The November 4 arithmetic rounds to the reported total. The November 5 arithmetic is **$0.005 above** the stated console figure and would conventionally round half-up to $5.54. That small discrepancy remains unresolved; these numbers are not an exact reconciliation to the cent. Both inventories support omitting a separate expansion charge and applying same-day resource deduplication on this account. They do not demonstrate month-long free rereads or guarantee every account's pricing.

The haze-only allocation inferred from the reported inventory is `285 × $0.005 + 2 × $0.005 = $1.435`, or **about $1.44** using half-up cents. It is an inferred allocation, not a separately verified pilot debit. The historical 0.3.1 local estimates were **$4.02 initially and $7.98 including verification**: that model counted expanded authors and duplicate reads again. These historical entries remain visible for audit, alongside the corrected interpretation. See the [pilot](live-pilot-2026-11-05.md) and [public sample](examples/singapore-haze/report.md).

The subsequent provider notice supports the explanation for unbilled expansions on November 4–5. Its November 22 change does not alter those historical runs; their figures must not be used as a post-change price quote. It also does not resolve the half-cent discrepancy or establish an invoice-confirmed pilot allocation.

## Account balance observations

Collection and actual `peak` reads attempt the [credit-balance endpoint](https://docs.x.com/x-api/usage/get-usage-credits) before and after X work. Failures do not prevent collection. Snapshots stay in the local database and are excluded from evidence exports. Logs print the local run estimate alongside the **observed account balance decrease**; `usage` also prints the latest recorded comparison.

This delta is not automatically a reconciled run charge: other tools, delayed charges, grants, credits, or top-ups can affect it. A negative value means the balance increased. Where both components are available, the comparison uses prepaid plus free funds; a clipped zero total alone cannot establish the change in a negative prepaid balance. Missing or unusable readings are reported as unavailable. A zero immediate difference does not prove a free run.

## Collection choices

`estimate` can make paid counts probes when credentials exist; it uses the same guarded ledger. `peak --dry-run` is offline and describes windows already represented in stored counts. `usage` reads provider meter fields separately from estimates.

`read_mode: on_alert` monitors counts and requests closed hours that trip a rule. Partial windows remain retryable; exhausted windows for the same query are skipped. `window_cap` bounds each pass. Full-archive access depends on the account. `sample_per_day` is a newest-first quota sample, not random sampling. No capped interval establishes complete topic coverage, and a count/search discrepancy has no assumed cause.

To increase a case budget or change price assumptions, stop the server, edit its `config.json`, and restart. Raising the cap does not erase prior spending. Do not delete ledger entries to force collection; investigate unresolved reservations against provider records.
