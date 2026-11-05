# What X costs, in detail

Rates as of 4 November 2026, from the X developer console's pricing page, checked against a real invoice the same day. X has changed this twice in 2026; check the console before you budget.

## The rate card

X retired its Free, Basic and Pro tiers in February 2026 and moved everyone to pay-per-use. There is no subscription and no minimum. You add a card, you get $20 in credit after your first purchase, and then the meter runs. For reading public posts, four prices matter:

| What | Price | Notes |
|---|---|---|
| A post returned by search | $0.005 | `GET /2/tweets/search/recent` (last 7 days) or `search/all` (back to 2006). Same price either way. Metered per unique post per billing cycle (below). |
| One counts request, recent | $0.005 | `GET /2/tweets/counts/recent`: the number of matching posts per minute, hour or day, for up to 7 days, in one response. |
| One counts request, full archive | $0.010 | `GET /2/tweets/counts/all`: the same for any period back to 2006. |
| Monthly ceiling | 3,000,000 post reads | $15,000 at list price. Past that, Enterprise. |

Things that cost nothing in practice: the author objects that come back with each post when you ask for `expansions=author_id` (the invoice matched posts plus counts requests, with nothing left over), the usage endpoint, pagination (you pay for posts, not pages), and errors.

For context, the tiers this replaced were Basic at $200 a month for 10,000 reads (two cents a post) and Pro at $5,000 a month for a million reads (half a cent a post). Pay-per-use is Pro's unit price with no floor. If you read fewer than a million posts a month, which is almost everyone, you are paying less than you would have under either tier.

## Why counting is cheap and reading is expensive

The counts endpoint returns an aggregate: how many posts matched your query in each bucket. One request, one price, regardless of whether the answer is 12 posts or 12 million. A seven-day series by the hour for one term is one request and costs half a cent, and it counts every post whether or not you ever read one.

Search returns the posts themselves, and you pay for each one. Reading posts is the only way to learn who posted them, what they linked to, how old the account is, how many likes it got. It is also the only way to run the analysis that matters for coordination work (originating accounts, uses per account, co-occurring tags, same-text bursts). So the shape of any sane budget is: count everything, read selectively.

Two consequences follow. First, the volume series is never the thing you economize on; it is the cheapest, most complete data you will get, and it tells you where to spend. Second, every dollar of reads should be aimed by the counts: at the hour that spiked, at the term that moved, not spread evenly over a quiet week.

## How the meter actually works

Measured on 4 November 2026 and confirmed against the invoice:

- X meters unique posts per billing cycle. Reading the same 20 posts again from a fresh database did not move the meter. Reading 20 posts of which 14 had never been read moved it by exactly 14. The console then showed $14.51 for the day, which is 2,865 unique reads at $0.005 plus 13 full-archive counts requests at a penny and 10 recent counts requests at half a cent, to the cent.
- The tool's own ledger counts every post returned, so it is an upper bound: across the day it said $17.16. The difference is posts that matched more than one query (a post carrying both the hashtag and the phrase is returned by both searches, metered once) and the overlap between two samples of the same period.
- The meter lags a run by a minute or two, and by twenty minutes or more after a read of several hundred posts. `python -m topicstream usage` prints it beside the tool's ledger; every collection records the meter at its start.
- The API's minimum page is 10 posts, so any cap can be overshot by up to 9 posts per query.

The cycle resets on a fixed day of the month shown by the usage endpoint (`cap_reset_day`). A post read in two different cycles is metered twice.

## The formula

For a run over Q queries (each tag and each phrase is its own query):

```
counts   = Q x (day series + hour series) x price per request        # $0.01 per query recent, $0.02 archive
reads    = unique posts returned x $0.005                           # bounded by min(volume, max_posts_per_tag) per query
```

For `watch` mode, per day, with runs every R minutes and counts refreshed every C minutes:

```
counts per day = Q x (1440 / C) x 2 x price per request             # C = 60 by default: $0.24 per query per day recent
reads per day  = new unique posts across the day x $0.005           # since_id means a post is read once, ever
                 capped at (1440 / R) x max_posts_per_tag x Q x $0.005
```

The cap is the number to put in the budget. The real figure is the new-post volume, which the counts tell you in advance.

## Worked examples

All at list price, originals only (`-is:retweet`), recent search unless stated.

| Job | Arithmetic | Cost |
|---|---|---|
| Probe 8 candidate terms for their 7-day volume | 8 counts requests | $0.04 |
| Hourly series, 3 terms, one week | 3 x 2 requests | $0.03 |
| Hourly series, 3 terms, three weeks (archive) | 3 x 2 x $0.01 | $0.06 |
| One complete peak hour of 784 posts | 784 x $0.005 | $3.92 |
| Deep sample, 1,000 posts x 3 terms | 3,000 x $0.005 (+ $0.03 counts) | $15.03 |
| Three-week retrospective on PHP2Shell: 1 hashtag + 2 phrases, archive, complete hourly counts, stratified sample of 2,865 unique posts | 2,865 x $0.005 + 23 counts requests | $14.51 (invoice) |
| Reading every original post on those three queries | 48,059 x $0.005 | $240 |
| Reading everything on a term doing 40,000 posts a day | 40,000 x $0.005 | $200 a day |
| Daily digest: 3 terms, one run a day, up to 200 new posts a term | $0.03 + up to 600 x $0.005 | up to $3.03 a day, $91 a month |
| Live watch: 3 quiet terms (50 new originals a day each), every 15 min, counts hourly | $0.72 counts + 150 x $0.005 | about $1.47 a day, $44 a month |
| Live watch: 3 busy terms (500 new originals a day each), same cadence | $0.72 + 1,500 x $0.005 | about $8.22 a day, $247 a month |
| The ceiling | 3,000,000 reads | $15,000 a month, then Enterprise |

