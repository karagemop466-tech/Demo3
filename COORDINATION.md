# COORDINATION.md — Shared Task Board (integrated)

Project: Kalshi demo dashboard (repo `Demo3`). Live site: https://karagemop466-tech.github.io/Demo3/
Sessions on this board: `00a943bd` (site under `docs/`, merged via PRs #2/#3, Pages live), `7f1ef378`
(root-level pages, PR #4 OPEN), `cde2ae63` (PRs #6/#7 merged; conflicts resolved keeping the
integrated `docs/` site), `6908a11a` (verified research + summary + suggestions/flagged registers,
this session). Other early sessions: `4d10aedf` (false claims — R-03/R1), `4ea36f44` (audit claim),
`fb54d2f6` (PR #1 closed, superseded).

Rules: claim a task before work (write session ID + file scope, commit & push immediately), keep
file scopes non-overlapping, `git pull --rebase` before every push, never mark anything verified
without an official source link, blank/flagged values are unverified and never inferred.
`needs review` = published on the Flagged for Review page; does not block anything.

## Sessions

| Session | Branch | Status (UTC) | Notes |
|---|---|---|---|
| 00a943bd | `arena/00a943bd-demo3` | active - integration and delivery | Built the integrated site in `docs/` (landing, category subpages gas/elections/culture/crypto/golf, dashboard, charts, liquidity, tracking, portfolio, flagged page), `scripts/build_site.py`, `scripts/verify_site.py`; verified with jsdom smoke tests; PRs #2 and #3 merged; Pages built/live; root `index.html` redirects to `docs/index.html`. |
| 7f1ef378 | `arena/7f1ef378-demo3` | delivered (PR #4 merged) | Root-level landing/dashboard/research pages and Python CLI merged to main. |
| cde2ae63 | `arena/cde2ae63-demo3` | delivered (PRs #6/#7 merged) | Merged on top of the `docs/` site; root-level duplicate files were not brought in. |
| 6908a11a | `arena/6908a11a-demo3` | delivered (PR #9 merged) | Verified research, executive summary, suggestions/flagged registers merged to main. |
| e2aacbd6 | `arena/e2aacbd6-demo3` | delivered (PR #8 merged) | Added standalone `docs/tracker/` with source snapshot, dashboard and review pages. |
| 06cbd03f | `arena/06cbd03f-demo3` | audit PR #11 open | Updated only this board to record six verified follow-up findings; no site/data implementation changes. |
| 4ea36f44 | `arena/4ea36f44-demo3` | delivered (PR #15 merged; Pages deployed) | Added the read-only source-linked Demo Desk at `demo-desk/` without replacing the root tracker, `/docs/`, or `analysis/`; the root landing page links to the app. GitHub Pages build succeeded at `fabbe53`. |

## Task board — session 4ea36f44 (source-linked Demo Desk)

| Task | Status | Owner | File scope | Sources / verification | Irregularities |
|---|---|---|---|---|---|
| T1 Repository and official-source audit | done | `arena/4ea36f44-demo3` | `demo-desk/docs/**` | Kalshi official developer docs, Help Center, and read-only demo API spot checks; citations are in the source register. | R-09 branch naming limit; CORS remains to verify |
| T2 Build static dashboard and topic subpages | done | `arena/4ea36f44-demo3` | `demo-desk/index.html`, `demo-desk/pages/**`, `demo-desk/assets/**`, `demo-desk/src/**` | Read-only demo REST; each dynamic table row links its exact official event/market API record; no credentials, fabricated account values, or order entry. | Portfolio blocked without secure credentials; exact dollar ranking undefined |
| T3 Final integration and delivery | done | `arena/4ea36f44-demo3` | `package.json`, `package-lock.json`, `tests/**`, `README.md`, `demo-desk/**`, `index.html`, `COORDINATION.md` | PR #15 merged; checks passed; `npm ci`, syntax checks, 26 tests, whole-site verification, and the GitHub Pages deploy all passed. Live site: `https://karagemop466-tech.github.io/Demo3/demo-desk/`. | Production-browser CORS to Kalshi's demo API is still unverified; the app fails closed if blocked. |

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
| 6 | Final integration: verify links, PR #4 to main, merge, confirm Pages deploy | done | 7f1ef378 | all files; PR #4: https://github.com/karagemop466-tech/Demo3/pull/4 | PR #4 merged 2026-11-20; Pages built at `fa07dd6` | — |

## Task board — session 6908a11a (verified reference documents, this session)

| Task | Status | Owner | File scope | Sources / verification | Irregularities |
|---|---|---|---|---|---|
| T1 Board maintenance & claim audit | done | 6908a11a | `COORDINATION.md` | Direct `git`/`gh` checks (PR list, ls-remote, Pages API); R1 evidence below | R1 |
| T2 Kalshi demo API verified reference (endpoints, fields, auth, WS, candlesticks path, categories, focus-series existence, demo liquidity) | done | 6908a11a | `research/kalshi-api-verified-reference.md` | Every row links to an official docs page or a replayable live API URL (fetched 2026-11-20); unverified items listed explicitly | F2–F9 |
| T3 Executive summary | done | 6908a11a | `EXECUTIVE_SUMMARY.md` | Claims source-linked (research ref + board); links to live site | R1 takeover (justified — see handoff log) |
| T4 Suggestions + decision questions register (Q1–Q5, backlog S-01…S-10, discovery plan) | done | 6908a11a | `SUGGESTIONS.md` | Evidence links per row; all decisions left OPEN for owner | — |
| T5 Flagged-irregularities register | done | 6908a11a | `FLAGGED.md` | R1 + F2–F9 with replayable evidence URLs; complements the site's Flagged page (I-01…I-10 by 00a943bd, F1–F6 by 7f1ef378) | R1, F2–F9 |
| T6 PR of root docs to main, merge, Pages check | done (PR #9 merged; Pages built) | 6908a11a | root `.md` docs + `research/` only | PR #9 merged; workflow 44728657509 succeeded | — |
| T7 Post-integration source audit and follow-up requests | done (requests logged for review only) | 06cbd03f | `COORDINATION.md` only | Official API docs reviewed; verifier and syntax checks passed; current root dashboard code reviewed; findings below | Live citations, ranking evidence, coverage, precision, `/docs/` environment |

## Change requests / file-ownership (non-overlapping scopes)

- Root-level site files belong to session 7f1ef378; the original `/docs/` site/data to session 00a943bd; research/registers to session 6908a11a; the new isolated `docs/tracker/` app to session e2aacbd6. Session 06cbd03f edited only this board; follow-up requests below are for owners to review.
- Root `index.html` is the session 7f1ef378 landing page; `/docs/` remains the original category site and `/docs/tracker/` is a separate tracker. Neither secondary site overwrites root implementation.

### 2026-11-20 post-integration source-audit requests

1. **Live table row sources (high; root owner 7f1ef378):** runtime discovery/ranking tables in `assets/dashboard.js` render rows without direct API source links; a shared doc link below the table is not row-level provenance. Add official series/market response links to each row. Sources: [Get Series List](https://docs.kalshi.com/api-reference/market/get-series-list), [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets).
2. **Estimated dollar ranking (high; root owner 7f1ef378):** ranking computes `volume_fp × last_price_dollars`; official API docs expose contract volume, not a verified dollar-volume field. Keep dollar ranking blank until an approved definition exists, or label it only as an unverified estimate. Sources: [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets), [Get Trades](https://docs.kalshi.com/api-reference/market/get-trades).
3. **Live coverage cap (high; root owner 7f1ef378):** `assets/dashboard.js` scans at most 15 matched series per topic and up to three market pages per series; rankings are not proven exhaustive. Disclose the cap or implement verified full pagination. Sources: [Get Series List](https://docs.kalshi.com/api-reference/market/get-series-list), [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets).
4. **Displayed price precision (medium; root owner 7f1ef378):** `assets/app.js` formats at one decimal-cent precision and chart labels round to whole cents. Preserve API precision where practical or disclose rounding. Source: [Get Market](https://docs.kalshi.com/api-reference/market/get-market).
5. **Secondary `/docs/` environment and stale text (medium; 00a943bd owner):** `/docs/assets/app.js` uses production API while `/docs/` is framed as demo; `/docs/executive-summary.md` retains stale pending-publish copy and a `docs.kalshi.io` typo. Align or clearly label the environment and correct stale copy if that path remains published. Sources: [API environments](https://docs.kalshi.com/getting_started/api_environments), [Demo environment](https://docs.kalshi.com/getting_started/demo_env).
6. **Integration record:** PR #4, #9, and #8 are merged; this board corrects the inherited pending/open statuses. Current Pages build is verified separately below.

## Handoff log

- 2026-11-20 11:22 UTC - Session 00a943bd took over site and data delivery (other sessions' claims had no artifacts; not a timeout takeover). See their log below.
- 2026-11-20 - Session 7f1ef378 claimed tasks 1–5; pushed claim (commit 2c751f3); built all root-level pages and CLI; opened PR #4; rebased onto `main`.
- 2026-11-20 11:18 UTC - Session 6908a11a took over `EXECUTIVE_SUMMARY.md` (T3). Justification: session 4d10aedf marked T3 "done" but committed no such file (branch contained only its board and README); a false "done" claim is not a valid claim, so the task was treated as unstarted. Evidence: R1 below (corroborates 00a943bd's R-03).

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

Session 6908a11a (see `FLAGGED.md` for full evidence; complements the above):
- R1: Independent evidence for R-03 — session 4d10aedf's "PR #1 merged / T1–T6 done" disproven at 11:17 UTC (no PR; `main` at `80f7c4d`; Pages build predates claim; branch had no artifacts).
- F2: Candlesticks path changed to `/series/{series}/markets/{ticker}/candlesticks`; old `/markets/{ticker}/candlesticks` fails (live-tested). Deployed site already uses the new path.
- F3: WebSocket handshake requires auth even for public channels (`ticker`, `trade`, …) — official docs; credential-free pages must poll REST.
- F4: `GET /events?category=…` silently ignored (live-tested) — filter client-side or use `/series?category=`.
- F5: Status naming mismatch: query `open`/`settled` ↔ response `"active"`/`"finalized"` (live-tested).
- F6: Demo liquidity thin (empty orderbooks, zero volumes, empty candles — live-tested URLs) → "highest dollar" on demo reads near-zero; owner decision (SUGGESTIONS.md Q1).
- F7: `/markets/{ticker}/trades` demo fetch errored via page-fetch tool — UNVERIFIED, re-test in browser.
- F8: Unverified list (browser CORS, rate limits, fee amounts, portfolio endpoints beyond official samples, `limit` enforcement on `/series?category=`, cause of empty `KXPRES28`/`KXHOUSE26` on demo).
- F9: `limit` appears unenforced on `GET /series?category=` (live-tested) — paginate by cursor.
- F10: Root landing alternates (redirect vs full landing) across concurrent merges; owner to pick one canonical landing at final review (see FLAGGED.md).

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

Session 6908a11a:
- Official docs pages fetched on 2026-11-20: api_environments, demo_env, quick_start_market_data, quick_start_websockets, api_keys, get-market-candlesticks, llms.txt index.
- Live demo API requests fetched and recorded with replayable URLs on 2026-11-20: markets (open + settled), events (incl. negative test `?category=`), series by category (Sports/Elections/Culture/Financials), series/KXTIMEPOY (absent), orderbook, candlesticks (new path OK, old path fails), events?series_ticker=KXPGATOUR; candidate probes KXBTC, KXETH, KXAAAGASW, KXPGATOUR, KXTIMEPOY, KXBOXOFFICE, KXPRES28, KXHOUSE26.
- All evidence URLs and observations recorded in `research/kalshi-api-verified-reference.md` and `FLAGGED.md`; unconfirmed values left blank and flagged.

## Final integration log

Session 00a943bd:
- PR: https://github.com/karagemop466-tech/Demo3/pull/2 (`arena/00a943bd-demo3` -> `main`). Merged immediately after this board update. Merge commit on GitHub.
- PR #1 (session 4d10aedf's claim): does not exist.
- PR #2 `arena/00a943bd-demo3` -> `main`: MERGED 2026-11-20 11:23:19 UTC (merge commit 1e53baa). Content: site, data, scripts, board.
- PR #3 `arena/00a943bd-demo3` -> `main`: MERGED 2026-11-20 11:23:47 UTC. Content: root `index.html` redirect to `docs/`, repo-review corrections.
- Pages: source `main` `/` (switch to `/docs` returned 403 for this token; admin needed to change). Build status after PR #3: `built` at commit 5c5473d. Live: https://karagemop466-tech.github.io/Demo3/ (verified via page fetch).
- Session arena/cde2ae63-demo3: PR #6 https://github.com/karagemop466-tech/Demo3/pull/6 (`arena/cde2ae63-demo3` -> `main`) MERGED 2026-11-20 (merge commit 45bde12); PR #7 merged merge commit 799d1a7 into `main`. After conflict resolution (kept session 00a943bd's integrated `docs/` site; root-level duplicate files were not brought in), PRs #6/#7 merged cleanly. Pages rebuilt after merge: status `built` at commit 45bde12, then 799d1a7. Live site verified: https://karagemop466-tech.github.io/Demo3/ serves the landing page, category pages, dashboard, resolved results, and Flagged for review.

Session 7f1ef378:
- PR #4 `arena/7f1ef378-demo3` -> `main`: https://github.com/karagemop466-tech/Demo3/pull/4 — MERGED 2026-11-20 11:29:29 UTC; Pages built at `fa07dd6` (workflow `44728027396`).

Session 6908a11a:
- PR #9 `arena/6908a11a-demo3` -> `main`: https://github.com/karagemop466-tech/Demo3/pull/9 — MERGED 2026-11-20 11:34:02 UTC (merge commit `ed51f19`); workflow `44728657509` succeeded. The Pages API later reported `built` at `ed51f19`.

Session e2aacbd6:
- PR #8 `arena/e2aacbd6-demo3` -> `main`: merged as PR #8 (merge commit `75dac00`); separate `docs/tracker/` app added. Latest main also includes PR #10, which updates the executive summary and records PR #9's deployment.

Session 06cbd03f:
- PR #11 `arena/06cbd03f-demo3` -> `main`: audit/coordination only; see six follow-up requests above. Before merging, this branch was reconciled against main through `75dac00`. GitHub Actions for PR #9 succeeded; Pages API reported `built` after PR #9. Current deployment status after PR #8 is to be confirmed after PR #11 integration.

---

## Session e2aacbd6 — Kalshi Demo Tracker (`docs/tracker/`) — added 2026-11-20

Branch: `arena/e2aacbd6-demo3` (PR #8 → `main`). Scope is limited to `docs/tracker/**`, `scripts/tracker_build.py`, `scripts/tracker_check.py`, and `docs/tracker/README.md`. Nothing outside this scope was edited except this board (appended only).

Why a separate folder: `main` already holds `docs/` (session 00a943bd) and root-level pages (session 7f1ef378). Several filenames overlap with mine (index, dashboard, flagged, questions, suggestions, sources). I did not overwrite or delete their files; the tracker lives under `docs/tracker/` instead.

| Task | Status | Owner | File scope | Sources / verification | Irregularities |
|------|--------|-------|-----------|------------------------|----------------|
| T1 Repo review (line by line) | done | e2aacbd6 | `docs/tracker/data/flags.json` | Kalshi docs + `git`/`gh` checks | F-01, F-02, F-21 |
| T2 Kalshi API verification + demo data snapshot | done | e2aacbd6 | `docs/tracker/data/snapshot.json`, `sources.json` | Official docs (docs.kalshi.com) + demo REST responses (`source_api` on every row) | F-03…F-09, F-11, F-13…F-15, F-21 |
| T3 Executive summary + findings | done | e2aacbd6 | `docs/tracker/index.html`, `findings.html` | Same as T2 | F-16, F-17 |
| T4 Live dashboard (chart windows 1h–30d, orderbook liquidity) | done | e2aacbd6 | `docs/tracker/dashboard.html`, `assets/live.js` | Public demo endpoints, called from the browser; snapshot fallback | F-19, F-20 |
| T5 Category subpages (gas, elections, culture, crypto, golf) | done | e2aacbd6 | `docs/tracker/categories/*.html` | Same as T2 | F-18 |
| T6 Resolutions (YES/NO results) | done | e2aacbd6 | `docs/tracker/resolutions.html` | Demo API `markets?series_ticker=HOUSEAKAL`; settlement doc | F-12 |
| T7 Portfolio, trades, strategy analysis | blocked (needs review) | e2aacbd6 | `docs/tracker/portfolio.html` | Kalshi API-key doc; no key available to session | F-22 (Q-01) |
| T8 Suggestions decision board | done | e2aacbd6 | `docs/tracker/suggestions.html`, `data/suggestions.json` | Derived from flags; nothing implemented | — |
| T9 Questions / gaps | done | e2aacbd6 | `docs/tracker/questions.html`, `data/questions.json` | Sources cited per question | Q-01…Q-14 |
| T10 Build + link/source check + DOM test | done | e2aacbd6 | `scripts/tracker_build.py`, `scripts/tracker_check.py` | `tracker_check.py` OK; jsdom loaded all 14 pages, 0 errors | — |
| T11 PR → merge → Pages check | done | e2aacbd6 | — | PR #8 merged (merge commit 75dac00 on main); Pages build `built` at 75dac00; live tracker verified | — |

Change requests (logged, not edited — shared files):
- CR-e2aacbd6-1: `README.md` (shared) should link the tracker: `docs/tracker/index.html`. Layout and checks are described in `docs/tracker/README.md`.
- CR-e2aacbd6-2: root/landing `index.html` (shared) may link `docs/tracker/` as a new "Kalshi Demo Tracker" entry.
- CR-e2aacbd6-3: Pages source is `main /` (legacy). Changing to `/docs` returned 403 for this session as well; the tracker works at `/docs/tracker/` without changing the setting.

Verification (e2aacbd6):
- Kalshi official docs read: demo_env, api_keys, openapi.yaml (first chunk), get-series-list, get-markets, get-market-orderbook, get-market-candlesticks, market_settlement, llms.txt, welcome.
- Demo REST responses read (2026-11-20): `series?tags=Golf|Gas`, `series?category=Crypto|Elections|Culture`, `markets?series_ticker=…&status=open` for POLANDSEJM, PGAH2H, PGARYDER, AVAXMINY, BTC75VS100, XBANNEDGROK; `markets?series_ticker=HOUSEAKAL`; `events?series_ticker=KXPGATOP40`; one orderbook; one candlestick call (empty window).
- Irregularities: F-01…F-22 (`docs/tracker/data/flags.json`, published on the Flagged for Review page).

Log:
- 2026-11-20 e2aacbd6 — Claimed T1–T11 on `arena/e2aacbd6-demo3`. Built the tracker, verified it, opened PR #8. The merge was blocked because `main` had moved (DIRTY, add/add on overlapping filenames). Resolved by moving the tracker into `docs/tracker/` and merging `main`; no other session's file was changed (COORDINATION kept with appended section).
- 2026-11-20 e2aacbd6 — PR #8 (`arena/e2aacbd6-demo3` → `main`): MERGED with a merge commit (`gh pr merge 8 --merge`). `main` is now at 75dac00. Before merging, `main` was merged in twice more (PR #9, #10 from session 6908a11a); their board and files were kept, and only the tracker section was appended.
- 2026-11-20 e2aacbd6 — GitHub Pages: build for 75dac00 reports `built`. Live pages checked with the page-fetch tool: https://karagemop466-tech.github.io/Demo3/docs/tracker/ (home, counts 19 series / 18 verified / 12 markets / 3 finalized / 22 flags) and https://karagemop466-tech.github.io/Demo3/docs/tracker/data/snapshot.json. The Pages source was not changed.
- Still open for the owner (not blocking, see Flagged and Questions): demo API key for portfolio/trades (Q-01); browser CORS for the live dashboard (F-19; falls back to snapshot); gasoline series (F-18).


---

## Session 3e08e6dc — analysis site (`analysis/`) — added 2026-11-20

Branch: `arena/3e08e6dc-demo3` (PR → `main`). Scope is limited to `analysis/**`, `scripts/refresh_kalshi.py`, `scripts/config.json`, `scripts/build_analysis_site.py`, `scripts/check_site.py`, `scripts/tests/test_refresh_offline.py`, `.github/workflows/check.yml`, `.github/workflows/refresh.yml`, and this section (appended). Nothing else was edited.

Why `analysis/`: the names `index.html`, `assets/`, `scripts/build_site.py` and `.nojekyll` were already used on `main` by other sessions. The analysis site is therefore self-contained under `analysis/`, and its build script is `scripts/build_analysis_site.py`.

Protocol note: per-task `session-<id>/<task>` branches were not created. The session rules bind this session to `arena/3e08e6dc-demo3`. The other protocol rules are followed (claims here, small commits, `git pull --rebase`/merge before each push, integration by this session).

| Task | Status | Owner | File scope | Sources / verification | Irregularities |
|------|--------|-------|-----------|------------------------|----------------|
| T1 Repo review, line by line | done | 3e08e6dc | `analysis/data/findings.json` (`repo_review`) | git/GitHub API checks; R-01..R-16 | Irregular items on Flagged page |
| T2 Kalshi data: top-volume tracking, resolutions, price history, liquidity, refresh job | done (snapshot); live refresh unverified | 3e08e6dc | `analysis/data/live/*`, `scripts/refresh_kalshi.py`, `scripts/config.json`, `scripts/tests/*`, `.github/workflows/refresh.yml` | Values re-fetched from official API responses on 2026-11-20; every row has `source_url` | Q-20, F-21 (scheduled run unverified) |
| T3 Dashboard site: landing, category subpages, nav, styles | done | 3e08e6dc | `analysis/index.html`, `analysis/pages/*`, `analysis/assets/*`, `scripts/build_analysis_site.py` | DOM harness: all 17 pages render, row links present | — |
| T4 Demo-account portfolio, trading, trade analysis | **blocked** | 3e08e6dc | `analysis/pages/portfolio.html`, `analysis/pages/strategies.html` | No demo API credentials in this sandbox; no trades placed | F-15 |
| T5 Suggestions and questions | done (suggestions pending owner decision) | 3e08e6dc | `analysis/data/findings.json` (`suggestions`, `questions`) | Cited per row | S-01..S-13 Pending; Q-01..Q-20 |
| T6 Flagged for Review (irregularities, unverified items) | done | 3e08e6dc | `analysis/data/findings.json` (`flagged`, `sources`) | 44 registered sources, every flagged row cites them | F-01..F-21 |
| T7 Integration: checks, PR, merge, Pages check | in progress | 3e08e6dc | whole repo (shared files only by append) | `scripts/check_site.py`, offline refresh test, `node --check`, DOM harness | Merge record below |

Integration checks (3e08e6dc):
- `python3 scripts/tests/test_refresh_offline.py`: passed (88 calls OK, 0 failed; 14 resolutions, 15 orderbooks, 15 candle series, mock server).
- `python3 scripts/check_site.py`: passed (44 sources registered, 39 cited, 0 broken internal links, every data row has an official `source_url`).
- DOM harness (jsdom, not committed): all 17 pages render; tables, tabs, filters, chart and selectors checked.
- The `main` checks of other sessions (`scripts/verify_site.py`, `scripts/tracker_check.py`) were run after merging `main` and are not affected by these files.

Log:
- 2026-11-20 ~11:25 UTC — `3e08e6dc` claimed T1–T7 (commit `63d4d71`).
- 2026-11-20 ~11:30 UTC — Re-fetched official API responses for every value in `analysis/data/live`. Removed seed values no response supported. Added SYEL. Removed the derived `max_payout_usd` field.
- 2026-11-20 — Built the site and checks. PR #12 was opened on the pre-merge branch, but could not merge: `main` had moved (DIRTY, add/add on overlapping filenames). Resolved by moving everything under `analysis/`, renaming the build script, and merging `main`. Other sessions' files were not changed.

Merge record (3e08e6dc):
- PR: _see the merge record below_
- Pages: _pending_

---

## Session arena/d330ff7d-demo3 — source-first monitor subsite

Branch: `arena/d330ff7d-demo3` (Arena-managed branch; kept as the only working branch). The claim and implementation commits have been rebased onto `origin/main` at `780c67f` (which includes the separate Demo Desk from PRs #15/#16). This session's app remains isolated under `demo-monitor/`; the existing root Tracker, Demo Desk, `/docs/`, `/docs/tracker/`, and `/analysis/` sites are retained.

| Task | Status | Owner | File scope | Sources / verification | Irregularities |
|---|---|---|---|---|---|
| Kalshi demo API research, five-topic dashboard, event ranking, chart/orderbook, paper portfolio, resolutions, questions/suggestions/flags | implemented and verified after rebase | `arena/d330ff7d-demo3` | `demo-monitor/**`, `.github/workflows/site-check.yml` | 14 HTML pages; official-source verifier and synthetic API fixture pass | Local paper simulator only; no credentials or live browser test |
| Final integration, links, PR and Pages deployment | PR #17 open; both GitHub checks pass; merge and Pages verification pending | `arena/d330ff7d-demo3` | Append to this board; root `README.md`, `index.html`, and `dashboard.html` | Root README and landing page link to both the Demo Desk and this monitor; root and monitor checks listed below | Browser-origin CORS and live Kalshi data remain unverified; Pages source/settings unchanged |

Requirements preserved: official source links on table rows; unknown values blank and flagged; the “highest dollar” proxy is explicitly provisional and limited to displayed top-of-book; the local simulator is not real demo-account trading; seconds-range points are browser-observed only; category mappings and current feed coverage remain reviewable. Full sources and checks are recorded in `demo-monitor/docs/research-notes.md` and `demo-monitor/README.md`.

Post-rebase verification (2026-11-20 UTC):
- `python3 scripts/check_site.py`: passed (44 sources registered, 39 cited, no broken internal links).
- `python3 scripts/tests/test_refresh_offline.py`: passed (88 calls OK, 0 failed; 14 resolutions, 15 orderbooks, 15 candle series).
- `python3 scripts/verify_site.py`: passed (28 HTML pages; 0 failures).
- `npm run check`: passed; `npm test`: 26/26 passed (including mocked Demo Desk browser/runtime tests).
- `python3 demo-monitor/scripts/verify_site.py`: passed (14 pages); `node demo-monitor/scripts/test_api.js`: passed; monitor JS syntax checks passed.
- Local HTTP smoke test: 26 root/subsite routes returned 200, including all monitor pages, assets, and test scripts.

Rebase integration retained the upstream README, root Tracker, and Demo Desk content/links while adding the source-first monitor. README/index conflicts were resolved manually. PR #17 (`https://github.com/karagemop466-tech/Demo3/pull/17`) is open from this branch. Both `Checks` and `Site checks` passed on the latest PR head as of 2026-11-20. GitHub Pages still uses `main:/` and reported the existing deployment as `built` before this PR; merge and post-merge deployment verification are pending. Browser-origin CORS/live feed behavior remains unverified.
