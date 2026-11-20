# Analysis report

Generated 2026-11-20T12:02:12+00:00 from demo run `20261120T115918Z` and production run `20261120T120117Z`.

Every figure below is an aggregation of API fields listed in *Definitions*;
nothing is estimated. Where data is unavailable it says so instead of showing zero.

## Definitions

- **contracts_traded** — Kalshi `volume_fp` — contracts exchanged on the market. Source: GET /markets.
- **contracts_traded_24h** — Kalshi `volume_24h_fp`. Source: GET /markets.
- **open_interest_contracts** — Kalshi `open_interest_fp` — contracts currently held. Source: GET /markets.
- **traded_notional_dollars_derived** — volume_fp x price_used, where price_used is last_price_dollars if present else the mid of yes bid/ask. Derived, not returned by Kalshi.
- **open_interest_dollars_derived** — open_interest_fp x price_used (same price basis). Derived.
- **resting_liquidity_dollars** — sum over orderbook levels of price x contracts, for both YES and NO bids. Computed from GET /markets/{ticker}/orderbook.
- **implied_asks** — Kalshi returns bids only; a YES bid at X is a NO ask at 1-X, so asks are derived. Source: https://docs.kalshi.com/getting_started/orderbook_responses.md

## Per-topic aggregates (demo environment)

| Topic | Open markets | Contracts traded | Open interest (contracts) | Traded notional $ (derived) | Open-interest $ (derived) | Resting liquidity $ | Median price |
|---|---|---|---|---|---|---|---|
| crypto | 5217 | 2,223,100,260.09 | 414,526,990.83 | 253,015,378.99 | 49,553,049.79 | 30,055.54 | 0.0 |
| elections | 267 | 11,026,203,134.84 | 3,708,366,895.35 | 1,190,552,459.60 | 321,947,164.53 | 2,537,118.37 | 0.005 |
| culture | 254 | 34,463,746.36 | 23,028,325.58 | 3,687,524.81 | 2,001,295.30 | — | 0.02 |
| golf | 1171 | 18,369,763.98 | 16,907,205.87 | 203,346.96 | 183,906.46 | — | 0.0 |
| gas | 126 | 576,633.60 | 521,618.44 | 88,413.90 | 70,255.25 | — | 0.02 |

## Resolution outcomes

_Count of settled markets per topic by Kalshi `result` (yes/no/scalar/blank). Input: data/resolutions.json (GET /markets?status=settled)._

| Topic | yes | no | scalar | blank |
|---|---|---|---|---|
| crypto | 1023 | 3391 | 0 | 0 |
| golf | 332 | 3538 | 46 | 0 |
| elections | 73 | 166 | 0 | 0 |
| gas | 796 | 2595 | 0 | 0 |
| culture | 224 | 383 | 0 | 0 |

## Settlement timing

_(settlement_ts - close_time) in hours, for rows where both timestamps exist._

- observations: 12567
- median: 0.13 h
- mean: 247.35 h
- p90: 8.36 h
- settled before scheduled close: 0

## Liquidity snapshot

_Per tracked market: total resting dollars and derived YES spread from the orderbook._

- markets sampled: 34
- median resting dollars: 1084947.76
- median derived YES spread: 0.001

## Data quality

- markets sampled: 7035
- markets with at least one missing field: 0

## Not available (and why)

### portfolio

GET /portfolio/* requires the signed headers KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP and KALSHI-ACCESS-SIGNATURE (Ed25519 or RSA-PSS). No demo API key is configured for this repository, so no balance, position, fill or P&L figure is published. Observed 401 responses are recorded in the Auth status panel.

To enable: Add repository secrets KALSHI_DEMO_KEY_ID and KALSHI_DEMO_PRIVATE_KEY (Settings > Secrets and variables > Actions). The workflow portfolio.yml then writes data/portfolio.json and the Portfolio page lights up with real numbers.

Source: https://docs.kalshi.com/getting_started/api_keys.md

### trade_execution

POST /portfolio/orders is a signed, authenticated write. Without a key the dashboard cannot place demo orders, and it must not fabricate fills.

To enable: Same secrets as above, plus ALLOW_LIVE_DEMO_TRADING=true on the workflow so a human consciously enables write access.

Source: https://docs.kalshi.com/api-reference/orders/create-order.md

### websocket

The WebSocket API requires the same signed handshake even for public market-data channels, so it cannot be opened from an unauthenticated static page. The site therefore polls committed REST snapshots (hourly, plus manual dispatch).

To enable: Add the same demo key secrets; collector/ws_stream.py can then keep a signed socket open and append tick-by-tick observations to data/history/. Until then the chart uses REST candlesticks and the hourly snapshot log, both of which are real API data.

Source: https://docs.kalshi.com/getting_started/quick_start_websockets.md

