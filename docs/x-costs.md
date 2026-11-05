# X costs and collection coverage

`budget_usd` limits the accumulated local ledger in one database, including prior runs, pending reservations, and unresolved requests. It is not a global limit across cases or an authoritative provider invoice.

The configurable defaults are `post_read: 0.005`, `user_read: 0.010`, `counts_recent: 0.005`, and `counts_all: 0.010` USD. These match [public X pricing](https://docs.x.com/x-api/getting-started/pricing) checked November 5, 2026. Verify account-specific rates and retain provider billing limits separately. Search includes `author_id` expansions, so the estimate budgets for returned author profiles as well as posts. The local ledger does not assume daily provider deduplication; repeated resources are conservatively counted again, so the estimate may exceed the invoice.

```json
{
  "enabled": true,
  "budget_usd": 2.0,
  "max_posts_per_tag": 100,
  "query_extra": "",
  "archive": false,
  "read_mode": "always",
  "prices": {"post_read": 0.005, "user_read": 0.010, "counts_recent": 0.005, "counts_all": 0.010}
}
```

Before every counts request, reserve its configured request price. Before every search page, reserve `max_results × (post_read + user_read)`, allowing one author profile per post. A successful page settles against returned posts and included users. Other expansion types are rejected until they have an explicit pricing model. An uncertain network/API failure retains its full reservation because a failed client response cannot prove the provider did not bill. The ledger records endpoint, time, query hash, status, reservation, and settlement.

For example, at the supplied estimate, a page requesting 100 posts with author profiles requires $1.50 available before it is sent. Ten returned posts and six included profiles settle to $0.11 locally. A later page is refused if its maximum would exceed the remaining cap, even when the expected result count is smaller. X recent search's documented minimum page size is 10, so a configured cap smaller than 10 is a soft limit; the reservation still covers all 10. [X recent search parameters](https://docs.x.com/x-api/posts/search-recent-posts).

Paid requests have no hidden HTTP retry loop. A field-name compatibility retry is separately reserved and the first failed request remains uncertain. Other failures require another collection pass. Prices must be finite and nonnegative; zero is allowed for explicitly configured mock/free use and provides no spending protection against an incorrectly priced provider.

`estimate` is not always offline: when credentials exist it probes counts through the same guarded request path. `peak --dry-run` is offline and only describes windows already represented in stored counts. `usage` prints the provider post meter, [credit balance in USD](https://docs.x.com/x-api/usage/get-usage-credits) when accessible, and local estimate separately without promising reconciliation or unique-post billing semantics. Capture a balance before and after collection; meter updates may lag, and simultaneous activity from other tools can affect the comparison.

`read_mode: on_alert` monitors counts and requests each closed hour that trips a rule. Later qualifying hours are not suppressed by the first alert. Partial windows remain retryable; only exhausted windows for the same query are skipped. `window_cap` bounds each pass, and archive reads are selected for historical windows. Full-archive access depends on the provider account.

`sample_per_day` selects newest-first quota windows. It is not random or unbiased sampling. No sampled or capped interval is labeled complete topic coverage. A count/search discrepancy alone never establishes deletion, manipulation, suppression, or API fault.

To increase a case budget or change price estimates, stop the server, edit that case's `config.json`, and restart it. Raising a budget does not erase prior spending. Do not delete ledger entries to force collection; unresolved reservations should be investigated against provider records.
