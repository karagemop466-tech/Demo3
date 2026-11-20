# Swing-alert console — specification

Session `5ab18dc3`, branch `arena/5ab18dc3-demo3`. Everything below is either (a) quoted from an
official Kalshi page that was fetched, (b) read out of a live demo-API response, or (c) computed by
`scripts/scan_swings.py` from files in this repository. Nothing is estimated silently: where a value
could not be confirmed the field is left empty and labelled `unverified`.

## 1. The alert rule (one implementation, two runtimes)

A *swing* is one leg of a price run on a single contract:

```
window(t_i)  = { samples with ts in [ts_i - window_minutes*60, ts_i) }   # strictly BEFORE i
up_move      = close_i - min(window.close)        # measured off the window LOW
down_move    = max(window.close) - close_i        # measured off the window HIGH
fire "up"    if up_move >= max(down_move, threshold)   # strongest leg wins; threshold = 1000 bits
fire "down"  if down_move >= max(up_move, threshold)
disarm       until |close_i - anchor| <= rearm_band    # 500 bits, so a one-way run prints once
skip         windows that start at or after the alert index (incomplete lookback)
```

* The window is expressed in **minutes**, never in candle counts, because the collector stores 1-minute,
  60-minute and 1440-minute series and a "24 bars" rule would mean 24 minutes or 24 hours depending on
  the file. `window_candles_for(window_minutes, interval_minutes)` converts, and is the only place the
  conversion happens.
