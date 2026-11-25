# Current report examples

The first three screenshots show TopicStream **0.3.2**, captured November 5, 2026; the last four show the panels restored in **0.3.9** to **0.3.11**, captured November 25, 2026. All accounts, posts, counts, and collection-window records are invented demonstration data. They are not the Singapore pilot or a classroom export, and no API requests were made to generate them.

Reproduce the example from the checkout:

```console
python examples/build_report_demo.py --data-dir ./demo-cases
python -m topicstream serve --data-dir ./demo-cases
```

Open the printed report path directly, or open the case in the local workspace and select its HTML report. The example includes 342 stored rows, 198 rows in analysis, and a 21-account group with 210 recurring pairs. It deliberately illustrates a detected group; it is not an accuracy benchmark.

## Headline triggers and scope

Activity triggers show source/query, first window, observed posts or API matches, account counts where known, and rule provenance. Pair tables are collapsed, with the first 25 ranked pairs and a separate control for the rest. Every pair remains in the file.

![Synthetic report: headline activity rules and scope](report-alerts.png)

## Activity in the light theme

The theme toggle works offline. Daily activity remains scoped to the investigation; the separate posting-hour comparison uses all stored rows inside the bounds and the available query-specific hourly counts.

![Synthetic report: daily activity in the light theme](report-tag.png)

## Coverage and peak-window status

The invented capped-window example remains partial. It demonstrates how an unfinished collection is displayed; it is not a real purchase or provider response.

![Synthetic report: coverage and partial collection window](report-peak.png)

## A tag card: busiest window and top accounts

Each tag or term card opens with its totals, daily bars, and a sentence giving the first post, the peak day, a typical active day and the days with nothing. Then the busiest window with posts per account, and up to fifteen accounts that used the tag most, most posts first, with how many of those posts are reposts and what the platform says about each account: age at first post, followers and median likes. "Unknown" is shown where a profile was not collected.

![Synthetic report: busiest window and top originating accounts for a term](report-accounts.png)

## The account table

One row per account with at least three posts in the analysis: its signals, and the facts behind them (age, followers, lifetime posts, median likes, share of replies, share of posts with a link and the domain linked most, languages, and its own tightest eight hours). The key above the table states the rule for every signal that appears.

![Synthetic report: account observations with the facts behind each signal](report-account-table.png)

## Posting hours, two groups side by side

For accounts with two or more signals, the report sets their posts by UTC hour beside all stored posts, each as a share of its own total, and marks the tightest eight hours. The sentence above the chart gives the shares; a table under it has the counts.

![Synthetic report: posting-hour comparison](report-hours.png)

## Tracking tokens and shared domains

Under Shared links and related tags, the report lists each tracking token that three or more accounts carry on their links, with the accounts. The note under the table says what a shared token does and does not show.

![Synthetic report: tracking tokens carried by several accounts](report-tokens.png)

Evidence links expand their target event or post and its parent section. Printing expands all reference sections with a light background and black text, then restores the screen's collapsed state after printing. A large case can therefore produce many printed pages even when its on-screen report is compact.
