# API Verification — Kalshi Demo Trade API (line-by-line)

Verification date: **2026-11-20** (all checks performed live during this session).
Method: every claim below was checked against an **official Kalshi source** (docs.kalshi.com,
kalshi.com) and, where noted, against **live responses** captured from the demo API itself via
the platform's page-fetch tool. The dev sandbox blocks direct egress to Kalshi hosts (flag F1
in COORDINATION.md), so bulk requests run on GitHub Actions runners; captured responses are
quoted in the collector logs and data snapshots.

## Endpoints

| # | Endpoint (demo) | Verified behavior | Official source | Live evidence |
|---|---|---|---|---|
| 1 | `GET https://external-api.demo.kalshi.co/trade-api/v2/events?status=open&limit=N` | Public, no auth. Returns `{cursor, events:[{event_ticker, series_ticker, title, sub_title, category, mutually_exclusive, last_updated_ts, settlement_sources[]}]}` | https://docs.kalshi.com/getting_started/quick_start_market_data | Captured 2026-11-20: events incl. `KXELONMARS-99`, `KXNEXTNATOSECGEN-99`, `KXNEWPOPE-70`, `KXWARMING-50`, `KXMARSVRAIL-50`; cursor `CgYI8JHtswkS...` |
| 2 | `GET /markets?status=open&limit=N` | Public. Dollar-denominated fields: `yes_bid_dollars`, `yes_ask_dollars`, `no_bid_dollars`, `no_ask_dollars`, `last_price_dollars` (4-dp strings), `volume_fp`, `volume_24h_fp`, `open_interest_fp`, `yes_bid_size_fp`, `yes_ask_size_fp`, `status:"active"`, `result`, `close_time`, `market_type`, `strike_type`, `rules_primary` | same + https://docs.kalshi.com/getting_started/fixed_point_migration.md | Captured 2026-11-20: e.g. market `KXMVECROSSCATEGORY-...` with `last_price_dollars:"0.4500"`, `volume_fp:"100.00"`, `open_interest_fp:"100.00"` |
| 3 | `GET /events/{event_ticker}?with_nested_markets=true` | Returns `{event:{..., markets:[...]}}` | https://docs.kalshi.com/api-reference/market/get-events (linked from quick_start_market_data) | Used by collector; response shape per quick-start JS example (`eventData.event.title`) |
| 4 | `GET /markets/{ticker}/orderbook` | Public. `orderbook_fp.{yes_dollars,no_dollars}` arrays of `[price_dollars, count_fp]`, **ascending**, best bid = last element; bids only (yes bid at X = no ask at 1−X) | https://docs.kalshi.com/api-reference/market/get-market-orderbook and https://docs.kalshi.com/getting_started/orderbook_responses.md | Shape verified against quick-start code sample (`orderbook_data['orderbook_fp']['yes_dollars'][-5:]` with comment "arrays are sorted ascending, best bid last"); live ladder stored in `data/orderbooks/*.json` |
| 5 | `GET /series/{series_ticker}/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval` | Public. `period_interval ∈ {1,60,1440}` minutes; timestamps in **seconds**; ≤5,000 periods/request; returns `candlesticks[{end_period_ts, price:{open/high/low/close_dollars}, yes_bid:{...}, yes_ask:{...}, volume_fp, open_interest_fp}]` | https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md (OpenAPI quoted on page) | OpenAPI schema on that page lists the demo server URL explicitly |
| 6 | `GET /exchange/status` | Public exchange status | https://docs.kalshi.com/api-reference/exchange/get-exchange-status.md | Used as CORS probe target (see `data/cors_test.json`) |
| 7 | `GET /portfolio/balance` (signed) | Returns `balance` in **dollars-as-cents** (docs example: `balance['balance'] / 100`) | https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md | Not executed live — no demo credentials in this environment (flag F3/F9, see docs/FLAGGED.md) |
| 8 | `POST /portfolio/events/orders` (signed) | Body: `{ticker, side:"bid"|"ask", count:"<int>", price:"<4dp dollars>", time_in_force:"good_till_canceled", self_trade_prevention_type:"taker_at_cross", client_order_id:"<uuid>"}`; 201 = accepted (check `remaining_count`); duplicate `client_order_id` → 409 `order_already_exists` | https://docs.kalshi.com/getting_started/quick_start_create_order.md | Not executed live — no demo credentials (flagged). Payload shape unit-tested in `trading/test_trading.py` |
| 9 | `DELETE /portfolio/events/orders/{order_id}` | Cancel order | https://docs.kalshi.com/getting_started/quick_start_create_order.md | Not executed live (no credentials) |
| 10 | `GET /portfolio/positions`, `/portfolio/fills`, `/portfolio/orders` (signed) | Account positions/fills/orders; response container keys parsed defensively (`market_positions` or `positions` etc.) | https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md ("Try these endpoints") | Not executed live (no credentials) |
| 11 | WebSocket `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | Demo WS recommended URL; dedicated user hosts `wss://user-ws.demo.kalshi.co/trade-api/ws/v2` serve `fill`/`user_orders` | https://docs.kalshi.com/getting_started/api_environments.md | Not exercised (browser WS handshake w/ auth headers unverified — flagged on site) |
| 12 | Auth headers/signing | `KALSHI-ACCESS-KEY` / `KALSHI-ACCESS-TIMESTAMP` (ms) / `KALSHI-ACCESS-SIGNATURE` (base64); message = `timestamp + METHOD + path-without-query`; Ed25519 signs message directly; RSA = RSA-PSS SHA-256 (MGF1-SHA256, salt = digest length); timestamp within 30 s of Kalshi clock | https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md | Signing implementation unit-tested offline (Ed25519 signature verified against generated public key) in `trading/test_trading.py` |
| 13 | Demo environments | REST root `https://external-api.demo.kalshi.co/trade-api/v2` (recommended; `https://demo-api.kalshi.co/trade-api/v2` also supported); demo credentials not shared with production; account sign-up at https://demo.kalshi.co | https://docs.kalshi.com/getting_started/demo_env.md and https://docs.kalshi.com/getting_started/api_environments.md | Matches the URLs quoted verbatim in the project brief |
| 14 | Pagination | Cursor-based: response `cursor` passed back as `cursor` query param until empty | https://docs.kalshi.com/getting_started/pagination.md | Collector paginates `/events` this way |
| 15 | Settlement semantics | Settled markets carry `result` = "yes"/"no"; each winning contract pays $1; settlement sources listed on the event | https://docs.kalshi.com/getting_started/market_settlement.md | Demo market objects include empty `result` while active (captured live); settled results stored in `data/resolutions.json` |

