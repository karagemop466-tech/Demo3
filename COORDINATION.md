# COORDINATION.md — Shared Task Board

> Multi-session task board for `karagemop466-tech/Demo3` (Kalshi demo dashboard project).
> Protocol: claim a task here (session id + file scope) and commit/push the claim before
> starting. Never edit files outside your claimed scope. Log requests for out-of-scope
> changes here instead. Mark items `done` only after recording sources + verification.

## Sessions

| Session ID | Branch | Status | Notes |
|---|---|---|---|
| session-e2160792 | `arena/e2160792-demo3` | active | Arena-managed branch name (platform fixes branch names; this session works only on this branch). Also serving as final integration session. |

Branch-naming note: the platform pins this session to `arena/e2160792-demo3` and does not
allow creating `session-<id>/<task>` branches. All work therefore happens on this one
branch with non-overlapping file scopes claimed below. If other sessions appear, keep
scopes disjoint and coordinate here.

## Task board

| # | Task | Status | Owner | File scope | Sources / verification | Irregularities |
|---|---|---|---|---|---|---|
| 1 | Repo review (line-by-line) | done | session-e2160792 | `README.md`, `docs/repo-review.html` | Repo contains only `README.md` (7 bytes: `# Demo3`); reviewed 2026-11-20. See docs/repo-review.html | README lacks description, license, topics — flagged |
| 2 | API research + verification (endpoints, auth, taxonomy) | done | session-e2160792 | `docs/data/*.json`, `docs/verification.html` | docs.kalshi.com (llms.txt index, api_environments.md, api_keys.md, demo_env.md, create-order-v2.md, fixed_point_migration.md, quick_start_websockets.md) + live demo API calls on 2026-11-20 (external-api.demo.kalshi.co) | `/series` ignores `limit`, `title`, `tag` filters (returns full list); `/events` ignores `category` filter. Both accepted silently (no 4xx). See flagged.html |
| 3 | Executive summary | done | session-e2160792 | `EXECUTIVE_SUMMARY.md`, `docs/index.html` | Built from verified rows in docs/data/snapshots + docs links | Demo prices "may not be reflective of real markets" per official demo docs |
| 4 | Live events dashboard (gas, elections, culture, crypto, golf) + resolution tracking | done | session-e2160792 | `docs/live-events.html`, `docs/js/live.js` | Runtime fetch of demo API (public, unauthenticated); series taxonomy verified live (see docs/verification.html rows) | Ranking basis labeled: dollar volume derived = volume_fp × notional_value_dollars (raw fields shown) |
| 5 | Price charts + liquidity depth | done | session-e2160792 | `docs/charts.html`, `docs/js/charts.js`, `docs/js/vendor/` | Candlesticks (1/60/1440 min) per docs.kalshi.com/api-reference/market/get-market-candlesticks.md; seconds-granularity = client-side live sampling (labeled) | Browsers cannot attach auth headers to WebSocket → WS feed unusable from static pages; REST polling used instead (flagged) |
| 6 | Portfolio + trade execution (demo account) | done | session-e2160792 | `docs/portfolio.html`, `docs/js/trading.js` | POST /portfolio/events/orders (Create Order V2) + auth signing per docs.kalshi.com/getting_started/api_keys.md | REQUIRES demo-account API credentials (key id + private key) entered in-browser; none were provided to this session → portfolio tables blank/unverified until connected (flagged) |
| 7 | Trade analysis, categorization, strategies | done | session-e2160792 | `docs/analysis.html` | Strategy templates derived from market-structure facts (verified in docs/data/api-surface.json); results fill in at runtime once account connected | No trade history available without credentials → analysis shows framework + empty verified tables |
| 8 | Suggestions board + open questions | done | session-e2160792 | `docs/suggestions.html`, `docs/questions.html` | Each suggestion/question cites its evidence source (doc link or API probe) | — |
| 9 | GitHub Pages site + landing/subpages | done | session-e2160792 | `docs/**` | Static site; links verified 2026-11-20 (all internal hrefs resolve to files in docs/) | — |
| 10 | Final integration: re-verify combined data, build check, PR, merge, Pages deploy | done | session-e2160792 | `COORDINATION.md`, repo root | Re-verification log in docs/verification.html; link check via tools/linkcheck (internal links pass); PR #1 merged to main; Pages enabled via GitHub API (docs/ from main) | See "Integration log" below for PR + deploy record |

Status vocabulary: `unclaimed` · `in progress` · `done` · `needs review`
(needs-review items are published on the site's Flagged for Review page and never block).

## Change requests (out-of-scope edits)

_None yet. If a task requires a file owned by another session, log the request here._

## Handoff log

- 2026-11-20 session-e2160792: board created; tasks 1–10 claimed in one scope pass (only session active; scopes partitioned by file).

## Sources register (top-level)

| Source | What it verifies | URL | Checked |
|---|---|---|---|
| Kalshi docs — API Environments | Demo/prod REST + WS base URLs (incl. user-supplied demo URLs) | https://docs.kalshi.com/getting_started/api_environments.md | 2026-11-20 |
| Kalshi docs — Demo environment | Demo account + mock funds, endpoint table | https://docs.kalshi.com/getting_started/demo_env.md | 2026-11-20 |
| Kalshi docs — API Keys | Auth headers, Ed25519/RSA-PSS signing, ±30s timestamp | https://docs.kalshi.com/getting_started/api_keys.md | 2026-11-20 |
| Kalshi docs — Create Order (V2) | POST /portfolio/events/orders schema | https://docs.kalshi.com/api-reference/orders/create-order-v2.md | 2026-11-20 |
| Kalshi docs — Fixed-point | `_dollars`/`_fp` units, price_ranges grid | https://docs.kalshi.com/getting_started/fixed_point_migration.md | 2026-11-20 |
| Kalshi docs — WebSockets | Channels, subscribe format, WS auth requirement | https://docs.kalshi.com/getting_started/quick_start_websockets.md | 2026-11-20 |
| Kalshi docs — Market Data quick start | Orderbook shape (orderbook_fp.yes_dollars) | https://docs.kalshi.com/getting_started/quick_start_market_data | 2026-11-20 |
| Kalshi demo Trade API (live probes) | Series/events/markets fields, categories, tickers | https://external-api.demo.kalshi.co/trade-api/v2 | 2026-11-20 |

## Integration log

- 2026-11-20 session-e2160792: All tasks 1–10 complete on `arena/e2160792-demo3`.
  - Verification re-pass: every data row on the site carries `source` link + `verified_at`;
    unconfirmed values left blank and listed on Flagged for Review.
  - Internal link check: PASS (all hrefs in docs/*.html resolve).
  - PR: https://github.com/karagemop466-tech/Demo3/pull/1 (branch → main), merged with `--merge`.
  - GitHub Pages: enabled via API, source `main` `/docs`; deployment `pages-build-deployment`
    status recorded in docs/verification.html (site URL: https://karagemop466-tech.github.io/Demo3/).
