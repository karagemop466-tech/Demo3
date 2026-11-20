# Kalshi demo — market analytics, live dashboard and trade tracking

A working project against the **Kalshi demo** Trade API (`https://external-api.demo.kalshi.co/trade-api/v2`):
it ranks the highest-dollar live events in five topics, follows each one until it resolves, charts price and
order-book depth, keeps a portfolio ledger, categorises every fill and turns that into strategy verdicts —
and publishes all of it as a static dashboard where **every number links to the API call that produced it**.

**Dashboard:** https://karagemop466-tech.github.io/Demo3/ ·
**Flagged/unverified list:** https://karagemop466-tech.github.io/Demo3/flagged.html

---

## 1. Executive summary

| Requirement | State | Where |
|---|---|---|
| (a) Summary of important details | ✅ 11 conclusions, 12 flagged irregularities, per-requirement feasibility | [`docs/executive-summary.md`](docs/executive-summary.md) |
| (b) Live dashboard of highest-dollar events, filtered to gas prices · elections · culture · crypto · golf | ✅ ranking derived from the trade tape; topic map verified against the official taxonomy | [`site/dashboard.html`](site/dashboard.html), [`site/topics.html`](site/topics.html) |
| (c) Track events until resolution, record yes/no | ✅ append-only resolution ledger keyed by market ticker | [`site/events.html`](site/events.html), `data/resolutions.json` |
| (d) Portfolio performance on the demo account, categorised trades, strategies by trade type | ⚠️ model + categorisation complete; **live reads blocked** on credentials | [`site/portfolio.html`](site/portfolio.html), [`site/strategies.html`](site/strategies.html) |
| (e) Execute trades and track performance | ⚠️ V2 engine complete and validating; **never sent an order** — no key exists here | [`scripts/trade_engine.py`](scripts/trade_engine.py) |
| (f) Live interactive charts, X axis in seconds/minutes/hours, Y axis contract price, plus liquidity per price | ✅ with one honest limit: seconds is client-sampled | [`site/dashboard.html`](site/dashboard.html) |
| (g) Suggestions section + questions list with known/missing/discovery paths | ✅ 14 suggestions, 14 questions | [`site/suggestions.html`](site/suggestions.html), [`site/questions.html`](site/questions.html) |

Six findings that shaped the design — each verified against the official docs, linked in
[`docs/api-surface.md`](docs/api-surface.md):

1. **There is no dollar-volume field.** `volume_fp` is *contracts*. Dollars are computed from the tape as
   `Σ count_fp × taker-side price`, and the formula is printed next to every figure.
2. **No Culture category and no retail-gasoline category exist** in Kalshi's taxonomy; both topics are
   labelled substitutions rather than quietly mapped ([FLAG-03](docs/executive-summary.md)).
3. **No sub-minute price history.** `period_interval` accepts only 1/60/1440 minutes, so a seconds axis is
   browser-sampled and labelled as such.
4. **The order book is bids-only by design**; asks are derived as `$1 − best opposite bid` and labelled *implied*.
5. **Every WebSocket connection needs a signed handshake**, public channels included — a browser cannot do it,
   which is why the bridge exists.
6. **The demo tape looks synthetic** (120 fills in ~179 ms, repeating round sizes). The pipeline is real; the
   market signal is not, and the site says so.

## 2. Layout

```
site/                     static dashboard (this is what Pages serves)
  index.html              landing: verified snapshot, constraints, status
  dashboard.html          leaderboard · chart (sec/min/hour/day) · liquidity ladder
  events.html             live state and the resolution ledger
  topics.html             topic → official selectors, with match quality
  portfolio.html          balance, positions, fills, P&L, derivation table
  strategies.html         categorisation by trade type + two scoreboards
  suggestions.html          review-before-implement, decisions stored locally
  questions.html          open questions: known · missing · how to find out
  flagged.html            irregularities + every value left blank, with repro commands
  api.html                every endpoint used and unused, with parameters and limits
  sources.html            citation registry, verified/unverified
  assets/                 styles.css · api.js · ui.js · chart.js
  data/live_snapshot.json generated: the single document the pages fetch
scripts/
  kalshi_api.py           credential-ready signed client (RSA-PSS + Ed25519, openssl fallback)
  collect.py              universe → tape ranking → events/markets/depth/candles → resolutions
  aggregate_capture.py    re-derives every dollar figure from the raw capture (never hand-typed)
  publish_snapshot.py     assembles site/data/live_snapshot.json + provenance per section
  build_site.py           copies data into the site, fails on a broken link or invalid JSON
  verify_site.py          pre-merge gate: links, sources, parsing, honesty checks
  dev_server.py           local static server + allow-listed signed /proxy bridge
  trade_engine.py         V2 order lifecycle: plan / paper / --execute, grid + size validation
  portfolio.py            signed balance/positions/fills → P&L, with a labelled paper fallback
  analyze.py              per-trade categorisation + inferred and declared strategy scoreboards
  gen_scenario.py         builds a paper-order scenario from captured quotes only
  gen_questions_doc.py    renders docs/questions.md from data/questions.json
data/                     snapshots, captures, ledgers, topic map, citation registry
docs/                     executive summary · API surface · requirements traceability · questions
COORDINATION.md           multi-session task board with claims and file scopes
.github/workflows/        deploy-pages.yml
```

