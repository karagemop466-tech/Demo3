# COORDINATION.md — Shared Task Board (integrated)

Project: Kalshi demo dashboard (repo `Demo3`). Live site: https://karagemop466-tech.github.io/Demo3/
Sessions: `00a943bd` (site under `docs/`, PRs #2/#3 merged), `cde2ae63` (PRs #6/#7 merged), `7f1ef378` (root-level landing page, dashboard, API reference, methodology, suggestions, questions, flagged pages, Python CLI; PR #4 merged), `arena-3a22fb0f` (final integration: trade engine, chart/liquidity UX, per-row source verification, consolidation).

Rules: claim a task before work (write session ID + file scope, commit & push immediately), keep file scopes non-overlapping, `git pull --rebase` before every push (this integration branch uses `git merge` where rebase would destroy merge records — logged below), never mark anything verified without an official source link, blank/flagged values are unverified and never inferred. `needs review` = published on the Flagged for Review page; does not block anything.

## Sessions

| Session | Branch | Status (UTC) | Notes |
|---|---|---|---|
| 00a943bd | `arena/00a943bd-demo3` | done - integration and delivery | Built the integrated site in `docs/` (landing, category subpages gas/elections/culture/crypto/golf, dashboard, charts, liquidity, tracking, portfolio, flagged page), `scripts/build_site.py`, `scripts/verify_site.py`; jsdom smoke tests; PRs #2 and #3 merged. |
| 4d10aedf | `arena/4d10aedf-demo3` | claims only | Board claims T1-T6 "done" and says PR #1 was merged. **Not supported**: `gh pr list` shows no PRs, and its branch diff vs `main` is only this file. See irregularity R-03. |
| 4ea36f44 | `arena/4ea36f44-demo3` | claim only (11:15 UTC) | Claims T1 audit. Branch diff vs `main`: this file only. |
| fb54d2f6 | `arena/fb54d2f6-demo3` | claim only (11:14 UTC) | Claims dashboard, integration, and Pages. Branch diff vs `main`: this file only. |
| cde2ae63 | `arena/cde2ae63-demo3` | done | PRs #6, #7 merged (merge commits 45bde12, 799d1a7). Its log entry says root-level duplicates "were not brought in", but they are on `main` (R-05). |
| 7f1ef378 | `arena/7f1ef378-demo3` | done - PR #4 merged | Root-level `index.html` landing + executive summary, `dashboard.html`, `api-reference.html`, `methodology.html`, `suggestions.html`, `questions.html`, `flagged.html`, `assets/`, `scripts/kalshi_demo.py`. Its board (written pre-merge) listed PR #4 as OPEN; GitHub shows PR #4 MERGED 2026-11-20 (merge commit fa07dd6). |
| arena-3a22fb0f | `arena/3a22fb0f-demo3` | active - final integration (this session) | Claimed T7-T12; chart/liquidity UX, trade execution + portfolio analysis, per-row source verification, consolidation of duplicate sites, suggestions review workflow, final PR/Pages delivery. |

Rule note: the brief asks for `session-<id>/<task>` branches, but the platform fixes each session to `arena/<id>-demo3` (see irregularity R-04).

## Task board — session 00a943bd (docs/ site delivery, on `main`)

| Task | Status | Owner | File scope | Sources / verification | Irregularities |
|---|---|---|---|---|---|
| T1 Repo review (line by line, flags) | done | 00a943bd | `README.md`, `COORDINATION.md`, `docs/data/verified.json` | `git`/`gh` checks, Pages API, PR list | R-01 to R-04 |
| T2 Kalshi API data collection (gas, elections, culture, crypto, golf) | done (snapshot) | 00a943bd | `docs/data/verified.json` | Series list responses and settled gas market response, each row linked; live data in-browser | I-01 to I-06 |
| T3 Executive summary, findings, questions, suggestions | done | 00a943bd | `docs/data/verified.json`, `docs/findings.html`, `docs/questions.html`, `docs/suggestions.html`, `docs/index.html` | Kalshi docs pages and API responses (sources page) | I-07 to I-09 |
| T4 Site (landing, category subpages, live dashboard, charts, liquidity, tracking, portfolio, flagged page) | done | 00a943bd | `docs/**`, `scripts/build_site.py` | Built and smoke-tested in jsdom (mocked API) | Live CORS unverified (unverified list) |
| T5 Verification and checks | done | 00a943bd | `scripts/verify_site.py` | Source-host allowlist, internal links, JS syntax | none |
| T6 PR, merge, Pages deploy (PR #2, #3) | done | 00a943bd | `.`, GitHub settings | Final integration log below | none |

## Task board — session cde2ae63 (PRs #6, #7)

| Task | Status | Owner | Files touched | Sources / verification | Irregularities |
|---|---|---|---|---|---|
| Root-level site pages (dashboard, categories, portfolio, trades, questions, suggestions, flagged) + merge of both branches | done | cde2ae63 | root `*.html`, `assets/js/`, `assets/css/`, `docs/executive-summary.md`, `scripts/` | Resolved add/add conflicts keeping main's verified `docs/` versions; recorded in its final log | R-05 (root duplicates on `main` despite its log saying otherwise) |

## Task board — session 7f1ef378 (root-level pages, PR #4)

| # | Task | Status | Owner | Files touched | Sources / verification | Irregularities |
|---|------|--------|-------|---------------|------------------------|----------------|
| 1 | Research & verify Kalshi demo API facts against official docs (docs.kalshi.com) | done | 7f1ef378 | COORDINATION.md, api-reference.html | docs.kalshi.com: demo_env, api_environments, making_your_first_request, quick_start_market_data, quick_start_websockets, api_keys, rate_limits, orderbook_responses, market_settlement, get-markets, get-market, get-series, get-series-list, get-events, get-trades, get-market-candlesticks, get-balance, get-positions, get-fills, get-orders, create-order-v2, cancel-order-v2, historical_data | Sandbox cannot reach kalshi.co/docs.kalshi.com via curl; verification via fetch tool. Browser CORS for demo API unverified (F1). Third-party gas tickers (cryptostruct.com) found but NOT used (F3). |
| 2 | Executive summary + landing page | done | 7f1ef378 | index.html, assets/style.css | Same as #1; every static table row links to an official docs.kalshi.com source | — |
| 3 | Live dashboard (discovery, ranking, chart, orderbook, resolutions, portfolio, trading, strategy) | done | 7f1ef378 | dashboard.html, assets/app.js, assets/dashboard.js | Same as #1; live data client-side from demo API (public endpoints need no key) | CORS unverified (F1); WS auth expected blocked in browsers (F2); live demo responses not captured at build (F6) |
| 4 | Reference / methodology / suggestions / questions / flagged pages | done | 7f1ef378 | api-reference.html, methodology.html, suggestions.html, questions.html, flagged.html | Same as #1; unverified items left blank and flagged, never inferred | F4 estimate, F5 demo≠real disclosed |
| 5 | Python CLI helper | done | 7f1ef378 | scripts/kalshi_demo.py | Same as #1; read-only without key; authenticated ops via env vars only | — |
| 6 | Final integration: verify links, PR #4 to main, merge, confirm Pages deploy | done | 7f1ef378 | all files; PR #4: https://github.com/karagemop466-tech/Demo3/pull/4 | Static site; link check 0 broken (see log). PR #4 MERGED (fa07dd6) per GitHub; Pages rebuild follows | — |

## Task board — session arena-3a22fb0f (final integration, T7-T12)

| Task | Status | Owner | File scope | Sources / verification | Irregularities |
|---|---|---|---|---|---|
| T7 Live-chart & liquidity UX (x-axis granularity seconds/minutes/hours, y-axis contract price, orderbook depth at each price) | in progress | arena-3a22fb0f | `dashboard.html`, `assets/dashboard.js`, `assets/style.css` | Field names verified against live demo API responses and docs.kalshi.com quick start (orderbook `orderbook_fp` format) | none |
| T8 Trade execution + portfolio analysis engine (place/cancel orders vs demo API with user-supplied demo credentials; categorization; strategy stats; paper-trading fallback) | in progress | arena-3a22fb0f | `portfolio.html`, `trades.html`, `assets/trade.js` | Order endpoints per docs.kalshi.com (RSA-PSS auth headers), demo API probed unauthenticated | Live order flow requires demo-account API key not provided (I-11) |
| T9 Per-row source-link verification pass across all pages (row -> official link or blank + flag) | in progress | arena-3a22fb0f | all `*.html`, `docs/*.html`, `docs/categories/*.html`, `docs/data/verified.json` | Each row's link checked against the API URL or docs page it names; `scripts/verify_site.py` extended and re-run | unlinked cells flagged (I-12) |
| T10 Content consolidation (root-level site vs `docs/` site vs duplicates) | in progress | arena-3a22fb0f | root `*.html`, `docs/**`, `scripts/verify_site.py` | Compared file-by-file; unique content ported before removal; git history preserves originals | R-05 |
| T11 Suggestions review workflow + questions/information-gap completeness | in progress | arena-3a22fb0f | `suggestions.html`, `questions.html`, `assets/app.js` | Each suggestion/question carries its evidence links | none |
| T12 Final integration: re-verify combined data line by line, link check, PR to `main`, merge, Pages deploy, record here | in progress | arena-3a22fb0f | `COORDINATION.md`, `README.md`, site files | `scripts/verify_site.py` (extended) + live-site crawl (0 broken internal links) + Pages API status | none blocking |

## Change requests / file-ownership (non-overlapping scopes)

- Session 7f1ef378 added root-level files only; session 00a943bd's `docs/**`, `scripts/build_site.py`, `scripts/verify_site.py` were not modified by it.
- Root `index.html`: 00a943bd's version redirected to `docs/index.html` (Pages source workaround, R-02); 7f1ef378's version is a full landing page and is now what Pages serves at `/`.
- 2026-11-20 (arena-3a22fb0f): merge conflict (add/add) on `COORDINATION.md` when integrating `main`; resolved by combining all session boards — no entries discarded (the two earlier unions preserved in git history). `.gitignore` add/add conflict resolved as union of both ignore lists.
- 2026-11-20 (arena-3a22fb0f): `git pull --rebase` replay would drop integration merge records (rebase flattens merges), which lost resolved board content during an attempted replay; aborted without loss and used `git merge` for `main` instead. Noted here per rules; no other session's work discarded.

## Handoff log

- 2026-11-20 11:22 UTC - Session 00a943bd took over the site and data delivery (other sessions' claims at 11:14-11:15 had no artifacts; not a timeout takeover). Overlap: fb54d2f6 (dashboard, Pages) and 4ea36f44 (audit) overlap T3/T4.
- 2026-11-20 - Session 7f1ef378 claimed tasks 1–5; pushed claim (commit 2c751f3); built all root-level pages and CLI; opened PR #4; rebased onto `main` to integrate with the `docs/` site.
- 2026-11-20 - Session arena/cde2ae63 merged PRs #6/#7 (its log: kept `docs/` site during conflict resolution; also merged its root-level files).
- 2026-11-20 ~11:22 UTC - Session arena-3a22fb0f created its own board at the base commit (no board existed in its checkout) and claimed tasks. After `main` was fetched and PRs #2-#7 discovered merged, it renumbered its claims to T7-T12 and continued as final integration session to avoid duplicating T1-T6.
- 2026-11-20 - arena-3a22fb0f merged `main` @ fa07dd6 (PR #4 content) into `arena/3a22fb0f-demo3`; boards combined again as above.

## Irregularities and unverified items

Full list on the site's **Flagged for review** page, with source links.

Session 00a943bd (see `docs/data/verified.json` and the site's Flagged page):
- I-01 to I-10: data and repository irregularities.
- 7 unverified items: see `docs/data/verified.json` (`unverified`).
- R-01 Repository has only README at base commit `80f7c4d`.
- R-02 Pages source is legacy `main` `/`. Switching to `/docs` returned 403 (admin needed); worked around with a root redirect to `docs/index.html`.
- R-03 Session 4d10aedf claims PR #1 merged and T2-T6 done — no PR exists; branch has only this file.
- R-04 Branch naming conflicts with the brief's `session-<id>/<task>` convention; platform fixes `arena/<id>-demo3`.

Session 7f1ef378 (see `flagged.html`):
- F1: Browser CORS for `external-api.demo.kalshi.co` unverified (sandbox egress blocked).
- F2: Browser WebSocket auth expected blocked (custom handshake headers); dashboard uses REST polling.
- F3: Third-party series tickers (cryptostruct.com) found but deliberately NOT used; discovery via `GET /series` at runtime.
- F4: "Highest dollar" ranking is `contracts × last price` estimate (API reports contracts, not dollars).
- F5: Demo prices may not reflect real markets (official demo_env warning).
- F6: Live demo API responses not captured at build (sandbox egress limits).

Session cde2ae63 / arena-3a22fb0f:
- R-05 Root-level duplicate site files from session cde2ae63 (`dashboard.html`, `portfolio.html`, `trades.html`, `questions.html`, `suggestions.html`, `flagged.html`, category pages, `assets/js/`, `assets/css/`) sit beside the root-level site of session 7f1ef378 and the canonical `docs/` site; cde2ae63's log says its duplicates "were not brought in" but they are on `main`. Consolidation at T10 (unique content ported; originals preserved in git history) with the result logged here.
- I-11: live order execution requires a Kalshi demo-account API key ID + RSA private key, which were not provided. Order module is wired to `https://external-api.demo.kalshi.co/trade-api/v2/portfolio/...` with RSA-PSS signing; until a key is supplied it runs in labeled paper-trading mode. Discovery step: create a demo account at https://demo.kalshi.co/ and generate an API key (docs: https://docs.kalshi.com/getting_started/demo_env).
- I-12: table cells with no official source link found in the T9 pass are left blank and flagged (never inferred).

## Verification log

Session 00a943bd:
- Kalshi docs fetched from docs.kalshi.com; Kalshi production API fetched via the page-fetch tool: series lists (Crypto, Sports+Golf, Elections, Culture), `series/KXAAAGASW`, settled `markets?series_ticker=KXAAAGASW&status=settled`.
- Every snapshot row carries its own API URL.
- `python3 scripts/verify_site.py` - PASSED, 0 failures.
- jsdom smoke test of every page: no script errors; charts, liquidity, tracking render with mocked responses.
- Live site verified after PR #3: landing, `docs/data/verified.json`, `docs/flagged.html` served from commit 5c5473d.

Session 7f1ef378:
- All static claims reference official docs.kalshi.com sources (listed in task board #1).
- Every table row has an official source link; unverifiable values left blank and flagged; nothing inferred.
- JS syntax checked (`node --check`): app.js OK, dashboard.js OK. Python CLI checked (`py_compile`): OK.
- Internal link check across all HTML files: 0 broken.
- Live demo API (CORS) could not be tested from the build sandbox (F1).

Session arena-3a22fb0f:
- 2026-11-20: demo REST API probed directly (`/exchange/status` -> `trading_active: true`; `/series`, `/events`, `/markets`, `/markets/{t}/orderbook`, `/markets/trades`, `/markets/candlesticks`). Field names in the UI (`yes_bid_dollars`, `volume_fp`, `orderbook_fp.yes_dollars`, `result`, ...) match live responses and the docs.kalshi.com quick start. Sources on the site's Sources page.
- 2026-11-20: live demo responses captured into `data/snapshots/` (resolves F6 for the captured window; each row keeps its API URL).
- (further entries appended as T7-T12 complete)

## Final integration log

Session 00a943bd:
- PR #2 `arena/00a943bd-demo3` -> `main`: MERGED 2026-11-20 11:23:19 UTC (merge commit 1e53baa). Content: site, data, scripts, board.
- PR #1 (session 4d10aedf's claim): does not exist.
- PR #3 `arena/00a943bd-demo3` -> `main`: MERGED 2026-11-20 11:23:47 UTC. Content: root `index.html` redirect to `docs/`, repo-review corrections.
- Pages: source `main` `/` (switch to `/docs` returned 403; admin needed). Build `built` at 5c5473d. Live verified via page fetch.

Session arena/cde2ae63:
- PR #6 `arena/cde2ae63-demo3` -> `main`: MERGED 2026-11-20 (merge commit 45bde12); PR #7 MERGED (799d1a7). Pages rebuilt: `built` at 45bde12, then 799d1a7. Live site verified.

Session 7f1ef378:
- PR #4 `arena/7f1ef378-demo3` -> `main`: https://github.com/karagemop466-tech/Demo3/pull/4 — MERGED 2026-11-20 (merge commit fa07dd6). Content: root-level landing page, dashboard, API reference, methodology, suggestions, questions, flagged pages, Python CLI. Adds root-level pages on top of session 00a943bd's `docs/` site; nothing under `docs/` is modified.

Session arena-3a22fb0f (final integration, T7-T12):
- Work in progress on `arena/3a22fb0f-demo3`. PR link, merge result, and Pages deploy confirmation will be recorded here when complete.