## Topic series evidence (official)

| Topic | Evidence |
|---|---|
| Gas prices | Kalshi fee schedule lists series `KXAAAGASM` "US gas price": https://kalshi.com/docs/kalshi-fee-schedule.pdf ; collector also matches `KXGAS*` prefixes and "gas price" title keywords |
| Crypto | Fee schedule + exchange series (e.g. `KXBTCD` Bitcoin price above/below, `KXBTC15M`); collector matches `KXBTC/KXETH/KXSOL/KXXRP/KXDOGE/KXCRYPTO` prefixes and crypto keyword regex, plus any `Crypto` category |
| Elections | Category `Elections` observed live on demo (`KXNEXTNATOSECGEN`, `KXNEWPOPE` events carry it) + keyword match |
| Golf | Fee schedule lists `KXPGATOUR` (PGA Tour), `KXPGARYDER` (Ryder Cup), `KXPGASOLHEIM` (Solheim Cup): https://kalshi.com/docs/kalshi-fee-schedule.pdf ; collector matches `KXPGA*/KXGOLF/KXLPGA/KXDPWORLD` prefixes + golf keywords |
| Culture | Fee schedule lists `KXEMMY*` award series; collector matches `Culture/Entertainment` categories + award-show keyword regex |

## Values deliberately left blank / unverified

See `docs/FLAGGED.md` and the site's Flagged for Review page. Nothing was inferred: where the
exchange does not report a field (e.g. an official "dollar volume"), the site shows the
clearly-labeled estimate and flags it; where no demo credentials exist, portfolio/trade rows
stay empty and flagged.
