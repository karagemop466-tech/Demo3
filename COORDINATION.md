# Coordination Board — Demo3 / Kalshi Dashboard

**Session:** arena/cde2ae63-demo3 (branch `arena/cde2ae63-demo3`, based on main `80f7c4d`)
**Shared task board:** this file. Claim a task by writing your session ID and file scope, then commit and push immediately. Never start a task another session has claimed. Keep scopes non-overlapping. Make small, frequent commits; run `git pull --rebase` before every push. A claim older than 60 minutes with no commits may be taken over by another session (note the handoff in the log). When finished, record sources, verification performed, and irregularities here, then mark done.

## Ground rules
- Verify every table row against an official source (demo-api.kalshi.co / external-api.demo.kalshi.co); link the source.
- If a value cannot be confirmed from an official source, leave it blank and flag as "unverified". Never infer or fill in values.
- Work on your own branch or git worktree named `session-<id>/<task>`; edit only files in your claimed scope.
- Shared outputs (table data, index/navigation) are changed only by the final integration session.

## Tasks

| ID | Task | Status | Owner | File scope | Sources / verification | Notes |
|----|------|--------|-------|------------|------------------------|-------|
| T1 | Create COORDINATION.md task board | done | arena-session-1 | COORDINATION.md | — | Created at session start |
| T2 | Data gathering from official Kalshi demo API | done | arena-session-1 | docs/executive-summary.md | https://external-api.demo.kalshi.co/trade-api/v2/events, /markets | Gas and golf not found in sampled pages; flagged |
| T3 | Executive summary | done | arena-session-1 | index.html, docs/executive-summary.md | Kalshi trade API docs | |
| T4 | Site scaffolding | done | arena-session-1 | 14 html pages, assets/css/style.css, assets/js/app.js | — | Clean landing page, category subpages, shared nav |
| T5 | Live events tables per category | done | arena-session-1 | category pages + dashboard | https://external-api.demo.kalshi.co/trade-api/v2/events | |
| T6 | Price movement graph (time axis sec/min/hour; Y = contract price; liquidity) | done | arena-session-1 | dashboard.html (Chart.js CDN) | Kalshi markets API | Live fetch with graceful degradation |
| T7 | Portfolio performance tracking (demo account) | done | arena-session-1 | portfolio.html | Requires demo API key auth | Framework built; flagged F6 — no credentials provided |
| T8 | Trade execution + trade categorization / strategies | done | arena-session-1 | trades.html | Requires auth | Framework built; flagged F7 — no credentials provided |
| T9 | Suggestions section (review before implementing) | done | arena-session-1 | suggestions.html | — | Suggestion register, pending-review decisions |
| T10 | Questions / information / answers for decision-making | done | arena-session-1 | questions.html | — | Decision-readiness register + discovery paths |
| T11 | Flagged-for-review page (unverified items + irregularities) | done | arena-session-1 | flagged.html | official Kalshi API | F1–F8 + I1–I4 |
| T12 | Verification line-by-line; source links on every row | done | arena-session-1 | all pages | official Kalshi API | Blank/unverified where not confirmed |
| T13 | GitHub Pages: build check, no broken links, publish | in progress | arena-session-1 | GitHub Pages settings | — | Next: enable Pages, verify deploy |
| T14 | PR from this branch to main + merge + record result | pending | arena-session-1 | GitHub PR | — | Do not merge a broken site |

## Log
- 2026-11-20: Built full static site on `arena/cde2ae63-demo3`. Verified data gathered via `fetch_page` from https://external-api.demo.kalshi.co/trade-api/v2 (bash curl to kalshi.co is blocked by sandbox egress — irregularity I3). All pages committed next; then GitHub Pages enablement, PR to main, merge.

| T2 | Executive summary | unclaimed | — | docs/executive-summary.md | Kalshi trade API docs | |
| T3 | Site scaffolding + GitHub Pages config | unclaimed | — | index.html, category pages, css/, js/, _config.yml if needed | — | Clean landing page, category subpages |
| T4 | Live events dashboard: highest $ events (gas, elections, culture, crypto, golf) | unclaimed | — | dashboard.html, category pages | https://external-api.demo.kalshi.co/trade-api/v2/events | |
| T5 | Price movement graph (time axis sec/min/hour; Y = contract price; liquidity) | unclaimed | — | dashboard.html, js/chart.js | Kalshi markets API | |
| T6 | Portfolio performance tracking (demo account) | unclaimed | — | portfolio.html | Requires demo API key auth | Flag if credentials unavailable |
| T7 | Trade execution + trade categorization / strategies | unclaimed | — | trades.html | Requires auth | Flag if credentials unavailable |
| T8 | Suggestions section (review before implementing) | unclaimed | — | suggestions.html | — | |
| T9 | Questions / information / answers for decision-making | unclaimed | — | questions.html | — | |
| T10 | Flagged-for-review page (unverified items + irregularities) | unclaimed | — | flagged-for-review.html | — | |
| T11 | Verification line-by-line; source links on every row | unclaimed | — | all pages | official Kalshi API | |
| T12 | GitHub Pages: build check, no broken links, publish | unclaimed | — | GitHub Pages settings | — | Integration session |
| T13 | PR from integration branch to main + merge + record result | unclaimed | — | GitHub PR | — | Do not merge a broken site |

## Log
- 2026-11-20: Session started on `arena/cde2ae63-demo3`. Repo contains only README.md (`# Demo3`). COORDINATION.md missing — created now. Claiming T1–T13 for this session (single session).
