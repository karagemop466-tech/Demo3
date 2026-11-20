# Kalshi Trade API v2 — Verified Surface

Every row below is either (a) a documentation page on `docs.kalshi.com` that was read in this session, or (b) a live HTTP response from the demo exchange captured in this session and archived to [`data/snapshot.json`](../data/snapshot.json). Rows we could not confirm are left blank and repeated on the Flagged for Review page.

## 1. Environments

| Surface | Environment | Recommended endpoint | Also supported | Status | Source |
|---|---|---|---|---|---|
| REST Trade API | Demo | `https://external-api.demo.kalshi.co/trade-api/v2` | `https://demo-api.kalshi.co/trade-api/v2` | ✅ Responded 200 in this session | [api_environments](https://docs.kalshi.com/getting_started/api_environments.md) · [demo_env](https://docs.kalshi.com/getting_started/demo_env.md) |
| REST Trade API | Production | `https://external-api.kalshi.com/trade-api/v2` | `https://api.elections.kalshi.com/trade-api/v2` | Documented (not exercised — this project is demo-only) | [api_environments](https://docs.kalshi.com/getting_started/api_environments.md) |
| WebSocket | Demo | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | `wss://demo-api.kalshi.co/trade-api/ws/v2` | Documented; **not** reachable from this sandbox (no TLS egress, and the handshake requires signing) | [api_environments](https://docs.kalshi.com/getting_started/api_environments.md) · [quick_start_websockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md) |
| WebSocket (fills/orders, lower latency) | Demo | `wss://user-ws.demo.kalshi.co/trade-api/ws/v2` | — | Documented. Serves `fill` and `user_orders` only; any other channel returns error code 8 | [api_environments](https://docs.kalshi.com/getting_started/api_environments.md) |
| External feeds WS | Demo | `wss://external-feeds.demo.kalshi.co/trade-api/v2/external-feeds` | — | Documented as mid-migration to dedicated hostnames | [api_environments](https://docs.kalshi.com/getting_started/api_environments.md) |
| FIX | Demo | `fix.demo.kalshi.co` / `marketdata.fix.demo.kalshi.co` (per third-party guides) | — | ⚠️ **Unverified** — not on the two pages read; left blank on the site | — |
| Demo web UI (account, mock funds) | Demo | `https://demo.kalshi.co/` | — | Documented | [demo_env](https://docs.kalshi.com/getting_started/demo_env.md) |

Credentials are **not shared** between production and demo: a demo key only works on demo hosts ([api_environments](https://docs.kalshi.com/getting_started/api_environments.md)).

## 2. Public (unauthenticated) endpoints used by this project

| Endpoint | Method | Returns | Params we use | Verified by live call | Source |
|---|---|---|---|---|---|
| `/exchange/status` | GET | `exchange_active`, `trading_active`, `intra_exchange_transfers_active`, `exchange_index_statuses[]` | — | ✅ | [get-exchange-status](https://docs.kalshi.com/api-reference/exchange/get-exchange-status.md) |
| `/search/tags_by_categories` | GET | map of category → tag list | — | ✅ | [get-tags-for-series-categories](https://docs.kalshi.com/api-reference/search/get-tags-for-series-categories.md) |
| `/series` | GET | series templates: `ticker`, `title`, `category`, `categories[]`, `tags[]`, `frequency`, `fee_type`, `fee_multiplier`, `settlement_sources[]`, `contract_url`, `contract_terms_url`, `exchange_index`, `volume_fp` | `category`, `tags`, `include_volume` | ✅ | [get-series-list](https://docs.kalshi.com/api-reference/market/get-series-list.md) |
| `/events` | GET | event objects: `event_ticker`, `series_ticker`, `title`, `sub_title`, `category` (deprecated), `mutually_exclusive`, `collateral_return_type`, `settlement_sources[]`, `strike_date`/`strike_period`, `last_updated_ts`, optional `markets[]` | `limit` (≤200), `cursor`, `status`, `series_ticker`, `tickers`, `with_nested_markets`, `with_milestones`, `min_close_ts`, `min_updated_ts` | ✅ | [get-events](https://docs.kalshi.com/api-reference/events/get-events.md) |
| `/markets` | GET | market objects (prices, sizes, `volume_fp`, `volume_24h_fp`, `open_interest_fp`, `result`, `settlement_ts`, `price_ranges`, `rules_primary`) | `limit` (≤200? see note), `cursor`, `event_ticker`, `series_ticker`, `tickers`, `status`, `min_/max_` ts filters | ✅ | [get-markets](https://docs.kalshi.com/api-reference/market/get-markets.md) |
| `/markets/{ticker}` | GET | one market (uncached-ish read; use to disambiguate an empty book) | — | Documented | [get-market](https://docs.kalshi.com/api-reference/market/get-market.md) |
| `/markets/{ticker}/orderbook` | GET | `orderbook_fp.yes_dollars[]`, `orderbook_fp.no_dollars[]` as `[price_dollars, count_fp]`, ascending, best last; **bids only** | `depth` | ✅ | [get-market-orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook.md) · [orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses.md) |
| `/markets/orderbooks` | GET | batched order books, up to 100 tickers | `tickers` | Documented | [get-multiple-market-orderbooks](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md) |
| `/markets/trades` | GET | the tape: `trade_id`, `ticker`, `count_fp`, `yes_price_dollars`, `no_price_dollars`, `taker_outcome_side`, `taker_book_side`, `created_time`, `is_block_trade` | `limit` (1–1000, default 100), `cursor`, `ticker`, `min_ts`, `max_ts`, `is_block_trade` | ✅ | [get-trades](https://docs.kalshi.com/api-reference/market/get-trades.md) |
| `/series/{series_ticker}/markets/{ticker}/candlesticks` | GET | per-period `price`, `yes_bid`, `yes_ask` OHLC distributions, `volume_fp`, `open_interest_fp`, `end_period_ts` | `start_ts`\*, `end_ts`\*, `period_interval`\* ∈ {1, 60, 1440}, `include_latest_before_start` | ✅ | [get-market-candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md) |

`\*` required. Max 5,000 periods per request (≈3.5 days of 1-minute bars).

## 3. Authenticated endpoints the trading engine targets

Signed with three headers — `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP` (unix **ms**), `KALSHI-ACCESS-SIGNATURE` over `timestamp + METHOD + path-from-root` (no query string), using **RSA-PSS/SHA-256** (or Ed25519).

| Endpoint | Method | Purpose | Verified |
|---|---|---|---|
| `/portfolio/balance` | GET | cash position; own rate bucket (1/s Basic–Advanced, 5/s above) | Documented — [get-balance](https://docs.kalshi.com/api-reference/portfolio/get-balance.md), [rate_limits](https://docs.kalshi.com/getting_started/rate_limits.md) |
| `/portfolio/positions` | GET | unsettled positions (qty + cost basis retained after close) | Documented — [get-positions](https://docs.kalshi.com/api-reference/portfolio/get-positions.md) |
| `/portfolio/fills` | GET | your fills (pre-cutoff via `/historical/fills`) | Documented — [get-fills](https://docs.kalshi.com/api-reference/portfolio/get-fills.md) |
| `/portfolio/orders` | GET | order history (resting always live; completed/cancelled older than cutoff via `/historical/orders`) | Documented — [get-orders](https://docs.kalshi.com/api-reference/orders/get-orders.md) |
| `/portfolio/settlements` | GET | settlement records in the live data set | Documented — [get-settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements.md) |
| `/portfolio/events/orders` | POST | **create** order (V2: `bid`/`ask` side, fixed-point dollars, `client_order_id` idempotency) | Documented — [create-order-v2](https://docs.kalshi.com/api-reference/orders/create-order-v2.md) |
| `/portfolio/events/orders/{order_id}` | DELETE | cancel — **must** pass `market_ticker` (or `exchange_index`) or it routes to shard 0 | Documented — [cancel-order-v2](https://docs.kalshi.com/api-reference/orders/cancel-order-v2.md) |
| `/portfolio/events/orders/{order_id}/amend` | POST | amend price / max fillable count / expiry | Documented — [amend-order-v2](https://docs.kalshi.com/api-reference/orders/amend-order-v2.md) |
| `/portfolio/events/orders/{order_id}/decrease` | POST | `reduce_by` **xor** `reduce_to` | Documented — [decrease-order-v2](https://docs.kalshi.com/api-reference/orders/decrease-order-v2.md) |
| `/portfolio/events/orders/batched` | POST / DELETE | batch; bills the **unscoped** write bucket at per-order cost | Documented — [batch-create-orders-v2](https://docs.kalshi.com/api-reference/orders/batch-create-orders-v2.md) |
| `/portfolio/orders` (+ amend/decrease/cancel/batch) | — | **REMOVED — returns `410 Gone`** | [create-order-v2](https://docs.kalshi.com/api-reference/orders/create-order-v2.md) via official docs index |
| `/account/limits` | GET | your tier + token-bucket budget | Documented — [get-account-api-limits](https://docs.kalshi.com/api-reference/account/get-account-api-limits.md) |
| `/account/endpoint_costs` | GET | authoritative list of non-default token costs | Documented — [list-non-default-endpoint-costs](https://docs.kalshi.com/api-reference/account/list-non-default-endpoint-costs.md) |
| `/api-keys/*` | GET/POST/DELETE | key lifecycle; `generate` returns the private key exactly once | Documented — [api-keys](https://docs.kalshi.com/getting_started/api_keys.md) |

**Not verified by execution.** No demo API key exists in this environment, so no `/portfolio/*` request was ever sent. `scripts/trade_engine.py` is unit-tested for request shape and signing only. Marked `needs review`.

## 4. WebSocket channels

| Channel | Class | Content | Source |
|---|---|---|---|
| `ticker` | public market data, **authed session** | price/volume/open-interest updates | [quick_start_websockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md) |
| `trade` | public market data | public fills, reports taker side | same |
| `market_lifecycle_v2` | public market data | market state changes; new events arrive with their `exchange_index` | same |
| `multivariate_market_lifecycle` | public market data | combo-market lifecycle | same |
| `orderbook_delta` | private channel name, public data | snapshot then deltas; needs `market_ticker(s)` | same |
| `fill` | private | your fills | same |
| `market_positions` | private | your positions | same |
| `user_orders` | private | your order updates | same |
| `communications`, `order_group_updates` | private | RFQ/block flow; order groups | same |

Handshake is **header-authenticated** (`KALSHI-ACCESS-*`) and signs `timestamp + "GET" + "/trade-api/ws/v2"`. A browser cannot set handshake headers on `WebSocket`, therefore:

> **The published GitHub-Pages dashboard cannot open a Kalshi WebSocket by itself.** Live updates are delivered by REST polling; true streaming requires a local signed bridge (`scripts/dev_server.py`). This is a design consequence, not a bug.

Server sends Ping only after 10 s of silence — do not treat a quiet connection as dead ([quick_start_websockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md)).

## 5. Rate limits (affects dashboard polling design)

| Fact | Value | Source |
|---|---|---|
| Default cost per request | 10 tokens | [rate_limits](https://docs.kalshi.com/getting_started/rate_limits.md) |
| Buckets | independent **Read** and **Write**; most GETs are Read | same |
| Burst | Basic/Advanced Read and >Basic Write hold 3 s of budget; others 1 s | same |
| On throttle | `429` `{"error":{"code":"too_many_requests"}}`, **no `Retry-After`**; use exponential backoff | same |
| Headers | `X-RateLimit-Limit/Remaining/Reset/Cost` | same |
| Unauthenticated traffic | subject to **separate, undocumented** limits | same — ⚠️ the actual public number is not published; flagged |
| Balance endpoint | own bucket, 1/s (Basic–Advanced) | same |
| Order writes | per-shard Write buckets when `exchange_index ≥ 1`; auto-route bills **every** shard | same |

Dashboard consequence: with one anonymous browser session, polling a 12-market watchlist every 5 s = 144 req/min of public reads. Kept well inside typical tolerance, with backoff and a "stale" badge rather than hammering.

## 6. Data-type conventions (must not be ignored)

| Type | Wire form | Meaning | Source |
|---|---|---|---|
| Fixed-point dollars | string, `"0.5600"` | prices; responses emit up to 6 dp | [fixed_point_migration](https://docs.kalshi.com/getting_started/fixed_point_migration.md) |
| Fixed-point count | string, `"10.00"` | contracts; 2 dp, min granularity 0.01 contracts | same |
| `volume_fp` | string | **contracts** traded, not dollars | [get-series-list](https://docs.kalshi.com/api-reference/market/get-series-list.md) |
| `notional_value_dollars` | `"1.0000"` in every sampled market | one winning contract pays $1.00 | live `/markets` read |
| Orderbook level | `["0.4200","13.00"]` | price, contracts resting | [orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses.md) |
| Order `price` / `count` | strings, e.g. `"0.0100"`, `"1"` | V2 order shape | [quick_start_create_order](https://docs.kalshi.com/getting_started/quick_start_create_order.md) |

Older integer-cent fields (`yes_bid: 42`) are gone from the responses we sampled; the API spec version returned by the docs is **3.37.0**.

## 7. Pagination rules that bite

| Rule | Consequence | Source |
|---|---|---|
| `/events`, `/markets`, `/series`, `/markets/trades`, `/portfolio/*` list endpoints are **cursor**-paginated; return an empty cursor at the end | stop on empty cursor, always pass back verbatim | [pagination](https://docs.kalshi.com/getting_started/pagination.md), [get-events](https://docs.kalshi.com/api-reference/events/get-events.md) |
| `/events` limit max = 200 (default 200) | 200 is the ceiling, not a suggestion | [get-events](https://docs.kalshi.com/api-reference/events/get-events.md) |
| `/markets` when `event_ticker`/`tickers` is the **only** filter: everything returns, `limit` ignored, cursor empty | do not expect paging there | [get-markets](https://docs.kalshi.com/api-reference/market/get-markets.md) |
| `/markets` default sort = creation time **newest first** | head of list = freshly created combos | same |
| `/series` has **no** limit/cursor; `limit` is silently ignored | must fetch whole set; `include_volume` cannot be sorted server-side | live test + [get-series-list](https://docs.kalshi.com/api-reference/market/get-series-list.md) |
| A market whose close time moves during paging can be skipped or duplicated | deduplicate by `ticker` | [get-markets](https://docs.kalshi.com/api-reference/market/get-markets.md) |
| `min_updated_ts` on `/events` | the cheap way to poll for changes | [get-events](https://docs.kalshi.com/api-reference/events/get-events.md) |

## 8. Exchange sharding

Four shards are live in demo (index 0 "Default", 1 "Demo shard 1", 2 "Demo shard 2", 3 unnamed), each reporting `trading_active=true`. A market's `exchange_index` tells you which shard it is on; reads that omit it work, but a **cancel** routed without `market_ticker`/`exchange_index` lands on shard 0 ([exchange_sharding](https://docs.kalshi.com/getting_started/exchange_sharding.md), [cancel-order-v2](https://docs.kalshi.com/api-reference/orders/cancel-order-v2.md)). Observed placement: golf/oil/election series on index 0, crypto series on index 2, `KXGOLFTENNISMAJORS` on index 3, some combo markets on index 1 — all read from live responses.

## 9. Fees

`fee_type` and `fee_multiplier` are **series-level** fields (every series sampled: `quadratic`, multiplier `1`). Fee tables live at `https://kalshi.com/docs/kalshi-fee-schedule.pdf`, referenced by the [Get Series List](https://docs.kalshi.com/api-reference/market/get-series-list.md) schema. Event-level overrides are readable via [Get Event Fee Changes](https://docs.kalshi.com/api-reference/events/get-event-fee-changes.md). Settlement fee is zero for simple yes/no, non-zero for sub-cent scalar settlement ([market_settlement](https://docs.kalshi.com/getting_started/market_settlement.md)).

⚠️ The PDF itself was **not** fetched in this session, so no fee number is published on the site — only the per-series `fee_type`/`fee_multiplier` actually returned by the API.
