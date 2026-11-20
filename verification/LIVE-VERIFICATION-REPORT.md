# Live verification report — session `a613b9fd` (2026-11-20)

**What this is.** The post-merge verification pass that audits `32f91e0e` (I-32F-01) and `edf9de2a`
(F-edf-03) explicitly could not perform from their sandboxes: fetching the **live GitHub Pages
pages**, checking **CI/collector health**, and **re-fetching committed data rows from the live
demo API**. Scope is verification only — no code, data, or page files owned by other sessions were
changed. Everything below was executed 2026-11-20 ~19:30–19:40 UTC by session `a613b9fd`
(branch `arena/a613b9fd-demo3`, based on actual `main` history).

---

## V1 · Live GitHub Pages pages (all render correctly)

Fetched live from https://karagemop466-tech.github.io/Demo3/ via the page-fetch tool. Pages build
state at fetch time: commit `fa6525b` `building` (superseding `5f0335f`, which included PR #34);
served content reflects the merged alert feature. Pages source: `main` `/` (legacy build).

| Page | Result | Evidence |
|---|---|---|
| `/` (landing) | Renders: live status widget **“LIVE · trading active (demo)”**, executive summary with per-row sources, topic links, decision registers (57 questions · 46 suggestions · 83 flagged · 78 sources), archive links | https://karagemop466-tech.github.io/Demo3/ |
| `dashboard.html` | All 6 sections render: (1) discovery & ranking with scan-depth control and **“unverified estimate”** disclosure; (2) price chart with windows **30 s / 2 m / 10 m / 30 m / 1 h / 6 h / 24 h**, x = time, y = contract price; orderbook depth; (3) resolution tracking (yes/no) with seeded rows; (4) demo account (optional) + paper mode labeled; (5) trade categorization & strategy analysis; (6) **two scrolling alert chats (≥ $0.10)** with “All events” and “High ROI model” tabs | https://karagemop466-tech.github.io/Demo3/dashboard.html |
| `data-tracking.html` | Renders committed collector snapshot: ranked events per topic, **every row links its exact API URL**, collector status and warnings shown | https://karagemop466-tech.github.io/Demo3/data-tracking.html |
| `flagged.html` | Consolidated flagged register renders (F-01…F-83, each row with evidence links) | https://karagemop466-tech.github.io/Demo3/flagged.html |
| `sources.html` | Source register renders (SRC-01… with what each source supports) | https://karagemop466-tech.github.io/Demo3/sources.html |

Alert-feature code check (merged via PR #28, `assets/alerts.js`):
`SWING = 0.10` (dollars) is the alert threshold; the “High ROI model” chat applies the **labeled
placeholder heuristic** (swing ≥ $0.10 **and** move ≥ 10 % of prior price) and the page states it is
“Not a real model” — properly flagged as F-alert-01, never presented as verified ROI.
Source: `assets/alerts.js` (lines 25, 97–100), `dashboard.html` (sections 6).

---

## V2 · CI + collector health

| Check | Result | Evidence |
|---|---|---|
| `Checks` workflow (main) | **0 failures on main.** 40 completed runs in the window; the only 2 failures belong to PR #32’s branch (`arena/26973298-demo3`, in-flight strategy work), not main | `gh run list` (GitHub API) |
| `Collect Kalshi demo data` (main) | 31 completed runs, **0 failures** | `gh run list` |
| Collector status | `status: "ok"`, finished 2026-11-20T19:28:28Z | `data/latest/collector_status.json` |
| Row-level self-verification | **725/725 checks pass, 0 drift notices, 0 hard failures** (verified_at 19:28:28Z) | `data/latest/verification_report.json` (`scripts/verify_rows.py` re-fetches every stored row from its own URL) |
| Snapshot freshness | `data/latest/*` committed 19:26–19:30 UTC this hour (markets_open 15,139 markets; resolutions 1,000 rows; series 16,647) | `data/latest/meta.json`, file timestamps |
| GitHub Pages | Builds triggered for `5f0335f` and `fa6525b`; status `building` at 19:36 UTC, no error message | Pages API `repos/…/pages/builds/latest` |
| CORS (browser → demo API from Pages origin) | Verified evidence on file: HTTP 200, `access-control-allow-origin` echoes the Pages origin, `browser_direct_fetch_allowed: true` (tested 2026-11-20T12:14:51Z) | `data/cors_test.json` (recorded by session 3b5e95bd) |

---

## V3 · Live demo-API row re-verification (exact re-fetch of stored source URLs)

### Resolutions — stored vs live (all match exactly)

| Market | Stored (committed) | Live response (re-fetched 19:33 UTC) | Match |
|---|---|---|---|
| `KXQUICKSETTLE-20NOV26H1350-2` (gas row; synthetic demo market, see I-15) | result `yes`, settlement_value `1.0000`, settlement_ts `2026-11-20T19:20:33.775273Z`, close `18:50:00Z` | identical fields | **exact** — [source](https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=KXQUICKSETTLE-20NOV26H1350-2) |
| `KXBTC-26NOV2013-T72799.99` (crypto) | result `no`, settlement_value `0.0000`, settlement_ts `2026-11-20T19:07:34.207893Z`, close `18:00:00Z` | identical fields | **exact** — [source](https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=KXBTC-26NOV2013-T72799.99) |
| `KXPGATOP10-THRC26-CCHA` (golf) | result `no`, settlement_value `0.0000`, settlement_ts `2026-11-20T02:49:40.839538Z`, close `02:41:41Z` | identical fields | **exact** — [source](https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=KXPGATOP10-THRC26-CCHA) |

Settlement semantics (winner paid $1/contract, yes/no result field) per the official
[Market Settlement](https://docs.kalshi.com/getting_started/market_settlement) page.

### Top-dollar event per topic — live existence + classification

| Topic | Event | Live check | Source |
|---|---|---|---|
| Elections | `KXPRESNOMD-28` | Returns 62 active markets (live prices/volumes, e.g. `KXPRESNOMD-28-GW` volume_fp 432,107,353.42) | [source](https://external-api.demo.kalshi.co/trade-api/v2/events?tickers=KXPRESNOMD-28&with_nested_markets=true) |
| Crypto | `KXBTCY-27JAN0100` | Returns active BTC ladder markets, category Crypto | [source](https://external-api.demo.kalshi.co/trade-api/v2/events?tickers=KXBTCY-27JAN0100&with_nested_markets=true) |
| Culture | `KXOSCARPIC-27` | Category Entertainment, “Oscar for Best Picture?”, settlement source oscars.org | [source](https://external-api.demo.kalshi.co/trade-api/v2/events?tickers=KXOSCARPIC-27) |
| Gas | `KXWTIMAX-26DEC31` | Returns “How high will WTI oil get by end of year?”, category Financials (see observation V-A613-01) | [source](https://external-api.demo.kalshi.co/trade-api/v2/events?tickers=KXWTIMAX-26DEC31) |
| Golf | `KXPGATOUR-THRC26` | “The RSM Classic Winner”, Sports, settlement sources pgatour.com/ESPN/Fox Sports | [source](https://external-api.demo.kalshi.co/trade-api/v2/events?tickers=KXPGATOUR-THRC26) |

### Derived “dollar” figure — formula verified exactly

`top_events.json` → `open_interest_dollars_derived` was recomputed offline from the same run’s
`data/latest/markets_open.json` for all five topics: it equals **Σ `open_interest_fp`** (open
interest in contracts × $1 notional per contract) to the cent on every row:

| Topic | Event | Stored | Σ OI recomputed |
|---|---|---|---|
| Crypto | `KXBTCY-27JAN0100` | 387,160,134.46 | 387,160,134.46 |
| Culture | `KXOSCARPIC-27` | 20,802,893.04 | 20,802,893.04 |
| Elections | `KXPRESNOMD-28` | 2,507,890,527.21 | 2,507,890,527.21 |
| Gas | `KXWTIMAX-26DEC31` | 2,446,611.65 | 2,446,611.65 |
| Golf | `KXPGATOUR-THRC26` | 14,885,455.55 | 14,885,455.55 |

Formula source: `scripts/collect_kalshi_data.py` line 413 (`a["open_interest_dollars_derived"] += (oi or 0.0) * notional`).

### Orderbook — structure + prices exact; one size drift

`KXPRESNOMD-28-BOBA` re-fetched live: YES levels identical (`0.0010 × 166,706.66`,
`0.0020 × 83,333.33`), NO best bid price identical (`0.9950`); one NO size drifted
`31,990.18` (stored 19:26:46Z) → `31,963.18` (live 19:34Z) — **drift notice**, expected for a live
book. Structure matches the official spec (ascending lists, best bid = last element):
[orderbook responses](https://docs.kalshi.com/api-reference/market/get-market-orderbook) —
[source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-BOBA/orderbook?depth=25).

### Candlesticks — documented path live and non-empty

`GET /series/KXPRESNOMD/markets/KXPRESNOMD-28-BOBA/candlesticks?start_ts=1795200000&end_ts=1795203000&period_interval=1`
returned 1-minute candles with `price` (open/high/low/close/mean), `yes_bid`/`yes_ask`,
`volume_fp`, `open_interest_fp` — matching the official schema
([Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)) —
[source](https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-BOBA/candlesticks?start_ts=1795200000&end_ts=1795203000&period_interval=1).

### Exchange status — trading active

`GET /exchange/status` → `exchange_active: true`, `trading_active: true` on all demo shards
([source](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status);
[Get Exchange Status](https://docs.kalshi.com/api-reference/exchange/get-exchange-status)).

### Drift notice (expected, recorded not failed)

`KXPRESNOMD-28-KH`: stored volume_fp `134,222,694.59` (retrieved 19:26:46Z) → live
`134,222,723.36` (19:33Z); `last_price_dollars` unchanged `0.0500`.
Source: [markets?tickers=KXPRESNOMD-28&with_nested_markets=true](https://external-api.demo.kalshi.co/trade-api/v2/events?tickers=KXPRESNOMD-28&with_nested_markets=true).

---

## V4 · Local check suite (this branch, 2026-11-20 ~19:35 UTC)

| Check | Result |
|---|---|
| `scripts/verify_root_site.py` | **0 failures** |
| `scripts/verify_site.py` | **PASSED, 0 failures** (28 HTML pages, 21 render hooks) |
| `scripts/tracker_check.py` | OK (JSON valid, every row has a source link, no broken internal links) |
| `scripts/check_site.py` | passed (44 sources registered, 39 cited) |
| `node --check assets/*.js` | 6/6 OK (`alerts.js`, `app.js`, `dashboard.js`, `data-tracking.js`, `site.js`, `trade.js`) |
| `npm test` | **26/26 pass** (after `npm ci`; the one local failure before install was only missing `jsdom` in the sandbox — CI installs it via `check.yml`) |
| `python3 collector/test_collect.py` | 2/2 OK |
| `python3 trading/test_trading.py` | 9/9 OK (after `pip install cryptography`; dependency documented in README) |

---

## Flagged observations (new; nothing blocks the merge)

| ID | Severity | Observation | Evidence |
|---|---|---|---|
| V-A613-01 | low | The **“gas prices” topic includes WTI crude-oil series** (`KXWTIMAX-26DEC31`, “How high will WTI oil get by end of year?”). Crude oil is energy, not a gasoline price; whether it belongs in the gas topic is a classification-scope decision for the topic owner (sessions 3b5e95bd / 4d10aedf). | [live event response](https://external-api.demo.kalshi.co/trade-api/v2/events?tickers=KXWTIMAX-26DEC31) |
| V-A613-02 | info | Two pipelines publish **different, each-labeled dollar proxies**: `collector/` + `data-tracking.html` rank by Σ(volume_fp × last_price) (“Est. $ volume”), while `scripts/collect_kalshi_data.py` publishes Σ open interest (above). Neither is exchange-reported dollars (consistent with F4/I-16). A single canonical definition remains an owner decision. | [data-tracking.html](https://karagemop466-tech.github.io/Demo3/data-tracking.html), `data/latest/top_events.json` |
| V-A613-03 | medium | Re-confirmed live: the dashboard’s **seeded resolution rows and several Sources rows (SRC-10…) link the production host** (`api.elections.kalshi.com`, `external-api.kalshi.com`) instead of the demo endpoint the brief specifies — the provenance is real but production-environment (already recorded as I-14 / R-06). | [dashboard.html live](https://karagemop466-tech.github.io/Demo3/dashboard.html), [sources.html live](https://karagemop466-tech.github.io/Demo3/sources.html) |
| V-A613-04 | low | `collect.yml` triggers **on every branch push** (40+ workflow runs in ~10 minutes across concurrent sessions → runner congestion and snapshot churn). Consider `push: branches: [main]` or a paths filter. Workflow owned by session 3b5e95bd — logged here, **not edited**. | `.github/workflows/collect.yml`, `gh run list` |
| V-A613-05 | info | Session sandbox was seeded with a content-copy of `7e795b2` as an **unrelated git history** (no merge base with `origin/main`). Resolved by resetting the (empty) session branch to actual `main` before any work. Platform artifact, not a repo defect. | board section, `git merge-base` output 19:30 UTC |
| V-A613-06 | info | Alert history and paper-trade state persist **per browser** (localStorage) — no server-side store, so the two chat streams start empty on a fresh browser. Already flagged by b13c6a8d (F-B13-06); re-confirmed in code. | `assets/alerts.js`, `assets/trade.js` |

---

## Sources used by this report

Official documentation: [demo environment](https://docs.kalshi.com/getting_started/demo_env) ·
[quick start: market data](https://docs.kalshi.com/getting_started/quick_start_market_data) ·
[orderbook responses](https://docs.kalshi.com/api-reference/market/get-market-orderbook) ·
[market candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) ·
[market settlement](https://docs.kalshi.com/getting_started/market_settlement) ·
[exchange status](https://docs.kalshi.com/api-reference/exchange/get-exchange-status).

Live demo API (re-fetched 2026-11-20, replayable URLs):
[status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) ·
[resolutions ×3](https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=KXQUICKSETTLE-20NOV26H1350-2) ·
[top events ×5](https://external-api.demo.kalshi.co/trade-api/v2/events?tickers=KXPRESNOMD-28&with_nested_markets=true) ·
[orderbook](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-BOBA/orderbook?depth=25) ·
[candlesticks](https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-BOBA/candlesticks?start_ts=1795200000&end_ts=1795203000&period_interval=1).

Live site: [landing](https://karagemop466-tech.github.io/Demo3/) ·
[dashboard](https://karagemop466-tech.github.io/Demo3/dashboard.html) ·
[data-tracking](https://karagemop466-tech.github.io/Demo3/data-tracking.html) ·
[flagged](https://karagemop466-tech.github.io/Demo3/flagged.html) ·
[sources](https://karagemop466-tech.github.io/Demo3/sources.html).

Repository evidence: `data/latest/collector_status.json`, `data/latest/verification_report.json`,
`data/latest/top_events.json`, `data/latest/markets_open.json`, `data/latest/orderbooks.json`,
`data/cors_test.json`, `scripts/collect_kalshi_data.py`, `.github/workflows/collect.yml`,
GitHub API (`gh run list`, Pages builds).