Two things stand out in that table. At the quiet end, the counts refresh is most of the bill, which is why the tool refreshes counts hourly in watch mode rather than every cycle (`counts_every_minutes`; at 15-minute refresh the same three quiet terms would cost $2.88 a day in counts alone, twice their reads). At the busy end, the reads cap is the only thing between you and a surprise, which is why `budget_usd` counts every run in the database and refuses to start one that could cross it.

## How the tool spends, in order

1. `estimate` buys one counts request per query and prints each query's volume for the window next to what reading all of it would cost and what your cap will actually read. Four terms, four cents, and you know whether this is a $3 job or a $300 one.
2. Every collection buys the day series and the hour series first, one request each per query, unless a series younger than `counts_every_minutes` is already stored.
3. Then it reads, up to `max_posts_per_tag` per query. After the first run it passes `since_id`, so only posts newer than the newest one stored come back and get metered. In sampling mode (`sample_per_day`) it instead reads the newest N posts from each four-hour window across the whole period, which covers a three-week event end to end for the same price per post.
4. Before reading, it adds what the database has already recorded to the worst case for this run and compares that with `budget_usd`. Over the line, X is skipped and the run log says so.
5. `usage` shows X's meter next to the ledger. The meter is what you will be billed for.

## Peak hours and the tripwire: where 0.2 changed the arithmetic

The sample in the retrospective above ($14.51) was the expensive way to answer the question. The counts series, which cost six cents, already said which hour mattered: 14:00 UTC on 21 October, 784 posts. Reading that hour complete is $3.92, and on a complete hour the coordination rules (bursts, leading edge, posts per account, who was there in the first ten minutes) are the record rather than an estimate from a 60-post-a-day sample. `peak --hours 2` buys the two busiest hours per term; `peak --at 2026-10-21T08:00` buys the hour the counts say it started.

```
peak, 2 busiest hours, 1 term:   784 + 206 posts x $0.005                     = $4.95 by the counts
same, 3 terms sharing the peak:  unique posts across the three queries x $0.005; a post carrying both the hashtag
                                 and the phrase is metered once, so usually well under 3x
```

Done for real on 5 November 2026 against the retrospective's database: the counts said 784 and 206, search returned 645 and 175, the tool's ledger said $4.10 and the meter moved by 762 unique reads, $3.81. The gap between counted and returned (18% and 15%) is posts the index still counts but search no longer serves, deleted or from accounts suspended since; on a vulnerability topic with bot traffic that is normal, and it is a number worth having. The two hours held 493 and 143 originating accounts at 1.2 posts each, which is what a story breaking looks like, not a push.

`read_mode: "on_alert"` does the same thing live. `watch` buys the counts series every `counts_every_minutes` and nothing else. When an hour trips a counts rule (absolute uses, a multiple of the average hour, or both), it buys that hour complete, once, and goes back to counting. The standing cost is the counts refresh:

```
tripwire, Q terms, counts hourly:   Q x 24 x 2 x $0.005 = Q x $0.24 a day      # 3 terms: $0.72 a day, $22 a month
first alerted hour:                 that hour's posts x $0.005                   # typically $1 to $5; a 4,000-post hour is $20
```

Set `budget_usd` to what you are willing to pay for the alerted hour; the tripwire refuses an hour that would cross it and says so in the run log, and the counts keep flowing.

Against the three ways of reading the same week:

| Approach | What you get | Three terms, one week |
|---|---|---|
| Counts only | complete volume series, velocity alerts, nothing about accounts | $0.03 once, $5.04 refreshed hourly for a week |
| Stratified sample, 60 posts a day a term | every day represented, timing approximate, bursts suggestive | $6.30 |
| Tripwire plus the alerted hour complete | complete volume series, and the hour that mattered with every post in it | $5.04 + the hour ($1 to $5) |
| Read everything | everything, most of it quiet | $0.005 x total volume: $240 for the retrospective's three queries |

## Ways to spend less

- `query_extra: "-is:retweet"` roughly halves a busy term. Retweet volume is visible in the `retweet_count` of the originals you do read.
- `lang:en` (or whichever language) in `query_extra` if you only read one.
- Combine terms with OR in a single phrase (`PHP2Shell OR CVE-2026-109618`) if you do not need a separate series per term: one counts request, and a post matching both is returned once.
- Buy the peak hour complete instead of sampling the week (`peak`). The counts tell you which hour; 784 posts is $3.92, and the rules that matter for coordination only hold on a complete window anyway.
- Watch in `on_alert` mode and let the counts decide when to read. Three terms around the clock are $0.72 a day until something happens.
- Let the free sources carry the baseline. Mastodon costs nothing and reports uses and originating accounts per day on its own; Bluesky costs nothing with an app password. Spend on X when the counts say X is where the event is.
