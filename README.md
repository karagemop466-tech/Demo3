# Demo3 — Kalshi demo tracker

Live site (GitHub Pages): https://karagemop466-tech.github.io/Demo3/

A static dashboard for Kalshi **demo** markets on five topics: gas prices, elections, culture, crypto and golf.
Every table row links to the Kalshi API response it came from. Anything not confirmed from an official source is left blank and marked *Unverified*.

## Layout

| Path | What it is |
|------|------------|
| `docs/` | The published site (GitHub Pages source: `main` / `/docs`) |
| `docs/data/snapshot.json` | Verified series, events, markets and one orderbook from the demo API |
| `docs/data/flags.json` | Flagged for Review: irregularities and unverified items |
| `docs/data/questions.json` | Questions, known facts, gaps and how to close them |
| `docs/data/suggestions.json` | Decision board: options only, nothing implemented |
| `docs/data/sources.json` | Official Kalshi docs and API endpoints used |
| `docs/assets/live.js` | Live dashboard: calls the public demo API from the browser, falls back to the snapshot |
| `scripts/build_site.py` | Generates the HTML shells in `docs/` |
| `scripts/check_site.py` | Validates JSON, source links and internal links |
| `COORDINATION.md` | Shared task board and log |

## Build and check

```bash
python3 scripts/build_site.py   # regenerate HTML shells
python3 scripts/check_site.py   # must print OK
```

## Limits

- Demo data only (mock funds). Kalshi's docs say demo prices may not reflect real markets.
- Trading and portfolio pages are blocked until a demo API key is provided (see Questions, Q-01). No credentials are stored in this repo.
- The API reports volume as contracts, not dollars.
- Live calls run from the visitor's browser; cross-origin access is not verified (see Flagged, F-19).
