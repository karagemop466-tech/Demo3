# Coordination board

Session: `arena/fb54d2f6-demo3` (current Arena branch; platform requires all work to remain on this branch).

| Task | Status | Owner / session | File scope |
|---|---|---|---|
| Standalone dashboard integration attempt (superseded by the already merged site on `main`) | needs review | `arena/fb54d2f6-demo3` | This branch: `README.md`, `index.html`, `executive-summary.html`, `styles.css`, `app.js`, `.gitignore` |

## Coordination constraints

This checkout is fixed to branch `arena/fb54d2f6-demo3`; no other branches/worktrees may be created or switched to in this session. No other task claims existed when this board was created. The data and navigation are being treated as a single integration scope because this is the only active session and the requested deliverable is one coherent, verified site.

## Change requests (files owned by another integration session)

| Priority | Owner | File scope | Verified issue and request |
|---|---|---|---|
| High | `00a943bd` | `docs/assets/app.js`, `docs/data/verified.json`, `docs/index.html`, `docs/flagged.html` | Published dashboard is titled as demo, but `docs/assets/app.js` sets `API` to `https://external-api.kalshi.com/trade-api/v2` (production), and the snapshot metadata also records that production host. The user's requested demo base is `https://external-api.demo.kalshi.co/trade-api/v2`. Official endpoint docs state demo and production are separate environments with non-shared credentials: https://docs.kalshi.com/getting_started/api_environments. Request: switch the live monitor to demo, clearly label/exclude any production-only snapshot, add the mismatch to Flagged for review, and verify. Do not edit these owned files in this branch. Notified integration PR #3 in https://github.com/karagemop466-tech/Demo3/pull/3#issuecomment-7038340897. |

## Verification log

- Reviewed the original repository contents: only a 7-byte README existed at the branched base; no source code, tests, API client, or Pages workflow was present.
- Checked official Kalshi documentation for environment URLs, market and event schemas, orderbook response semantics, WebSocket authentication, portfolio balance/positions/fills, and demo order creation. Sources are linked in `README.md`, `executive-summary.html`, and in the applicable dashboard rows/sections.
- Implemented a static, read-only monitor. It reports official API values only after successful fetches, links each rendered market/orderbook/resolution row to the official API record, keeps absent values blank, and labels category discovery as heuristic. Dollar-volume ranking and authenticated account/trading capabilities remain explicitly unimplemented and flagged.
- Local checks passed: `node --check app.js`; `git diff --check`; parsed both HTML pages to check duplicate IDs and local links; served both pages locally and confirmed HTTP responses/title tags. Dynamic browser CORS/live demo responses remain unverified due the restricted external network available to this session; the UI surfaces failure rather than using fixtures.
- The GitHub Pages API reports this repository publishes `main` at `https://karagemop466-tech.github.io/Demo3/` using a legacy build rooted at `/`. The current `main` root redirects to `docs/index.html`; no deployment workflow was added here to avoid replacing or conflicting with that integration.
- After this branch was created, the `main` branch advanced through merged PRs #2 and #3 from session `00a943bd`, adding a comprehensive `docs/` site, source-backed dataset, verification script, and root redirect. This is overlapping work and is already the live source of truth. The working branch's root-page replacement conflicts with that redirect and is not safe to merge as-is.
- PR #1 (`https://github.com/karagemop466-tech/Demo3/pull/1`) was non-mergeable against the updated `main` and has been closed as a duplicate rather than overwriting the integrated site. No changes from this branch were merged.
- Inspected the live deployed home and dashboard. The site is present; the dashboard currently reports the public API fetch failed in its browser and falls back to a verified snapshot. This is an observed CORS/network limitation, not a confirmed failure of all users' browsers.
- The already integrated PRs #2 and #3 were merged by session `00a943bd`; Pages deployment run `44727361352` completed successfully. The deployed root redirects to `/docs/`; the live home and dashboard pages were fetched successfully. The dashboard itself reports a browser API-fetch failure and falls back to its source-linked snapshot.
- No other session claims were present when this board was first created. The initial claim commit was pushed after rebasing on `origin/main` because the new remote branch did not initially exist for a branch-specific pull. The later `main` update was detected before a forced merge; no other session's changes were discarded. The branch is `needs review` because it duplicates an already delivered integration.
