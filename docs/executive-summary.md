# Executive Summary — Kalshi Demo Dashboard

**Project:** Demo3 (repo `karagemop466-tech/Demo3`)
**Date:** 2026-11-20
**Status:** Published — the canonical site is live at https://karagemop466-tech.github.io/Demo3/ (PR/merge log in [COORDINATION.md](../COORDINATION.md)). This file is an archive of the earlier session summary (see [Sources](../sources.html)); the current executive summary is on the site's [home page](../index.html).

## Goal
Collect, organize, and analyze Kalshi demo exchange data, tracking the highest-dollar live events across five
topics: **gas prices, elections, culture, crypto, and golf**, until each event resolves (Yes / No).

## Official data sources (all verified reachable)

| Source | URL |
|--------|-----|
| Trade API REST (recommended demo) | https://external-api.demo.kalshi.co/trade-api/v2 |
| Trade API REST (alternate) | https://demo-api.kalshi.co/trade-api/v2 |
| WebSocket API | https://external-api-ws.demo.kalshi.co/trade-api/ws/v2 |
| WebSocket API (alternate) | https://demo-api.kalshi.co/trade-api/ws/v2 |
| API documentation | https://docs.kalshi.com |

## What the site contains

- **Landing page** (`index.html`) with executive summary and status at a glance.
- **Live dashboard** (`dashboard.html`): Chart.js price graph, X axis = time (seconds/minutes/hours selectable),
  Y axis = current contract price, liquidity panel (contracts available at ask price), live active-markets table
  sorted by dollar volume.
- **Category pages** for gas prices, elections, culture, crypto, golf — each a verified table with official-source links.
- **Portfolio** (`portfolio.html`) and **trades** (`trades.html`): framework only; require a signed demo API key.
- **Suggestions** (`suggestions.html`): register of improvements to review before implementing.
- **Questions & answers** (`questions.html`): decision-readiness register plus missing-information discovery paths.
- **Flagged for review** (`flagged.html`): unverified items left blank and irregularities.

## Verified findings (snapshot from official demo API)

Events captured from `GET /events?limit=100` on https://external-api.demo.kalshi.co/trade-api/v2:

| Category | Event ticker | Title | Settlement source |
|----------|-------------|-------|-------------------|
| Crypto | KXBTCD-32FEB1010 | Bitcoin price on Feb 10, 2032 at 10am EST? | CF Benchmarks |
| Elections | KXNEWPOPE-70 | Who will the next Pope be? | NYT, AP, Reuters, et al. |
| Elections | KXNEXTNATOSECGEN-99 | Next Secretary General of NATO? | NATO |
| Elections | KXINDIANPM-29APR30 | Next PM of India after general election? | Lok Sabha |
| Elections | KXKOREAPRES-30MAR27 | Next South Korea Presidential winner? | National Election Commission |
| Elections | KXGERELECTION-29MAR25 | Next German federal election winner? | Bundeswahlausschuss |
| Elections | KXJAPANHOUSE-30FEB07 | Next Japanese general election winner? | MIC Japan |
| Culture | KXGTAPRICE | Price of GTA VI on PS5? | Rockstar Games |
| Culture | KXLIPATURNERLOCATION-30 | Dua Lipa / Callum Turner wedding location? | Press sources |
| Sports | KXF1RETIRE-30VERSTAPPEN | Max Verstappen retirement | F1, press |
| Sports | KXMLBDEBUT-GEMERSON | Grady Emerson debut date | ESPN, MLB |
| Sports | KXNFLRETIRE-ARODGERS8 | Aaron Rodgers retirement | NFL, press |

Markets captured from `GET /markets?limit=100` include prices, bid/ask, sizes, volume, and open interest
(for several synthetic cross-category and eSports markets).

## Items left blank / unverified (flagged)

- **Gas prices:** no gas/energy events or markets in sampled demo-API pages.
- **Golf:** no golf events or markets in sampled demo-API pages.
- **Dollar amounts / liquidity:** mostly zero in the sampled snapshot; full market dump needed.
- **Event resolutions:** all sampled events still open.
- **Portfolio / trade execution:** require a signed demo API key (not provided, not stored).

See `flagged.html` for the full register with official sources checked.

## Next steps
1. Publish to GitHub Pages and confirm the build has no broken links.
2. Create a pull request from this branch to `main` and merge.
3. Review flagged items; resolve gas/golf data and any CORS questions; optionally add authenticated portfolio/trade views with a locally held demo key.
