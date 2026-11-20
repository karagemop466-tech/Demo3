# Executive Summary — Kalshi Demo Dashboard

**Project:** Demo3 (repo `karagemop466-tech/Demo3`)
**Date:** 2026-11-20
**Status:** Site live at https://karagemop466-tech.github.io/Demo3/ · automated demo-API data pipeline active (twice hourly) · row-level re-verification passing (latest CI run: 725/725 checks, 0 hard failures — `data/latest/verification_report.json`) · portfolio/trade execution staged behind demo credentials (not provided — flagged, never inferred)

## Goal

Collect, organize, and analyze Kalshi data, tracking the highest-dollar live events across five
topics: **gas prices, elections, culture, crypto, and golf**, until each event resolves (Yes / No),
with portfolio-performance tracking and trade execution on the **Kalshi demo account**.

## Official data sources (all verified reachable, 2026-11-20)

| Source | URL |
|--------|-----|
| Trade API REST (recommended demo) | https://external-api.demo.kalshi.co/trade-api/v2 |
| Trade API REST (alternate demo) | https://demo-api.kalshi.co/trade-api/v2 |
| WebSocket API (demo) | wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2 |
| WebSocket API (alternate demo) | wss://demo-api.kalshi.co/trade-api/ws/v2 |
| API documentation | https://docs.kalshi.com (index: /llms.txt) |

The endpoint table above is the one published in the API docs "API Environments and Endpoints"
page (checked 2026-11-20): https://docs.kalshi.com/getting_started/api_environments

## What the site contains

- **Landing page** (`index.html`) with executive summary and status at a glance.
- **Live dashboard** (`dashboard.html`): price graph with **seconds / minutes / hours** time-axis
  modes and selectable window lengths, Y axis = current contract price; liquidity panel showing
  **contracts available at each price** (orderbook depth); live active-markets table; and the
  **top live events by dollar volume** table from the automated demo-API pipeline (every row
  links to the exact API request that produced it).
- **Category pages** — gas prices, elections, culture, crypto, golf — each with the live table,
  the pipeline snapshot, and the verified snapshot, with official-source links per row.
- **Resolved** (`resolved.html`): final yes/no results plus the pipeline **resolution tracker**
  (all five topics, accumulated across runs).
- **Portfolio & trades** (`portfolio.html`): demo-account state (blank + flagged until API
  credentials are configured as repo secrets), trade-categorisation taxonomy, **strategy
  playbook** (proposed, for review before anything is implemented), and a **dry-run order
  ticket** showing the exact official request shape. Execution path: `scripts/trade_runner.py`.
- **Findings**, **Questions** (what is known / missing / how to discover it), **Suggestions**
  (reviewable, choose-an-option workflow), **Flagged for review**, **Sources** (including the
  automated pipeline's source register and the latest row re-verification report).

## Verified findings (demo API, 2026-11-20, series-first snapshot)

Highest dollar-volume live events per topic (derived metric =
`volume_fp × notional_value_dollars`, both API fields shown per row):

| Topic | Top live event | Derived dollar volume |
|-------|---------------|----------------------|
| Elections | KXPRESNOMD-28 — Who will be the Democratic nominee in 2028 | $7.98 B |
| Elections | KXPRESPERSON-28 — Who will win the next presidential election | $1.44 B |
| Crypto | KXBTCY-27JAN0100 — BTC price on Jan 1, 2027 | $1.97 B |
| Culture | KXOSCARPIC-27 — Oscar for Best Picture | $31.5 M |
| Golf | KXPGATOUR-THRC26 — The RSM Classic: Taylor Moore wins | $16.1 M |
| Gas | KXAAAGASM-26NOV30 — Will average gas prices be above $4.70 | $436.6 K |

Sources for every row: the linked API requests in `data/latest/top_events.json` (published at
`../data/latest/top_events.json` on the site). Example:
https://external-api.demo.kalshi.co/trade-api/v2/markets?event_ticker=KXPRESNOMD-28

- **Market data is unauthenticated**; portfolio and order endpoints require an API key and
  RSA-PSS request signature (official starter code:
  https://github.com/Kalshi/kalshi-starter-code-python ).
- **Settlement results are `yes` / `no`** (`result` field, per
  https://docs.kalshi.com/getting_started/market_settlement). The pipeline records every settled
  in-scope market with its result and settlement timestamp; results are re-verified exactly.
- **Candlesticks** for the price graph use the documented path
  `/series/{series}/markets/{ticker}/candlesticks` (`period_interval` 1 / 60 / 1440 minutes):
  https://docs.kalshi.com/api-reference/market/get-market-candlesticks
- **WebSockets require auth headers at handshake**, which browsers cannot attach to WS
  connections — the site's live layer therefore uses public REST polling plus CI snapshots and
  says so in its banner (https://docs.kalshi.com/getting_started/quick_start_websockets).

## Items left blank / unverified (flagged)

- **Portfolio / trade execution:** no demo API key was provided. All account values stay blank
  and flagged ("credentials_missing"). To activate: add repo secrets `KALSHI_KEY_ID` and
  `KALSHI_PRIVATE_KEY`; the hourly workflow fills the tables automatically. Nothing is inferred.
- **"Highest dollar amount" definition:** the API has no dollar-volume field; the site shows
  both the verbatim contracts ranking and the labelled derived dollar volume. Definition is an
  open question for review (Questions page).
- **Demo synthetic series** (KXDEMOFUTHOURLY, KXQUICKSETTLE test markets) rank high in demo
  volume; flagged so they are not read as real-world markets.
- Full register with source links: the site's **Flagged for review** page and
  `COORDINATION.md` (I-01 … I-16).

## How the data pipeline works (no manual input)

1. GitHub Actions (`.github/workflows/kalshi-data.yml`) runs `scripts/collect_kalshi_data.py`
   twice hourly against the official demo API: series catalog (classified into the five topics
   by published rules), markets for the top-volume topic series, events, orderbooks, candlesticks,
   recent trades, and settled results. Every stored row carries `source_url` + `retrieved_at`.
2. `scripts/verify_rows.py` immediately re-fetches the same official URLs and diffs the stored
   rows: static fields and settlement results must match exactly; price drift is reported.
3. The site renders the published snapshots in `data/latest/` (plus live browser panels when
   CORS allows), so the dashboard is never empty and every number is traceable.

## Next steps for the owner

1. Review the **Flagged for review** page (I-01 … I-16) and the **Questions** page; pick options
   on the **Suggestions** page (saved in-browser, exportable as JSON).
2. Add demo-account API credentials as repository secrets to activate portfolio tracking and
   (optionally) dry-run-then-live trade execution via `scripts/trade_runner.py`.
3. Confirm the "highest dollar amount" ranking definition (contracts vs derived dollar volume).
