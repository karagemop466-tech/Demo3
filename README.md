# Demo3 - Kalshi demo dashboard

Static GitHub Pages site with verified Kalshi market data, a live in-browser dashboard, category pages, resolved results, findings, questions, suggestions, and a Flagged for Review page.

- Live site: https://karagemop466-tech.github.io/Demo3/ (Pages serves `main` at `/`; the root `index.html` redirects to `docs/index.html`)
- Coordination board: [COORDINATION.md](COORDINATION.md)

## Layout

| Path | What it is |
|---|---|
| `docs/` | The published site (HTML pages, `assets/app.js`, `assets/style.css`) |
| `docs/data/verified.json` | Single source of verified data. Every row has a source URL. |
| `scripts/build_site.py` | Generates the HTML page shells in `docs/` |
| `scripts/verify_site.py` | Checks sources, internal links, and JS syntax |

## Rebuild and verify

```bash
python3 scripts/build_site.py
python3 scripts/verify_site.py
```

## Data sources

Kalshi documentation at https://docs.kalshi.com (the `llms.txt` index lists every page) and the public Kalshi Trade API at https://external-api.kalshi.com/trade-api/v2. The live dashboard calls the public endpoints from the browser. If the browser cannot reach them, the page says so and shows the verified snapshot. Demo-account portfolio data needs an API key and is not connected.

## Not included

No trading or order placement. No credentials are stored in this repo.
