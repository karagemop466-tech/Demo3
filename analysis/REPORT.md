# Analysis report

Generated 2026-11-20T12:15:15+00:00 from demo run `20261120T121208Z` and production run `20261120T121407Z`.

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
| crypto | 5217 | 2,223,100,114.09 | 414,526,838.83 | 253,015,293.53 | 49,552,964.27 | 30,055.54 | 0.0 |
| elections | 267 | 11,026,212,353.07 | 3,708,371,386.87 | 1,080,846,474.61 | 269,108,570.69 | 2,405,850.66 | 0.005 |
| culture | 254 | 34,463,984.89 | 23,028,516.74 | 3,687,571.80 | 2,001,340.87 | — | 0.02 |
| golf | 1171 | 18,376,234.42 | 16,911,744.95 | 205,804.79 | 186,315.04 | — | 0.0 |
| gas | 126 | 576,841.46 | 521,730.82 | 86,043.70 | 68,452.83 | — | 0.02 |

## Resolution outcomes

_Count of settled markets per topic by Kalshi `result` (yes/no/scalar/blank). Input: data/resolutions.json (GET /markets?status=settled)._

| Topic | yes | no | scalar | blank |
|---|---|---|---|---|
| crypto | 1016 | 3398 | 0 | 0 |
| gas | 796 | 2595 | 0 | 0 |
| golf | 332 | 3538 | 46 | 0 |
| elections | 73 | 166 | 0 | 0 |
| culture | 224 | 383 | 0 | 0 |

## Resolution study: realised outcome vs. price

_yes_expectancy = win_rate_yes - avg_yes_price; no_expectancy = (1 - win_rate_yes) - (1 - avg_yes_price). Both in dollars per contract, fees excluded._

Input: data/resolutions-compact.json (settled markets with a result and a last price) — usable rows 12,521, excluded {'no_result': 0, 'no_price': 0, 'scalar_result': 46}.

| YES price band | n | resolved yes | win rate | avg YES price | YES expectancy / contract | NO expectancy / contract |
|---|---|---|---|---|---|---|
| <=0.10 | 10,478 | 808 | 7.71% | 0.0039 | +0.0732 | -0.0732 |
| 0.10-0.20 | 143 | 6 | 4.20% | 0.1366 | -0.0946 | +0.0946 |
| 0.20-0.40 | 76 | 11 | 14.47% | 0.2863 | -0.1416 | +0.1416 |
| 0.40-0.60 | 41 | 19 | 46.34% | 0.4768 | -0.0134 | +0.0134 |
| 0.60-0.80 | 35 | 15 | 42.86% | 0.6820 | -0.2534 | +0.2534 |
| 0.80-0.90 | 47 | 35 | 74.47% | 0.8602 | -0.1155 | +0.1155 |
| 0.90-0.99 | 276 | 197 | 71.38% | 0.9613 | -0.2476 | +0.2476 |
| >=0.99 | 1,425 | 1,350 | 94.74% | 0.9952 | -0.0478 | +0.0478 |

**0.80-0.99 favourite band**: n=929, win rate 82.13%, avg price 0.9749, YES expectancy -0.1536/contract, NO expectancy +0.1536/contract.

**0.01-0.20 longshot band**: n=1,820, win rate 1.65%, avg price 0.0322, YES expectancy -0.0158/contract, NO expectancy +0.0158/contract.

**all settled rows**: n=12,521, win rate 19.50%, avg price 0.1477, YES expectancy +0.0472/contract, NO expectancy -0.0472/contract.

Caveats:
- last_price_dollars is the last traded price, not the average price paid by holders.
- Fees are excluded; Kalshi series carry fee_type (quadratic/flat) and a fee_multiplier.
- Only markets that settled inside the collection window are counted.
- Historical expectancy does not predict future results.

## Strategy candidates from the current order book

Policy: `{"longshot_max_yes": 0.2, "min_volume_24h": 1.0, "max_price": 0.99, "max_spread": 0.04, "min_resting_depth_dollars": 50.0, "size_contracts": 10, "where": "docs/portfolio/STRATEGY.md"}`

- candidates that survived the rules: **2**
- markets skipped, including 0 rejected because they sit in the measured negative-expectancy favourite band
- simulation: `{"candidates": 2, "simulated": 2, "total_cost_dollars": 19.52, "median_breakeven_probability": 0.976}`

Simulation, not a forecast or backtest. It answers 'what would these orders cost right now given the visible book' and nothing more. The probability that the market resolves in your favour is not knowable from this dataset.

## Settlement timing

_(settlement_ts - close_time) in hours, for rows where both timestamps exist._

- observations: 12567
- median: 0.13 h
- mean: 247.36 h
- p90: 8.36 h
- settled before scheduled close: 0

## Liquidity snapshot

_Per tracked market: total resting dollars and derived YES spread from the orderbook._

- markets sampled: 34
- median resting dollars: 1084837.97
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

