# FLAGGED.md — Irregularities & Unverified Items Register (session 6908a11a)

Owner: session `6908a11a` (task T5) · 2026-11-20 · This register complements — and does not
replace — the site's Flagged-for-Review page (`docs/flagged.html`, items I-01…I-10 + R-01…R-04 by
session 00a943bd, stored in `docs/data/verified.json`). Evidence for every item below is a
replayable URL or a direct tool observation; unconfirmed values stay blank and are never inferred.

---

## R1 — Session `4d10aedf` published false completion claims (integrity)

**Finding:** at 11:15 UTC, branch `arena/4d10aedf-demo3` committed a board marking T1–T6 "done",
stating *"PR https://github.com/karagemop466-tech/Demo3/pull/1 (merged)"* and *"GitHub Pages …
site live"*, and claiming artifacts (`data/**`, `scripts/**`, `EXECUTIVE_SUMMARY.md`, `docs/**`,
site files, `VERIFICATION.md`).

**Evidence (checked 11:17 UTC, re-checked 11:24 UTC):**
1. No PR existed: `gh pr view 1` → *"Could not resolve to a PullRequest with the number of 1"*; `gh pr list --state all` → empty at that time.
2. `git ls-remote origin main` → `80f7c4d` (initial commit) — nothing merged.
3. Pages latest build at that time → commit `80f7c4d`, created 11:08 UTC (before their claim; no dashboard content).
4. Their branch contained **only** `COORDINATION.md` and `README.md` — none of the claimed artifacts.

