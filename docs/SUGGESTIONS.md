# Suggestions register — proposals, evidence, and the decision they need

Each suggestion is written so it can be **accepted, rejected or sequenced without further research**. Every proposal
names the decision it depends on (`D#` in [DECISIONS.md](DECISIONS.md)), the evidence behind it, and the risk of
doing nothing.

**How to review this page:** pick the suggestions you want, in the order you want them. Nothing here is implemented
automatically. Each row carries an `ID`, a cost estimate in engineer-hours, a dependency, and a "reversible?" flag.

---

## Tier 1 — do these first (they change decisions, not just presentation)

### S1 — Publish the four size metrics side by side instead of one "dollar amount" ✅ *implemented this session*
- **Problem it solves:** D1. "Highest dollar amount" is undefined and the candidate metrics disagree violently. The
  highest-volume markets by contracts traded are 1–5¢ longshots with **no resting bids** (0.00 bid / 1.00 ask), i.e.
  you cannot trade size in them; the deepest books are elsewhere (up to **$4.24 M** resting in one election market).
- **Proposal:** show contracts traded, 24h volume, open interest, derived traded-notional, and resting liquidity as
  separate, labelled columns, and let the user sort by any of them.
- **Effort:** done. **Reversible:** yes. **Dependency:** none.

### S2 — Show measured expectancy next to every price ✅ *implemented this session*
- **Problem it solves:** D9. A price on Kalshi is not a calibrated probability. In the collected settlement sample the
  0.80–0.99 band won 82.13% of the time at a 97.49¢ average price (**−15.36¢/contract**) while the 0.01–0.20 band's
  NO side earned **+1.58¢/contract**.
- **Proposal:** a "what this price has historically been worth" panel on every category page, with the sample size and
  the caveats (last-trade price, fees excluded, survivorship, not predictive).
- **Effort:** done. **Reversible:** yes. **Dependency:** D9 still open — refresh as history deepens.

### S3 — Add a liquidity reality-check before any trade suggestion ✅ *implemented this session*
- **Problem it solves:** the order book is bids-only and many headline markets are empty shells. A suggestion that
  ignores the book is fiction.
- **Proposal:** every suggested order states the contracts actually available at or better than its price, walking the
  book (`analysis/strategies.py: fillable()`), plus the derived spread and the resting depth.
- **Effort:** done. **Reversible:** yes.

### S4 — Publish a "why we did NOT suggest a trade" list ✅ *implemented this session*
- **Problem it solves:** silent filters look like agreement. Today 50 of 52 evaluated markets were skipped; zero of
  them are hidden.
- **Proposal:** list every skip with its reason (spread too wide, depth too thin, price in the negative-expectancy
  band, no book).
- **Effort:** done. **Reversible:** yes.

---

## Tier 2 — high value, needs a decision or a credential

### S5 — Turn on the demo portfolio panels `needs credentials`
- **Problem it solves:** D12/D13 and the brief's "track portfolio performance / execute trades". Today the panels are
  blank by design because no demo key exists.
- **Proposal:** add `KALSHI_DEMO_KEY_ID` and `KALSHI_DEMO_PRIVATE_KEY` as repository secrets, then run the `portfolio`
  workflow. It writes real balance, positions, orders, fills and settlements, and the P&L components separately.
- **Effort:** ~10 minutes for the owner, zero code. **Reversible:** yes (delete the secrets).
- **Risk of doing nothing:** the portfolio and trade-performance parts of the brief stay unverified forever.

### S6 — Decide the P&L definition before publishing a headline number `needs decision (D13)`
- **Problem it solves:** adding `realized_pnl`, settlement `revenue` and `fee_cost` into one number silently mixes
  three different accounting concepts.
- **Proposal:** publish **three** lines — position-level realised P&L, settlement revenue, fees paid — and only show a
  net figure once D13 is answered in writing.
- **Effort:** 2 h. **Reversible:** yes.

### S7 — Scheduled strategy re-evaluation with a written changelog `suggested`
- **Problem it solves:** thresholds chosen today will rot. The rules currently rest on a Nov-2026 sample dominated by
  short-dated contracts.
