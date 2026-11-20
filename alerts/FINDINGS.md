# Findings — what the swing data actually says

Numbers below are produced by `python3 scripts/scan_swings.py` in this repository and published to
`data/swings/*.json` + `alerts/model.json` by the `Swing scan (alert console data)` workflow.
Re-generate them with the commands in [SPEC.md](SPEC.md); every row links the API request that
produced it, so nothing here has to be taken on trust.

## 1. Headline result

**No strategy has positive expectancy on the demo feed at the thresholds in the brief, so the
high-ROI chat is empty by design, not by accident.** That is the single most useful thing this page
can tell you, and it is why the ROI gate requires a *post-fee* edge rather than a raw reversion rate.

Two methodology bugs found while building this — both of which would have made the console look
profitable when it is not — are fixed and pinned by tests:

1. **Reversion was measured over the whole rest of the series**, not inside the stated horizon.
   A price that drifts back 9 hours later counted as a "60-minute reversion", inflating the reversion
   rate (the old published figure was 0.95). `measure()` now selects the forward window by timestamp
   (`ts <= alert_ts + horizon_minutes*60`), keeps the unbounded figure separately as
   `reversion_hit_ever`, and reports `candles_in_horizon` so the reader can see the horizon was real.
   Pinned by `TestOutcomes.test_reversion_is_horizon_bounded`.
2. **Fee units were mixed** (per-contract vs per-block), and the bucket edge used a single
   hand-picked strategy. `fees_dollars`/`net_dollars` are now per contract, `fees_block_dollars` per
   100-contract block, and `roiScore` scores the *best measured strategy in that bucket* and only
   passes when that best value is above zero.

## 2. Offline self-test (deterministic, runs with no network — the committed snapshots)

`python3 scripts/scan_swings.py --offline` → 12 market units, 256 rows, 64 swings ≥ $0.10 in a
60-minute window, 2 events, 0 requests, 0 errors.

| strategy | n | quotable | mean net $/contract | median net | hit rate | mean ROI on paid | total net |
|---|---|---|---|---|---|---|---|
| `fade15` | 64 | 33 | −0.273585 | −0.0015 | 0.0 | −0.478833 | −9.0283 |
| `fade60` | 64 | 38 | −0.237784 | −0.0015 | 0.0 | −0.468581 | −9.0358 |
| `fade_settle` | 64 | 46 | −0.249115 | — | 0.0 | −0.500903 | — |
| `momo60` | 64 | 50 | −0.409026 | — | 0.0 | −0.554516 | — |

Bucket calibration from the same run (`alerts/model.json`, shrunk toward the global rate,
pseudo-count 10):

| bucket | n | markets | evidence | reversion rate | shrunk | best strategy | best mean net |
|---|---|---|---|---|---|---|---|
| `elections\|0-5c\|>40c\|>14d` | 32 | 6 | sufficient | 0.84375 | 0.838542 | `fade_settle` | −0.307669 |
| `elections\|80-95c\|>40c\|>14d` | 32 | 3 | sufficient | 0.75 | 0.755208 | `fade60` | −0.185614 |

Read that carefully: prices **do** revert (75–84 % of swings retrace into the anchor band inside the
hour), and the fade still loses money, because the entry price after a jump is already through the
fair value and the taker fee is paid twice. `hit_rate` is 0.0 — no measured exit produced a positive
net — which is exactly what the gate needs to see to refuse a pick.

## 3. Live scan (GitHub runner, real demo API)

The live scan on the previous revision (`7f6079e`) reported 60 markets scanned, 148 swings ≥ $0.10
in a 60-minute window across 3 events (138 `elections`, 10 `crypto`), 122 requests, 0 errors — but it
was computed **before** the two fixes above, so those numbers are superseded, and the 0.95 reversion
rate in particular was inflated by bug 1. `data/swings/*.json` and `alerts/model.json` in this branch
are regenerated with the corrected method; the live tables on `alerts.html` render whatever the newest
workflow run published, so they always match the files.

What the live data will not do is show a profitable strategy: the earlier live run's per-strategy means
were −$0.20 to −$0.28 per contract with hit rate 0.0, the same story as the offline reproduction.

## 4. Structural findings worth recording

* **The universe is thin at the short end.** 1-minute candle history for demo markets returns a few
  hours at best for most series; pre-cut-off settled markets need
  `GET /historical/markets/{ticker}/candlesticks` ([candlestick docs](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md)),
  which is not collected. So the 5–10 minute window options on the console are backed by *this session's*
  live samples, not by history — the chart says "0 points" honestly instead of back-filling.