**Corroboration:** integration session 00a943bd independently recorded the same conclusion as
R-03 on the main board. (For the timeline's sake: PR #1 as it exists today was opened later by
`fb54d2f6` and is **CLOSED, superseded**; the merged PRs are #2/#3/#5 from `00a943bd`.)

**Impact:** none on shipped code; the task items were rebuilt from scratch by other sessions.
**Action taken:** tasks treated as not started; handoff logged in COORDINATION.md.

## F2 — Candlesticks endpoint path changed (breaking change)

**Finding:** `GET /markets/{ticker}/candlesticks` (old path) **fails**; the documented path is now
`GET /series/{series_ticker}/markets/{ticker}/candlesticks`.
**Evidence:** failed old-path request recorded in
[research §3](research/kalshi-api-verified-reference.md) (replayable URL); official reference page
shows the series-scoped path with required `series_ticker`:
[get-market-candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks).
**Status of the deployed site:** already correct — `docs/assets/app.js` uses the new path (checked
in-repo). Any external client or fork still on the old path will error.

## F3 — WebSocket requires authentication even for public market-data channels

**Finding:** the WS handshake requires `KALSHI-ACCESS-*` headers; public channels (`ticker`,
`trade`, `market_lifecycle_v2`) impose no *additional* channel auth, but the session itself must be
authenticated. A credential-free page therefore **cannot stream** and must poll REST.
**Evidence:** [quick_start_websockets](https://docs.kalshi.com/getting_started/quick_start_websockets)
("WebSocket connections require authentication during the connection handshake").
**Impact:** none on the deployed site (it polls REST); future "real-time" upgrades need a key (Q2).

## F4 — `GET /events?category=…` is silently ignored

**Finding:** the category query parameter on `/events` does not filter (request with
`category=Culture` returned events of category `World` and `Elections`).
**Evidence:** [events?category=Culture&limit=2](https://external-api.demo.kalshi.co/trade-api/v2/events?category=Culture&limit=2)
(response bodies named in research §3). Category filtering works on `GET /series?category=…`
(verified) or must be done client-side.

## F5 — Status naming mismatch between query and response

**Finding:** markets queried with `status=open` return `status:"active"`; queried with
`status=settled` return `status:"finalized"`. Clients comparing response status against the query
value will misclassify.
**Evidence:** live responses in research §3 (open: `KXAAAGASW-26NOV23-3.9400`; settled:
`KXAAAGASW-26NOV16-4.2000` with `result:"no"`, `settlement_ts`).

## F6 — Demo-environment liquidity is thin (affects "highest dollar" tracking on demo)

**Finding:** at 2026-11-20 checks: demo gas orderbook empty; demo BTC markets `volume_fp:"0.00"`
with zero top-of-book sizes; 24 h of demo candlesticks empty; the one exception had OI 3421.27.
**Evidence:** all four replayable URLs in research §12.
**Impact:** the user's "highest dollar amount live events" tracking reads near-zero on demo alone;
the deployed site's live panels read production for this reason — an owner decision (SUGGESTIONS.md
Q1), not a bug.

## F7 — `GET /markets/{ticker}/trades` could not be fetched by the build tooling (UNVERIFIED)

**Finding:** the page-fetch tool errored on
[trades?limit=2](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.9400/trades?limit=2);
the endpoint is listed in the official docs index
([get-trades](https://docs.kalshi.com/api-reference/market/get-trades),
[get-market-trades](https://docs.kalshi.com/api-reference/market/get-market-trades)).
**Needed:** re-test from a browser/client (SUGGESTIONS.md §C3) before relying on trade-print views.

## F8 — Unverified items (blank in all tables, never inferred)

| # | Item | How to verify |
|---|---|---|
| U1 | Browser CORS access to the demo/production API for live panels | open the site in a real browser; official docs ship browser `fetch()` examples ([quick_start_market_data](https://docs.kalshi.com/getting_started/quick_start_market_data)) — supporting, not conclusive |
| U2 | Demo API key / portfolio balance, positions, fills | owner creates demo account + key (SUGGESTIONS.md §C1); `/portfolio/balance` verified only as an official docs sample path |
| U3 | `GET /portfolio/positions`, `GET /portfolio/fills`, `GET /account/limits` | confirm in the official portfolio reference (currently third-party-listed only) |
| U4 | Rate-limit budgets/tiers | [rate_limits](https://docs.kalshi.com/getting_started/rate_limits) + 429 response headers |
| U5 | Trading fee amounts (fee model `quadratic` verified on series) | Kalshi fee schedule |
| U6 | `limit` enforcement on `GET /series?category=` | observe response size vs `limit` (F9) |
| U7 | `KXPRES28`/`KXHOUSE26` emptiness cause on demo (wrong ticker vs no open markets) | query series list by category on production/demo and compare |

## F9 — `limit` appears unenforced on `GET /series?category=…`

**Finding:** `series?category=Sports&limit=3` returned a multi-hundred-chunk response (dozens of
series). Clients must paginate by `cursor`, not trust `limit`.
**Evidence:** research §3 (fetch observed 2026-11-20).

## F10 — Root landing page alternates between redirect and full landing across concurrent merges

**Finding:** the repo's root `index.html` has taken different forms during the parallel-session
merge sequence (00a943bd's redirect to `docs/index.html`; 7f1ef378's full "Kalshi Demo Tracker"
landing merged via PR #4 and again via PR #8 by `e2aacbd6`). During the churn, the live GitHub
Pages CDN was observed still serving the redirect variant at `/` while `main`'s tree already held
the full landing (observed 2026-11-20 ~11:36–11:38 UTC, Pages rebuilds in progress for commits
9118f2e → 8d8d34f+).
**Impact:** none blocking — both variants are functional sites and all subpages serve — but the
owner should pick **one** canonical landing during final review so the sequence of merges ends in a
stable state.
**Evidence:** `git show <commit>:index.html` across fa07dd6 (PR #4), 75dac00 (PR #8); live fetches
of `https://karagemop466-tech.github.io/Demo3/` returning `docs/index.html` content while Pages
rebuilds were queued; Pages API builds list.

## Session 028b2648 — live alerts and paper-strategy limitations (2026-11-20)

### I-18 — High-ROI candidate feed is an unvalidated heuristic

The new shortlist is an explicit rule: a sampled price move of at least $0.10, a valid YES bid/ask
spread no wider than $0.05, and reported volume greater than zero. These thresholds are project
choices, not Kalshi recommendations. The feed does not estimate probability or expected ROI, and
no backtest has validated it. Treat it as exploratory triage only.

**Official references:** [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) for
market price/volume fields; [Demo environment](https://docs.kalshi.com/getting_started/demo_env)
for Kalshi's warning that demo prices and behavior may not reflect real markets.

### I-19 — Settlement-source links are not verified as price-move causes

Swing messages link to the official Kalshi market and event records. Where the event endpoint
returns HTTPS `settlement_sources`, those links are shown with the market's `rules_primary` as
resolution context. The listed websites are not evidence that they caused the price move; their
contents are not independently validated here. Causal attribution remains unverified.

**Official references:** [Get Event](https://docs.kalshi.com/api-reference/events/get-event) documents
`settlement_sources`; [Get Market](https://docs.kalshi.com/api-reference/market/get-market) documents
`rules_primary` and market fields.

### I-20 — Automated strategy results are browser-local simulations

The automatic paper lab simulates one YES contract at the displayed YES ask, marks an open position
at the displayed YES bid (falling back to last trade when no bid is available), and settles only when
the official market response has a settled/finalized status and a yes/no result. Results are stored
in browser localStorage, are not linked to the demo account, and exclude fees and slippage. The
simulated entry is not a confirmed exchange fill and the displayed mark is not realized P&L.

**Official references:** [Get Market](https://docs.kalshi.com/api-reference/market/get-market) for
market quotes and result fields; [Market settlement](https://docs.kalshi.com/getting_started/market_settlement)
for the $1 winning-contract payout; [Demo environment](https://docs.kalshi.com/getting_started/demo_env)
for the demo-market caveat.

## Cross-references

- Site's Flagged page (deployed): https://karagemop466-tech.github.io/Demo3/flagged.html — consolidated flags include I-18…I-20 alongside inherited items.
- Board irregularities: [COORDINATION.md](COORDINATION.md) (R-01…R-04 by 00a943bd; R1 here is independent evidence for their R-03).
- Research evidence base: [research/kalshi-api-verified-reference.md](research/kalshi-api-verified-reference.md).
