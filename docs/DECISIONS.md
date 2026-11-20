# Decision register — questions, what we know, what we don't, and what would close the gap

**Purpose.** The brief asks for "a clear list of questions, information and answers that need to be addressed before
any decision can be reasonably made based upon the information we already have and do not have". This file is that
list. Each item states:

- **Q** — the question a decision-maker must answer,
- **Known** — what the collected data / official docs already establish (with a link),
- **Unknown / missing** — exactly what information is absent,
- **What would close it** — the concrete action, and who can take it,
- **Blocks?** — whether an implementation decision is currently unsafe without it.

Status legend: `CLOSED` (evidence in hand) · `OPEN` (needs the account owner or an external source) ·
`RESEARCHABLE` (this project can close it with another data run).

---

## A. Scope and definition questions

### D1 — What does "highest dollar amount" mean? `OPEN → partially resolved`
- **Known:** Kalshi's `Market` object exposes `volume_fp` (contracts traded), `volume_24h_fp`,
  `open_interest_fp`, `last_price_dollars`, `yes_bid/ask_dollars`, and the order book exposes resting size per price.
  Kalshi does **not** return a dollar notional field. Source:
  [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets.md),
  [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses.md).
- **Unknown:** which of those the business means. They rank markets very differently — in this snapshot the largest
  markets by contracts traded are 1–5¢ longshots with **no resting bids at all** (0.00 bid / 1.00 ask shells), while
  the deepest books are election nomination markets with up to **$4.24 M** resting.
- **What would close it:** a one-line business definition. Until then the dashboard publishes **four labelled
  metrics** and lets the reader pick, rather than inventing a single "dollar amount".
- **Blocks?** No (mitigated by publishing all four), but it blocks any *ranking* claim.