* **Depth is bid-only and single-sided in the demo books.** `GET /markets/orderbooks`
  ([docs](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md)) returns bids
  ascending; a YES ask at *p* is the mirror of a NO bid at 1−*p*
  ([order-book responses](https://docs.kalshi.com/getting_started/orderbook_responses.md)). Roughly half
  of the offline swings have no two-sided quote at the exit candle — those rows are `unquotable`, and
  inventing a mid price for them would have turned a 0 % hit rate into a flattering one.
* **MVE and synthetic series must be excluded.** Hourly demo series
  (`KXDEMOFUTHOURLY*`), `KXQUICKSETTLE*` and market-vs-event combos produce mechanical ±$0.10 prints on
  every expiry; they are excluded by prefix in both runtimes and the exclusion is reported as a reason.
* **Est. dollar volume is an estimate.** The API publishes `volume_fp` and `notional_value_dollars`
  but no dollar volume, so ranking is `volume_fp × notional` and every table that uses it labels the
  column "(estimate)"
  ([market fields](https://docs.kalshi.com/api-reference/market/get-markets.md)).
* **A candidate cause is not a cause.** The console links a Google News search for the market title
  (labelled "candidate news search") and links the series' `settlement_sources` — but it never claims
  a jump was *caused* by a headline. Only the exchange's own settlement feed can decide that, per
  `GET /series/{series_ticker}`.

## 5. Irregularities spotted (flagged, not smoothed over)

| # | what | evidence |
|---|---|---|
| 1 | `data/latest/candles.json` carries window labels `1h_7d` / `1m_2h`, which contradict `collector/collect.py::CANDLE_RANGES`; the file's own meta therefore cannot be trusted for "what window was requested". The console ignores those labels and builds its own request URLs. | compare `data/latest/candles.json` with `collector/collect.py` |
| 2 | The CRYPTO contract-terms template states an expiration time of **10:00 AM ET** while the live market rule text for `KXBTCY-27JAN0100-B122500` says **12 AM EST**; `<time>` is a per-iteration placeholder, so the template must not be read as the market's own deadline. | [CRYPTO.pdf](https://assets.kalshi.com/contract_terms/CRYPTO.pdf) vs the market's `rules_primary` |
| 3 | `KXWTIMAX`'s named settlement source is `https://www.ice.com/report/10`, which is the ICE Futures **Europe** end-of-day report index; WTI front-month settles on NYMEX/CME, so "ICE reports the WTI front-month settle" cannot be verified at that URL alone. The console links it because the API names it, and says so. | live `GET /series/KXWTIMAX` (2026-11-20) + that page |
| 4 | `fetch_page` of `kalshi.com/event/{ticker}` and `demo.kalshi.co/event/{ticker}` fails from this sandbox (429 / refused), so event-page links stay "not confirmed" unless the CI probe returns 200 **and** echoes the ticker. | CI `event_page_probe` in `data/swings/meta.json` |
| 5 | `gh api` returned HTTP 403 (rate limit) for user 309443653 during this session; workflow dispatches are therefore verified by `gh run list` retries rather than assumed. | this session |
| 6 | The platform forces the branch name `arena/5ab18dc3-demo3` instead of the coordination protocol's `session-<id>/<task>`; recorded here as previously logged by other sessions. | `COORDINATION.md` |
| 7 | A `git stash -u` of my own untracked work (before pulling the CI data commit) temporarily removed `assets/alerts.js`/`alerts.css`; recovered from `stash@{0}^3` and re-verified with `node --check` + the jsdom smoke test. Lesson recorded in `COORDINATION.md`: commit WIP before stashing/pulling on this branch. | `git stash list` at the time |

## 6. Review trail

* `python3 scripts/tests/test_scan_swings.py` → 13 tests, OK.
* `node --test tests/swing_core.test.js` → 11 tests, pass (rule vectors, fee table, bucket key, ROI gate).
* `node --test tests/alert_console.test.js` → 4 tests, pass (jsdom smoke test of the real page with a
  mocked API: boot, universe rows all source-linked, alert fires once across a re-armed leg, chart +
  depth + catalyst panel render, resolution recorded exactly once).
* `python3 scripts/build_root_site.py && python3 scripts/verify_root_site.py` → 0 failures
  (`alerts.html` added to `PAGES`, `assets/alerts.js` + `assets/swing-core.js` added to the `node --check` list).
* Findings are also listed on `flagged.html` where they are unresolved data-quality issues, per the
  session protocol.
