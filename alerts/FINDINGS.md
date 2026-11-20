# Findings — what the swing data actually says

Numbers below are produced by `python3 scripts/scan_swings.py` in this repository and published to
`data/swings/*.json` + `alerts/model.json` by the `Swing scan (alert console data)` workflow.
The live table in §3 is the run `44809090393` (2026-11-20T20:18:30Z, commit `da3ef92`); re-generate
anything with the commands in [SPEC.md](SPEC.md). Every row of every table on the page links the API
request that produced it, so nothing here has to be taken on trust.

## 1. Headline result

**No strategy has positive expectancy on the demo feed at the thresholds in the brief, so the
high-ROI chat is empty by design, not by accident.** That is the single most useful thing this page
can tell you, and it is why the ROI gate requires a *post-fee* edge rather than a raw reversion rate.

Two methodology bugs found while building this — both of which would have made the console look
profitable when it is not — are fixed and pinned by tests:

1. **Reversion was measured over the whole rest of the series**, not inside the stated horizon.
   A price that drifts back 9 hours later counted as a "60-minute reversion". The published figure
   under that bug was a reversion rate of **0.952703**; with the horizon enforced it is
   **0.873563** on the same style of data — a 7.9-point inflation that would have looked like an edge.
   `measure()` now selects the forward window by timestamp (`ts <= alert_ts + horizon_minutes*60`),
   keeps the unbounded figure separately as `reversion_hit_ever`, and publishes
   `candles_in_horizon` per row (e.g. a 1-minute series gives 57 candles inside a 60-minute horizon,
   a 60-minute series gives 1) so the reader can see the horizon was real.
   Pinned by `TestOutcomes.test_reversion_is_horizon_bounded`.
2. **Fee units were mixed** (per-contract vs per-block), and the bucket edge used a single
   hand-picked strategy. `fees_dollars`/`net_dollars` are now per contract, `fees_block_dollars` per
   100-contract block, and `roiScore` scores the *best measured strategy in that bucket* and only
   passes when that best value is above zero.

## 2. Offline self-test (deterministic, no network — the committed snapshots)

`python3 scripts/scan_swings.py --offline --out /tmp/x` → 12 market units, 256 rows, 64 swings
≥ $0.10 in a 60-minute window, 2 events, 0 requests, 0 errors. (An offline run pointed at the default
`--out` now refuses to write, because `data/swings/**` and `alerts/model.json` are the published
**live** feed — a self-test must not masquerade as it.)

| strategy | n | quotable | mean net $/contract | median net | hit rate | mean ROI on paid | total net |
|---|---|---|---|---|---|---|---|
| `fade15` | 64 | 33 | −0.273585 | −0.0015 | 0.0 | −0.478833 | −9.0283 |
| `fade60` | 64 | 38 | −0.237784 | −0.0015 | 0.0 | −0.468581 | −9.0358 |
| `fade_settle` | 64 | 46 | −0.249115 | — | 0.0 | −0.500903 | — |
| `momo60` | 64 | 50 | −0.409026 | — | 0.0 | −0.554516 | — |

Offline buckets (shrunk toward the global rate, pseudo-count 4):

| bucket | n | markets | evidence | reversion (in horizon) | shrunk | best strategy | best mean net |
|---|---|---|---|---|---|---|---|
| `elections\|0-5c\|>40c\|>14d` | 32 | 6 | sufficient | 0.84375 | 0.838542 | `fade_settle` | −0.307669 |
| `elections\|80-95c\|>40c\|>14d` | 32 | 3 | sufficient | 0.75 | 0.755208 | `fade60` | −0.185614 |

Read that carefully: prices **do** revert (75–84 % of swings retrace into the anchor band inside the
hour), and the fade still loses money, because the entry price after a jump is already through the fair
value and the taker fee is paid twice. `hit_rate` is 0.0 — no measured exit produced a positive
net — which is exactly what the gate needs to see to refuse a pick.

## 3. Live scan (GitHub runner, real demo API) — 2026-11-20T20:18:30Z

`mode=live` · 60 markets scanned (12 per topic × 5 topics, ranked by the labelled est. dollar volume)
· **174 swings ≥ $0.10** in a 60-minute window across **3 events** (153 `elections`, 21 `crypto`;
`gas`, `culture` and `golf` produced none in this window) · 122 requests · **0 errors** · 8 series
records read for settlement sources and fee multipliers.

| strategy | n | quotable | unquotable | mean gross $/contract | mean net $/contract | hit rate | mean ROI on paid | total net |
|---|---|---|---|---|---|---|---|---|
| `fade15` | 174 | 88 | 86 | −0.248477 | **−0.252375** | 0.0 | −0.477032 | −22.209 |
| `fade60` | 174 | 93 | 81 | −0.295516 | **−0.300043** | 0.0 | −0.525557 | −27.904 |
| `fade_settle` | 174 | 113 | 61 | −0.193487 | **−0.196657** | 0.0 | −0.448607 | −22.2222 |
| `momo60` | 174 | 115 | 59 | −0.486087 | **−0.492957** | 0.0 | −0.619288 | −56.6901 |

