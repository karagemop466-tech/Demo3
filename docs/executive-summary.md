# Executive Summary — Kalshi Demo Analytics & Trading Dashboard

**Prepared:** 2026-11-20 · **Session:** `arena-b2e728ab` · **Environment:** Kalshi **demo** (paper) exchange
**Live site:** published from this repo via GitHub Pages (see `COORDINATION.md` for the URL recorded at deploy time)

---

## 1. What was asked, in one paragraph

Build a system that (a) collects and organises Kalshi's market data, (b) surfaces the **highest-dollar live events** in five topics — gas prices, elections, culture, crypto, golf — (c) tracks each event **until it resolves** and records **yes/no**, (d) tracks **portfolio performance** on the demo account, (e) **analyses and categorises trades** and derives **strategies**, (f) **executes trades** and tracks the result, (g) renders a **live interactive chart** (X = time in seconds/minutes/hours, Y = contract price) with **liquidity by price level**, and (h) provides a dedicated **suggestions** section plus an explicit **open-questions** register so a human can choose a path before anything is implemented.

## 2. Headline conclusions

| # | Conclusion | Confidence | Evidence |
|---|---|---|---|
| 1 | The endpoint list in the brief is **correct and current** — it matches Kalshi's own published table verbatim (REST `https://external-api.demo.kalshi.co/trade-api/v2`, alt `https://demo-api.kalshi.co/trade-api/v2`; WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`, alt `wss://demo-api.kalshi.co/trade-api/ws/v2`). | Verified | [API Environments and Endpoints](https://docs.kalshi.com/getting_started/api_environments.md), [Test In The Demo Environment](https://docs.kalshi.com/getting_started/demo_env.md) |
| 2 | The demo exchange is **live and accepting orders right now**: `exchange_active=true`, `trading_active=true` on all four shards, with a continuous global tape (trades observed at ~100 fills/second). | Verified | live read of `/exchange/status` and `/markets/trades` on 2026-11-20, archived in [`data/snapshot.json`](../data/snapshot.json) |
| 3 | **Market data needs no key; everything else does.** Series/events/markets/trades/candlesticks/order books are public. All `/portfolio/*` reads and **all WebSocket connections** require an RSA-PSS (or Ed25519) signed handshake. | Verified | [Quick Start: Market Data](https://docs.kalshi.com/getting_started/quick_start_market_data.md), [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md) |
| 4 | **No demo credentials exist in this repo or environment**, so live balance/positions/fills and real order submission could not be executed. This is the single largest gap against the brief. A credential-ready signed client and order engine are shipped and tested against public endpoints; the switch is an environment variable. | Verified gap | [Demo environment](https://docs.kalshi.com/getting_started/demo_env.md) — account creation at `https://demo.kalshi.co/` is a manual human step |
| 5 | "**Highest dollar amount**" is not a field Kalshi returns. There is no dollar-volume field on a market, event or series — only `volume_fp` (contracts). Dollar volume must be **computed** from the trade tape. We define it, implement it, and label it as derived. | Verified | `GET /markets` response shape; [Get Series List](https://docs.kalshi.com/api-reference/market/get-series-list.md) (`volume_fp` = contracts, not dollars) |
| 6 | **Second-level candles do not exist.** The candlestick endpoint accepts only `period_interval` ∈ {1 min, 60 min, 1440 min}, max 5,000 periods per request. A "seconds" X-axis is therefore only achievable by **client-side sampling** (REST polling or WS tape), which is exactly what this dashboard does — and it is labelled as such, not as exchange history. | Verified | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md) |
| 7 | **Liquidity is bids-only by design.** The order book returns `yes_dollars` and `no_dollars` arrays of `[price_dollars, count_fp]`, ascending, best last; a YES bid at *X* **is** the NO ask at $1.00−*X*. "Contracts available at a given price" is answered directly by this structure; the ask side must be **derived**, never read. | Verified | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses.md) |
| 8 | **Resolution is tracked by `result` + `settlement_ts` + `settlement_value_dollars` + `status="finalized"`.** A settled market sampled live returned `result="no"`, `settlement_ts=2026-11-16T22:33:33Z`, `settlement_value_dollars="0.0000"`. Yes-payout is $1/contract to the winning side, net positions only. | Verified | live read of `/markets?series_ticker=KXPGATOUR&status=settled&limit=1`; [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement.md) |
| 9 | The legacy `/portfolio/orders` write endpoints are **gone** — they return `410 Gone`. Order lifecycle must use `POST /portfolio/events/orders` (+ `/amend`, `/decrease`, `DELETE …?market_ticker=`, `/batched`). Any older tutorial code is wrong today. | Verified | [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2.md) via the official docs index; see §5 FLAG-04 |
| 10 | The demo catalogue **does contain active markets in all five requested topics** — oil/gas (`KXWTI*`, `KXBRENT*`, `KXNATGAS*`), elections (`KXPRESNOMD-28`, `KXPRESPERSON-28`, `KXFRENCHPRES-27`), culture (`KXTIME-26`, `KXGTA6UNITS-01JAN27`), crypto (`KXBTCY-27JAN0100`, `KXAVAX`, `KXLINK`), golf (`KXPGATOUR-THRC26`, `KXDPWORLDTOUR`). | Verified | live reads archived in `data/snapshot.json` |
| 11 | There is **no `Culture` category** in Kalshi's published taxonomy. Culture had to be mapped onto `Entertainment` (+ its tags). That is an editorial decision and is flagged. | Verified gap | live read of `/search/tags_by_categories` |

## 3. What we built

```
Demo3/
├── data/snapshot.json      verified evidence base — every value traced to a live read
├── docs/                   this summary, api-surface, requirements, questions, sources
├── scripts/
│   ├── kalshi_api.py       REST client: unsigned public calls + RSA-PSS/Ed25519 signing, 429 backoff
│   ├── collect.py          snapshot collector: topics → series → events → markets → tape → depth
│   ├── trade_engine.py     order lifecycle on demo (create/amend/decrease/cancel), dry-run by default
│   ├── portfolio.py        balance / positions / fills / settlements → normalised ledger + P&L
│   ├── analyze.py          trade categorisation, strategy rules, per-strategy performance
│   └── dev_server.py       localhost bridge so the dashboard can run "live" without a CORS dependency
└── site/                   GitHub Pages site: landing, dashboard, events, portfolio,
                            suggestions, questions, flagged-for-review
```

Everything on the site is rendered from **either** a live read of the demo API **or** the archived snapshot, and every table row carries the URL it came from. There is no hand-typed market data anywhere in the pipeline.

## 4. Feasibility of each requirement — the short version

| Requirement | Feasible now? | How / why not |
|---|---|---|
| Collect + organise full market list | **Yes** | `/series`, `/events`, `/markets` public, cursor-paginated (`/events` max 200/page) |
| Highest-dollar live events, 5 topics | **Yes, with a defined metric** | Rank by `Σ count_fp × taker_price` over `/markets/trades` in the window; topic filter via official `category`+`tags` |
| Track live until resolved, record yes/no | **Yes** | Poll `/markets?event_ticker=` until `status ∈ {closed, finalized}`; read `result`, `settlement_ts`, `settlement_value_dollars` |
| Live interactive dashboard | **Yes, via polling** | Public REST has permissive caching (seconds-level). Sub-second requires WS. |
| Chart, X = **seconds** | **Partly** | Only from client-side sampling; exchange history starts at 1 minute |
| Chart, X = minutes / hours | **Yes** | `period_interval=1` / `60` (and `1440` for days) |
| Liquidity by price level | **Yes** | `/markets/{ticker}/orderbook?depth=N` — bids only, asks derived |
| Portfolio performance on demo account | **Blocked on credentials** | Needs a demo account + API key created by a human at `demo.kalshi.co` |
| Execute trades on demo | **Blocked on credentials** | Same; plus `POST /portfolio/events/orders` is a *write* and needs a key with trading rights |
| Trade analysis, categorisation, strategy | **Yes** | Runs on the fills ledger; also demoed in paper mode against live prices |
| Suggestions + review-before-change | **Yes** | `site/suggestions.html` — each suggestion is an option card with cost, risk and evidence |

## 5. Irregularities found (1-8 found while reading the API, 9-12 while building; all reproduced on the Flagged for Review page)

| ID | Irregularity | Why it matters |
|---|---|---|
| FLAG-01 | `GET /markets?status=open` is sorted by **creation time, newest first**. The head of the list was occupied by `is_provisional=true` multivariate combos with `volume_fp="0.00"`. | Naïve "first N markets = biggest markets" logic silently produces a junk leaderboard. |
| FLAG-02 | **Filter vocabulary ≠ object vocabulary.** Request `status=open` → object `status:"active"`; request `status=settled` → object `status:"finalized"`. | Any code that filters client-side on the documented enum will drop every row. |
| FLAG-03 | `category` on the **event** object is marked `deprecated` in the schema but is still returned and populated; `series.category`/`series.categories` is the supported source. A *category* called `Entertainment` holds what the brief calls *culture*. | Topic filters must read series metadata, not event metadata, or they break when the deprecated field is removed. |
| FLAG-04 | Third-party guides (and older internal code) still document `POST /portfolio/orders`. The official reference now says the legacy write endpoints are **removed, `410 Gone`**. | Integrations copied from tutorials fail at the first order. |
| FLAG-05 | `GET /series` publishes **no `limit`/`cursor`** — the whole filtered result set returns in one response (Crypto alone spanned 36 response chunks). `limit=2` was **silently ignored** in a live test. | Catalogue discovery cannot be paginated or server-side sorted; a client-side index is mandatory. |
| FLAG-06 | Order book returns an **empty `200`** for an unknown or mistyped ticker instead of `404`. | "No liquidity" and "typo" are indistinguishable unless the market is also checked with `GET /markets/{ticker}`. |
| FLAG-07 | REST responses are **explicitly cached** ("prices, sizes and status can lag the exchange by several seconds; filtered listings can lag longer"). | A dashboard that claims "live" must state its lag budget; our UI shows the `updated_time` of every instrument. |
| FLAG-08 | No **CORS** statement exists in the official docs for the demo/production REST hosts, and a GitHub-Pages-hosted page cannot verify it from this sandbox. | Whether the published site can call the API **directly from the browser is unverified**. The site therefore auto-detects: live if allowed, snapshot if not, `dev_server.py` in between. |

| FLAG-09 | The **demo trade tape looks synthetic**: 120 fills inside ~179 ms, in repeating round sizes (`5555.55`, `1851.85` contracts). | Flow-derived signals measured on demo will not transfer; every strategy verdict on this site therefore stays "insufficient data". |
| FLAG-10 | The **WebSocket handshake must be signed for every channel**, public ones included, and a browser cannot set handshake headers. | "Live charts" in a static deployment can only mean polling; the site labels its seconds axis *client-sampled* instead of pretending to stream. |
| FLAG-11 | A long API response **can be truncated mid-record** by the retrieval path used here (one `KXTIME-26` market was cut inside `rules_secondary`). | Reconstructing a cut field from a neighbouring row would fabricate a value, so truncated rows are published as `null` with a do-not-trade note. |
| FLAG-12 | **This sandbox has no network egress to `kalshi.co`** (TLS fails from the shell while GitHub/npm work), so `collect.py`, `portfolio.py` and the signed client were never executed against the network here. | Any claim that the collector "ran successfully" would be false. Scripts are compile-checked and shipped; all published values come from archived reads under `data/`. |

## 6. Decision posture

Nothing in this repo asserts a price, a volume, or a portfolio number that was not read from a Kalshi response. Where the brief asked for something the API cannot give (second-resolution history, a dollar-volume field, a `Culture` category, credential-less trading), the system **does the nearest honest thing and labels it**. The four decisions that genuinely need a human — demo credentials, the culture category mapping, the dollar-volume definition, and whether to trade passively or aggressively — are written up as questions with options in `docs/questions.md` and on the site's Questions page.
