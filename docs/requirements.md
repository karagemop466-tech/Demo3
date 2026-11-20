# Requirements Register — Kalshi Demo Project

Full list of requirements as stated in the brief, decomposed into testable items. Each row states what was
**built**, what was **verified**, and what remains **open**. "Verified" means against an official Kalshi
source (docs page or live demo API response), linked. No requirement is marked done on assumption.

Legend — **Status**: `done` · `in progress` · `blocked` · `needs review` (published on Flagged for Review, non-blocking)
Legend — **Feasibility**: `full` · `partial` (honest degraded implementation) · `blocked`

| # | Requirement (from brief) | Sub-requirement | Status | Feasibility | Where it lives | Verification / evidence |
|---|---|---|---|---|---|---|
| R1 | Collect, organise, analyse using a full list of requirements | Complete requirements inventory | done | full | this file | derived line-by-line from the brief text |
| R2 | Use the demo REST endpoint `https://external-api.demo.kalshi.co/trade-api/v2` | Reachability + correct base URL | done | full | `scripts/kalshi_api.py`, `site/assets/kalshi.js` | live 200s from 10 demo endpoints archived in `data/snapshot.json`; base URL matches [api_environments](https://docs.kalshi.com/getting_started/api_environments.md) |
| R3 | Also support `https://demo-api.kalshi.co/trade-api/v2` | Secondary host usable | in progress | full | `scripts/kalshi_api.py --base` | documented as "also supported"; not separately exercised → see Q-11 |
| R4 | WebSocket API at `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | Consume live stream | blocked | partial | `scripts/dev_server.py` (bridge), documented in `docs/api-surface.md` §4 | [quick_start_websockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md): handshake **requires** signed headers; browser WS cannot set headers |
| R5 | Executive summary of important details | — | done | full | `docs/executive-summary.md`, `site/` Summary page | 11 headline conclusions, each linked to a docs page or a live response |
| R6 | Dashboard tracking **highest dollar amount live events** | Define "dollar amount" | needs review | full | `site/dashboard/`, `scripts/collect.py` | **No dollar-volume field exists** on market/event/series; only `volume_fp` (contracts). Definition adopted: `Σ count_fp × taker_price` over `/markets/trades`. See Q-01 |
| R6a | ↳ rank live events by that metric | leaderboard | done | full | dashboard leaderboard (live) + `data/snapshot.json` (raw tape) | `/markets/trades?limit=120` observed live; `limit` 1–1000 per [get-trades](https://docs.kalshi.com/api-reference/market/get-trades.md) |
| R6b | ↳ restrict to *live* events | status semantics | done | full | `scripts/collect.py` | `status=open` filter per [get-markets](https://docs.kalshi.com/api-reference/market/get-markets.md); note object returns `"active"` (FLAG-02) |
| R7 | Focus on topics: gas prices, elections, culture, crypto, golf | map topics → official taxonomy | needs review | partial | `data/snapshot.json` `topic_mapping`, `site/topics/` | `/search/tags_by_categories` live read. **No `Culture` category exists**; mapped to `Entertainment`. "Gas prices" mapped to `Commodities/Oil & Gas` + `Economics/Oil and energy` — no pump-price category was found in the taxonomy. See Q-02 |
| R8 | Track live events **until they resolve** | detect close → settlement | done | full | `site/events/`, `scripts/collect.py --watch` | fields `close_time`, `status`, `result`, `settlement_ts`, `settlement_value_dollars` observed live on a settled market |
| R9 | Record **how** it resolved: yes or no | capture outcome | done | full | `data/resolutions.json` (written by collector), site Events page | settled sample returned `result:"no"`, `status:"finalized"`, `settlement_value_dollars:"0.0000"`; payout rule per [market_settlement](https://docs.kalshi.com/getting_started/market_settlement.md) |
| R10 | Track portfolio performance using the **Kalshi demo account** | read balance/positions | **blocked** | blocked | `scripts/portfolio.py` | requires a demo API key created by a human at [demo.kalshi.co](https://demo.kalshi.co/) — [demo_env](https://docs.kalshi.com/getting_started/demo_env.md). Brief forbids asking the user; therefore shipped credential-ready and unexecuted. See B1 in `COORDINATION.md` |
| R10a | ↳ portfolio value over time | time series | needs review | partial | `site/portfolio/` | `GET /portfolio/balance` is rate-limited to 1/s on Basic/Advanced tiers → time series must be sampled by our own poller, not replayed from the API. [rate_limits](https://docs.kalshi.com/getting_started/rate_limits.md) |
| R11 | Analyse results of trades | per-trade P&L, fees, edge | done (paper) / blocked (live) | partial | `scripts/analyze.py`, `site/portfolio/` | analysis engine runs on the fills ledger; ledger is empty until credentials exist. Unit-verified on synthetic ledger, labelled synthetic |
| R12 | Categorise trades | taxonomy of trade types | done | full | `scripts/analyze.py` | categories defined from **official** response fields only: side (`taker_outcome_side`), liquidity (`taker_book_side`), size bucket, price bucket, topic, time-to-expiry bucket, block flag. No invented labels |
| R13 | Create strategies based on the type of trade | rule set + evaluation | needs review | full | `site/strategies/`, `scripts/analyze.py` | strategies are *descriptions of rules evaluated against the ledger*, each with the metric that would confirm/refute it. Not backtested on real history (no historical access without a key + cutoff) — see Q-05 |
| R14 | **Execute trades** on events | submit order | **blocked** | partial | `scripts/trade_engine.py` | `POST /portfolio/events/orders` per [create-order-v2](https://docs.kalshi.com/api-reference/orders/create-order-v2.md); no key ⇒ not executed. Engine dry-runs by default and refuses to send without `KALSHI_API_KEY_ID` + private key |
| R14a | ↳ track performance of executed trades | order→fill→settlement join | done (design) | partial | `scripts/portfolio.py`, `scripts/analyze.py` | join keys are documented API fields: `order_id`, `client_order_id`, `trade_id`, `ticker` |
| R15 | Live interactive dashboard | polling + deltas | done | full | `site/dashboard/` | REST cache lag documented in [get-markets](https://docs.kalshi.com/api-reference/market/get-markets.md); UI surfaces per-row `updated_time` + a staleness badge |
| R16 | Price-movement graph, X = time | axis controls | done | full | `site/assets/chart.js` | custom canvas renderer, no CDN (Pages-safe) |
| R16a | ↳ selectable **seconds** | sub-minute resolution | needs review | **partial** | dashboard "Live ticks" mode | candlestick API minimum period = **1 minute** ([get-market-candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md)). Seconds data therefore comes from client-side sampling of `/markets/{ticker}` + `/markets/trades`, labelled "client-sampled, not exchange history". See Q-03 |
| R16b | ↳ minutes | — | done | full | dashboard | `period_interval=1` |
| R16c | ↳ hours | — | done | full | dashboard | `period_interval=60` (and `1440` for days) |
| R16d | Y = current contract price | — | done | full | dashboard | Y plots `last_price_dollars` / candle `price.close_dollars`; range 0–1 against `notional_value_dollars="1.0000"` |
| R17 | Show current liquidity: **how many contracts at a given price** | depth ladder | done | full | dashboard depth panel | `orderbook_fp.yes_dollars/no_dollars` `[price,count]`, bids-only; implied ask = $1.00 − best NO bid ([orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses.md)) |
| R17a | ↳ distinguish "empty book" from "bad ticker" | — | needs review | full | `scripts/kalshi_api.py` | orderbook returns 200 + empty arrays for an unknown ticker, so the client also calls `GET /markets/{ticker}`. [get-market](https://docs.kalshi.com/api-reference/market/get-market.md) |
| R18 | Suggestions to improve decision-making | — | done | full | `site/suggestions/` | 14 suggestions, each with problem, evidence link, expected effect, cost, risk, and an explicit "choose / defer / reject" control |
| R19 | Dedicated section to review & choose a path before implementing | — | done | full | `site/suggestions/` + `docs/questions.md` | decisions are recorded as a JSON choice file in-repo; nothing auto-implements |
| R20 | Clear list of questions / info needed / answers before a reasonable decision | — | done | full | `site/questions/`, `docs/questions.md` | 14 questions, each with what is known, what is missing, how to find out, and who must answer |
| R21 | Suggestions to discover missing information | — | done | full | same | every question carries a "how to close it" probe (endpoint, doc page, or 1-line command) |
| R22 | Repo review, line by line, verified, links for manual review, flag irregularities | — | done | full | `COORDINATION.md`, `docs/SOURCES.md`, `site/flagged/` | 8 irregularities flagged (FLAG-01…08) |
| R23 | No manual input from the user | — | **needs review** | partial | — | 100% self-driven except items that are *impossible* without a human: demo account creation/API key (R10, R14) and the four decisions in `docs/questions.md`. Documented rather than silently skipped |
| R24 | GitHub Pages site, clean landing + subpages by category | — | done | full | `site/` | Pages workflow `.github/workflows/deploy-pages.yml` |
| R25 | All entries/findings in a simple, readable **table** format with analysis | — | done | full | every subpage | tables carry value + source link per row |
| R26 | Every table row has an official source link; unverifiable ⇒ blank + flagged | — | done | full | every subpage | enforced by `scripts/verify_site.py` (link + blank-cell audit) |
| R27 | Parallel-session coordination | COORDINATION.md board | done | full | `COORDINATION.md` | created in repo root before any other write; 10 tasks claimed; no other session found on the board |
| R28 | Small frequent commits, `pull --rebase` before push, non-overlapping scope | — | done | full | git history | see commit list in `COORDINATION.md` |
| R29 | PR from integration branch → main, merge without waiting, confirm Pages deploy | — | in progress | full | GitHub | executed at the end of this session; result recorded in `COORDINATION.md` |
| R30 | Do not merge a broken site; fix and retry until live | — | in progress | full | — | `scripts/verify_site.py` must pass before the PR; deploy retried on failure |

## Coverage summary

| | count |
|---|---|
| Requirements + sub-requirements decomposed | **36** |
| Done | 26 |
| In progress (integration/deploy only) | 2 |
| Needs review (published, non-blocking) | 5 |
| **Blocked (needs a human/credential)** | **3** — R10, R10a, R14 |
| Feasibility *partial* (API cannot do what was literally asked) | 5 — R4, R10a, R11, R14, R16a, R23 |

## What "blocked" means here, precisely

Three requirements in the brief — read the demo portfolio, track its performance over time, and execute trades —
cannot be satisfied by any amount of engineering inside a sandbox that (a) has no Kalshi credentials, (b) is told
not to ask for any, and (c) cannot create a demo account because account creation on `demo.kalshi.co` is a
human flow. Rather than fabricate a portfolio, this repo ships:

1. the **complete, correct, signed client** (`kalshi_api.py`, `trade_engine.py`, `portfolio.py`) that activates the moment `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PEM` exist;
2. a **paper ledger** driven by the *live public* order book and tape, so trade categorisation (R12) and strategy evaluation (R13) are real code paths over real market prices, clearly labelled as paper;
3. an empty-state UI that says exactly which call will fill it in, instead of showing zeros.
