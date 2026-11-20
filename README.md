# Demo3 — Kalshi Demo Dashboard

A clean, static dashboard tracking live Kalshi demo exchange events across **gas prices, elections, culture,
crypto, and golf**, built on the official [Kalshi demo Trade API v2](https://external-api.demo.kalshi.co/trade-api/v2).

## Site pages

| Page | Purpose |
|------|---------|
| [index.html](index.html) | Landing page + executive summary |
| [dashboard.html](dashboard.html) | Live dashboard: price graph (time axis sec/min/hour; Y = contract price), liquidity, highest-dollar active markets |
| [gas-prices.html](gas-prices.html) | Gas prices category (flagged: no demo data found) |
| [elections.html](elections.html) | Elections category |
| [culture.html](culture.html) | Culture / entertainment category |
| [crypto.html](crypto.html) | Crypto category |
| [golf.html](golf.html) | Golf category (flagged: no demo data found) |
| [portfolio.html](portfolio.html) | Portfolio performance (demo API key required — not wired) |
| [trades.html](trades.html) | Trade execution, categorization & strategies (demo API key required — not wired) |
| [suggestions.html](suggestions.html) | Improvement suggestions for review before implementing |
| [questions.html](questions.html) | Questions / information / answers for decision readiness |
| [flagged.html](flagged.html) | Flagged for review: unverified items, blank values, irregularities |

## Verification rules followed

- Every table row carries a link to an official Kalshi demo API source.
- If a value cannot be confirmed from an official source, it is left **blank** and flagged **unverified**.
- Nothing is inferred or filled in.

## Official sources

- Trade API (REST, recommended demo): https://external-api.demo.kalshi.co/trade-api/v2
- Also supported: https://demo-api.kalshi.co/trade-api/v2
- WebSocket API: https://external-api-ws.demo.kalshi.co/trade-api/ws/v2 and https://demo-api.kalshi.co/trade-api/ws/v2
- API docs: https://docs.kalshi.io

## Authentication note

Authenticated endpoints (portfolio balance, trade execution, order placement) require a signed Kalshi demo API key.
This site does **not** collect, store, or transmit any API key. Those pages are intentionally flagged as not live.

## Branch

Built on `arena/cde2ae63-demo3`, based on `main` (`80f7c4d`). Published via GitHub Pages.
