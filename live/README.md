# Kalshi Live Alert Desk (`/live`)

Static GitHub Pages desk for the Kalshi **demo** exchange
(`https://external-api.demo.kalshi.co/trade-api/v2`), covering five topics only:
gas prices, elections, culture, crypto, golf.

## What it does

| Requirement | Where it lives |
|---|---|
| Highest-dollar live events, five topics only | `index.html`, topic pages, `data/markets.json` |
| Swing alerts ≥ $0.10 either direction | `data/alerts.json` (rule in `scripts/build_live_data.py`) |
| Two scrolling chat streams (all / high-ROI model) | `dashboard.html` → `assets/desk.js` `Chat()` |
| Track events until resolved, YES/NO | `tracking.html`, `data/resolutions.json` |
| Auto-simulated trades, no manual input | `data/trades.json`, `data/portfolio.json` |
| Portfolio performance + trade categories | `strategies.html`, `portfolio.html` |
| Price graph, x = time (s/m/h/d), y = price | `graph.html`, `assets/desk.js` `priceChart()` |
| Liquidity: contracts available per price | `graph.html` + dashboard depth chart |
| Live charts with links to possible causes | every alert links the candlestick request, the market record and a headline search |
| Suggestions to make it more live | `suggestions.html` (25 items) |
| Sources + flagged irregularities | `sources.html`, `flagged.html` |

## Rebuild

```bash
python3 scripts/build_live_candles.py   # candlestick store from committed official payloads
python3 scripts/build_live_data.py      # alerts, ROI model, simulation, registers
python3 scripts/build_live_site.py      # the pages
python3 scripts/verify_live_site.py     # links, per-row sources, JSON shape, JS syntax
node live/tests/smoke.mjs               # headless render test (jsdom, offline)
```

`data/latest/*.json`, `data/history/*.json` and `analysis/data/live/candles.json` are the inputs;
all three are committed collector artifacts of official Kalshi responses. Nothing is fetched at
build time in this environment because the sandbox has no HTTPS egress to the Kalshi API.

## Honesty rules applied here

* Every table row carries a link to the official request or docs page behind it, or says
  **unverified** and is listed on `flagged.html`.
* Dollar volume is **derived** (contracts × notional) — the trade API publishes no dollar-volume
  field.
* ROI/EV is a **model** with a published formula; simulated fills are labelled SIMULATED and never
  sent to Kalshi. No account values are shown because no demo credentials exist in this repo.
* Missing candle periods stay gaps (never interpolated), and zero-volume quote moves are labelled.
