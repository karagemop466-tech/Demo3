# COORDINATION.md — shared task board

Repository: `karagemop466-tech/Demo3` · Working branch: `arena/3e08e6dc-demo3` (base `80f7c4d`, branch of `main`)
Session ID: `3e08e6dc`

## Protocol notes (read first)

- The brief asks for per-task branches named `session-<id>/<task>`. The sandbox rules for this session fix work to the single branch `arena/3e08e6dc-demo3`, so **no other branches are created**. Task scopes below are kept disjoint by directory/file instead.
- No other session has claimed any task. Before this claim the only files in the repo were `README.md`; `COORDINATION.md` did not exist and was created here.
- Every task is performed by this session. Because this session also runs the final integration step, the integration check is recorded at the bottom of this file.
- Status words: `unclaimed` · `in progress` · `done` · `needs review` · `blocked`.

## Task board

| ID | Task | Status | Owner | File scope | Notes |
|----|------|--------|-------|-----------|-------|
| T1 | Repo review, line-by-line, with source links | in progress | 3e08e6dc | `pages/repo-review.html`, `data/findings.json` (`repo_review`) | Claimed 2026-11-20 ~11:25 UTC |
| T2 | Kalshi market data: top-volume tracking, resolutions, price history, liquidity, refresh job | in progress | 3e08e6dc | `data/live/*`, `scripts/refresh_kalshi.py`, `scripts/config.json`, `.github/workflows/refresh.yml` | Claimed 2026-11-20 ~11:25 UTC |
| T3 | Dashboard site: landing page, category subpages, nav, styles | in progress | 3e08e6dc | `index.html`, `pages/markets.html`, `pages/resolutions.html`, `pages/price-history.html`, `pages/liquidity.html`, `assets/*`, `.nojekyll` | Claimed 2026-11-20 ~11:25 UTC |
| T4 | Demo-account portfolio, trade execution, trade analysis | **blocked** | 3e08e6dc | `pages/portfolio.html`, `pages/strategies.html` | Blocked: no demo API credentials are available in this sandbox. No trades were placed. |
| T5 | Suggestions section and questions / information gaps | in progress | 3e08e6dc | `pages/suggestions.html`, `pages/questions.html`, `data/findings.json` (`suggestions`, `questions`) | Claimed 2026-11-20 ~11:25 UTC |
| T6 | Flagged for Review page (irregularities, unverified items) | in progress | 3e08e6dc | `pages/flagged.html`, `pages/sources.html`, `data/findings.json` (`flagged`, `sources`) | Claimed 2026-11-20 ~11:25 UTC |
| T7 | Integration: build check, link check, data re-verification, PR, merge, Pages verification | unclaimed | 3e08e6dc | whole repo | Runs after T1–T6 |

## Activity log

- 2026-11-20 ~11:25 UTC — `3e08e6dc` claimed T1–T7 on branch `arena/3e08e6dc-demo3` and pushed this file before any other change.
