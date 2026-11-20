# COORDINATION.md — Shared Task Board

**Repo:** [karagemop466-tech/Demo3](https://github.com/karagemop466-tech/Demo3)
**Project:** Kalshi Demo Dashboard — live event tracking (gas prices, elections, culture, crypto, golf), portfolio performance, trade execution, decision-support (questions, suggestions), verified data tables, GitHub Pages site.
**Branch policy for this run:** Platform constraint — this session works exclusively on branch `arena/3a22fb0f-demo3` (branched from `main` @ `80f7c4dcdbfe1e8821ebb6b5f319c5cfa3eb38f2`). No other branches are created. This branch therefore serves as both the session branch and the final integration branch. Integration = re-verification of combined data, site link check, PR to `main`, merge, GitHub Pages publish.

## Sessions

| Session ID | Branch | Status | Notes |
|---|---|---|---|
| `arena-3a22fb0f` | `arena/3a22fb0f-demo3` | active | Only active session. Also performs final integration. Claimed all tasks 2026-11-20. |

## Task board

Statuses: `unclaimed` · `in progress` · `done` · `needs review`

| # | Task | Status | Owner (session) | Files in scope | Sources | Verification performed | Irregularities |
|---|---|---|---|---|---|---|---|
| T1 | Repo review (line by line) | done | `arena-3a22fb0f` | `repo-review.html`, `data/repo-review.json` | repo git history; GitHub API | Reviewed every tracked file at base commit `80f7c4d`; verified repo metadata via `gh repo view` | README was 1 line ("# Demo3") with no project info — replaced/expanded; no license file present (flagged) |
| T2 | API research & verification (official docs) | done | `arena-3a22fb0f` | `api-reference.html`, `data/api-sources.json` | [docs.kalshi.com demo_env](https://docs.kalshi.com/getting_started/demo_env), [docs.kalshi.com](https://docs.kalshi.com), live demo API probes | Confirmed demo REST/WS endpoints match official demo-env page; probed `/exchange/status`, `/series`, `/events`, `/markets`, orderbook, trades, candlesticks on `external-api.demo.kalshi.co` | `demo-api.kalshi.co` (legacy host) not probed directly — docs mark it "also supported" only |
| T3 | Live data capture (5 topics: gas, elections, culture, crypto, golf) | done | `arena-3a22fb0f` | `data/snapshots/*.json`, `data/tables/*.json` | `https://external-api.demo.kalshi.co/trade-api/v2/...` (per-row API URLs stored in tables) | Each captured row carries its exact API request URL; re-fetch spot-checked | Demo volumes/prices are synthetic per Kalshi's own warning (flagged); dollar-volume is a computed estimate = Σ(contracts × price), formula documented |
| T4 | Site build (landing, dashboard, portfolio, trade, questions, suggestions, flagged, sources) | done | `arena-3a22fb0f` | `index.html`, `dashboard.html`, `portfolio.html`, `questions.html`, `suggestions.html`, `flagged.html`, `sources.html`, `repo-review.html`, `api-reference.html`, `assets/**` | Chart.js 4.6.1 + chartjs-adapter-date-fns 3.0.0 (npm registry, MIT, vendored) | Site is static, no build step; all external data fetched live from Kalshi demo API with static fallback tables | Live trading requires demo-account API credentials (RSA key) that were not provided — wired but flagged |
| T5 | Verification pass (every row → official source link or blank + flag) | done | `arena-3a22fb0f` | all `*.html` tables | per-row source links | Checked every table row of every page: rows either carry an official `docs.kalshi.com` / `external-api.demo.kalshi.co` / `assets.kalshi.com` link or are explicitly blank + flagged | — |
| T6 | Suggestions & decision-support content | done | `arena-3a22fb0f` | `suggestions.html`, `questions.html` | research + API findings | Suggestions cite sources; each question lists known/unknown + discovery method | — |
| T7 | Final integration: link check, PR, merge, Pages publish | done | `arena-3a22fb0f` | `COORDINATION.md`, `README.md`, `.nojekyll` | GitHub Actions/Pages API | Crawl of all pages: 0 broken internal links; Pages deployment confirmed via `gh api .../pages` + HTTP 200 on live URL | GitHub Pages build is branch-based (`main` / root) |

## Shared-output rule

`index.html` navigation, `data/tables/*` combined data, and `README.md` are shared outputs. In this single-session run they are edited by `arena-3a22fb0f` only at integration time (T7) after the component tasks completed.

## Requests to other sessions

_None — single session run._

## Handoff log

| Time (UTC) | Event |
|---|---|
| 2026-11-20 | Session `arena-3a22fb0f` created this board and claimed T1–T7 (commit pushed immediately per rules). |
| 2026-11-20 | T1–T6 completed on `arena/3a22fb0f-demo3`; sources recorded per task above. |
| 2026-11-20 | T7 integration: re-verified combined data rows against stored API URLs, crawled site links (0 broken), opened PR #1 to `main`, merged (squash), GitHub Pages enabled and confirmed live (HTTP 200) at https://karagemop466-tech.github.io/Demo3/ . PR link recorded in final entry below. |

## Final integration record

- **PR:** [#1](https://github.com/karagemop466-tech/Demo3/pull/1) — merged (squash) into `main`.
- **GitHub Pages:** enabled from `main` / root; deployment verified 2026-11-20 — https://karagemop466-tech.github.io/Demo3/ returned HTTP 200 and serves the new landing page.
- **Re-verification at integration:** every data table row checked against its source link (official Kalshi demo API URL or docs.kalshi.com page); unverifiable cells left blank and listed on the Flagged for Review page.
- **Flagged irregularities published at:** [Flagged for Review](https://karagemop466-tech.github.io/Demo3/flagged.html) — 8 items (demo data is synthetic; no demo-account credentials provided; dollar-volume is an estimate; README/license gaps at base commit; etc.). None block the merge per instructions.

## Rules of engagement (as instructed)

1. Claim a task here (write session ID + file scope) and commit + push the claim immediately. Never start a task another session has claimed.
2. Keep file scopes non-overlapping. If a task needs a file owned by another session, log the request here instead of editing it.
3. Small, frequent commits. `git pull --rebase` before every push. Resolve merge conflicts without discarding others' work; log what happened.
4. When a task is finished: record sources, verification performed, and irregularities here, then mark it `done`. Never mark anything verified without checking against an official source, and link that source.
5. `needs review` items are published on the site's Flagged for Review page and do not block anything.
6. If a claim is >60 minutes old with no commits, any other session may take over and note the handoff here.
