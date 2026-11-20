# Demo3 — Kalshi demo tracker

Live site (GitHub Pages): https://karagemop466-tech.github.io/Demo3/docs/tracker/

A static dashboard for Kalshi **demo** markets on five topics: gas prices, elections, culture, crypto and golf.
Every table row links to the Kalshi API response it came from. Anything not confirmed from an official source is left blank and marked *Unverified*.

## Layout

| Path | What it is |
|------|------------|
| `docs/tracker/` | The Kalshi Demo Tracker site (served at `/docs/tracker/` from the existing Pages source) |
| `docs/tracker/data/snapshot.json` | Verified series, events, markets and one orderbook from the demo API |
| `docs/tracker/data/flags.json` | Flagged for Review: irregularities and unverified items |
| `docs/tracker/data/questions.json` | Questions, known facts, gaps and how to close them |
| `docs/tracker/data/suggestions.json` | Decision board: options only, nothing implemented |
| `docs/tracker/data/sources.json` | Official Kalshi docs and API endpoints used |
| `docs/tracker/assets/live.js` | Live dashboard: calls the public demo API from the browser, falls back to the snapshot |
| `scripts/tracker_build.py` | Generates the HTML shells in `docs/` |
| `scripts/tracker_check.py` | Validates JSON, source links and internal links |
| `COORDINATION.md` | Shared task board and log (session e2aacbd6 section appended) |

## Build and check

```bash
python3 scripts/tracker_build.py   # regenerate HTML shells
python3 scripts/tracker_check.py   # must print OK
```

## Limits

- Demo data only (mock funds). Kalshi's docs say demo prices may not reflect real markets.
- Trading and portfolio pages are blocked until a demo API key is provided (see Questions, Q-01). No credentials are stored in this repo.
- The API reports volume as contracts, not dollars.
- Live calls run from the visitor's browser; cross-origin access is not verified (see Flagged, F-19).
