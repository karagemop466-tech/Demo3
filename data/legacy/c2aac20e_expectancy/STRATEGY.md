# Portfolio, trade execution and strategy framework

This document explains exactly how the portfolio half of the dashboard works, what it will do once demo credentials
exist, and — more importantly — **what the collected data says about whether these strategies are worth running**.

---

## 1. What runs today

| Piece | Behaviour with no credentials | Behaviour with demo credentials |
|---|---|---|
| `collector/portfolio.py` | writes `data/portfolio.json` with `configured: false`, a reason, and the three enablement steps | signs real requests, stores balance, positions, orders, fills, settlements, and P&L components with the field each comes from |
| `.github/workflows/portfolio.yml` | runs, commits the "not configured" artifact, exits 0 | same, plus optional order placement behind two switches |
| `analysis/build.py` | publishes the explicit "not available, here's why" block in `analysis/report.json` | summarises real positions/fills |

**Nothing in this repo fabricates a balance.** A blank panel with a reason is the correct output when the data is
unavailable.

### Enabling it (account owner, ~10 minutes)

1. Open the Kalshi **demo** account → [demo.kalshi.co](https://demo.kalshi.co/) (tutorial:
   [creating and using a demo account](https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account)).
2. Create an API key — [API Keys](https://docs.kalshi.com/getting_started/api_keys.md). Ed25519 is the default.
3. Repository → Settings → Secrets and variables → Actions → add
   `KALSHI_DEMO_KEY_ID` and `KALSHI_DEMO_PRIVATE_KEY` (paste the whole PEM).
4. Actions → **portfolio** → *Run workflow*.

If you also want order placement, set `place_orders = true` **and** put each order in `data/orders-to-place.json`
with `"confirm": "I_ACCEPT_DEMO_MONEY_IS_FAKE"`. Production hosts are refused outright by the script.

---

## 2. Authentication, exactly as documented

```
pre-sign text = timestamp_ms + METHOD + path_without_query
signature     = base64(sign(pre-sign text))        # Ed25519, or RSA-PSS/SHA-256
headers       = KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
```

- Timestamp must be within **30 s** of Kalshi's clock; outside that window the request fails with
  `401 header_timestamp_expired` even if the signature is correct.
- Sign the path **without** the query string.
- Source: [API Keys](https://docs.kalshi.com/getting_started/api_keys.md).

---

## 3. Order execution — the endpoint changed, and that matters

The legacy write endpoints under `/portfolio/orders` (create, cancel, amend, decrease and their batch forms) have been
**removed and now return `410 Gone` with code `deprecated_v1_order_endpoint`**. Orders go to:

```
POST /trade-api/v2/portfolio/events/orders
{
  "ticker": "…",
  "client_order_id": "…",              // optional, unique while open
  "side": "bid" | "ask",               // bid = YES book, ask = NO book
  "count": "10.00",                    // fixed-point contracts
  "price": "0.5600",                   // REQUIRED, fixed-point dollars
  "time_in_force": "good_till_canceled" | "immediate_or_cancel" | "fill_or_kill",
  "self_trade_prevention_type": "taker_at_cross" | "maker"
}
```

- A `201` means **accepted, not resting** — read `fill_count` and `remaining_count`.
- Prices must sit on the market's own grid (`price_ranges`) or the order is rejected with `invalid_price`.
  `analysis/strategies.py` snaps every suggested price onto the grid and records whether the grid was available.
- Sources: [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2.md),
  [Order Errors](https://docs.kalshi.com/getting_started/order_errors.md).

---

## 4. How trades are categorised

Each fill/order can be labelled on four independent axes, all derived from observable fields:

| Axis | Buckets | Derived from |
|---|---|---|
| Topic | gas, elections, culture, crypto, golf | series → `collector/topics.json` |
| Side / action | yes / no, buy / sell | fill fields |
| Entry price band | ≤0.10, 0.10–0.30, 0.30–0.70, 0.70–0.90, >0.90 | fill price |
| Strategy shape | longshot, mid-price, favourite; maker / taker | price band + order type |

These describe the **shape** of a trade, not the trader's intent, and they can be recomputed from
`data/trade-log.jsonl` alone — which is the point: any performance claim must be reproducible from the log.

---

## 5. Strategy framework — and the evidence that killed the obvious one

### 5.1 The measured facts (from `data/expectancy.json`, 12,521 settled markets)

| Band (YES price) | n | Realised YES rate | Avg price paid | YES expectancy / contract | NO expectancy / contract |
|---|---|---|---|---|---|
| 0.01 – 0.20 | 1,820 | 1.65% | 0.0322 | −0.0158 | **+0.0158** |
| 0.80 – 0.99 | 929 | 82.13% | 0.9749 | **−0.1536** | +0.1536 |
| all rows | 12,521 | 19.50% | 0.1477 | +0.0472 | −0.0472 |

**Interpretation:** buying the "sure thing" at 97.5¢ to win $1 is a bad trade in this sample — it wins 82% of the time
and still loses 15.2¢ per contract. The cheap side is where the residual edge sat, and only just.

### 5.2 The rules that survived

| Rule | Condition | Why it survives | Status |
|---|---|---|---|
| **R1 longshot-fade** | buy **NO** when YES trades 0.01–0.20, 24h volume > 0, derived spread ≤ 0.04, NO ask ≤ 0.99 | measured +1.58¢/contract in that band | candidate generator (`analysis/strategies.py`) |
| **R2 favourite-trap** | YES ≥ 0.80 | measured **−15.23¢/contract** | detected and **explicitly not recommended**, listed with the number so the reason is visible |
| **R3 liquidity-provide** | rest a limit order | needs a fill model and maker-fee treatment per series (`fee_type`) | documented only, no auto-suggestion |
| **R4 avoid** | spread > 0.10, resting depth < $50, or price outside [0.01, 0.20] | book too thin to enter | enforced as a skip, with the reason published |

### 5.3 What the simulation is, and is not

`data/order-rules.json → simulation` answers one question: **what would these orders cost right now, given the visible
book?** It walks the actual ladder to see how many contracts exist at or better than the price, multiplies by the
size, and shows the payout if the side resolves YES. It is **not** a backtest, **not** a fill model, and **not** a
forecast. The probability that a market resolves in your favour is not knowable from this dataset.

### 5.4 Fees

Every series carries `fee_type` (`quadratic`, `quadratic_with_maker_fees`, `quadratic_with_combo_maker_fees`, `flat`)
and `fee_multiplier`. Fees are **excluded** from every expectancy figure in this repo because a correct calculation
needs the official fee schedule applied per series and per contract count. Before trading, compute fees — a 1.58¢ edge
is smaller than many fee schedules.

### 5.5 Prerequisites before anyone trades on this

1. **D13** — agree the P&L definition (realised vs. settlement revenue vs. fees).
2. **D9** — widen the settlement sample beyond the Nov-2026 window via the historical endpoints.
3. **D12** — name who is accountable for automated order entry, and the size limit.
4. Confirm demo results are not assumed to transfer: Kalshi states demo prices may not reflect real markets
   ([Demo Environment](https://docs.kalshi.com/getting_started/demo_env.md)).

---

## 6. Reading the portfolio page

| Panel | With data | Without credentials |
|---|---|---|
| Balance & portfolio value | `GET /portfolio/balance` fields | `—` + "requires a demo API key" |
| Positions | `GET /portfolio/positions?settlement_status=all` incl. `realized_pnl` | `—` |
| Orders / fills / settlements | `GET /portfolio/{orders,fills,settlements}` | `—` |
| Realised P&L | sum of `realized_pnl`, **field named** | `—` |
| Settlement revenue | sum of `revenue` (cents), **field named** | `—` |
| Fees paid | sum of `fee_cost` (dollars), **field named** | `—` |
| By topic / side / price band | joins to `data/dashboard.json` series | `—` |
| Strategy buckets | rule output, rule printed | `—` |

Three separate lines rather than one net number is deliberate: merging them would encode an accounting assumption
nobody has agreed to (D13).
