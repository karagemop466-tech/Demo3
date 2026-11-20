# Demo3 - Kalshi demo dashboard

Static GitHub Pages site with verified Kalshi market data, a live in-browser dashboard, category
pages, resolved results, findings, questions, suggestions, and a Flagged for Review page — plus an
automated data pipeline that keeps the site fed from the official **demo** Trade API.

- Live site: https://karagemop466-tech.github.io/Demo3/ (Pages serves `main` at `/`; the root
  `index.html` redirects to `docs/index.html`)
- Coordination board: [COORDINATION.md](COORDINATION.md)
- Executive summary: [docs/executive-summary.md](docs/executive-summary.md)

## Layout

| Path | What it is |
|---|---|
| `docs/` | The published site (HTML pages, `assets/app.js`, `assets/style.css`) |
| `docs/data/verified.json` | Verified snapshot data. Every row has a source URL. |
| `data/latest/` | Automated pipeline snapshots (markets, events, top-dollar ranking, orderbooks, candles, trades, resolutions, portfolio status, verification report). Every row carries `source_url`. |
| `data/history/` | Rolling history: price samples and the accumulated resolution log (trimmed to 20,000 lines). |
| `scripts/collect_kalshi_data.py` | CI collector (official demo API; series-first topic selection; published classification rules) |
| `scripts/verify_rows.py` | Row-level re-verification against the live API (static fields + settlement results must match exactly) |
| `scripts/kalshi_client.py` | Authenticated demo-API client (RSA-PSS signing per official starter code) |
| `scripts/portfolio_pull.py` | Credential-gated portfolio/fills pull with automatic trade categorisation |
| `scripts/trade_runner.py` | Order placement for the demo account (dry-run default, size caps) |
| `scripts/build_site.py` | Generates the HTML page shells in `docs/` |
| `scripts/verify_site.py` | Checks sources, internal links, JS syntax, render-hook coverage |
| `.github/workflows/kalshi-data.yml` | Twice-hourly collection + verification + data commit |
| `.github/workflows/kalshi-portfolio.yml` | Hourly portfolio pull (activates when repo secrets exist) |

## Rebuild and verify

```bash
python3 scripts/build_site.py
python3 scripts/verify_site.py
```

## Data sources

Kalshi documentation at https://docs.kalshi.com (the `llms.txt` index lists every page) and the
**demo** Kalshi Trade API at
[`https://external-api.demo.kalshi.co/trade-api/v2`](https://external-api.demo.kalshi.co/trade-api/v2)
(also supported: `https://demo-api.kalshi.co/trade-api/v2`) per
[API Environments and Endpoints](https://docs.kalshi.com/getting_started/api_environments).
The live dashboard calls the public endpoints from the browser (market data needs no key); if the
browser cannot reach them, the page says so and shows the pipeline/verified snapshots instead.

## Portfolio and trading

Portfolio and order endpoints require a demo-account API key (never stored in this repo). To
activate: add repository secrets `KALSHI_KEY_ID` and `KALSHI_PRIVATE_KEY`, and the hourly
workflow fills the site's portfolio tables automatically. Trade execution runs through
`scripts/trade_runner.py` (dry-run by default; demo environment only). No credentials are stored
in this repo, and no values are ever inferred — missing data is shown blank and flagged.
