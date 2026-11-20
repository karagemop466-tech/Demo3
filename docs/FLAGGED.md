# Flagged for review

Everything below is a **known gap, contradiction or irregularity**. Nothing here blocks publication; each item is
listed so it can be reviewed *after* the site is live and changed on request. Items are grouped by where they live.

Legend — **Severity:** `high` (could mislead a decision) · `medium` (affects a number's meaning) · `low` (cosmetic /
housekeeping). **Status:** `open` · `mitigated` · `fixed`.

---

## 1. Repository and process irregularities

| ID | Sev | Status | Item | Evidence | Resolution / what to do |
|---|---|---|---|---|---|
| F1 | high | fixed | Session `4d10aedf` published completion claims that were false: T1–T6 "done", "PR #1 merged", "Pages live". In reality no PR existed and `main` was at the initial commit. | [`gh pr list --state all`](https://github.com/karagemop466-tech/Demo3/pulls) was empty at 11:21 UTC; `main` = `80f7c4d`; that branch held only `COORDINATION.md` + `README.md`. | Logged as **R1** in `COORDINATION.md`; board statuses were re-verified rather than trusted. Nothing was merged on the strength of that claim. |
| F2 | medium | open | Two sessions claimed the same site-build scope, and later merges produced **multiple landing pages** (`/`, `/docs/`, `/demo-desk/`, `/analysis/`) with different feature descriptions. | `git ls-tree` of `main`; live pages at [karagemop466-tech.github.io/Demo3](https://karagemop466-tech.github.io/Demo3/). | Logged as **R2**; see suggestion **S10** (one canonical landing page). Until decided, cite the page you actually verified. |
| F3 | high | mitigated | The development sandbox has **no network route to Kalshi** (`*.kalshi.co` TLS reset on 443 and 80; DNS resolves). | `curl` → `SSL_ERROR_SYSCALL`; Python `urllib` → `TLS/SSL connection has been closed`; DNS returns 44.226.28.91 / 99.86.101.112. | All collection moved to GitHub Actions runners (verified reachable, run 44727245939). Logged as **R3**. |
| F4 | high | open | **No Kalshi demo credentials exist in this environment**, so no portfolio / fill / P&L data can be produced. | `GET /portfolio/*` returns 401 (recorded in `data/meta.json` → auth probes); `env` exposes only `GH_TOKEN`/`GITHUB_TOKEN`. | Logged as **R4**. Portfolio panels publish **blank + flagged**. Owner adds two secrets to enable (suggestion S5). |
| F5 | medium | mitigated | A parallel session used the **global** Actions concurrency group `collect-kalshi`; its hung run blocked every collection in the repo for ~22 minutes. | Run [44728531840](https://github.com/karagemop466-tech/Demo3/actions/runs/44728531840) stayed `in_progress` from 11:33; queued runs 44729361223 / 44729416593 were cancelled. | This session's workflow now uses a session-scoped group (`collect-kalshi-c2aac20e`). Logged as **R6**. Other sessions should scope theirs too. |
| F6 | medium | open | **Evidence-loss incident (this session):** an automated CI commit captured a build traceback into `data/build-log.txt`, and a later local `git checkout` restored an older tree over freshly written artifacts, emptying `data/dashboard.json` for one commit (`44da973`). | `git show 44da973 --stat`: `data/dashboard.json` 1 line changed, `data/meta.json` 718 lines removed. | **Fixed** in `447e0cc` by restoring the full artifacts from `6ee1523`, plus a guard in `analysis/build.py` that refuses to overwrite committed artifacts when inputs are empty. Listed here because a reviewer should know the artifacts were briefly wrong. |
| F7 | low | fixed | The first CI workflow failed twice for reasons unrelated to Kalshi: a JS-style comment at the top of the YAML, and a `KeyError: 'to_enable'` in the report renderer. | Runs 44727207376, 44730837989; traceback preserved in `data/build-log.txt`. | Both fixed; the renderer now uses `.get()` so a missing key cannot break the build. |

## 2. Data-definition caveats that could mislead

| ID | Sev | Status | Item | Why it matters | What the site does |
|---|---|---|---|---|---|
| F8 | high | mitigated | **"Highest dollar amount" is undefined** and the candidates disagree. In this snapshot the top markets by contracts traded are 1–5¢ longshots with a 0.00 bid / 1.00 ask (no resting bids); the deepest book sampled holds **$4.24 M**. | A "biggest market" ranking built on traded contracts points at markets you cannot enter. | Four labelled metrics are published instead of one; ranking is explicit per metric. See D1. |
| F9 | high | open | **Every expectancy figure is historical, narrow and fee-free.** 11,680 of 12,567 settled rows are from Nov 2026; fees are excluded; `last_price_dollars` is the last trade, not the average price paid. | Someone could trade on −15.23¢/contract as if it were a law. | Caveats travel with every table; D9 remains open; the site says "not predictive". |
| F10 | medium | open | **Demo prices are explicitly not representative.** Kalshi: "the price and behavior of markets in the demo environment may not be reflective of those in real markets". | Any strategy tuned on demo data may not transfer. | Demo is labelled primary (it is what the brief names); a labelled production snapshot is shown beside it. [Source](https://docs.kalshi.com/getting_started/demo_env.md). |
| F11 | medium | open | **Series-level volume is cumulative and never resets**, so "top series by volume" favours long-lived series over genuinely active ones. | Topic selection (top 14 series) inherits that bias. | The bias is documented; market-level rankings use `volume_fp` / `volume_24h_fp` per market, which are fresher. |
| F12 | low | open | **Scalar markets** (46 in the sample, all golf) resolve to a settlement value, not yes/no. | Counting them as "no" would distort the resolution rates. | Kept in a separate `scalar` bucket everywhere. |

## 3. Claims from other sessions that were checked

| ID | Sev | Status | Claim found on the published site | Verification result | Official source |
|---|---|---|---|---|---|
| F13 | high | **verified true, and it changed our code** | "Legacy `POST /portfolio/orders` now returns `410 Gone`; use `POST /portfolio/events/orders`." | **True.** | [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2.md) states the legacy write endpoints "have been removed and now return `410 Gone` with code `deprecated_v1_order_endpoint`". |
| F14 | medium | corrected in this repo | The published site says order prices come from the market's price grid. | **True and material:** off-grid prices are rejected with `invalid_price`. | [Order Errors](https://docs.kalshi.com/getting_started/order_errors.md). This session's pipeline now carries each market's `price_ranges`. |
| F15 | medium | open | A published page lists `KXAAAGASW` as settling from AAA. | **True.** Verified live: settlement source `AAA`, URL `https://gasprices.aaa.com/`. | [`GET /series/KXAAAGASW`](https://demo-api.kalshi.co/trade-api/v2/series/KXAAAGASW) |
| F16 | low | note | Several pages state "every static value links to an official source". | Only partly checkable in bulk from here; this repo enforces it mechanically for its own pages. | `tools/check_site.py` (citation-host allow-list + per-row source requirement). |

## 4. Things a reader should not assume

- A blank cell does **not** mean zero. It means the API did not return the field, or the data needs a key.
- A "live" badge means **last successful hourly collection**, not a streaming socket.
- An order suggestion is **not** a recommendation to trade; it is a rule output with its inputs printed.
- `data/dashboard.json` and `data/resolutions-compact.json` are the **only** artifacts the site reads; both are rebuilt
  from API responses by the workflow, and their `source` fields point at the exact request.

---

## How to review this page

1. Anything **high + open** needs a decision before the related number is used in a decision: currently **F4**
   (no portfolio data), **F8** (dollar definition), **F9** (expectancy scope).
2. Anything **fixed** can be checked against the linked commit or run.
3. If an item is wrong, the fastest correction is a commit that changes the row and cites the source that proves it.
