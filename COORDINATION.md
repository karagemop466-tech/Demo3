# COORDINATION.md — Shared Task Board (integrated)

Project: Kalshi demo dashboard (repo `Demo3`). Live site: https://karagemop466-tech.github.io/Demo3/
Sessions: `00a943bd` on branch `arena/00a943bd-demo3` (site under `docs/`, PRs #2/#3 merged to `main`, Pages built/live at commit 5c5473d) and `7f1ef378` on branch `arena/7f1ef378-demo3` (root-level landing page, dashboard, API reference, methodology, suggestions, questions, flagged pages, Python CLI; PR #4 opens this branch to `main`).

Rules: claim a task before work (write session ID + file scope, commit & push immediately), keep file scopes non-overlapping, `git pull --rebase` before every push, never mark anything verified without an official source link, blank/flagged values are unverified and never inferred. `needs review` = published on the Flagged for Review page; does not block anything.

## Sessions

| Session | Branch | Status (UTC) | Notes |
|---|---|---|---|
| 00a943bd | `arena/00a943bd-demo3` | active - integration and delivery | Built the integrated site in `docs/` (landing, category subpages gas/elections/culture/crypto/golf, dashboard, charts, liquidity, tracking, portfolio, flagged page), `scripts/build_site.py`, `scripts/verify_site.py`; verified with jsdom smoke tests; PRs #2 and #3 merged; Pages built/live at 5c5473d; root `index.html` redirects to `docs/index.html`. |
| 7f1ef378 | `arena/7f1ef378-demo3` | active - integration (this session) | Root-level `index.html` landing + executive summary, `dashboard.html` live client-side dashboard, `api-reference.html`, `methodology.html`, `suggestions.html`, `questions.html`, `flagged.html`, `assets/style.css`, `assets/app.js`, `assets/dashboard.js`, `scripts/kalshi_demo.py`; PR #4 (`arena/7f1ef378-demo3` -> `main`) adds root-level pages on top of the `docs/` site. |
| 3b5e95bd | `arena/3b5e95bd-demo3` | active - automation delivery | Scheduled server-side collector (`collector/`, `.github/workflows/collect.yml`, committed `data/` snapshots: tracked live events ranked by estimated dollar volume, orderbooks, 1m/60m/1440m candlestick history, resolution tracking until settled), demo-account trade/portfolio automation (`trading/`, `.github/workflows/trade.yml`), offline pipeline tests. See task board below. |

Rule note: the brief asks for `session-<id>/<task>` branches, but the platform fixes each session to `arena/<id>-demo3` (see irregularity R-04).

## Task board — session 00a943bd (docs/ site delivery, on `main`)

| Task | Status | Owner | File scope | Sources / verification | Irregularities |
|---|---|---|---|---|---|
| T1 Repo review (line by line, flags) | done | 00a943bd | `README.md`, `COORDINATION.md`, `docs/data/verified.json` | `git`/`gh` checks, Pages API, PR list | R-01 to R-04 |
| T2 Kalshi API data collection (gas, elections, culture, crypto, golf) | done (snapshot) | 00a943bd | `docs/data/verified.json` | Series list responses and settled gas market response, each row linked; live data in-browser | I-01 to I-06 |
| T3 Executive summary, findings, questions, suggestions | done | 00a943bd | `docs/data/verified.json`, `docs/findings.html`, `docs/questions.html`, `docs/suggestions.html`, `docs/index.html` | Kalshi docs pages and API responses (sources page) | I-07 to I-09 |
| T4 Site (landing, category subpages, live dashboard, charts, liquidity, tracking, portfolio, flagged page) | done | 00a943bd | `docs/**`, `scripts/build_site.py` | Built and smoke-tested in jsdom (mocked API) | Live CORS unverified (unverified list) |
| T5 Verification and checks | done | 00a943bd | `scripts/verify_site.py` | Source-host allowlist, internal links, JS syntax | none |
| T6 PR, merge, Pages deploy | done (PR #2 and #3 merged; Pages built) | 00a943bd | `.`, GitHub settings | Final integration log below | none |

## Task board — session 7f1ef378 (root-level pages, PR #4)

| # | Task | Status | Owner | Files touched | Sources / verification | Irregularities |
|---|------|--------|-------|---------------|------------------------|----------------|
| 1 | Research & verify Kalshi demo API facts against official docs (docs.kalshi.com) | done | 7f1ef378 | COORDINATION.md, api-reference.html | docs.kalshi.com: demo_env, api_environments, making_your_first_request, quick_start_market_data, quick_start_websockets, api_keys, rate_limits, orderbook_responses, market_settlement, get-markets, get-market, get-series, get-series-list, get-events, get-trades, get-market-candlesticks, get-balance, get-positions, get-fills, get-orders, create-order-v2, cancel-order-v2, historical_data | Sandbox cannot reach kalshi.co/docs.kalshi.com via curl; verification via fetch tool. Browser CORS for demo API unverified (F1). Third-party gas tickers (cryptostruct.com) found but NOT used (F3). |
| 2 | Executive summary + landing page | done | 7f1ef378 | index.html, assets/style.css | Same as #1; every static table row links to an official docs.kalshi.com source | — |
| 3 | Live dashboard (discovery, ranking, chart, orderbook, resolutions, portfolio, trading, strategy) | done | 7f1ef378 | dashboard.html, assets/app.js, assets/dashboard.js | Same as #1; live data client-side from demo API (public endpoints need no key) | CORS unverified (F1); WS auth expected blocked in browsers (F2); live demo responses not captured at build (F6) |
| 4 | Reference / methodology / suggestions / questions / flagged pages | done | 7f1ef378 | api-reference.html, methodology.html, suggestions.html, questions.html, flagged.html | Same as #1; unverified items left blank and flagged, never inferred | F4 estimate, F5 demo≠real disclosed |
| 5 | Python CLI helper | done | 7f1ef378 | scripts/kalshi_demo.py | Same as #1; read-only without key; authenticated ops via env vars only | — |
| 6 | Final integration: verify links, PR #4 to main, merge, confirm Pages deploy | in progress | 7f1ef378 | all files; PR #4: https://github.com/karagemop466-tech/Demo3/pull/4 | Static site; link check 0 broken (see log) | — |

## Task board — session 3b5e95bd (automation: scheduled collection + demo trading)

| # | Task | Status | Owner | Files touched | Sources / verification | Irregularities |
|---|------|--------|-------|---------------|------------------------|----------------|
| A1 | Scheduled server-side collector: snapshot tracked live events (gas, elections, culture, crypto, golf) ranked by estimated dollar volume; orderbooks; 1m/60m/1440m candlestick history; CORS probe; commit under `data/` | done | 3b5e95bd | `collector/kalshi_api.py`, `collector/collect.py`, `collector/test_collect.py`, `.github/workflows/collect.yml`, `data/**` | Offline pipeline tests against mock shapes mirroring live demo responses captured 2026-11-20 (`/events?status=open`, `/markets?limit=2&status=open` via page fetch); docs.kalshi.com quick_start_market_data, api_environments, get-market-candlesticks, pagination | F7 (sandbox egress), F8 (status enum active/open), F4-style dollar-volume estimate reused, labeled `est_` |
| A2 | Resolution tracking: tracked events re-polled until settled; outcome (yes/no), winning markets, settlement sources persisted to `data/resolutions.json` + `data/tracked.json` | done | 3b5e95bd | `collector/collect.py` (sweep), `data/tracked.json`, `data/resolutions.json` | docs.kalshi.com market_settlement; demo settled-market shape (`result` yes/no) verified via live capture; sweep capped 40/run, 15-min fresh-skip for rate budget | none |
| A3 | Demo-account trade/portfolio automation: signed REST (Ed25519/RSA-PSS per docs), portfolio snapshots, order placement workflow (manual dispatch, secrets only), trade categorization + strategy framework | done | 3b5e95bd | `trading/kalshi_trade.py`, `trading/strategies.py`, `trading/test_trading.py`, `.github/workflows/trade.yml`, `data/portfolio.json`, `data/trades.json` | docs.kalshi.com quick_start_authenticated_requests (header names, message format, PSS salt), api_environments (sign path rule); NO demo credentials exist in this environment — account sign-up at https://demo.kalshi.co requires human registration | F9: trading unverified against a live demo account (no credentials); published on Flagged for Review |
| A4 | Integration of A1-A3 outputs into the site + final PR/merge/Pages | done | 3b5e95bd | `data-tracking.html` (new page), nav/index touch-ups on pages owned by A1-A4 scope only, final PR | Data page renders committed `data/` snapshots (same-origin fetch, no CORS dependency); link check; PR -> main -> Pages verify | logged below in handoff |

## Handoff log

- 2026-11-20 11:22 UTC - Session 00a943bd took over site and data delivery (other sessions' claims had no artifacts; not a timeout takeover). See their log below.
- 2026-11-20 ~11:21 UTC - Session 3b5e95bd created a standalone COORDINATION.md and claimed T1-T7 before discovering this integrated board (its work began in parallel and its first push predated main's board). On discovering the conflict it discarded its own board copy in favor of this one (merge commit 5bf2bf7 kept main's version), re-registered here, and narrowed its scope to the tasks above, which no other session had claimed (no scheduled collector, no resolution tracking, no demo-account trade automation exist on main). No other session's files were modified.
- 2026-11-20 - Session 7f1ef378 claimed tasks 1–5; pushed claim (commit 2c751f3); built all root-level pages and CLI; opened PR #4; rebased onto `main` (this document) to integrate with session 00a943bd's `docs/` site.

- Session 7f1ef378 adds root-level files only: `index.html`, `dashboard.html`, `api-reference.html`, `methodology.html`, `suggestions.html`, `questions.html`, `flagged.html`, `assets/`, `scripts/kalshi_demo.py`.
- Session 00a943bd's files are NOT touched: `docs/**`, `scripts/build_site.py`, `scripts/verify_site.py`.
- Root `index.html`: session 00a943bd's version was a redirect to `docs/index.html` (Pages source workaround, R-02). Session 7f1ef378's version is a full landing page. Both are served at different paths once merged (`/` = landing page; `/docs/` = category site). Logged at merge time — neither session's `docs/` content is discarded.

## Handoff log

- 2026-11-20 11:22 UTC - Session 00a943bd took over site and data delivery (other sessions' claims had no artifacts; not a timeout takeover). See their log below.
- 2026-11-20 - Session 7f1ef378 claimed tasks 1–5; pushed claim (commit 2c751f3); built all root-level pages and CLI; opened PR #4; rebased onto `main` (this document) to integrate with session 00a943bd's `docs/` site.

## Irregularities and unverified items

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

## Final integration log

Session 00a943bd:
- PR: https://github.com/karagemop466-tech/Demo3/pull/2 (`arena/00a943bd-demo3` -> `main`). Merged immediately after this board update. Merge commit on GitHub.
- PR #1 (session 4d10aedf's claim): does not exist.
- PR #2 `arena/00a943bd-demo3` -> `main`: MERGED 2026-11-20 11:23:19 UTC (merge commit 1e53baa). Content: site, data, scripts, board.
- PR #3 `arena/00a943bd-demo3` -> `main`: MERGED 2026-11-20 11:23:47 UTC. Content: root `index.html` redirect to `docs/`, repo-review corrections.
- Pages: source `main` `/` (switch to `/docs` returned 403 for this token; admin needed to change). Build status after PR #3: `built` at commit 5c5473d. Live: https://karagemop466-tech.github.io/Demo3/ (verified via page fetch).
- Session arena/cde2ae63-demo3: PR #6 https://github.com/karagemop466-tech/Demo3/pull/6 (`arena/cde2ae63-demo3` -> `main`) MERGED 2026-11-20 (merge commit 45bde12); PR #7 merged merge commit 799d1a7 into `main`. After conflict resolution (kept session 00a943bd's integrated `docs/` site; root-level duplicate files were not brought in), PRs #6/#7 merged cleanly. Pages rebuilt after merge: status `built` at commit 45bde12, then 799d1a7. Live site verified: https://karagemop466-tech.github.io/Demo3/ serves the landing page, category pages, dashboard, resolved results, and Flagged for review.

Session 7f1ef378:
- PR #4 `arena/7f1ef378-demo3` -> `main`: https://github.com/karagemop466-tech/Demo3/pull/4 — OPEN. Content: root-level landing page, dashboard, API reference, methodology, suggestions, questions, flagged pages, Python CLI, this board. Adds root-level pages on top of session 00a943bd's `docs/` site; nothing under `docs/` is modified.
- Next: merge PR #4 (`gh pr merge 4 --merge`, no approval wait), confirm GitHub Pages rebuilds from `main`, then record the merge result and Pages status here.
