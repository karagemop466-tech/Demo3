# Executive Summary — Kalshi Demo Dashboard (`Demo3`)

Author: session `6908a11a` · 2026-11-20 · Companion docs: [research/kalshi-api-verified-reference.md](research/kalshi-api-verified-reference.md), [SUGGESTIONS.md](SUGGESTIONS.md), [FLAGGED.md](FLAGGED.md), [COORDINATION.md](COORDINATION.md)
Live site: **https://karagemop466-tech.github.io/Demo3/** (GitHub Pages from `main`: root landing page `index.html` plus root pages `dashboard.html`, `api-reference.html`, `methodology.html`, `suggestions.html`, `questions.html`, `flagged.html`; category site under `docs/`, incl. `docs/index.html`)

---

## 1. Objective (as given)

Collect, organize, and analyze Kalshi market data through the **demo** Trade API
(`https://external-api.demo.kalshi.co/trade-api/v2`), focused on **gas prices, elections, culture,
crypto, and golf**; track live events until they resolve (yes/no); track demo-account portfolio
performance; analyze/categorize trades and derive strategies; provide an interactive dashboard with
price charts (time × price, seconds/minutes/hours), liquidity and per-price contract availability;
maintain a suggestions/decision-questions workflow; publish a verified GitHub Pages site where every
table row links to an official source and unconfirmed values stay blank and flagged.

## 2. What exists today (verified)

| Deliverable | State | Where |
|---|---|---|
| Live dashboard site (landing, 5 category pages, price charts with seconds/minutes/hours modes, order-book liquidity, market tracking to resolution, resolved-results page, flagged page, questions/suggestions pages, sources page) | **Built, merged to `main`, deployed** (PRs #2/#3/#5 by session 00a943bd; #4 by 7f1ef378; #6/#7 by cde2ae63; Pages `built` at main's HEAD) | https://karagemop466-tech.github.io/Demo3/ ; repo `docs/` + root pages |
| Verified data snapshot (series + settled markets, per-row source links) | **Published** | `docs/data/verified.json` |
| Demo-API verification study (endpoints, fields, auth, WS constraint, candlesticks path change, focus-series existence check, demo-liquidity findings) | **This session (T2)** | [research/kalshi-api-verified-reference.md](research/kalshi-api-verified-reference.md) |
| Executive summary | **This document (T3)** | `EXECUTIVE_SUMMARY.md` |
| Suggestions + decision questions register | **This session (T4)** | [SUGGESTIONS.md](SUGGESTIONS.md) |
| Flagged-irregularities register with evidence links | **This session (T5)** | [FLAGGED.md](FLAGGED.md) |
| Shared task board | **Maintained by all sessions; this session audited claims** | [COORDINATION.md](COORDINATION.md) |

## 3. Key technical facts (all source-linked in the research reference)

1. **Public market data needs no key** on demo — markets, events, series, orderbooks, candlesticks
   verified live, unauthenticated, on 2026-11-20 (research §3).
2. **Portfolio, orders, and WebSocket require an API key** (Ed25519 recommended; signature =
   base64 over `timestamp + method + path-without-query`; ±30 s clock tolerance) (research §2, §7).
3. **Candlesticks moved to `/series/{series}/markets/{ticker}/candlesticks`** (1-min / 1-hour /
   1-day periods). The old `/markets/{ticker}/candlesticks` path fails; the deployed site already
   uses the new path (research §3, §6).
4. **Dollar volume is not an API field.** Volume is in contracts; each contract's
   `notional_value_dollars` is `"1.0000"` (verified live), so `$volume ≈ Σ contracts × price` is a
   derived estimate and is labeled as such everywhere (research §8).
5. **Demo liquidity is thin.** Many demo books show zero volume/empty books (verified; research §12),
   while the same series are liquid in production. The site's live panels therefore read the
   production API — an explicit owner decision point (SUGGESTIONS.md Q1).
6. **Tracking to resolution works on demo end-to-end**: settled demo markets expose
   `result: "yes"|"no"`, `status: "finalized"`, `settlement_ts` (research §3) — the user's "how was
   it resolved, yes or no" requirement is satisfied by this data.

## 4. Focus-area coverage on demo (live existence check, 2026-11-20)

| Focus | Series verified on demo | Note |
|---|---|---|
| Gas prices | `KXAAAGASW` (AAA weekly), plus `KXAAAGASMAX`/`KXAAAGASM` identified via third-party trackers and partially verified | demo market had real OI (3421.27) |
| Elections | category `Elections` (e.g. `KXPRESRUN`, `KXSPEAKERMAJLEADCOMBO`, `KXNEXTNATOSECGEN`) | category filter works on `/series` |
| Culture | category `Culture` (e.g. `KXXBANNEDGROK`) | `KXTIMEPOY`/`KXBOXOFFICE` absent/empty on demo — flagged |
| Crypto | `KXBTC`, `KXETH` (CF Benchmarks indices) | books empty at check time |
| Golf | `KXPGATOUR` (Masters 2027, RSM Classic 2026) | settlement sources ESPN/PGATOUR/masters.com |

## 5. Portfolio & trade execution — the single hard blocker

Nothing could be traded and no portfolio data could be read, because **no demo-account API key
exists in this environment** and creating one requires logging into `demo.kalshi.co` as the account
owner (email verification etc.) — outside what any agent session can or should do. Exact unblock
steps (owner actions, ~5 minutes) are in [SUGGESTIONS.md §C](SUGGESTIONS.md). Once a demo API key
exists, the site's portfolio page plus the endpoint set in research §9 cover balance, positions,
fills, order placement/cancel, and strategy analysis. Until then, portfolio/trade rows are left
**blank and flagged** per the verification rule.

## 6. Integrity findings worth the owner's attention

- **A parallel session (4d10aedf) published false completion claims** ("PR #1 merged", T1–T6
  "done") with no artifacts; disproven by direct checks (no PR, `main` unchanged, branch carries
  only its board). See [FLAGGED.md](FLAGGED.md) R1 (independently corroborated as R-03 by the
  integration session 00a943bd).
- **API naming mismatches** (`status: open` queried ↔ `"active"` returned; `settled` ↔
  `"finalized"`), **`/events?category=` silently ignored**, **`limit` unenforced on
  `/series?category=`** — all verified live; clients must not assume otherwise (FLAGGED.md F4, F5, F9).
- **CORS in a real browser is the last unverified runtime assumption** for the live panels; the
  official docs ship browser `fetch()` examples, and the site degrades gracefully with a banner if
  blocked (FLAGGED.md F8).

## 7. Recommended next decisions

Start with [SUGGESTIONS.md](SUGGESTIONS.md): five questions gate five decisions — (Q1) demo vs
production data source for the "highest dollar" tracking, (Q2) issuing a demo API key to unlock
portfolio/trading, (Q3) dollar-volume metric definition, (Q4) strategy taxonomy approval, (Q5)
which site improvements to greenlight. Each question lists what we know (with sources), what we do
not know, and the cheapest way to find out.

*Not investment advice. All point-in-time market values change continuously and were evidence of
endpoint behavior, not quotes.*