Global reversion rate inside the 60-minute horizon: **0.873563**. Buckets:

| bucket | n | markets | evidence | reversion | shrunk | best strategy | best mean net $/contract |
|---|---|---|---|---|---|---|---|
| `crypto\|0-5c\|>40c\|>14d` | 9 | 2 | insufficient | 0.888889 | 0.884173 | `momo60` | −0.9628 |
| `crypto\|5-20c\|>40c\|>14d` | 2 | 1 | insufficient | 1.0 | 0.915709 | `fade15` | −0.0174 |
| `crypto\|95-100c\|>40c\|>14d` | 10 | 1 | insufficient | 0.7 | 0.749589 | `fade15` | −0.0121 |
| `elections\|0-5c\|>40c\|>14d` | 74 | 7 | **sufficient** | 0.851351 | 0.85249 | `fade_settle` | −0.12068 |
| `elections\|80-95c\|>40c\|>14d` | 79 | 5 | **sufficient** | 0.911392 | 0.909569 | `fade15` | −0.208898 |

Two buckets clear the evidence bar and both have a negative best-case expectancy; three do not clear
it at all. So the gate rejects every alert, and the "why" line on each dimmed row says so
(`no calibrated bucket for this setup` / the bucket's negative `best_mean_net_dollars`).

The interesting rows are the near-breakeven crypto ones: at 5–20 c and 95–100 c the taker fee is only
a fraction of a cent per contract (`0.07·P·(1−P)` is smallest at the extremes), and gross is already
negative — **the loss is the spread being crossed, not the commission**. That is why the console shows
`spread_dollars` and the size at touch next to every alert instead of a profit number.

## 4. What the live run could not answer (recorded, not hidden)

* **Resolutions: 0 of 174.** Every swing in this run sits on a market that is still `active` with a
  future close (the tracked crypto strikes close 2027-01-01T05:00Z; the election nominations later
  still), so `result`, `settlement_ts`, `settlement_value_dollars` and `resolved_after_swing` are
  legitimately empty. The register fills when the console is open at settlement (live re-poll) or from
  the collector's historical sweep (`data/latest/resolutions.json`). Nothing was back-filled to make
  the column look complete.
* **`event_title` is empty on all 174 rows**, because the collector snapshot of
  `GET /markets` does not carry that field; the row links its own API request instead
  ([get-markets](https://docs.kalshi.com/api-reference/market/get-markets.md)).
* **Event pages are `not confirmed`.** The CI probe got `https://kalshi.com/event/KXBTCY-27JAN0100` →
  **HTTP 429** and `https://demo.kalshi.co/event/…` → **404**, so no `kalshi.com/event/...` link is
  rendered as verified anywhere. That is the documented policy, not a missing feature.
* **Half the exits are unquotable** (86/174 for `fade15`): the candle series has no bid/ask on the exit
  side, and those rows are published as `{"status": "not-quotable", "note": "no bid/ask in candle data
  for that side"}` rather than being priced at the close.

## 5. Structural findings worth recording

* **The universe is thin at the short end.** 1-minute candle history for demo markets returns a few
  hours at best for most series; pre-cut-off settled markets need
  `GET /historical/markets/{ticker}/candlesticks` ([candlestick docs](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md)),
  which is not collected. So the 5–10 minute window options on the console are backed by *this session's*
  live samples, not by history — the chart says "0 points" honestly instead of back-filling.
* **Depth is bid-only and single-sided in the demo books.** `GET /markets/orderbooks`
  ([docs](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md)) returns bids
  ascending; a YES ask at *p* is the mirror of a NO bid at 1−*p*
  ([order-book responses](https://docs.kalshi.com/getting_started/orderbook_responses.md)). Inventing a
  mid price for the missing side would have turned a 0 % hit rate into a flattering one.
* **MVE and synthetic series must be excluded.** Hourly demo series (`KXDEMOFUTHOURLY*`),
  `KXQUICKSETTLE*` and market-vs-event combos produce mechanical ±$0.10 prints on every expiry; they
  are excluded by prefix in both runtimes and the exclusion is reported as a reason.
* **Est. dollar volume is an estimate.** The API publishes `volume_fp` and `notional_value_dollars`
  but no dollar volume, so ranking is `volume_fp × notional` and every table that uses it labels the
  column "(estimate)" ([market fields](https://docs.kalshi.com/api-reference/market/get-markets.md)).
* **The exchange names its own catalysts.** `GET /series/{series_ticker}` publishes
  `settlement_sources[]`; on the tracked topics that is ICE (WTI), the Republican and Democratic
  parties (nominations), the Academy (Oscars), CF Benchmarks (crypto) and PGA TOUR / Fox / ESPN
  (golf). Linking those is a fact; linking a headline to a jump is an inference, and the console only
  ever offers the latter as a labelled candidate search.
* **Settlement can disagree with the screen.** Per the
  [CRYPTO contract terms](https://assets.kalshi.com/contract_terms/CRYPTO.pdf), the underlying is a
  60-second simple average of the CF index *before* the stated time, "between X and Y" includes both
  endpoints, and *"If no data is available or incomplete on the Expiration Date at the Expiration Time,
  then affected strikes resolve to No"* — a demo price that looks inside a band on a chart can still
  resolve No.

## 6. Irregularities spotted (flagged, not smoothed over)

| # | what | evidence |
|---|---|---|
| 1 | `data/latest/candles.json` carries window labels `1h_7d` / `1m_2h`, which contradict `collector/collect.py::CANDLE_RANGES`; the file's own meta therefore cannot be trusted for "what window was requested". The console ignores those labels and builds its own request URLs. | compare `data/latest/candles.json` with `collector/collect.py` |
| 2 | The CRYPTO contract-terms template prints an expiration time of **10:00 AM ET** while the live market rule text for `KXBTCY-27JAN0100-B122500` says **12 AM EST**; `<time>` is a per-iteration placeholder, so the template must not be read as the market's own deadline. | [CRYPTO.pdf](https://assets.kalshi.com/contract_terms/CRYPTO.pdf) vs the market's `rules_primary` |
| 3 | `KXWTIMAX`'s named settlement source is `https://www.ice.com/report/10`, which is the ICE Futures **Europe** end-of-day report index; WTI front-month settles on NYMEX/CME, so "ICE reports the WTI front-month settle" cannot be verified at that URL alone. The console links it because the API names it, and says so. | live `GET /series/KXWTIMAX` (2026-11-20) + that page |
| 4 | `fetch_page` of `kalshi.com/event/{ticker}` and `demo.kalshi.co/event/{ticker}` fails from this sandbox (429 / refused), and the CI probe gets 429/404 as well, so event-page links stay "not confirmed" everywhere. | `event_page_probe` in `data/swings/meta.json` |
| 5 | `gh api`/`gh run` returned HTTP 403 ("API rate limit exceeded for user ID 309443653") for ~15 minutes; the corrected scan had to be dispatched in a retry loop, and two push-triggered runs were cancelled by `cancel-in-progress` before it. Data published here comes from the run that completed. | this session, `gh run list` |
| 6 | The platform forces the branch name `arena/5ab18dc3-demo3` instead of the coordination protocol's `session-<id>/<task>`; recorded as prior sessions did. | `COORDINATION.md` |
| 7 | A `git stash -u` of my own untracked work (before pulling a CI data commit) temporarily removed `assets/alerts.js`/`alerts.css`; recovered from `stash@{0}^3`, re-verified with `node --check` + the jsdom smoke test. Lesson recorded in `COORDINATION.md`: commit WIP before stashing/pulling on this branch. | `git stash list` at the time |
| 8 | `alerts/model.json` currently carries an `alert_rule.definition` string from an earlier revision ("max … for up"), which does not describe the implemented rule (up is measured off the window **low**). The code is corrected; the published string updates on the next scan run, and both runtimes' behaviour was always pinned by the shared reference vectors, not by that sentence. | `git log -p scripts/scan_swings.py`, `tests/swing_core.test.js` |
| 9 | Another session's collector bot pushed `data: refresh snapshot 2026-11-20T20:04Z` to this branch mid-work; merged without discarding it (`86d9f67`), and my restored live scan data sits alongside it. | `git log` on this branch |

## 7. Review trail

* `python3 scripts/tests/test_scan_swings.py` → 13 tests, OK.
* `node --test tests/swing_core.test.js` → 11 tests, pass (rule vectors, fee table, bucket key, ROI gate).
* `node --test tests/alert_console.test.js` → 4 tests, pass (jsdom smoke test of the real page with a
  mocked API: boot, universe rows all source-linked, alert fires once across a re-armed leg, chart +
  depth + fills + catalyst panel render, resolution recorded exactly once).
* `npm test` → 41 tests, 0 failures (the new tests run beside the existing suite).
* `python3 scripts/build_root_site.py && python3 scripts/verify_root_site.py` → **0 failures**
  (`alerts.html` in `PAGES`, `assets/alerts.js` + `assets/swing-core.js` in the `node --check` list).
* `python3 scripts/check_site.py` → passes.
* The irregularities in §6 are published on `flagged.html` as I-18…I-24, per the session protocol;
  "needs review" items do not block the merge, they are listed there with their sources.
