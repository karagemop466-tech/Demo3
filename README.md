# Demo3 - Kalshi demo dashboard

Static GitHub Pages site with verified Kalshi market data, a live in-browser dashboard, category pages, resolved results, findings, questions, suggestions, and a Flagged for Review page.

- Live root site: https://karagemop466-tech.github.io/Demo3/ (Pages serves `main` at `/`; the root landing page keeps the Kalshi Demo Tracker and links to the separate Demo Desk and source-first monitor).
- Other published sites: [`demo-desk/`](https://karagemop466-tech.github.io/Demo3/demo-desk/), [`demo-monitor/`](https://karagemop466-tech.github.io/Demo3/demo-monitor/), [`docs/`](https://karagemop466-tech.github.io/Demo3/docs/), [`docs/tracker/`](https://karagemop466-tech.github.io/Demo3/docs/tracker/), and [`analysis/`](https://karagemop466-tech.github.io/Demo3/analysis/).
- Coordination board: [COORDINATION.md](COORDINATION.md)

## Layout

| Path | What it is |
|---|---|
| `docs/` | Integrated static site under `/docs/` (HTML pages, `docs/assets/app.js`, `docs/assets/style.css`) |
| `demo-desk/` | Separate, source-linked, read-only public demo dashboard with five topic pages, event/resolution views, charts, order-book, portfolio/security boundary, strategy and review pages |
| `demo-monitor/` | Separate source-first monitor with a disclosed displayed-top-of-book proxy and local-only paper-trade simulator |
| `docs/data/verified.json` | Single source of verified data. Every row has a source URL. |
| `scripts/build_site.py` | Generates the HTML page shells in `docs/` |
| `scripts/verify_site.py` | Checks sources, internal links, and JS syntax |

## Rebuild and verify

```bash
python3 scripts/build_site.py
python3 scripts/verify_site.py
```

The root landing page links to the Demo Desk and source-first monitor. The public dashboards use demo-market data only; private portfolio values and real order placement are intentionally unavailable. For the Demo Desk syntax checks and mocked API/DOM tests, run `npm run check` and `npm test`.

## Data sources

Kalshi documentation at https://docs.kalshi.com (the `llms.txt` index lists every page) and the public Kalshi Trade API at https://external-api.kalshi.com/trade-api/v2. The live dashboard calls the public endpoints from the browser. If the browser cannot reach them, the page says so and shows the verified snapshot. Demo-account portfolio data needs an API key and is not connected.

## Not included

No real trading or order placement. No credentials are stored in this repo. The source-first monitor's paper simulator is browser-local and does not submit orders.

## Analysis site (session 3e08e6dc) — `analysis/`

A self-contained dashboard lives in `analysis/` (it does not replace `docs/` or the root pages). It covers gas prices, elections, culture, crypto and golf, with a landing page, category subpages, resolutions, price history, liquidity, a flagged page, sources and repo review.

- Open: `analysis/index.html` on Pages at `https://karagemop466-tech.github.io/Demo3/analysis/`
- Data: `analysis/data/live/*.json` (Kalshi public API snapshot; each row links to its query) and `analysis/data/findings.json` (sources, repo review, flagged items, questions, suggestions).
- Refresh (stdlib): `python3 scripts/refresh_kalshi.py`, scheduled hourly by `.github/workflows/refresh.yml`. It does not overwrite data when no API call succeeds.
- Rebuild pages: `python3 scripts/build_analysis_site.py`. Checks: `python3 scripts/check_site.py` and `python3 scripts/tests/test_refresh_offline.py`.

## Source-first demo monitor (session `arena/d330ff7d-demo3`) — `demo-monitor/`

A separate, self-contained subsite for gas prices, elections, culture/entertainment, crypto, and golf. It shows open events with direct API source links, a clearly provisional displayed-top-of-book proxy, interactive price ranges, order-book levels, a local-only paper ledger, a resolution watchlist, and review registers. The unique subpath preserves the existing root, `/docs/`, `/docs/tracker/`, `/demo-desk/`, and `/analysis/` sites.

- Open: `demo-monitor/index.html` on Pages at `https://karagemop466-tech.github.io/Demo3/demo-monitor/`
- Verify: `python3 demo-monitor/scripts/verify_site.py` and `node demo-monitor/scripts/test_api.js`.
- Account balance/positions/fills and real demo orders remain unavailable without a secure authenticated connection. The paper simulator does not submit orders. See `demo-monitor/flagged-review.html` for the feed, metric, taxonomy, and deployment caveats.
