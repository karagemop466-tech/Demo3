# Sources — every page used, and what it established

Rule for this project: a claim is only made if an official page (Kalshi docs, Kalshi API response, or the Kalshi
Help Center) or the GitHub/Actions API supports it. Everything else is flagged in [FLAGGED.md](FLAGGED.md).
All pages were fetched on **2026-11-20 (UTC)**.

## Kalshi official documentation (docs.kalshi.com)

| # | Page | What it established here |
|---|---|---|
| 1 | [API Environments and Endpoints](https://docs.kalshi.com/getting_started/api_environments.md) | Demo REST roots (`external-api.demo.kalshi.co`, `demo-api.kalshi.co`), demo WS roots, request-signing path rules, host changes |
| 2 | [Test In The Demo Environment](https://docs.kalshi.com/getting_started/demo_env.md) | Demo account behaviour, mock funds, credentials not shared with production, **"prices may not be reflective of real markets"** |
| 3 | [Quick Start: Market Data](https://docs.kalshi.com/getting_started/quick_start_market_data.md) | Which endpoints need no key (markets, order books, series, trades, candlesticks) |
| 4 | [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md) | **Every WS connection is signed**, including public-data channels; channel split; handshake errors |
| 5 | [API Keys](https://docs.kalshi.com/getting_started/api_keys.md) | Ed25519 / RSA-PSS, `KALSHI-ACCESS-*` headers, `timestamp+METHOD+path`, **30 s** clock tolerance |
| 6 | [Rate Limits and Tiers](https://docs.kalshi.com/getting_started/rate_limits.md) | Token buckets, default 10 tokens, separate **unauthenticated** limits, back off on 429 |
| 7 | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets.md) | `volume_fp`, `volume_24h_fp`, `open_interest_fp`, `last_price_dollars`, `result`, `status`, filter rules, caching note |
| 8 | [Get Series](https://docs.kalshi.com/api-reference/market/get-series.md) & [Get Series List](https://docs.kalshi.com/api-reference/market/get-series-list.md) | Series-level `category`, `categories`, `tags`, `volume_fp`, `settlement_sources` |
| 9 | [Get Events](https://docs.kalshi.com/api-reference/events/get-events.md) | Event status filters (`unopened/open/closed/settled`), nested markets, `with_nested_markets` |
| 10 | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses.md) | **Bids only**, `orderbook_fp`, ascending arrays, best bid last, YES ask = 1 − best NO bid, spread formula, worked example used as a unit test |
| 11 | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md) | Periods `1/60/1440`, max 5,000 periods, seconds-only timestamps |
| 12 | [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement.md) | $1/contract to the winning side; `result` semantics; settlement timing |
| 13 | [Historical Data](https://docs.kalshi.com/getting_started/historical_data.md) | Live vs. historical partitioning, `/historical/cutoff`, how to combine position endpoints |
| 14 | [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2.md) | **Legacy `/portfolio/orders` writes removed → 410 Gone**; V2 shape (`side: bid|ask`, required `price`) |
| 15 | [Order Errors](https://docs.kalshi.com/getting_started/order_errors.md) | `invalid_price` (price grid), `insufficient_balance`, `remaining_count` semantics, batch errors |
| 16 | [Get Balance](https://docs.kalshi.com/api-reference/portfolio/get-balance.md) | Balance + portfolio value fields |
| 17 | [Get Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions.md) | Position fields incl. `realized_pnl`, `settlement_status` |
| 18 | [Get Fills](https://docs.kalshi.com/api-reference/portfolio/get-fills.md) | Fill fields incl. `fee_cost` |
| 19 | [Get Settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements.md) | Settlement record fields incl. `revenue` |
| 20 | [Fixed-Point Representation](https://docs.kalshi.com/getting_started/fixed_point_migration.md) | `*_fp` strings, 2-decimal counts, up-to-6-decimal dollars |
| 21 | [Kalshi Glossary](https://docs.kalshi.com/getting_started/terms.md) | Terminology used in labels |
| 22 | [Documentation index](https://docs.kalshi.com/llms.txt) | Canonical list of doc URLs used to avoid guessing any link |

## Kalshi API responses actually stored in this repo

| Response | Where it is referenced | Note |
|---|---|---|
| [`GET /exchange/status`](https://demo-api.kalshi.co/trade-api/v2/exchange/status) | `data/meta.json` → demo status | `exchange_active`, `trading_active`, 4 shards |
| `GET /series?limit=200&include_volume=true` | every row in `data/dashboard.json` → `series[].source` | 16,643 series in the verified run |
| `GET /markets?series_ticker=…&status=open&mve_filter=exclude` | `data/dashboard.json` → `tables[].*.source` | per-series |
| `GET /markets?series_ticker=…&status=settled&mve_filter=exclude` | `data/resolutions-compact.json` rows | `result` = yes/no/scalar |
| `GET /markets/{ticker}/orderbook` | `data/dashboard.json` → `ladders[].source` | bids only; implied asks derived |
| `GET /series/{s}/markets/{t}/candlesticks?period_interval=1|60|1440` | `data/dashboard.json` → `candles[].source` | exact query string stored |
| `GET /historical/cutoff` | `data/live.json` (runner-side) | documents the archive boundary |
| `GET /portfolio/{balance,positions,orders}` **without** a key | `data/meta.json` → auth probes | 401 recorded as evidence, **not** as data |
| [`GET /series/KXAAAGASW`](https://demo-api.kalshi.co/trade-api/v2/series/KXAAAGASW) | gas topic justification | settlement source = AAA, `https://gasprices.aaa.com/` |

## GitHub / platform sources

| Source | Used for |
|---|---|
| [Repository](https://github.com/karagemop466-tech/Demo3) | code, data, history |
| [Pull requests](https://github.com/karagemop466-tech/Demo3/pulls) | verifying what was actually merged (F1) |
| [Pages API](https://api.github.com/repos/karagemop466-tech/Demo3/pages) | Pages source branch/path and build status |
| [Actions run 44727245939](https://github.com/karagemop466-tech/Demo3/actions/runs/44727245939) | proving CI runners can reach the Kalshi demo API |
| [Actions run 44731483738](https://github.com/karagemop466-tech/Demo3/actions/runs/44731483738) | pipeline end-to-end success |

## Not used, on purpose

- Third-party blogs, social posts, summarised API descriptions and AI-generated snippets — none of them are citations.
- kalshi.com UI screenshots or scrape-only values: if a number is not in an API response we can store, it is not
  published here.
