# Demo3 — Kalshi market dashboard

Read-only analysis of public Kalshi markets (gas prices, elections, culture, crypto, golf), published with GitHub Pages from `main`.

- Site: `index.html` (overview and executive summary), `pages/*.html` (categories, resolutions, price history, liquidity, demo portfolio, strategies, suggestions, questions, repo review, Flagged for Review, sources).
- Data: `data/live/*.json` (market snapshot from the Kalshi public API; every row links to its query), `data/findings.json` (sources, repo review, flagged items, questions, suggestions).
- Refresh: `python3 scripts/refresh_kalshi.py` (stdlib only; writes `data/live`). Scheduled hourly by `.github/workflows/refresh.yml`.
- Build the pages: `python3 scripts/build_site.py`.
- Checks: `python3 scripts/tests/test_refresh_offline.py` and `python3 scripts/check_site.py`.

Coordination for parallel work is in `COORDINATION.md`. Values that cannot be confirmed from an official response are left blank and flagged.