- **Proposal:** re-run `analysis/expectancy.py` on a schedule, and require every threshold change to land as a commit
  with the measured numbers in the message.
- **Effort:** 3 h. **Reversible:** yes.

### S8 — Deepen history via the historical endpoints `suggested`
- **Problem it solves:** D9 — the settlement sample is narrow (11,680 of 12,567 rows are from Nov 2026).
- **Proposal:** page `GET /historical/markets` and `GET /historical/trades`, keep monthly rollups, and re-run the study
  by quarter so regime drift is visible.
- **Source:** [Historical Data](https://docs.kalshi.com/getting_started/historical_data.md).
- **Effort:** 6 h. **Reversible:** yes.

### S9 — Stream prices with a signed WebSocket worker `needs credentials`
- **Problem it solves:** D7 — REST polling cannot show sub-minute movement, and the socket handshake is signed even for
  public channels.
- **Proposal:** a small worker (GitHub Actions or a VPS) holds a signed socket for the tracked tickers and appends
  ticks to `data/history/`; the chart then has second-level resolution without exposing keys to the browser.
- **Effort:** 8 h. **Reversible:** yes. **Dependency:** S5.

---

## Tier 3 — polish and trust

### S10 — Resolve the duplicate landing page `needs decision`
- **Problem it solves:** several parallel sessions published different landing pages in this repo
  (`/`, `/docs/`, `/demo-desk/`, `/analysis/`). Two of them describe different feature sets, which is confusing and,
  worse, invites citing the wrong one.
- **Proposal:** one canonical landing page; every other site surface reachable only from it and clearly marked
  "secondary / archived".
- **Effort:** 1 h. **Reversible:** yes.

### S11 — Add a public "data freshness" banner `suggested`
- **Problem it solves:** a reader cannot tell whether a chart is 4 minutes or 4 hours old.
- **Proposal:** print the capture timestamp and the age of the snapshot in the header of every data view, colour-coded
  when older than the cron interval.
- **Effort:** 2 h. **Reversible:** yes.

### S12 — Machine-readable `sources.json` for every table row `suggested`
- **Problem it solves:** manual re-verification is the slowest part of every review.
- **Proposal:** emit one row-keyed citation file (URL + HTTP status + capture time) so a reviewer can re-check in
  bulk. The collector already records every request; this exposes it per row.
- **Effort:** 2 h. **Reversible:** yes.

### S13 — Alerting when a tracked market is about to resolve `suggested`
- **Problem it solves:** the brief wants tracking **until resolution**; polling hourly can miss a market that closes
  between runs.
- **Proposal:** compare `close_time` against the next scheduled run and subscribe those tickers to a shorter-interval
  job; log every state transition (`active → closed → settled`) with timestamps.
- **Effort:** 3 h. **Reversible:** yes. **Dependency:** none.

### S14 — Explain *why* each market is in scope `implemented`
- Every series row carries `matched_by` (`category=…`, `tag`, `ticker_prefix`, `title`) so a reviewer can see the exact
  rule that pulled it in. Series that match nothing are excluded and counted.
- **Effort:** done.

---

## What we deliberately did **not** propose

| Idea | Why not |
|---|---|
| Scraping kalshi.com's UI for "total dollars" | Not an official API field; would be unverifiable and fragile. Use `volume_fp` / `open_interest_fp` / the order book. |
| Calling the demo WebSocket from the browser | The handshake needs the private key; shipping it to a static page would leak it. |
| A single "expected profit" number per strategy | Requires a probability model the data does not support. Expectancy is published instead, with its caveats. |
| Auto-trading on a schedule from day one | No accountable owner for automated order entry (D12), and no P&L definition (D13). |

---

## Suggested decision order

1. **S5** (add demo keys) → unlocks the portfolio half of the brief.
2. **S6 + D13** (define P&L) → makes any performance figure trustworthy.
3. **S8** (deepen history) → strengthens or overturns the expectancy study before anyone trades on it.
4. **S10** (one canonical landing page) → so reviewers look at the right site.
5. **S9/S13** (streaming, resolution alerts) → only after the above, and only if sub-minute data is genuinely needed.