* Prices are handled as **integer bits** (1 cent = 100 bits, $1 = 10 000 bits) because the API now
  speaks fixed-point dollars with 4 decimals
  ([fixed-point migration](https://docs.kalshi.com/getting_started/fixed_point_migration.md)).
* `$0.0999` does not alert, `$0.1000` does — pinned by `tests/swing_core.test.js` and
  `scripts/tests/test_scan_swings.py` against identical reference vectors, so the browser engine and
  the backtest cannot drift apart.
* Reference vectors (18 prices, 10-minute spacing, 60-minute window) produce exactly two alerts:
  index 5 `up` 5000→6000 bits (Δ1000) and index 17 `down` 8700→4000 bits (Δ4700). Both runtimes, and
  the incremental live tracker, must reproduce them.

## 2. Resolution tracking

Each swing row re-polls its own market record (`GET /markets?tickers=…`) so the register can answer
"did it resolve, when, and how": `status`, `result`, `settlement_ts`, `settlement_value_dollars`,
`resolved_after_swing`. A market that settles *before* the swing is recorded as such rather than being
silently dropped. Settlement semantics come from the exchange's own contract terms, e.g.
[CRYPTO.pdf](https://assets.kalshi.com/contract_terms/CRYPTO.pdf): *"If no data is available or
incomplete on the Expiration Date at the Expiration Time, then affected strikes resolve to No"* and
*"Between X and Y means greater or equal to X and less than or equal to Y"*.

## 3. Fee model (integer cents, both languages)

Per the published fee schedule (<https://kalshi.com/docs/kalshi-fee-schedule.pdf>), a taker pays

```
model_fee = ceil_to_6dp( M * 0.07 * C * P * (1 - P) )
```

* [Kalshi fee schedule PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf): general quadratic taker
  formula, `M = 0` for most series (so the fee is the quadratic term), maker `0.0175`; spot values
  P$0.50/C100 → $1.75, P$0.05 → $0.34, P$0.99 → $0.07.
* [Fee rounding](https://docs.kalshi.com/getting_started/fee_rounding.md): the model fee is rounded to
  6 dp, then cash is aligned to the member's cent grid — buyer rounds **up**, seller rounds **down**.
* The per-series multiplier and type are read from `GET /series/{series_ticker}`
  (`fee_type: "quadratic"`, `fee_multiplier: 1` observed on every tracked series on 2026-11-20);
  a non-default multiplier scales the 0.07 term rather than being assumed.

Implementation: exact integer numerators (`_num_units` / `numUnits`), 0 mismatches against all 21
worked cells of the published table, asserted from both test suites. `fees_dollars` and `net_dollars`
are **per contract**; `fees_block_dollars` is per 100-contract block.

## 4. The ROI gate

`roiScore(market, alert, model, now)` in `assets/swing-core.js` (the browser) — the CI scanner writes
the bucket statistics it reads.

| component | weight | source |
|---|---|---|
| `calibrated_edge` | 0.35 | the bucket's reversion rate, shrunk toward the global rate |
| `relative_move` | 0.20 | Δ / anchor price, saturating at 30 % |
| `executability` | 0.20 | bid/ask both present and crossed, spread ≤ 3 c |
| `liquidity_depth` | 0.15 | contracts at the touch vs the 100-contract block |
| `time_to_resolution` | 0.10 | closer to resolution scores higher (fees are per round trip) |

`pass` requires **all** of: `score ≥ 0.60`, `executability > 0`, `liquidity_depth > 0`, market not in
an excluded series, bucket `evidence == "sufficient"`, **and** the bucket's best measured strategy
having `best_mean_net_dollars > 0`. Bucket key:
`{topic}|{entry price band}|{move band}|{time-to-resolution band}`, e.g.
`elections|0-5c|>40c|>14d`.

Because the edge term is the *strategy's* post-fee expectancy and not the raw reversion rate, a bucket
where prices do revert but every measured exit loses money after fees is **not** a pick. On the current
demo data that is every bucket, so the ROI chat is legitimately empty and says so.

## 5. Strategies measured in the backtest

`fade15` (exit at the first close re-touching the anchor within 15 min), `fade60` (same, 60-min
horizon), `momo60` (ride the momentum 60 minutes), `fade_settle` (hold to resolution). Each exit is
quoted only when the candles carry a two-sided book (`yes_bid_close`/`yes_ask_close`); otherwise the
row is `unquotable` and is **never** filled with an assumed price. `not_measurable` counts rows whose
horizon ran past the end of the series. Reversion is scored **inside** the horizon only — measuring the
retrace over the whole remaining series was a real bug in an earlier revision and inflated the reported
reversion rate.

## 6. Live data flow (browser)

| what | endpoint | notes |
|---|---|---|
| universe | `data/latest/markets_open.json` snapshot, or `GET /markets?status=open&limit=1000&mve_filter=exclude` | 1000 is the documented max `limit` ([get-markets](https://docs.kalshi.com/api-reference/market/get-markets.md)); `mve_filter` excludes minimum-viable-event combos |
| prices | `GET /markets?tickers=…` | batched, ≤ 50 tickers/chunk; re-poll doubles as the resolution check |
| liquidity | `GET /markets/orderbooks?tickers=…` | 1–100 tickers/request ([docs](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md)); bids only, price ascending |
| fills | `GET /markets/trades?ticker=…` | ([docs](https://docs.kalshi.com/api-reference/market/get-trades.md)) |
| history | `GET /series/{series}/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval` | `period_interval ∈ 1,60,1440` ([docs](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md)); settled markets older than the retention cut-off need `/historical/markets/{ticker}/candlesticks` |
| what settles it | `GET /series/{series_ticker}` | `settlement_sources[].{name,url}`, `contract_terms_url`, `fee_*` ([docs](https://docs.kalshi.com/api-reference/market/get-series.md)) |
| calibration | `alerts/model.json`, `data/swings/*.json` | written by the `Swing scan` workflow |

Rate limits: the [documented buckets](https://docs.kalshi.com/getting_started/rate_limits.md) cover
authenticated traffic (most requests 10 tokens, Read buckets hold ~3 s of budget, `429` carries no
`Retry-After` → "apply exponential backoff"); **unauthenticated public requests are subject to
separate, unpublished limits**, so the console defaults to a 10 s cadence, doubles its backoff to a
120 s ceiling, gates every request behind a `nextAllowed` clock, and pauses while the tab is hidden.
WebSockets are not used: the handshake needs `KALSHI-ACCESS-*` headers a browser cannot attach
([WebSockets quick start](https://docs.kalshi.com/getting_started/quick_start_websockets.md)).

## 7. Files

| file | role |
|---|---|
| `alerts/page-body.html` | the page body; `scripts/build_root_site.py` wraps it in the shared shell so nav/footer/styles match every other root page |
| `assets/alert-console.js` / `assets/alerts.css` | console engine + styles. The file is named `alert-console.js`, **not** `alerts.js`: `assets/alerts.js` on `main` is session a7ce6f14's dashboard chat engine, which `dashboard.html` loads; the two engines coexist rather than fight over one path (the repo has already been bitten by duplicate engines — flag R-05) |
| `assets/swing-core.js` | the shared rule, fee model and ROI score (loaded by the console, mirrored by the scanner) |
| `scripts/scan_swings.py` | detector + backtest + bucket calibration + resolution re-poll + event-page probe |
| `data/swings/{swings,strategies,events,meta,series_meta}.json`, `alerts/model.json` | published outputs |
| `scripts/tests/test_scan_swings.py`, `tests/swing_core.test.js`, `tests/alert_console.test.js` | 13 Python + 11 core-JS + 4 jsdom console tests |
| `.github/workflows/swing-scan.yml` | `*/30` schedule + manual dispatch; regenerates the data and triggers a Pages build |

Reproduce locally:

```bash
python3 scripts/scan_swings.py --offline            # writes the repo outputs (needs committed snapshots)
python3 scripts/scan_swings.py --offline --out /tmp/x   # sandbox-safe self-test, touches nothing
python3 scripts/tests/test_scan_swings.py
npm ci --no-audit --no-fund && node --test tests/swing_core.test.js tests/alert_console.test.js
python3 scripts/build_root_site.py && python3 scripts/verify_root_site.py
```

A live scan cannot run from the dev sandbox: direct HTTPS to `external-api.demo.kalshi.co` is blocked
there (every request dies with `TLS/SSL connection has been closed (EOF)`), which is why the workflow
runs it on a GitHub runner and the scanner refuses to publish when a live run reads nothing.

## 8. Link policy and known irregularities

* `kalshi.com/event/{event_ticker}` links are emitted **only** when the CI probe got HTTP 200 **and**
  the ticker appears in the page; otherwise the row says `not confirmed`. The probe runs on the CI
  runner because the sandbox cannot reach `kalshi.com` HTML at all.
* Every chat row carries four links: the API request that produced it, the candlestick request for the
  plotted window, the orderbook request for the quoted depth, and a **labelled candidate** news search.
  A news link is a candidate cause, never a conclusion — temporal proximity is not evidence.
* Irregularities flagged during this work (full text in `alerts/FINDINGS.md`): the collector's
  `data/latest/candles.json` labels (`1h_7d`, `1m_2h`) do not match `collector/collect.py::CANDLE_RANGES`;
  the CRYPTO contract-terms template prints a 10:00 AM ET expiration time while the KXBTCY market rule
  text says 12 AM EST; the ICE URL named as `KXWTIMAX`'s settlement source is the ICE Futures *Europe*
  report page, which does not list NYMEX WTI settles; `gh api` was rate-limited (HTTP 403) mid-session;
  and a `git stash -u` on my own untracked files temporarily removed `assets/alerts.js`.
* This is the **demo** environment: prices, liquidity and volume are simulated
  ([demo environment](https://docs.kalshi.com/getting_started/demo_env.md)). Nothing here is
  investment advice, and no strategy on the tracked data has positive expectancy after fees.
