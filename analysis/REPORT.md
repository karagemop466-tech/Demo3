# Analysis report

Generated 2026-11-20T12:03:48+00:00 from demo run `None` and production run `None`.

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

## Resolution outcomes

_Count of settled markets per topic by Kalshi `result` (yes/no/scalar/blank). Input: data/resolutions.json (GET /markets?status=settled)._

| Topic | yes | no | scalar | blank |
|---|---|---|---|---|

## Settlement timing

_(settlement_ts - close_time) in hours, for rows where both timestamps exist._

- observations: 0
- median: None h
- mean: None h
- p90: None h
- settled before scheduled close: 0

## Liquidity snapshot

_Per tracked market: total resting dollars and derived YES spread from the orderbook._

- markets sampled: 0
- median resting dollars: None
- median derived YES spread: None

## Data quality

- markets sampled: 0
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