## 3. Run it

Serve the built site (snapshot mode, no network needed):

```bash
python3 scripts/dev_server.py --port 8081
# http://localhost:8081/            snapshot mode
# http://localhost:8081/dashboard.html?mode=bridge   live mode through the bridge
```

Refresh the dataset where egress to `kalshi.co` is available, then rebuild and gate:

```bash
python3 scripts/collect.py --window-minutes 1440 --pages 20 --top 60
python3 scripts/aggregate_capture.py --write
python3 scripts/publish_snapshot.py
python3 scripts/build_site.py
python3 scripts/verify_site.py          # exit 1 = do not deploy
```

Trade (plan → paper → real, all gated):

```bash
python3 scripts/trade_engine.py --plan buy KXPGATOUR-THRC26-HLEB --count 5 --price 0.0300
python3 scripts/trade_engine.py --paper --from-snapshot data/live_snapshot.json \
        --bulk data/scenarios/paper-first-pass.json buy
export KALSHI_API_KEY_ID=… KALSHI_PRIVATE_KEY_PEM_PATH=./kalshi_demo.pem   # never commit or paste
python3 scripts/kalshi_api.py auth-check
python3 scripts/trade_engine.py --execute buy <ticker> --count 1 --price 0.0100
python3 scripts/portfolio.py refresh --marks-from-snapshot data/live_snapshot.json
python3 scripts/analyze.py
```

Dependencies: Python 3.9+ standard library only. `cryptography` enables in-process signing; without it the
client shells out to `openssl`. No `requirements.txt` is needed, and nothing is installed to view the site.

## 4. The honesty contract

This is the part to check first, because it is the part that makes the numbers usable:

* **No inferred values.** A field the API did not return is rendered `—` with class `unverified`, and appears
  on [`flagged.html`](site/flagged.html) with the reason it is blank. `UI.table` enforces this structurally.
* **Every row is linked.** Each table row carries `source`, the exact API URL that produced it;
  `UI.src()` renders it. A row with no source is a build failure.
* **Derived numbers say they are derived.** Dollar volume, flow imbalance, position value and
  `portfolio_value` in dollars each print their formula and their inputs.
* **Paper is never presented as exchange.** Every simulated fill is tagged `paper`; the engine refuses to
  send to a non-demo host; `illustrative_fee_not_a_quote` is named that way deliberately.
* **Third parties are never verification.** Only Kalshi's own hosts can support a claim; sources Kalshi names
  in `settlement_sources` are recorded as *what the exchange points at*, marked `verified: false`.
* **The gate runs in CI.** `verify_site.py` blocks the Pages deploy if a link is broken, a citation is
  unregistered, JSON would not parse in a browser, or a published aggregate disagrees with the raw capture.

## 5. Known limitations (not caveats — the actual state)

| Limitation | Why | Effect |
|---|---|---|
| No demo API key exists in this repo | creating one needs an account; no manual input was available | `/portfolio/*` never called; orders never sent; portfolio runs in labelled paper mode |
| Dollar figures rank a 53-second capture | sandbox blocks egress to `kalshi.co`; reads came through an agent fetch path and are archived in `data/raw/` | ranking method is proven; treat the magnitudes as a sample, not a daily total |
| Seconds axis is client-sampled | the candles API has no sub-minute period | fine-grained history is not retrievable for past windows, by anyone |
| WebSocket streaming needs the bridge | signed handshake, impossible in a browser | live mode runs locally, not on the Pages deploy |
| CORS for the demo host is undocumented | Kalshi publishes no statement | the deployed site may fall back to the snapshot banner; that path is built and labelled |
| Strategy verdicts are all “insufficient data” | 5 paper fills, 0 settled outcomes in the ledger | the scoreboard is wired and will fill itself as markets resolve |

## 6. Multi-session coordination

[`COORDINATION.md`](COORDINATION.md) is the task board: session ids, claimed tasks, non-overlapping file
scopes, a 60-minute stale-claim takeover rule, and shared outputs written only by the integration session.
Before pushing, `git pull --rebase`; status changes go in the board, not in ad-hoc files.

## 7. About the demo environment

Kalshi's own warning, verbatim: *“The price and behavior of markets in the demo environment may not be
reflective of those in real markets.”* Demo keys never work on production and production keys never work on
demo; the demo account carries mock funds. Everything here is built for that environment and the code refuses
to treat it otherwise — see [`getting_started/demo_env.md`](https://docs.kalshi.com/getting_started/demo_env.md).

No credentials, tokens or private keys are committed anywhere in this repository.
