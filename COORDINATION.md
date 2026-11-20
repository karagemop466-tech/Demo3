# COORDINATION.md — Shared Task Board

This file is the coordination mechanism for all agent sessions working on this repository.
Read it before starting. Claim work by adding a row (or flipping a status) with your session ID
and file scope, then **commit and push the claim immediately**.

Conventions:
- Statuses: `unclaimed` → `in progress` → `needs review` (published on the Flagged for Review page) → `done`.
- Branch naming: `session-<id>/<task>`. Arena sessions are tracked on their own session branch; the
  session ID below is the Arena branch ID so work can be traced back.
- `git pull --rebase` before every push. Never edit a file owned by another in-progress task;
  log a request in the **Change Requests** section instead.
- A claim older than 60 minutes with no commits may be taken over; note the handoff in **Activity Log**.
- Shared outputs (`docs/` site index + navigation, `data/*`) are changed only by the final
  integration session.

Session ID for this session: `arena-b2e728ab` (branch `arena/b2e728ab-demo3`).

---

## Tasks

| # | Task | Status | Owner (session ID) | File scope | Notes |
|---|------|--------|--------------------|------------|-------|
| 1 | Establish coordination board + repo conventions | in progress | arena-b2e728ab | `COORDINATION.md`, `.gitignore` | Created this commit |
| 2 | Kalshi API surface audit (REST + WS, demo vs prod, auth, rate limits) | unclaimed | — | `docs/executive-summary.md`, `docs/api-surface.md` | Must cite docs.kalshi.com only |
| 3 | Requirements register (full list of requirements, gaps, open questions) | unclaimed | — | `docs/requirements.md` | |
| 4 | Live data collection scripts (demo Trade API → `data/*.json`) | unclaimed | — | `scripts/kalshi_client.py`, `scripts/collect_*.py`, `data/` | Read-only public endpoints |
| 5 | Trading engine + portfolio tracking (RSA-PSS signed, demo) | unclaimed | — | `scripts/trade_engine.py`, `scripts/portfolio.py` | Needs API key; see Blocked Items |
| 6 | Analytics: trade categorization + strategy rules | unclaimed | — | `scripts/analyze.py` | |
| 7 | Dashboard site (events, charts, orderbook depth, portfolio, suggestions) | unclaimed | — | `site/` | GitHub Pages |
| 8 | Suggestions + open-questions pages | unclaimed | — | `site/suggestions/`, `site/questions/` | |
| 9 | Flagged-for-review page | unclaimed | — | `site/flagged/` | |
| 10 | Final integration, re-verification, PR to main, Pages deploy | unclaimed | — | `site/` index/nav, `data/` | Only after 1–9 |

## Blocked Items

| # | Item | Blocking reason | Workaround applied |
|---|------|-----------------|--------------------|
| B1 | Portfolio tracking + trade execution on the Kalshi **demo account** | Requires an API key ID + RSA private key (`KALSHI-ACCESS-KEY` / `KALSHI-ACCESS-SIGNATURE`, RSA-PSS/SHA-256). No credentials exist in this repo or environment, and the user requires zero manual input. | Ship a fully implemented, credential-ready signed client (`scripts/trade_engine.py`) that is exercised against the **public** endpoints, plus a clearly-labelled paper-trading engine driven by live public market data. Marked `needs review` in the requirements register. |

## Change Requests

_None yet._

## Irregularities Flagged

_None yet._

## Activity Log

| Timestamp (UTC) | Session | Action |
|---|---|---|
| 2026-11-20 11:20 | arena-b2e728ab | Repo is a bare checkout (`README.md` only, 1 commit `80f7c4d`). No prior work, no other sessions. Created COORDINATION.md. |
| 2026-11-20 11:22 | arena-b2e728ab | Sandbox network policy blocks direct `curl` to `*.kalshi.co`; data is collected through the agent's HTTP fetch tool against `https://external-api.demo.kalshi.co/trade-api/v2`. `GET /exchange/status` verified live: `exchange_active=true`, `trading_active=true`, 4 shards (0 Default, 1 "Demo shard 1", 2 "Demo shard 2", 3 unnamed), `intra_exchange_transfers_active=true`. |
| 2026-11-20 11:23 | arena-b2e728ab | Single-session run: this session claims tasks 1–10 and executes them sequentially (no other session is active on the board). |

## Verification Method

Every published table row in the site carries a source link. Sources are restricted to:
1. **Kalshi official API documentation** — `https://docs.kalshi.com/...`
2. **Kalshi live API responses** — `https://external-api.demo.kalshi.co/trade-api/v2/...` (fetched and archived to `data/` in this session)
3. **GitHub** — this repository, for build/verification artifacts.

Anything not confirmable from one of those is left blank in the tables and listed on the
**Flagged for Review** page.
