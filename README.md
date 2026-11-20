# Demo3 - Kalshi demo dashboard

Static GitHub Pages site with verified Kalshi market data, a live in-browser dashboard, category pages, resolved results, findings, questions, suggestions, and a Flagged for Review page.

- Live site: https://karagemop466-tech.github.io/Demo3/ (Pages serves `main` at `/`; the root landing page keeps the Kalshi Demo Tracker and links to the separate Demo Desk, while the integrated site remains under `docs/`)
- Coordination board: [COORDINATION.md](COORDINATION.md)

## Layout

| Path | What it is |
|---|---|
| `docs/` | The published site (HTML pages, `assets/app.js`, `assets/style.css`) |
| `demo-desk/` | Separate, source-linked, read-only public demo dashboard with five topic pages, event/resolution views, charts, order-book, portfolio/security boundary, strategy and review pages |
| `docs/data/verified.json` | Single source of verified data. Every row has a source URL. |
| `scripts/build_site.py` | Generates the HTML page shells in `docs/` |
| `scripts/verify_site.py` | Checks sources, internal links, and JS syntax |

## Rebuild and verify

```bash
python3 scripts/build_site.py
python3 scripts/verify_site.py
```

The root landing page links to the Demo Desk. It uses public demo-market endpoints only; private portfolio values and order placement are intentionally unavailable. For its syntax checks and mocked API/DOM tests, run `npm run check` and `npm test`.

## Data sources

Kalshi documentation at https://docs.kalshi.com (the `llms.txt` index lists every page) and the public Kalshi Trade API at https://external-api.kalshi.com/trade-api/v2. The live dashboard calls the public endpoints from the browser. If the browser cannot reach them, the page says so and shows the verified snapshot. Demo-account portfolio data needs an API key and is not connected.

## Not included

No trading or order placement. No credentials are stored in this repo.

## Analysis site (session 3e08e6dc) — `analysis/`

A second, self-contained dashboard lives in `analysis/` (it does not replace `docs/` or the root pages). It covers gas prices, elections, culture, crypto and golf, with a landing page, category subpages, resolutions, price history, liquidity, a flagged page, sources and repo review.

- Open: `analysis/index.html` on Pages at `https://karagemop466-tech.github.io/Demo3/analysis/`
- Data: `analysis/data/live/*.json` (Kalshi public API snapshot; each row links to its query) and `analysis/data/findings.json` (sources, repo review, flagged items, questions, suggestions).
- Refresh (stdlib): `python3 scripts/refresh_kalshi.py`, scheduled hourly by `.github/workflows/refresh.yml`. It does not overwrite data when no API call succeeds.
- Rebuild pages: `python3 scripts/build_analysis_site.py`. Checks: `python3 scripts/check_site.py` and `python3 scripts/tests/test_refresh_offline.py`.