### D2 — Which environment is the source of truth? `CLOSED`
- **Known:** Demo is `https://external-api.demo.kalshi.co/trade-api/v2` (recommended) and
  `https://demo-api.kalshi.co/trade-api/v2`; credentials are not shared with production; demo prices "may not be
  reflective of those in real markets". Sources:
  [API Environments](https://docs.kalshi.com/getting_started/api_environments.md),
  [Demo Environment](https://docs.kalshi.com/getting_started/demo_env.md).
- **Resolution taken:** demo is primary (it is what the brief names and where the demo portfolio lives); a
  production snapshot is published **alongside and clearly labelled** so demo distortions are visible.
- **Blocks?** No.

### D3 — Where is the boundary of "culture"? `OPEN`
- **Known:** Kalshi publishes an `Entertainment` category (music charts, film, TV, awards) and it is the only
  category that matches "culture". 2,674 series matched; 14 were selected by volume.
- **Unknown:** whether sports-adjacent entertainment, celebrity, or "mentions" markets belong in scope.
- **What would close it:** a list of included/excluded series titles for review. Every matched series is listed on the
  Culture page precisely so this can be audited.
- **Blocks?** No, but the topic's headline totals are sensitive to it.

### D4 — Is "gas prices" only the AAA national average? `OPEN`
- **Known:** `KXAAAGASW` ("US gas price up", weekly, category `Economics`) settles from
  [AAA gas prices](https://gasprices.aaa.com/) — verified via
  [`GET /series/KXAAAGASW`](https://demo-api.kalshi.co/trade-api/v2/series/KXAAAGASW).
- **Unknown:** whether regional gas series, diesel, or crude-oil series should count.
- **Deliberate decision:** the `gas` topic deliberately **excludes** the broad `Economics` category and generic
  `oil`/`energy` tags, because ~900 unrelated series share that category. Matching is ticker-prefix / tag / title only
  (`collector/topics.json`).
- **Blocks?** No.

### D5 — What counts as "resolved"? `CLOSED`
- **Known:** settlement sets `result` to `yes`, `no`, or `scalar`, and pays $1/contract to the winning side; the
  `Market` object carries `settlement_value_dollars`, `settlement_ts`, `expiration_value`. Sources:
  [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement.md),
  [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets.md).
- **Observed:** 46 of 12,567 settled rows (all in golf) are `scalar`, not yes/no. They are counted separately and
  never coerced into yes/no.
- **Blocks?** No.

---

## B. Data quality questions

### D6 — Can the browser call the Kalshi API directly from GitHub Pages? `RESEARCHABLE`
- **Known:** the docs do not state a CORS policy. The collector therefore performs an **empirical probe**: it calls
  the API with `Origin: https://karagemop466-tech.github.io` and records the returned `access-control-*` headers in
  every run (`data/live.json` → `cors_probe`).
- **Unknown:** whether the probe returns an allow-origin header at all.
- **What would close it:** read the recorded probe result in the latest artifact; if no allow-origin header comes
  back, browser-side direct polling is impossible and the site must rely on committed snapshots (which it already
  does, so nothing breaks either way).
- **Blocks?** No.

### D7 — How "live" can an unauthenticated static site be? `CLOSED`
- **Known:** WebSocket connections **require signed headers on the handshake even for public market-data channels**
  ([Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md)). A static page
  cannot hold a secret, so it cannot open a socket.
- **Consequence, implemented:** "live" = hourly REST snapshots (GitHub Actions cron) + per-market candlesticks at 1/60/1440
  minutes + an append-only observation log, each labelled with capture time. This is stated on the site, not hidden.
- **Blocks?** No.

### D8 — How stale is "current price"? `CLOSED`
- **Known:** Kalshi documents short-lived response caching ("prices, sizes and status can lag the exchange by several
  seconds, and filtered listings can lag longer"); most recent candlesticks "can be a few seconds behind".
  [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets.md),
  [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md).
- **Unknown:** the exact cache duration at any moment.
- **Blocks?** No; the site shows capture timestamps and never claims sub-second freshness.

### D9 — Do we have enough settlement history for reliable expectancy? `OPEN`
- **Known:** 12,567 settled rows, but they are concentrated in a short window (Nov 2026 = 12,004 rows; Oct 2026 = 563
  rows), dominated by short-dated crypto and golf contracts.
- **Unknown:** whether the measured expectancy holds across regimes, seasons and market types.
- **What would close it:** deeper history via `GET /historical/markets` and `GET /historical/trades`
  ([Historical Data](https://docs.kalshi.com/getting_started/historical_data.md)), plus a rolling comparison.
- **Blocks?** Yes — **any strategy recommendation must be treated as provisional until this is broader.** The site says
  so next to every number.

---

## C. Portfolio and trading questions

### D10 — How do we authenticate to the demo account? `CLOSED`
- **Known:** demo API keys are Ed25519 (default) or RSA-2048; sign `timestamp + METHOD + path` **without** query
  string; send `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`; timestamp must be within
  **30 s** of Kalshi's clock or the request returns `401 header_timestamp_expired`. Source:
  [API Keys](https://docs.kalshi.com/getting_started/api_keys.md).
- **Implemented:** `collector/portfolio.py` signs exactly this way and records every response.
- **Blocks?** No — the code is ready and dormant.

### D11 — Which order endpoint is current? `CLOSED (and this mattered)`
- **Known:** the legacy `/portfolio/orders` write endpoints (create, cancel, amend, decrease, and batch forms) have
  been **removed and return `410 Gone`** with code `deprecated_v1_order_endpoint`. Orders go to
  `POST /portfolio/events/orders` with `{ticker, side: bid|ask, count, price, time_in_force,
  self_trade_prevention_type}`; a `201` means accepted, not resting — check `remaining_count`. Sources:
  [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2.md),
  [Order Errors](https://docs.kalshi.com/getting_started/order_errors.md).
- **Also known:** prices must sit on the market's own `price_ranges` grid or the order is rejected with
  `invalid_price`. The pipeline now carries each market's `price_ranges` and snaps candidate prices onto it.
- **Blocks?** No — corrected before shipping.

### D12 — Should the dashboard place trades automatically? `OPEN — needs an explicit human decision`
- **Known:** the account can place demo orders with mock funds; the brief asks to "execute trades on events and track
  the performance".
- **Unknown:** who is accountable for automated order entry, how large, and under what stop conditions.
- **Mitigation implemented:** placement is **double-gated** — workflow input `place_orders = true` **and** every order
  spec must carry `"confirm": "I_ACCEPT_DEMO_MONEY_IS_FAKE"`. Production orders are refused outright. With no
  secrets configured, nothing can be sent.
- **Blocks?** It blocks nothing today (no keys), but the owner should decide before adding keys.

### D13 — How will P&L be defined when the data arrives? `OPEN`
- **Known:** the API exposes `market_positions[].realized_pnl`, `settlements[].revenue`, and `fills[].fee_cost`;
  fees are `fee_type` quadratic/flat with a per-series `fee_multiplier`.
- **Unknown:** whether the owner wants net-of-fees mark-to-market, realised-only, or both; and how to treat the
  live/historical partition ("realised P&L is not a single field" — see
  [Historical Data](https://docs.kalshi.com/getting_started/historical_data.md)).
- **Mitigation implemented:** the portfolio artifact reports the underlying fields **separately** with their names
  attached, instead of summing them into one invented number.
- **Blocks?** Yes, for any headline "portfolio performance" number.

---

## D. Publishing questions

### D14 — What is published when a value cannot be verified? `CLOSED`
- **Rule applied everywhere:** blank cell + explicit `unverified` flag + a link to the page where it is listed
  (site → *Flagged for Review*). No value is ever inferred, interpolated or copied from an unofficial page.
- **Enforced by:** `tools/check_site.py` (every table row needs a source URL; citation hosts must be official) and
  `collector/tests/test_pipeline.py`.

---

## Summary table

| ID | Question | Status | Blocks a decision? |
|---|---|---|---|
| D1 | Definition of "highest dollar amount" | OPEN (mitigated) | Ranking claims |
| D2 | Which environment is authoritative | CLOSED | No |
| D3 | Boundary of "culture" | OPEN | Topic totals |
| D4 | Scope of "gas prices" | OPEN (deliberately narrow) | No |
| D5 | Definition of resolved | CLOSED | No |
| D6 | Can the browser call the API directly | RESEARCHABLE (probe recorded) | No |
| D7 | How live can a static site be | CLOSED | No |
| D8 | Price staleness | CLOSED | No |
| D9 | Is the settlement sample sufficient | OPEN | **Strategy recommendations** |
| D10 | Demo authentication | CLOSED (implemented) | No |
| D11 | Current order endpoint | CLOSED (corrected) | No |
| D12 | Automatic trade execution | OPEN (human decision) | Only before keys are added |
| D13 | P&L definition | OPEN | Headline performance numbers |
| D14 | Handling of unverifiable values | CLOSED (enforced) | No |
