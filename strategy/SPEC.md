# Strategy lab — specification and verification (session 26973298)

Requirement this addresses (owner brief, verbatim): *"Automate simulated trades to test different
strategies"* and *"analyze the results of the trades and categorize trades and create strategies
based on the type of trade"*.

Audit of `main` at `b3b2b231` before this session started: the site already had **paper trading**
(`assets/trade.js`, labeled simulated fills) and generic *candidate strategy* notes generated from
whatever fills a user typed in. There was **no measured backtest** — no rule was ever run over
recorded prices and scored. This page adds exactly that, using only data already committed to the
repository.

## 1. What is simulated

| Item | Rule | Source |
|---|---|---|
| Fill price | The candle's `price.close_dollars`, i.e. the last traded YES price in the period. Buy NO at `1 − price` (binary complement). | [candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks), [orderbook responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Quotes | `yes_bid` / `yes_ask` closes are reported as the spread estimate and **not** applied to fills (bid/ask can invert around a stale quote in the raw captures). | same |
| Fee | `round_up(M × 0.07 × C × P × (1 − P))`, `M = 1`, taker only; no fee on a settlement exit | [fee schedule PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf), [live fee schedule](https://kalshi.com/fee-schedule), [settlement](https://docs.kalshi.com/getting_started/market_settlement) |
| Exit — settled | `settlement_value_dollars` from the committed settled snapshot | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) |
| Exit — marked | Last traded price at the horizon candle; the trade is labeled `mark`, never "settled" | [candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) |
| Size | 1 contract per trade; no slippage or depth modelling | — |
| Liquidity filter | Entry candle must record `volume_fp > 0` | [candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) |

The fee function is verified against **all 21 rows** of the official 100-contract table in the
fee-schedule PDF (`scripts/tests/test_backtest.py::FeeFormulaTest`). The one-contract column of
that PDF is itself rounded to the cent, so the closed-form value is used and pinned by a test.

## 2. Strategy families (fixed before scoring)

| Family | Rules | Horizon |
|---|---|---|
| Momentum (`MOM_1/3/6`) | After a ≥ \$0.10 close-to-close move, take the **same** side | 1 / 3 / 6 candles |
| Reversion (`FADE_1/3/6`) | After a ≥ \$0.10 close-to-close move, take the **opposite** side | 1 / 3 / 6 candles |
| Threshold (`CHEAP_YES_15`, `CHEAP_NO_15`) | Buy the side priced at ≤ \$0.15 | 6 candles |

The \$0.10 threshold is the owner's own alerting threshold, so the same events that would fire a
live alert are the events that are backtested.

## 3. Datasets (never mixed)

| Dataset | Series | Trades | Exit types | Why |
|---|---|---|---|---|
| **Resolved** | 2 | 4 | settlement only | The only recorded series in the repo with **both** a price path and a documented settlement (both are `KXAAAGASW` gas markets that settled on 2026-10-26). |
| **Exploratory** | 81 | 23,323 | mark only | The committed collector candles (`data/latest/candles.json`, `data/history/*.json`). None of these had settled at capture time. |

Verification that the exploratory series really were unresolved: for every batch of the 37
`data/history` tickers, `GET /markets?status=settled&tickers=…` returned an empty list
(replayable, e.g.
[this request](https://external-api.demo.kalshi.co/trade-api/v2/markets?status=settled&tickers=BEYONCEGENRE-30-TRA,KXARTISTCOLLABDRAKEKENDRICK-30,KXBRUVSEAT-35,KXECCOMPACT-30,KXEUEXITCOUNTRY-30-HUN)),
and `?tickers=…` without the status filter showed `status: "active"`, `result: ""`.
`data/latest/candles.json` markets are 2028 election nominees, also open.

## 4. How to reproduce

```bash
python3 scripts/backtest_strategies.py     # writes strategy/data/backtest.json
python3 scripts/build_strategy_page.py     # writes strategy.html
python3 -m unittest discover -s scripts/tests -p "test_backtest*.py" -v
```

The backtest is fully offline: it reads committed JSON only, so a reviewer gets identical numbers.

## 5. Committed raw captures (the only network-dependent step)

`strategy/data/raw/*.json` holds two official 1440-minute candlestick responses for settled gas
markets, each with its exact `request_url` and `retrieved_at_utc`:

| File | Request URL | Retrieved |
|---|---|---|
| `KXAAAGASW-26OCT26-4.2400.json` | `…/series/KXAAAGASW/markets/KXAAAGASW-26OCT26-4.2400/candlesticks?start_ts=1790131200&end_ts=1792987140&period_interval=1440` | 2026-11-20T19:40Z |
| `KXAAAGASW-26OCT26-4.3000.json` | `…/series/KXAAAGASW/markets/KXAAAGASW-26OCT26-4.3000/candlesticks?start_ts=1790131200&end_ts=1792987140&period_interval=1440` | 2026-11-20T19:40Z |

Only the fields used by the engine are kept (open/close/previous traded price, `volume_fp`,
`yes_bid.close_dollars`, `yes_ask.close_dollars`, `end_period_ts`); the note field in each file
says so. The corresponding settlement rows (result + `settlement_value_dollars` + source URL) come
from the committed `data/latest/markets_settled.json`.

## 6. Reading the results honestly

- **The resolved sample is tiny** (2 markets). It is published because it is the only
  outcome-based evidence available offline, and it is explicitly labeled as too small to
  establish an edge.
- The exploratory sample is large but its exits are **candle marks**, so it is a *rule screen*,
  not profit. It is labeled that way on every table.
- The scoreboard publishes a **temporal split** (net PnL in the earlier vs later half of trades).
  A rule that only earns in one half is not evidence of a stable edge.
- The scoreboard publishes **concentration** (share of gross profit from the single best series),
  because one outlier series can carry a whole rule.
- ROI is computed against summed entry cost, which is why cheap long-shot rules show very high
  ROI percentages with very low win rates. Both are shown; neither is a recommendation.

## 7. Unverified items (published on the page and the Flagged register)

| ID | Item | Why unverified |
|---|---|---|
| ST-U1 | Whether the demo environment charges trading fees | The official demo documentation describes mock funds but does not state fee behaviour ([demo_env](https://docs.kalshi.com/getting_started/demo_env)). Fees are a stated modelling assumption. |
| ST-U2 | Whether candle closes equal achievable fills | Candles are aggregates; a live order may fill better or worse ([candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)). |
| ST-U3 | Sub-minute resolution | `period_interval` is limited to 1, 60 or 1440 minutes. |
| ST-U4 | Fee tier multipliers per series | The official schedule lists per-series multipliers; this backtest uses the default `M = 1` because the recorded series are not in the non-standard table. |

## 8. Limitations that are not bugs

- No slippage, no queue position, no partial fills, 1 contract per trade.
- Candles for some demo markets contain empty `price` objects (no trade in that period); those
  candles are skipped rather than interpolated.
- The demo exchange is not the production exchange: [demo_env](https://docs.kalshi.com/getting_started/demo_env)
  states demo prices may not reflect real markets.
