# Kalshi Demo Monitor

A self-contained static GitHub Pages subsite for reviewing Kalshi **demo** market data across gas prices, elections, culture/entertainment, crypto, and golf. It lives under `demo-monitor/` so the existing root, `docs/`, tracker, and analysis sites remain intact. It contains no fabricated market rows, portfolio balances, or trade results.

Published path: `https://karagemop466-tech.github.io/Demo3/demo-monitor/` (pending merge and build verification).

## What is included

- Executive brief, decision questions, source catalog, and a **Flagged for Review** page.
- Category subpages and a dashboard that loads open events from the official Kalshi demo REST API, ranks them by a clearly labeled top-of-book displayed-value calculation, and links each returned row to its official API data.
- Market inspection with official order-book levels, contracts at each level, implied asks labeled as implied, and an interactive price chart with seconds/minutes/hours ranges.
- A local-only paper-trade simulator with topic/strategy labels. It does not send orders to Kalshi.
- Open-event watchlist and resolution view. Browser polling runs only while the page is open; it does not provide unattended background monitoring.
- GitHub Actions quality checks. This repository's existing GitHub Pages publishing source is the root of `main`, so the merge to `main` triggers its configured branch-based Pages build.

## Important limits

- The repository contains no Kalshi demo account credentials. Authenticated account balance, positions, fills, and real demo order entry cannot be accessed from this static site. No private key is requested, stored, or exposed; no real order was placed.
- The dashboard's “Displayed top-of-book value” is a site-defined calculation from the public market API's top YES bid/ask prices and contract sizes. It is not an official Kalshi event-level dollar total, full order-book liquidity, or traded volume. Contract volume and open interest remain labeled in contracts.
- REST candlesticks offer minute/hour/day intervals; seconds-range points are snapshots observed in the browser while the page is open. Kalshi's WebSocket handshake requires authentication.
- Browser access to the API may be affected by endpoint CORS/network behavior. If data cannot be retrieved, values remain blank and the page reports the issue.

## Pages

- [Executive summary](index.html)
- [Live dashboard](dashboard.html)
- [Gas prices](gas-prices.html) · [Elections](elections.html) · [Culture / entertainment](culture.html) · [Crypto](crypto.html) · [Golf](golf.html)
- [Portfolio & paper trades](portfolio.html) · [Strategies](strategies.html) · [Resolved events](resolved.html)
- [Decision questions](decision-questions.html) · [Suggestions](suggestions.html) · [Flagged for Review](flagged-review.html) · [Official sources](sources.html)
- [Research notes](docs/research-notes.md) · [Repository coordination board](../COORDINATION.md)

## Run locally

```sh
python3 -m http.server 8000
```

Open `http://localhost:8000/demo-monitor/`. The public demo market-data API is read-only in this site; portfolio/order routes are not called.

## Verify

```sh
python3 demo-monitor/scripts/verify_site.py
node demo-monitor/scripts/test_api.js
```

The verifier checks local page/asset links and requires every non-header HTML table row to include an HTTPS source link on an allowlisted official Kalshi or GitHub documentation host. The `Site checks` workflow runs this check and a synthetic API-client test on pushes to `main`/Arena branches and on pull requests. GitHub's Pages API confirms the source is `main` at `/` using legacy branch publishing; its latest pre-PR status on 2026-11-20 was `building`. The site changes are not yet merged or deployed, so check the Pages build and live URL after merge.

## Official API references

- [Quick Start: Market Data](https://docs.kalshi.com/getting_started/quick_start_market_data)
- [Kalshi API OpenAPI specification](https://docs.kalshi.com/openapi.yaml)
- [Market order-book response structure](https://docs.kalshi.com/getting_started/orderbook_responses)
- [Market candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)
- [API keys and signed requests](https://docs.kalshi.com/getting_started/api_keys)
- [GitHub Pages publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
