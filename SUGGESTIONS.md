# SUGGESTIONS.md — Suggestions & Decision Questions Register

Owner: session `6908a11a` (task T4) · 2026-11-20 · Feeds the site's Questions/Suggestions pages
(`docs/questions.html`, `docs/suggestions.html`). Evidence and source links: see
[research/kalshi-api-verified-reference.md](research/kalshi-api-verified-reference.md) and
[FLAGGED.md](FLAGGED.md).

Purpose: a **clear list of questions, information we have vs. do not have, and answers needed
before any decision can reasonably be made** — plus suggestions for discovering the missing
information. Nothing here was implemented without an owner decision; statuses start at `proposed`.

Review workflow: `proposed → reviewed → approved/rejected → implemented → verified`.
Record the decision + date in [COORDINATION.md](COORDINATION.md) (Change log).

---

## A. Decision-gating questions (answered with what we know today)

### Q1 — Which API environment should the "highest dollar amount live events" tracker read?

| | |
|---|---|
| **Why it matters** | The brief says to use the demo endpoint; but demo liquidity is thin (verified: demo gas orderbook empty, demo BTC markets `volume_fp:"0.00"`, 24 h of demo candlesticks empty — evidence links in research §12). Ranking "highest dollar" on demo alone would show mostly zeros. |
| **What we know** | Demo and production are separate environments with mock vs real liquidity ([demo_env docs](https://docs.kalshi.com/getting_started/demo_env)). The merged site's live panels already read **production** (`docs/assets/app.js`, `API = external-api.kalshi.com`). |
| **What we don't know** | Whether the owner wants strict-demo fidelity (matches the brief) or meaningful liquidity (matches the dashboard's purpose), or both side-by-side. |
| **Cheapest discovery** | Look at both: the site's category pages next to a `?env=demo` variant; decide in one sitting. |
| **Decision** | **OPEN — owner.** Options: (a) demo-only per brief; (b) production-only for liquidity; (c) dual-mode toggle (recommended). |

### Q2 — Create a demo account + API key to unlock portfolio tracking & trade execution?

| | |
|---|---|
| **Why it matters** | Portfolio endpoints, order placement, and even WebSocket streaming require a signed API key (research §2, §7, §9). No demo account credentials exist in this workspace; none of the agent sessions can (or should) create an account in the owner's name. |
| **What we know** | Exact self-service steps exist: create demo account at `demo.kalshi.co` ([help article](https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account)), then Account Settings → Profile (`kalshi.com/account/profile`) → "Create New API Key" (Ed25519 default) ([api_keys docs](https://docs.kalshi.com/getting_started/api_keys)). Key ID + private key are shown once. |
| **What we don't know** | Owner's consent to create the demo account, and where they want the key stored (browser `localStorage` only — never committed — is the recommendation). |
| **Cheapest discovery** | 5-minute owner action (steps in §C1 below); then the portfolio page + trading UI can be exercised immediately. |
| **Decision** | **OPEN — owner.** Until then every portfolio/trade cell stays blank + flagged (done today). |

### Q3 — Definition of "highest dollar amount" for rankings

| | |
|---|---|
| **Why it matters** | The API has volume in **contracts**, not dollars (research §8); different definitions change the leaderboard. |
| **What we know** | `notional_value_dollars = "1.0000"` per contract (live), so `$volume ≈ Σ contracts × price` is a sound derived estimate; alternatives: contracts volume only (current site), 24-h vs all-time volume, open-interest × price ("dollars at risk"). |
| **What we don't know** | Owner's preferred metric and window. |
| **Cheapest discovery** | Approve one of: (a) contracts traded (status quo), (b) Σ volume×last-price $ estimate (recommended), (c) OI×price. |
| **Decision** | **OPEN — owner.** |

### Q4 — Which trade-analysis strategies should be standardized?

| | |
|---|---|
| **Why it matters** | "Categorize trades and create strategies based on the type of trade" needs an agreed taxonomy, otherwise analysis is unfalsifiable. |
| **What we know** | Trade-level data exists (`GET /markets/{ticker}/trades`, all-markets `/trades`; per official docs index) with side/price/size; orderbook gives depth; candlesticks give OHLC — enough for momentum, mean-reversion, event-driven, spread/depth-based, and fee-aware classifications (fee model is `quadratic` per series, live-verified). |
| **What we don't know** | Owner's risk appetite, holding-period horizon, and whether strategies are for **demo practice** only. |
| **Cheapest discovery** | Approve/reject the proposed taxonomy in §B (S-04). |
| **Decision** | **OPEN — owner.** |

### Q5 — Should the Pages source switch from `/` to `/docs`?

| | |
|---|---|
| **Why it matters** | Root `index.html` is currently a redirect to `docs/index.html`; serving `/docs` directly removes the redirect hop. |
| **What we know** | Session 00a943bd hit `403` changing Pages source (needs admin) — see COORDINATION.md R-02. The redirect works today. |
| **What we don't know** | Whether the repo owner prefers `/docs` (admin-only setting). |
| **Cheapest discovery** | Settings → Pages → source `/docs` (1 minute, admin). |
| **Decision** | **OPEN — owner (admin).** Low priority; redirect works. |

## B. Suggestions backlog (status: all `proposed`, awaiting review)

| ID | Suggestion | Rationale (evidence) | Effort | Risk if skipped | Decision |
|---|---|---|---|---|---|
| S-01 | Add an environment toggle (`demo`/`production`) to live panels | Demo liquidity is thin (research §12); the brief names demo while meaningful rankings need production — a toggle answers Q1 without code forks | S | Tracker shows zeros on demo-only | — |
| S-02 | Store a demo API key client-side (`localStorage`) and wire portfolio/trade UI | Portfolio endpoints + orders need a signed key (research §2/§9); WebCrypto Ed25519 signing runs entirely in-browser; key never leaves the browser | M | Portfolio/trading stays blocked (Q2) | — |
| S-03 | Adopt `$volume ≈ Σ contracts × price` for "highest dollar" ranking | No dollar field exists (research §8); `notional_value_dollars=1.0000` verified live | S | Ranking semantics stay ambiguous (Q3) | — |
| S-04 | Standardize strategy taxonomy: momentum / mean-reversion / event-driven / spread & depth / fee-aware carry | Needs agreed definitions (Q4); data to compute all five exists (trades, orderbook, candles — research §3/§6) | M | "Strategies" stay anecdotal | — |
| S-05 | Add per-market trade-print microstructure view (from `/markets/{ticker}/trades`) once F7 is re-verified in-browser | Sub-minute detail complements 1-min candles for the seconds view | S | Seconds view relies on client-side sampling only | — |
| S-06 | Backfill resolved-market outcomes automatically for tracked markets (currently: manual watch list in `localStorage`) | "Track until resolved (yes/no)" is a brief requirement; settled status + `result` fields are live-verified (research §3) | S | Tracked markets may be missed | — |
| S-07 | Show Kalshi's quadratic fee formula next to any hypothetical P&L | Fee model verified (`fee_type:"quadratic"` on series); fee *amounts* unverified — label accordingly (research §13) | S | P&L estimates misleading | — |
| S-08 | Rate-limit guard: honor 429 + Retry-After, cache GETs for 15–60 s | Rate limits unverified (research §13); polling multiplies requests | S | Possible temporary API bans in-demo | — |
| S-09 | Re-verify the site in a real browser (CORS + charts) and record the result on the Flagged page | CORS is the last unverified runtime assumption (FLAGGED.md F8) | S | Live panels unconfirmed for end users | — |
| S-10 | Remove/replace any client that still calls the old `/markets/{ticker}/candlesticks` path | Old path fails (research §3); deployed site already uses the new path — audit any forks | S | Chart failures | — |

## C. Missing-information discovery plan (who does what, cheapest first)

1. **Owner (5 min):** create the demo account at `https://demo.kalshi.co/`
   ([steps](https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account)),
   then Account Settings → API Keys → "Create New API Key" (Ed25519)
   ([api_keys docs](https://docs.kalshi.com/getting_started/api_keys)). Keep the private key
   offline; paste into the site's portfolio panel only if/when S-02 is approved (browser-local only).
2. **Owner or any session with a browser (2 min):** open the site, confirm live panels populate
   (closes FLAGGED.md F8 / S-09); paste the console result into the Flagged page request log.
3. **Any session (10 min):** replay the trades-URL from research §3 in a browser to close F7;
   read response headers on a 429 to document real rate limits.
4. **Owner (admin, 1 min):** decide Q5 (Pages source) — optional.
5. **Any session:** once Q2 resolves, execute one mock demo order (buy 1 YES at the ask on a
   low-price market), then verify fill appears in `GET /portfolio/fills` — closes the portfolio
   verification column in the site tables.

## D. Information inventory (what we have vs. lack)

| Have (source-linked) | Lack (flagged, discovery in §C) |
|---|---|
| All public demo endpoints + response shapes (research §3–§6, live URLs) | Live browser CORS confirmation (F8) |
| Auth spec incl. signing text + tolerance (research §2, official docs) | Demo API key / any portfolio data (Q2) |
| Focus-series existence on demo, all 5 areas (research §11) | Real demo order-flow to analyze (thin demo liquidity, §12) |
| Settlement mechanics: `result` yes/no, `status:"finalized"` (research §3) | Fee *amounts* (fee model verified; schedule not) |
| WS channel list + auth constraint (research §7) | Rate-limit budgets (third-party only) |
| Site live at GitHub Pages, verified data snapshot in-repo (`docs/data/verified.json`) | Owner decisions Q1–Q5 |
