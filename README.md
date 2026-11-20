# Demo3 — Kalshi Demo Market Tracker

Static GitHub Pages site with verified Kalshi market data, a live in-browser dashboard, category
pages, resolved results, findings, questions, suggestions, and a Flagged for Review page — plus a
**scheduled server-side collector** (committed snapshots, resolution tracking, orderbooks, price
history) and a **demo-account trading/portfolio pipeline**.

- Live site: https://karagemop466-tech.github.io/Demo3/ (Pages serves `main` at `/`; the root `index.html` redirects to `docs/index.html`)
- Coordination board: [COORDINATION.md](COORDINATION.md)
- Executive summary: [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md)
- API verification table: [docs/API_VERIFICATION.md](docs/API_VERIFICATION.md)
- Flagged for review: [flagged.html](flagged.html) and [docs/flagged.html](docs/flagged.html)

## Layout

| Path | What it is |
|---|---|
| `docs/` | The integrated site built by session 00a943bd (landing, category subpages, dashboard, findings) + `docs/data/verified.json` |
| root `*.html` | Landing/executive summary, live dashboard, API reference, methodology, suggestions, questions, flagged pages (session 7f1ef378), **`data-tracking.html`** (collector-driven tracking page, session 3b5e95bd) |
| `data/` | Committed JSON snapshots produced every 10 minutes by the collector (events, orderbooks, candlestick history, resolutions, tracking state, CORS probe, run log) |
| `collector/` | Python pipeline + offline tests (`test_collect.py`) |
| `trading/` | Demo-account signed auth, portfolio snapshots, order execution, PnL settlement, strategy framework + offline tests (`test_trading.py`) |
| `scripts/` | `build_site.py` (docs/ shells), `verify_site.py` (source/links/JS checks), `kalshi_demo.py` (CLI) |
| `assets/` | Site CSS/JS incl. `data-tracking.js` (charts, orderbook ladders, resolution/portfolio renderers) |

## Automation (GitHub Actions)

| Workflow | Trigger | What it does |
|---|---|---|
| `collect.yml` | every 10 min + manual | Offline tests, then snapshots the demo exchange into `data/` (ranked events per topic, top-market orderbooks, 1m/60m/1440m candlesticks, resolution sweeps with per-series quotas, CORS probe) and commits |
| `trade.yml` | manual dispatch | Portfolio snapshot / demo order placement / settlement PnL sweep using secrets `KALSHI_DEMO_API_KEY_ID` + `KALSHI_DEMO_PRIVATE_KEY`; exits with a clear flag and writes nothing if secrets are absent |
| Pages | push to `main` | Publishes the site |

## Rebuild and verify

```bash
python3 scripts/build_site.py
python3 scripts/verify_site.py
python3 collector/test_collect.py          # offline pipeline tests (mock API shapes)
python3 trading/test_trading.py            # needs `pip install cryptography`
node --check assets/data-tracking.js       # JS syntax
```

## Data sources

Kalshi documentation at https://docs.kalshi.com (the `llms.txt` index lists every page) and the
public Kalshi Trade API at https://external-api.demo.kalshi.co/trade-api/v2 (demo; endpoints and
fields verified in `docs/API_VERIFICATION.md`). The live dashboard calls the public endpoints from
the browser (CORS verified: the API returns
`Access-Control-Allow-Origin: https://karagemop466-tech.github.io`). Demo-account portfolio data
needs demo API keys and is not connected until secrets are provided.

## Not included (yet)

Portfolio/trade rows are empty by design: no demo credentials exist in this environment, so the
implemented pipeline has produced no verified account data — nothing is inferred. See
[flagged.html](flagged.html) item F9 and [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) §4.
