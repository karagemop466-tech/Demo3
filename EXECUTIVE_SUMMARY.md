# Executive Summary — Kalshi Demo Dashboard

**Date:** 2026-11-20 · **Repo:** `karagemop466-tech/Demo3` · **Live site:** https://karagemop466-tech.github.io/Demo3/
**Scope:** collect, organize, and analyze live Kalshi **demo-exchange** data for five topics
(gas prices, elections, culture, crypto, golf); track events to resolution (yes/no); track a
demo-account portfolio; execute and categorize demo trades; publish a verified, interactive
GitHub Pages dashboard.

---

## 1. What was delivered

| Capability | Status | Where |
|---|---|---|
| Verified Kalshi demo API integration (events, markets, orderbooks, candlesticks, exchange status) | **Live-verified** | `collector/`, `docs/API_VERIFICATION.md` |
| Scheduled server-side snapshots (every 10 min, GitHub Actions) committed to `data/` | **Running** | `.github/workflows/collect.yml`, `data/meta.json` |
| Highest-dollar live-event ranking per topic | **Live** (estimate labeled) | `data/events.json`, `data-tracking.html` |
| Resolution tracking: events followed until settled; outcome YES/NO + winning markets + settlement sources | **Live** | `data/resolutions.json`, `data/tracked.json` |
| Price-movement charts (X = time, Y = contract price; 1-min/1-hour/1-day candles; auto x-axis units) | **Live** | `assets/data-tracking.js` |
| Orderbook ladders: contracts available at each price, best bid, liquidity context | **Live** | `data/orderbooks/*.json` |
| Live in-browser dashboard (client-side API polling) | **Live, CORS verified** | `dashboard.html` (session 7f1ef378) |
| Demo-account portfolio tracking + order execution + PnL-on-settlement | **Implemented & offline-tested; unverified live — no demo credentials exist in this environment** | `trading/`, `.github/workflows/trade.yml` |
| Trade categorization + strategy framework + performance aggregation | **Implemented** | `trading/strategies.py` |
| Suggestions board, questions/answers register, flagged-for-review page, methodology | **Published** | `suggestions.html`, `questions.html`, `flagged.html`, `docs/` |

## 2. Verified key facts (all from official sources, checked live on 2026-11-20)

1. **Demo REST root:** `https://external-api.demo.kalshi.co/trade-api/v2` (recommended); `https://demo-api.kalshi.co/trade-api/v2` also supported — [docs](https://docs.kalshi.com/getting_started/api_environments.md). Demo WebSocket: `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`.
2. **Public market data needs no key** — [docs](https://docs.kalshi.com/getting_started/quick_start_market_data).
3. **CORS for this site is explicitly allowed:** the demo API returns `Access-Control-Allow-Origin: https://karagemop466-tech.github.io` — probe recorded every run in `data/cors_test.json`. This *resolves* the previously flagged open question F1.
4. **Signed endpoints** (portfolio, orders) use `KALSHI-ACCESS-KEY`/`-TIMESTAMP`/`-SIGNATURE`; message = `timestamp + METHOD + path-without-query`; Ed25519 direct or RSA-PSS-SHA256 — [docs](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md). Demo credentials are **not** shared with production ([demo docs](https://docs.kalshi.com/getting_started/demo_env.md)).
5. **Order placement** is `POST /portfolio/events/orders` with `side: bid|ask`, dollar-string price, optional `client_order_id` for dedup — [docs](https://docs.kalshi.com/getting_started/quick_start_create_order.md).
6. **Settlement:** settled markets carry `result` = `yes`|`no`; each winning contract pays $1 — [docs](https://docs.kalshi.com/getting_started/market_settlement.md).
7. **Candlesticks:** 1/60/1440-minute intervals, ≤5,000 periods per request, seconds timestamps — [docs](https://docs.kalshi.com/api-reference/market/get-market-candlesticks). Sub-minute granularity is not available via REST (flagged F13).

## 3. What the live data shows (demo exchange, 2026-11-20)

- **~12,000 open events** paginated per run (7,600+ in the Elections category alone); ~40,500 nested markets seen.
- **Highest-dollar live events (estimated $ volume = Σ contracts × last price):** Democratic nominee 2028 (~$900M est.), next presidential election (~$135M est.), Republican nominee 2028 (~$48M est.), Oscar Best Picture (~$3.5M est.). *Demo money; estimates, not exchange-reported dollar volume.*
- **Gas prices:** no live gas events at collection time; **50 resolved gas markets** tracked via the officially documented `KXAAAGASM` series (e.g. "Will average gas prices be above $4.18?" → resolved **YES**, finalized 2026-10-31).
- **Golf:** 2 live events in the latest snapshot plus resolved `KXGOLFMAJOR` markets.
- **Crypto:** live BTC/SOL price markets plus 150 resolved markets across `KXBTC`/`KXBTCD`/`KXDEMOFUTHOURLY`.
- **Demo-exchange anomalies (flagged F11):** seeded volumes are unrealistic vs real markets; synthetic cross-category (MVE) events flood `/markets` newest-first (collector uses nested-events pagination to stay complete); demo prices may not reflect real behavior — [official warning](https://docs.kalshi.com/getting_started/demo_env.md).

## 4. Portfolio & trading — status and the one thing needed to activate it

The trading pipeline is **fully implemented and offline-tested (11 tests)**: signed demo requests,
portfolio snapshots (balance/positions/fills/orders), order placement with dedup, settlement PnL
($1/contract math), and per-topic/per-structure performance aggregation. It writes
`data/portfolio.json` + `data/trades.json` for the site. **It cannot run because no demo-account
credentials exist in this environment** — creating a demo account at https://demo.kalshi.co requires
human registration. Adding two repository secrets (`KALSHI_DEMO_API_KEY_ID`, `KALSHI_DEMO_PRIVATE_KEY`)
activates it; until then the site shows truthful "awaiting credentials" states and no values are
invented (flagged F9, published on Flagged for Review).

## 5. Decisions needed from you (before further changes)

Published for review, not auto-applied — see `suggestions.html` and `questions.html`:
1. Collector cadence (10-min today; 15–30 min proposed to protect API rate budget).
2. Provide demo credentials to activate portfolio/trade analytics (or leave read-only).
3. Sub-minute chart granularity via WebSocket (needs a live browser WS test first).
4. Whether to archive `data/` snapshots monthly (repo growth management).

## 6. Verification policy (followed everywhere)

Every table row on the site carries a source link to an official page or the exact API endpoint
queried. Values that could not be confirmed are **blank and flagged** — never inferred. Methodology:
`docs/METHODOLOGY.md` and `docs/API_VERIFICATION.md`. Flagged items: `flagged.html` + `docs/FLAGGED.md`.

## 7. Coordination

Multiple agent sessions worked in parallel; the shared task board (claims, scopes, handoffs,
incidents, merge record) is `COORDINATION.md`. This session (3b5e95bd) delivered the automation
layer and performed final integration (PR from `arena/3b5e95bd-demo3` → `main`, merge, Pages verify).
