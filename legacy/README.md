# Legacy builds — preserved, not published as live data

This folder exists because several sessions built their own version of this dashboard at the
same time. Nothing here is deleted or rewritten: every file is a byte-for-byte copy of what was
on `main` before the integration merge, apart from the asset references inside
`live-desk/*.html`, which were rewritten from `assets/app.js` / `assets/style.css` to the
`app.js` / `style.css` copies sitting beside them so the pages still render in place.

The published site is `docs/` (entry point: `../docs/index.html`). It is the only build with a
data pipeline, an analysis engine, a strategy section and an automated link/citation/render
check. Everything below is reference material.

| Folder | What it is | Why it is not the published site |
|---|---|---|
| `live-desk/` | The former root landing page plus `dashboard.html`, `trades.html`, `portfolio.html`, `methodology.html`, `data-tracking.html`, `api-reference.html`, `repo-review.html` and the five topic pages. | Its dashboard asks the visitor to paste a private API key into the page so the browser can sign requests. That is a poor default for a public site and cannot be tested from CI. Its chart and trade-ticket UX were worth keeping, so the files are here. |
| `docs-site/` | A complete earlier static site that lived under `docs/`. | Superseded by the current `docs/`; had no collector, no expectancy study and no strategy rules. |
| `demo-desk/` | A read-only static desk with its own assets and `pages/`. | Read-only: no order book depth, no candlestick chart, no portfolio state. |
| `analysis/` | A generated site plus `analysis/data/live/*.json` snapshots. | Its snapshots came from a different collector with a different schema; folding them in would mix two definitions of "volume" in one table. |
| `scripts/` | Python builders and verifiers for the sites above (`build_site.py`, `tracker_build.py`, `verify_site.py`, `verify_root_site.py`, `check_site.py`, `config.json`, `refresh_kalshi.py`, `kalshi_demo.py`). | They target the retired trees. The live equivalents are `analysis/build.py` and `tools/check_site.py`. |
| `trading/` | An earlier demo-trading module (`kalshi_trade.py`, `strategies.py`, `test_trading.py`). | The shipped path is `collector/portfolio.py`, which enforces the V2 order endpoint, refuses production, and requires an explicit `ALLOW_DEMO_TRADING` flag plus a confirmation string. |
| `collector/` | An earlier collector (`kalshi_api.py`, `test_collect.py`) that paged `/events?with_nested_markets=true`. | That approach hits the pagination cap and truncates (`max_pages=60` warning on every run); `collector/collect.py` v2 selects series first instead. |
| `tests/` | Node tests (`site.test.js`, `core.test.js`, `runtime.test.js`, `api.test.js`) for `demo-desk/`. | They assert against a directory that is no longer the published site. The live suites are `collector/tests/test_pipeline.py` and `tools/render_test.js`. |
| `research/` | `kalshi-api-verified-reference.md`, a hand-verified API reference. | Still accurate and useful; kept as documentation rather than as a page. |
| `workflows/` | `check.yml`, `refresh.yml`, `trade.yml` from `main`. | They build and deploy the retired trees. The active workflows are `checks.yml`, `collect.yml` and `portfolio.yml`. |

If you want any of these brought back as the primary site, say so — the files are complete and
self-consistent, they were simply not the version with verified analysis behind it.
