# COORDINATION — shared task board

Branch: `arena/e2aacbd6-demo3` (single working branch for this session; base `main` @ 80f7c4d)
Session: `e2aacbd6` (single agent session — no parallel sessions were detected in the repo at start)

Status values: `unclaimed` · `in progress` · `done` · `needs review` (published on the Flagged for Review page; does not block anything)

## Tasks

| ID | Task | Status | Owner | Files touched |
|----|------|--------|-------|---------------|
| T1 | Repo review + irregularities | done | e2aacbd6 | `docs/flagged.html`, `docs/data/flags.json`, `docs/sources.html` |
| T2 | Kalshi API verification (docs + demo data snapshot) | done | e2aacbd6 | `docs/data/snapshot.json`, `docs/data/sources.json` |
| T3 | Executive summary + findings/analysis | done | e2aacbd6 | `docs/index.html`, `docs/findings.html` |
| T4 | Live dashboard (price chart, time window, orderbook liquidity) | done | e2aacbd6 | `docs/dashboard.html`, `docs/assets/live.js` |
| T5 | Category subpages (gas, elections, culture, crypto, golf) | done | e2aacbd6 | `docs/categories/*.html` |
| T6 | Resolutions tracker (yes/no outcomes) | done | e2aacbd6 | `docs/resolutions.html` |
| T7 | Portfolio / trade execution / strategy analysis | needs review | e2aacbd6 | `docs/portfolio.html` — BLOCKED: no demo API key available to this session (see Q-01) |
| T8 | Suggestions decision board | done | e2aacbd6 | `docs/suggestions.html`, `docs/data/suggestions.json` |
| T9 | Open questions / information gaps | done | e2aacbd6 | `docs/questions.html`, `docs/data/questions.json` |
| T10 | Site build check (links, JSON, source links) + Pages | in progress (check_site.py passes; DOM test of all 14 pages passed; Pages source switch pending merge) | e2aacbd6 | `scripts/check_site.py`, Pages settings |
| T11 | PR → merge to `main`, Pages deploy confirmation | pending | e2aacbd6 | — |

## Log

- 2026-11-20 — e2aacbd6 — Claimed all tasks T1–T11 on this branch. The repo has no `COORDINATION.md`, so this file was created. The `session-<id>/<task>` branch scheme from the brief was not used: the session rules require all work on the current branch `arena/e2aacbd6-demo3`.
- 2026-11-20 — e2aacbd6 — Verified Kalshi docs (official) and demo REST API responses. Sandbox shell cannot reach `external-api.demo.kalshi.co` (SSL error); all API reads were made through the page-fetch tool, and the snapshot values were copied from those responses.
- 2026-11-20 — e2aacbd6 — Trading and portfolio are blocked: Kalshi authenticated endpoints need an API key pair created by a logged-in Kalshi demo account. No credentials were requested or stored. No trades were placed.

- 2026-11-20 — e2aacbd6 — Sources and verification: Kalshi docs fetched (demo_env, api_keys, openapi, get-series-list, get-markets, get-market-orderbook, get-market-candlesticks, market_settlement). Demo API responses fetched for series by category/tag, markets by series, events, one orderbook, and one candlestick call (empty window). Each snapshot row keeps its `source_api`. Irregularities logged as F-01…F-22 (docs/data/flags.json).
- 2026-11-20 — e2aacbd6 — Build: `scripts/build_site.py` generates 14 HTML pages in `docs/`; `scripts/check_site.py` reports OK. DOM test (jsdom, outside repo) loaded all 14 pages with 0 script errors; dashboard fallback path tested with the live API blocked.

## Handoffs / crashes
- none
