# Executive summary — Kalshi demo market dashboard

**Prepared:** 2026-11-20 (UTC) · **Data snapshot:** demo run `2026-11-20T11:59Z`, production run `2026-11-20T12:01Z`
· **Every figure below is traceable to a Kalshi API response or an official Kalshi documentation page; links are inline.**

---

## 1. What this project is

A live, source-linked dashboard for the **highest-volume live events** on Kalshi, restricted to the five topics
in the brief — **gas prices, elections, culture, crypto, golf** — that tracks each event until it settles and
records how it resolved (YES or NO), and that carries a portfolio / trade-execution layer for the Kalshi **demo**
account.

---

## 2. The verified technical facts (the foundation)

| Fact | Value | Official source |
|---|---|---|
| Recommended demo REST root | `https://external-api.demo.kalshi.co/trade-api/v2` | [API Environments and Endpoints](https://docs.kalshi.com/getting_started/api_environments.md) |
| Also-supported demo REST root | `https://demo-api.kalshi.co/trade-api/v2` | [API Environments and Endpoints](https://docs.kalshi.com/getting_started/api_environments.md) |
| Demo WebSocket (recommended) | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | [Test In The Demo Environment](https://docs.kalshi.com/getting_started/demo_env.md) |
| Demo WebSocket (also supported) | `wss://demo-api.kalshi.co/trade-api/ws/v2` | [Test In The Demo Environment](https://docs.kalshi.com/getting_started/demo_env.md) |
| Public market-data auth | **None required** for markets, order books, series, trades, candlesticks | [Quick Start: Market Data](https://docs.kalshi.com/getting_started/quick_start_market_data.md) |
| WebSocket auth | **Required for every connection**, including public-data channels | [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md) |
| Portfolio / trade auth | Ed25519 (default) or RSA-PSS; sign `timestamp + METHOD + path` (no query string); timestamp within **30 s** | [API Keys](https://docs.kalshi.com/getting_started/api_keys.md) |
| Order placement | `POST /portfolio/events/orders` (V2). Legacy `/portfolio/orders` writes **removed → `410 Gone`** (`deprecated_v1_order_endpoint`) | [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2.md) |
| Settlement | YES outcome → YES holders receive $1/contract; NO outcome → NO holders receive $1/contract | [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement.md) |
| Order book shape | Bids only; `orderbook_fp.yes_dollars` / `no_dollars`, each `[price, count]`, ascending, best bid last; YES ask = 1 − best NO bid | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses.md) |
| Candlestick periods | `1`, `60`, `1440` minutes; max 5,000 periods per request; no millisecond timestamps | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md) |
| Demo environment caveat | Demo prices "may not be reflective of those in real markets"; credentials are not shared with production | [Test In The Demo Environment](https://docs.kalshi.com/getting_started/demo_env.md) |
| Rate limits | Token buckets, default 10 tokens/request; **unauthenticated public requests have separate limits**; back off on `429` | [Rate Limits and Tiers](https://docs.kalshi.com/getting_started/rate_limits.md) |

**Observed live at 2026-11-20 11:20 UTC:** the demo exchange reported `exchange_active: true`, `trading_active: true`,
four exchange shards all active — [`GET /exchange/status`](https://demo-api.kalshi.co/trade-api/v2/exchange/status).

---

## 3. What the data shows (all counts computed from API fields, formulas printed)

### 3.1 Scope actually observed

| Item | Value | Where it comes from |
|---|---|---|
| Series in the catalogue | 16,643 | `GET /series` (paginated), snapshot run `2026-11-20T11:59Z`, demo environment |
| Series selected into the five topics | 70 (top 14 per topic by series volume) | `collector/topics.json` rules + `series.volume_fp` |
| Open markets in scope | 7,035 (demo collection of that run) | `GET /markets?series_ticker=…&status=open` |
| Settled markets in scope (that run) | 5,572; **12,567 accumulated** across runs | `GET /markets?status=settled` |
| Order books and candlestick sets sampled | 20 demo + 14 production | `GET /markets/{ticker}/orderbook`, `…/candlesticks` |

Counts are per run and change hourly; the dashboard shows each run's own counts and timestamp.

**Topic mapping is exact-match only** (category, tag, ticker prefix, title fragment) — see
[`collector/topics.json`](https://github.com/karagemop466-tech/Demo3/blob/main/collector/topics.json).
A series that matches nothing is excluded and counted, never guessed into a topic.

### 3.2 How events actually resolved

Kalshi's own `result` field, counted over the accumulated settled rows:

| Topic | YES | NO | scalar |
|---|---|---|---|
| Crypto | 1,016 | 3,398 | 0 |
| Golf | 332 | 3,538 | 46 |
| Elections | 73 | 166 | 0 |
| Gas prices | 796 | 2,595 | 0 |
| Culture | 224 | 383 | 0 |
| **Total** | **2,441** | **10,080** | **46** |

Source field: `result` on `GET /markets?status=settled`
· rules: [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement.md).

### 3.3 The most important finding: price ≠ probability, and favourites are expensive

This is the finding that should change how anyone uses the dashboard.

| YES price band | Settled markets | Resolved YES | Realised win rate | Average YES price | YES expectancy / contract | NO expectancy / contract |
|---|---|---|---|---|---|---|
| ≤ 0.10 | 10,478 | 808 | 7.71% | 0.0039 | +0.0732 | −0.0732 |
| 0.10–0.20 | 143 | 6 | 4.20% | 0.1366 | −0.0946 | +0.0946 |
| 0.20–0.40 | 76 | 11 | 14.47% | 0.2863 | −0.1416 | +0.1416 |
| 0.40–0.60 | 41 | 19 | 46.34% | 0.4768 | −0.0134 | +0.0134 |
| 0.60–0.80 | 35 | 15 | 42.86% | 0.6820 | −0.2534 | +0.2534 |
| 0.80–0.90 | 47 | 35 | 74.47% | 0.8602 | −0.1155 | +0.1155 |
| 0.90–0.99 | 276 | 197 | 71.38% | 0.9613 | −0.2476 | +0.2476 |
| ≥ 0.99 | 1,425 | 1,350 | 94.74% | 0.9952 | −0.0478 | +0.0478 |

Aggregated bands: the **0.80–0.99 "favourite" band** (n = 929) resolved YES 82.13% of the time but averaged a
97.49¢ price → **YES expectancy −15.36¢/contract**; the **0.01–0.20 "longshot" band** (n = 1,820) resolved YES 1.65%
of the time at a 3.22¢ average price → **NO expectancy +1.58¢/contract**. Fees are excluded in both.

*Formula:* `expectancy = realised win rate − price paid`; both in dollars per contract.
*Caveats that must travel with this number:* `last_price_dollars` is the **last trade**, not the average price paid;
fees are excluded (series carry `fee_type` and `fee_multiplier`); only markets that settled inside the collection
window are counted; **historical expectancy does not predict the future.**

### 3.4 Liquidity and settlement timing

- **Median settlement lag** (settlement time − scheduled close): **0.13 h (~8 minutes)** across 12,567 observations;
  p90 = 8.36 h; no market in the sample settled before its scheduled close.
- **Median resting liquidity** on the 34 sampled books: **$1,084,837.97**; median derived YES spread **$0.001**.
- Deep books concentrate in the election nomination markets (largest single book sampled: **$4.24 M** resting).
- **Order-book structure matters:** many in-scope markets quote with a **0.00 bid / 1.00 ask** shell, i.e. no
  resting bids at all. A "highest dollar volume" ranking built on traded contracts therefore points at markets
  that cannot actually be entered at size. The dashboard shows **four** explicitly-labelled size metrics instead of
  one invented "dollar amount": contracts traded, open interest, traded-notional (derived), resting liquidity.

---

## 4. What is built and verified

| Layer | What it does | Where | Verified by |
|---|---|---|---|
| Collector | Pages `/series`, selects the five topics, pulls those series' open and settled markets, order books, candles, exchange status, CORS probe | `collector/collect.py`, `collector/topics.json` | GitHub Actions run [44731483738](https://github.com/karagemop466-tech/Demo3/actions/runs/44731483738) — Job "collect" reported **completed/success** |
| Analysis | Compact artifacts, computed report, expectancy study, rule-based candidates + simulation | `analysis/build.py`, `analysis/expectancy.py`, `analysis/strategies.py`, `analysis/settle_check.py` | `analysis/REPORT.md`, `data/expectancy.json` |
| Portfolio / trading | Signed demo-account reads; V2 demo order placement gated behind two explicit switches | `collector/portfolio.py`, `.github/workflows/portfolio.yml` | Dormant by design: writes `configured: false` until demo keys exist |
| Tests | Offline suite incl. the official order-book worked example | `collector/tests/test_pipeline.py` | 16 tests pass locally; run in `.github/workflows/checks.yml` |
| Site check | Broken links, citation-host allow-list, required pages, data invariants | `tools/check_site.py` | run in CI |

---

## 5. Honest limits (what this project cannot do from here)

1. **No demo API credentials exist in this environment**, so **no balance, position, fill, order or P&L figure is
   published**. Portfolio panels are blank and flagged, not filled with plausible numbers. Enabling takes two
   repository secrets — see `docs/portfolio/STRATEGY.md`.
2. **WebSocket streaming is impossible without a key** (handshake is signed even for public channels), so "live" means
   hourly REST snapshots plus per-market candlesticks, labelled with capture time.
3. **The development sandbox cannot reach Kalshi** (TLS reset on 443/80); all collection runs on GitHub Actions
   runners, which can. See `COORDINATION.md` R3.
4. **The demo environment is not the real market.** Kalshi states demo prices may not reflect real markets; the
   production snapshot is published alongside, clearly labelled, for comparison.
5. **Nobody has validated that these order rules make money.** The simulation is arithmetic on the current book,
   not a backtest of fills.

---

## 6. What to decide next

The decision register lives in [`docs/DECISIONS.md`](DECISIONS.md): 14 questions grouped into *scope*, *data
definition*, *portfolio/trading* and *publishing*, each with the answer that is currently available, the evidence,
and what would be needed to close it. `SUGGESTIONS.md` carries the improvement proposals, each tied to a question.

---

## 7. Sources

Every row above links its own source. The consolidated list, with what each page was used for, is in
[`docs/SOURCES.md`](SOURCES.md) and on the site's **Sources** page.
