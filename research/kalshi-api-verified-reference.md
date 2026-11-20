# Kalshi Trade API — Verified Reference (session 6908a11a)

Status: **T2 done** (COORDINATION.md). Author session: `6908a11a` (branch `arena/6908a11a-demo3`).
Date of verification: **2026-11-20 (UTC)**.

Method: every row below was checked against either (a) an official Kalshi documentation page at
`docs.kalshi.com` fetched on 2026-11-20, or (b) a **live HTTP response** from the demo/production
API fetched on 2026-11-20 (the exact request URL is given per row and can be replayed in any
browser or client). Values that could not be confirmed from an official source are **blank and
flagged UNVERIFIED** — never inferred. Point-in-time values (prices, volumes) change continuously;
they are evidence that the endpoint/field exists, not current quotes.

Related in-repo documents: [EXECUTIVE_SUMMARY.md](../EXECUTIVE_SUMMARY.md),
[SUGGESTIONS.md](../SUGGESTIONS.md), [FLAGGED.md](../FLAGGED.md),
site data: [docs/data/verified.json](../docs/data/verified.json) (session 00a943bd).

---

## 1. Environments

| Item | Value | Source |
|---|---|---|
| Demo REST (recommended) | `https://external-api.demo.kalshi.co/trade-api/v2` | [docs.kalshi.com/getting_started/api_environments](https://docs.kalshi.com/getting_started/api_environments) |
| Demo REST (also supported) | `https://demo-api.kalshi.co/trade-api/v2` | same |
| Demo WebSocket (recommended) | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | same |
| Demo WebSocket (also supported) | `wss://demo-api.kalshi.co/trade-api/ws/v2` | same |
| Production REST (recommended) | `https://external-api.kalshi.com/trade-api/v2` | same |
| Demo UI / account signup | `https://demo.kalshi.co/` (credentials **not** shared with production; mock funds; "price and behavior … may not be reflective of real markets") | [docs.kalshi.com/getting_started/demo_env](https://docs.kalshi.com/getting_started/demo_env) |
| Demo account setup walkthrough | help.kalshi.com article "Creating and using a demo account" | [help.kalshi.com/en/articles/13823775](https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account) (linked from demo_env page) |

## 2. Authentication (needed only for portfolio/trading/WS)

| Item | Value | Source |
|---|---|---|
| Key types | **Ed25519** (recommended, RFC 8032, PKCS#8 PEM) and **RSA 2048** (RSA-PSS, SHA-256, MGF1, salt = digest length, PKCS#1 PEM) | [docs.kalshi.com/getting_started/api_keys](https://docs.kalshi.com/getting_started/api_keys) |
| Headers | `KALSHI-ACCESS-KEY` (key ID), `KALSHI-ACCESS-TIMESTAMP` (Unix ms), `KALSHI-ACCESS-SIGNATURE` (base64) | same |
| Pre-sign text | `timestamp + HTTP-method + path` — path **without query string**, starting at `/trade-api/v2` (e.g. sign `/trade-api/v2/portfolio/orders`, not the URL's query) | same; also [api_environments](https://docs.kalshi.com/getting_started/api_environments) "Request Signing" |
| Timestamp tolerance | ±30 s of Kalshi's clock, else `401 header_timestamp_expired` | [api_keys](https://docs.kalshi.com/getting_started/api_keys) |
| Key self-service endpoints | `POST /trade-api/v2/api_keys` (register own public key), `POST /trade-api/v2/api_keys/generate` (generate pair, `key_type` `rsa` when omitted) | same |
| Key limit | 100 directly-managed keys in production (demo may differ) | same |
| Public market data | **No key required** for market-data GETs (official quick start runs them unauthenticated against the demo base URL) | [quick_start_market_data](https://docs.kalshi.com/getting_started/quick_start_market_data) |

## 3. Public market-data endpoints (verified live against demo, unauthenticated)

| Endpoint | Verified live (2026-11-20) | Observed response (evidence) |
|---|---|---|
| `GET /markets?limit=n` | [markets?limit=3](https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=3) | `markets[]` with the fields in §4 |
| `GET /markets?series_ticker=X&status=open` | [markets?series_ticker=KXAAAGASW&status=open&limit=1](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXAAAGASW&status=open&limit=1) | gas market `KXAAAGASW-26NOV23-3.9400`, `status:"active"` |
| `GET /markets?series_ticker=X&status=settled` | [markets?series_ticker=KXAAAGASW&status=settled&limit=2](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXAAAGASW&status=settled&limit=2) | settled markets carry `result:"no"`, `status:"finalized"`, `settlement_ts`, `settlement_value_dollars` |
| `GET /events?limit=n&status=open` | [events?limit=60&status=open](https://external-api.demo.kalshi.co/trade-api/v2/events?limit=60&status=open) | `events[]` with `category`, `series_ticker`, `title`, `sub_title`, `mutually_exclusive`, `settlement_sources[]` |
| `GET /events?series_ticker=X` | [events?series_ticker=KXPGATOUR&limit=2](https://external-api.demo.kalshi.co/trade-api/v2/events?series_ticker=KXPGATOUR&limit=2) | golf events "2027 The Masters Champion" (`KXPGATOUR-MAST27`), "The RSM Classic Winner" (`KXPGATOUR-THRC26`) |
| `GET /events?category=X` | [events?category=Culture&limit=2](https://external-api.demo.kalshi.co/trade-api/v2/events?category=Culture&limit=2) | **UNFILTERED** — returned `KXELONMARS-99` (category "World") and `KXNEXTNATOSECGEN-99` (category "Elections"). The `category` query parameter is **not supported** on `/events`. See FLAGGED.md F4 |
| `GET /series?category=X` | [series?category=Culture&limit=1](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture&limit=1) | filtered; demo Culture series include `KXXBANNEDGROK` ("Will Grok be banned this year"), `KXXBANNEDMURRAYHILLGUY1`. Note: the `limit` parameter appears **not** enforced on this endpoint (responses were far larger than requested) — see FLAGGED.md F9 |
| `GET /series/{ticker}` | attempted [series/KXTIMEPOY](https://external-api.demo.kalshi.co/trade-api/v2/series/KXTIMEPOY) → error (series absent from demo); successful examples: KXAAAGASW / KXPGATOUR fields shown in §5 sources | series object with `category`, `categories[]`, `tags[]`, `fee_type:"quadratic"`, `contract_terms_url`, `settlement_sources[]` |
| `GET /markets/{ticker}/orderbook` | [orderbook for KXAAAGASW-26NOV23-3.9400](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.9400/orderbook) | `{"orderbook_fp":{"yes_dollars":[],"no_dollars":[]}}` — shape confirmed; arrays are `[price_dollars, size_fp]` pairs, **ascending**, best bid last; **bids only** (yes bids + no bids, because a yes bid at p = a no ask at 1−p) |
| `GET /series/{series}/markets/{ticker}/candlesticks` | [candlesticks (KXAAAGASW, 1h, 24h window)](https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASW/markets/KXAAAGASW-26NOV23-3.9400/candlesticks?start_ts=1795087650&end_ts=1795174050&period_interval=60) | HTTP 200 `{"candlesticks":[],"ticker":...}` (empty: no trading activity on this demo book); shape per docs §6 |
| ~~`GET /markets/{ticker}/candlesticks`~~ | [old path, failed](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.9400/candlesticks?start_ts=1795165000&end_ts=1795174000&period_interval=1) | **404-class failure** — the candlesticks path is now series-scoped (docs §6). Any client still on the old path gets errors. The merged site (`docs/assets/app.js`) already uses the new path |
| `GET /markets/{ticker}/trades` | [trades?limit=2](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.9400/trades?limit=2) | **UNVERIFIED** — the page-fetch tool returned an error; endpoint is documented in the official index ([get-trades](https://docs.kalshi.com/api-reference/market/get-trades), [get-market-trades](https://docs.kalshi.com/api-reference/market/get-market-trades)) but needs a browser/client re-test. FLAGGED.md F7 |

## 4. Market object — fields observed on live demo responses

| Field | Example (from live URL in §3) | Notes |
|---|---|---|
| `ticker` | `KXAAAGASW-26NOV23-3.9400` | `{SERIES}-{DATE}-{STRIKE}` or `-CANDIDATE` |
| `event_ticker` | `KXAAAGASW-26NOV23` | — |
| `title` / `yes_sub_title` / `no_sub_title` | "Will average **gas prices** be above $3.9400?" / "Above 3.9400" | — |
| `status` | `"active"` (query used `status=open`), `"finalized"` (query `status=settled`) | naming mismatch — FLAGGED.md F5 |
| `result` | `""` (live) → `"no"` (settled) | yes/no outcome once resolved |
| `last_price_dollars` | `"0.0200"` | **string, dollars** (fixed-point migration) |
| `yes_bid_dollars` / `yes_ask_dollars` / `no_bid_dollars` / `no_ask_dollars` | `"0.0000"` / `"1.0000"` / `"0.0000"` / `"1.0000"` | strings |
| `yes_bid_size_fp` / `yes_ask_size_fp` | `"0.00"` | top-of-book sizes |
| `volume_fp` / `volume_24h_fp` / `open_interest_fp` | `"3421.27"` / `"0.00"` / `"3421.27"` | **contracts**, not dollars |
| `notional_value_dollars` | `"1.0000"` | each contract pays **$1** → dollar-volume derivation in §8 |
| `close_time` / `open_time` / `expected_expiration_time` / `latest_expiration_time` | ISO-8601 Z | — |
| `strike_type` / `market_type` / `price_level_structure` | `greater` / `binary` / `linear_cent` | plus `price_ranges[]` with `step` |
| `rules_primary` / `rules_secondary` | "If average regular gas prices … according to AAA …" | — |
| `settlement_ts` / `settlement_value_dollars` | present on settled markets | — |
| `can_close_early` / `early_close_condition` / `settlement_timer_seconds` | `true` / "… after a winner is declared." / `60`–`300` | — |

## 5. Series & event objects (observed)

| Field | Observed on | Source (live URL) |
|---|---|---|
| series `category`, `categories[]`, `tags[]`, `frequency`, `fee_type`, `contract_terms_url`, `settlement_sources[]` | Sports/Elections/Culture series | [series?category=Sports&limit=3](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Sports&limit=3), [series?category=Elections&limit=1](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Elections&limit=1) |
| event `category`, `sub_title`, `mutually_exclusive`, `settlement_sources[]`, `product_metadata.competition` | golf events | [events?series_ticker=KXPGATOUR&limit=2](https://external-api.demo.kalshi.co/trade-api/v2/events?series_ticker=KXPGATOUR&limit=2) |
| fee model `quadratic` on series | e.g. KXPGATOUR | same series URLs |

## 6. Candlesticks (official shape)

| Item | Value | Source |
|---|---|---|
| Path | `GET /series/{series_ticker}/markets/{ticker}/candlesticks` | [docs.kalshi.com/api-reference/market/get-market-candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) |
| Required query | `start_ts`, `end_ts` (Unix seconds), `period_interval` ∈ `1` (1 min) / `60` (1 h) / `1440` (1 day) | same |
| Optional | `include_latest_before_start` (boolean, prepends latest candle before start) | same |
| Response | `candlesticks[]` each with `end_period_ts`, `yes_bid`/`yes_ask`/`price` blocks of `{open_dollars, low_dollars, high_dollars, close_dollars, …}`, `volume_fp`, `open_interest_fp` | same |
| Historical cutoff | markets settled before the cutoff: `GET /historical/markets/{ticker}/candlesticks` | same |

## 7. WebSocket (requires authentication — design constraint)

| Item | Value | Source |
|---|---|---|
| Handshake auth | **Required** — `KALSHI-ACCESS-*` headers on connect; signature over `timestamp + "GET" + "/trade-api/ws/v2"` | [docs.kalshi.com/getting_started/quick_start_websockets](https://docs.kalshi.com/getting_started/quick_start_websockets) |
| Public market-data channels | `ticker`, `trade`, `market_lifecycle_v2`, `multivariate_market_lifecycle` (no *additional* per-channel auth, but the **session itself is authenticated**) | same |
| Private channels | `orderbook_delta`*, `fill`, `market_positions`, `communications`, `order_group_updates`, `user_orders` (*orderbook_delta carries public data but sits in the private group per docs' key-permission table) | same |
| Keep-alive | server ping after 10 s idle | same |
| Implication | a browser page without API credentials **cannot** stream; the dashboard polls REST instead (60 s list refresh, 5 s chart sampling, candlesticks for 1 m/60 m) | same + merged site `docs/assets/app.js` |

## 8. Dollar-volume derivation (user's "highest dollar amount" metric)

The API exposes volume in **contracts** (`volume_fp`) and has **no dollar-volume field**
(also noted by integration session 00a943bd in `docs/data/verified.json`). Each contract's
`notional_value_dollars` is `"1.0000"` (live evidence: [markets?limit=3](https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=3)).
Therefore `dollar_volume ≈ Σ_markets volume_fp × traded_price_$` (proxy when trade-by-trade prices
are unavailable: `volume_fp × last_price_dollars`). This is a **derived estimate, not an API
field** — treated as such in all outputs and flagged in [FLAGGED.md](../FLAGGED.md) F8.

## 9. Portfolio & trading endpoints

| Endpoint | Status | Source |
|---|---|---|
| `GET /trade-api/v2/portfolio/balance` | **verified in official docs sample** (Python example signs exactly this path) | [api_keys](https://docs.kalshi.com/getting_started/api_keys) |
| `POST /trade-api/v2/portfolio/events/orders` (place; optional `client_order_id`), `POST /portfolio/events/orders/{order_id}/amend`, `DELETE /portfolio/events/orders/{order_id}` | verified in official quick start | [quick_start_create_order](https://docs.kalshi.com/getting_started/quick_start_create_order) |
| `GET /portfolio/positions`, `GET /portfolio/fills`, `GET /account/limits` | **third-party listing — UNVERIFIED against official docs** (third-party [botforkalshi guide](https://www.botforkalshi.com/blog/kalshi-api-tutorial)); confirm in the official portfolio reference before use | third-party — flagged F8 |
| Rate limits | **UNVERIFIED** — third-party reports (token budgets, 429s, Basic ≈ 200 read/100 write tokens/s); confirm against [docs.kalshi.com/getting_started/rate_limits](https://docs.kalshi.com/getting_started/rate_limits) | flagged F8 |

## 10. Category taxonomy observed on demo (2026-11-20)

| Category value (exact string) | Evidence (live URL) |
|---|---|
| `Sports` | [series?category=Sports](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Sports&limit=3) |
| `Elections` | [series?category=Elections](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Elections&limit=1); events [KXNEXTNATOSECGEN-99](https://external-api.demo.kalshi.co/trade-api/v2/events?limit=60&status=open) |
| `Culture` | [series?category=Culture](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture&limit=1) |
| `Financials` | [series?category=Financials](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Financials&limit=3) |
| `World`, `Climate and Weather`, `Science and Technology` | [events?limit=60&status=open](https://external-api.demo.kalshi.co/trade-api/v2/events?limit=60&status=open) |
| `Crypto` | **not observed on demo by this session**; observed on production per in-repo [docs/data/verified.json](../docs/data/verified.json) (`series?category=Crypto&include_volume=true`). Crypto markets on demo verified directly by series ticker instead (below) |

## 11. Focus-series existence check on demo (live, 2026-11-20)

| Focus area | Series | Live evidence | Status |
|---|---|---|---|
| Gas prices | `KXAAAGASW` ("Will average gas prices be above $X" — AAA) | [markets?series_ticker=KXAAAGASW&status=open](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXAAAGASW&status=open&limit=1) | present, open market with OI 3421.27 |
| Crypto | `KXBTC` ("Bitcoin price range…", CF Benchmarks BRTI) | [markets?series_ticker=KXBTC&status=open](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXBTC&status=open&limit=2) | present; books empty at check time |
| Crypto | `KXETH` (Ethereum, ERTI) | [markets?series_ticker=KXETH&status=open](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXETH&status=open&limit=1) | present |
| Golf | `KXPGATOUR` (per-player winner markets) | [markets?series_ticker=KXPGATOUR&status=open](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXPGATOUR&status=open&limit=1) | present ("The RSM Classic: Bill Haas wins") |
| Elections | multiple (e.g. `KXPRESRUN`, `KXSPEAKERMAJLEADCOMBO`, `KXNEXTNATOSECGEN`) | [series?category=Elections](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Elections&limit=1) | present |
| Culture | `KXXBANNEDGROK`, `KXXBANNEDMURRAYHILLGUY1` | [series?category=Culture](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture&limit=1) | present |
| Culture | `KXTIMEPOY`, `KXBOXOFFICE` | [series/KXTIMEPOY](https://external-api.demo.kalshi.co/trade-api/v2/series/KXTIMEPOY) (error), [markets?series_ticker=KXBOXOFFICE](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXBOXOFFICE&status=open&limit=1) (empty) | **absent / no open markets on demo** — flagged |
| Elections | `KXPRES28`, `KXHOUSE26` | [markets?series_ticker=KXPRES28](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXPRES28&status=open&limit=1), [KXHOUSE26](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXHOUSE26&status=open&limit=1) | empty on demo (ticker may be wrong or no open markets) — unverified which |

## 12. Demo liquidity reality (material for the user's "track highest dollar events on demo" ask)

| Observation | Evidence |
|---|---|
| Demo gas market book empty at check time | [orderbook](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.9400/orderbook) → `{"yes_dollars":[],"no_dollars":[]}` |
| Demo BTC markets `volume_fp:"0.00"`, zero sizes | [markets?series_ticker=KXBTC…](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXBTC&status=open&limit=2) |
| Demo candlesticks empty over 24 h | [candlesticks URL in §3](https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASW/markets/KXAAAGASW-26NOV23-3.9400/candlesticks?start_ts=1795087650&end_ts=1795174050&period_interval=60) |
| Exception: the gas weekly market had OI/volume 3421.27 | [markets?series_ticker=KXAAAGASW…](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXAAAGASW&status=open&limit=1) |

Implication: on the **demo** environment, "highest dollar amount live events" rankings will often be
near-zero. The merged site's live panels target the **production** API for this reason (see
[docs/assets/app.js](../docs/assets/app.js)). This is an owner decision — see
[SUGGESTIONS.md](../SUGGESTIONS.md) Q1.

## 13. Unverified items (blank values — never inferred)

| Item | What would confirm it |
|---|---|
| Browser CORS on the demo/production API | a real browser fetch of any §3 URL; official docs ship browser `fetch()` examples for market data ([quick_start_market_data](https://docs.kalshi.com/getting_started/quick_start_market_data)), which is supporting but not conclusive evidence |
| `GET /markets/{ticker}/trades` response shape on demo | replay the §3 trades URL in a browser/client |
| `GET /portfolio/positions`, `GET /portfolio/fills`, `GET /account/limits` | official portfolio reference pages |
| Rate-limit budgets per tier | [rate_limits](https://docs.kalshi.com/getting_started/rate_limits) |
| `limit` parameter behavior on `GET /series?category=` | observe actual response size vs `limit` |
| Trading fee amounts | Kalshi fee schedule (series carry `fee_type:"quadratic"` — live evidence in §5) |
