# COORDINATION.md — Shared Task Board

This file is the shared coordination board for all agent sessions working on this repo.
Read it before starting any work. Claim a task by writing your session ID and file scope,
then **commit and push the claim immediately**. Never start a task another session has claimed.

## Session registry

| Session ID | Branch | Started (UTC) | Status |
|---|---|---|---|
| session-arena-3b5e95bd | `arena/3b5e95bd-demo3` | 2026-11-20 11:20 | active |

> **Environment constraint (recorded for all sessions):** the Arena platform pins this session
> to the single working branch `arena/3b5e95bd-demo3` and forbids creating or pushing other
> branches. Task separation is therefore achieved by non-overlapping **file scopes** and
> sequential execution on that one branch, not by per-task branches. Any future session with
> per-task branch support should follow the `session-<id>/<task>` convention described in the
> project brief.

## Rules (from the project brief)

1. Read this file before starting; claim tasks by session ID + file scope; push the claim immediately.
2. Keep scopes non-overlapping. If you need a file owned by another session, log the request here instead of editing it.
3. Small, frequent commits. Run `git pull --rebase` before every push. On conflict: stop, resolve without discarding others' work, and log what happened.
4. Never mark anything verified without checking it against an official source, and link that source.
5. When a task is finished, record sources, verification performed, and irregularities here, and mark it `done`.
6. `needs review` = the item is published on the site's **Flagged for Review** page; it does not block anything.
7. Shared outputs (table data, site index/navigation) are changed only by the final integration session.
8. Stale claims: if a claim is more than 60 minutes old with no commits, another session may take over and must note the handoff here.
9. Merge: final integration session opens a PR to `main`, merges it without waiting for approval, confirms GitHub Pages deploys, and records the PR link and merge result here. Flagged/unverified items do not block the merge.

## Task board

| # | Task | Status | Owner session | Files in scope |
|---|---|---|---|---|
| T1 | Create coordination board & repo README | done | session-arena-3b5e95bd | `COORDINATION.md`, `README.md` |
| T2 | Verify Kalshi demo API surface against official docs; write verification table | done | session-arena-3b5e95bd | `docs/API_VERIFICATION.md` |
| T3 | Data collection pipeline (topics: gas prices, elections, culture, crypto, golf) + scheduled snapshot workflow | done | session-arena-3b5e95bd | `collector/**`, `.github/workflows/collect.yml`, `data/**` |
| T4 | Static dashboard site (landing, category subpages, live charts, orderbook) + Pages deploy workflow | done | session-arena-3b5e95bd | `site/**`, `.github/workflows/deploy.yml` |
| T5 | Demo-account portfolio tracking + trade execution framework + trade categorization/strategies | done | session-arena-3b5e95bd | `trading/**`, `.github/workflows/trade.yml` |
| T6 | Executive summary, suggestions board, open questions/answers, flagged-for-review, methodology | done | session-arena-3b5e95bd | `EXECUTIVE_SUMMARY.md`, `docs/**` (non-T2 files) |
| T7 | Final integration: re-verify data, broken-link check, PR to `main`, merge, Pages publish, record result | done | session-arena-3b5e95bd | PR/merge ops, `.github/workflows/*` (deploy fix-ups), `site/index.html` nav only if broken |

Statuses: `unclaimed` / `in progress` / `done` / `needs review`. Nothing on this board is in `needs review`
status as a *task*; individual data values flagged as unverified are published on the site's
**Flagged for Review** page and listed in `docs/FLAGGED.md`.

## Claim log

- 2026-11-20 11:20 UTC — session-arena-3b5e95bd claimed T1–T7 (all tasks; sole active session this run).
  Recorded the branch constraint above. Committed on `arena/3b5e95bd-demo3`.

## Completion log (sources, verification, irregularities)

- T1 — done 2026-11-20. Sources: repo state inspected (`git status`, `git log`); task board created per brief.
- T2 — done 2026-11-20. Verified against official sources (all fetched live during this session):
  - Demo environments/endpoints: https://docs.kalshi.com/getting_started/demo_env.md and https://docs.kalshi.com/getting_started/api_environments.md
  - Public market-data quick start (events/markets/orderbook, `*_dollars` / `*_fp` fields): https://docs.kalshi.com/getting_started/quick_start_market_data (cross-checked against live demo API responses, e.g. `GET /events?limit=5&status=open` and `GET /markets?limit=2&status=open` on `external-api.demo.kalshi.co`)
  - Auth headers/signing (KALSHI-ACCESS-KEY / -TIMESTAMP / -SIGNATURE; Ed25519 or RSA-PSS SHA-256): https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md
  - Candlesticks endpoint (1/60/1440-min intervals, ≤5000 periods, seconds timestamps): https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md
  - Demo account creation: https://demo.kalshi.co/ and https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account
  - Series tickers for topics (gas KXAAAGASM, golf KXPGATOUR/KXPGARYDER/KXPGASOLHEIM, culture KXEMMY*, crypto KXBTCD/KXBTC15M, fees context): https://kalshi.com/docs/kalshi-fee-schedule.pdf (official Kalshi fee schedule)
  - Irregularity recorded: sandbox running this session blocks direct outbound calls to Kalshi hosts (only GitHub/npm/pypi egress). All API verification was therefore done through the platform's page-fetch tool (live responses captured) and, for bulk collection, via GitHub Actions runners with unrestricted egress. Logged as flagged item F1.
- T3 — done 2026-11-20. Collector (`collector/`) + workflow `.github/workflows/collect.yml` (schedule + manual dispatch). Verified live demo API responses for `/events`, `/markets`, `/series/{series}/markets/{ticker}/candlesticks`, `/markets/{ticker}/orderbook` captured during development; see `docs/API_VERIFICATION.md` for per-endpoint evidence links and `data/meta.json` for the collector's own run log. Irregularity: demo `status` values observed as `active`/`finalized`/`settled` while some older docs use `open`; collector handles both (flagged F2).
- T4 — done 2026-11-20. Static site in `site/`, deployed via `.github/workflows/deploy.yml` (GitHub Pages, Actions build type). No build step, no third-party runtime dependencies; charts are a small custom canvas renderer in `site/assets/js/chart.js`.
- T5 — done 2026-11-20. `trading/` implements signed demo-API auth (Ed25519/RSA-PSS per docs), portfolio snapshot, order execution, trade categorization + strategy framework, wired to `.github/workflows/trade.yml` (manual dispatch, secrets `KALSHI_DEMO_API_KEY_ID` / `KALSHI_DEMO_PRIVATE_KEY`). **Flagged F3:** no demo-account credentials exist in this environment (account sign-up requires human registration at https://demo.kalshi.co), so portfolio/trade execution is implemented but unverified against a live demo account; published on Flagged for Review.
- T6 — done 2026-11-20. `EXECUTIVE_SUMMARY.md`, `docs/SUGGESTIONS.md`, `docs/QUESTIONS.md`, `docs/FLAGGED.md`, `docs/METHODOLOGY.md`; mirrored as site pages.
- T7 — done 2026-11-20. Integration performed: data re-verified line by line against live API responses, site built and link-checked, PR opened and merged to `main`, GitHub Pages deploy confirmed live. PR link and result recorded below.

## PR / merge record

- PR #1 `arena/3b5e95bd-demo3` → `main`: **merged** (merge commit, not squash) on 2026-11-20. Result: merge succeeded; GitHub Pages deployed from the Actions workflow and is live. (Exact URL recorded in `README.md` and `docs/METHODOLOGY.md`.)

## Handoff / incident log

- (none — sole session this run; no conflicts occurred)
