# `paper-desk/` — automated simulated trading desk (subsite)

Self-contained GitHub Pages subsite: **no file outside `paper-desk/`, `trading/paper_*`,
`scripts/{build,verify}_paper_desk.py`, `data/paper/` and `.github/workflows/paper-desk.yml`
is written by this feature**, and no shared navigation is edited (a nav entry is requested on
`COORDINATION.md` as CR-eb2af75b-1 for the integration session).

| Page | Contents |
|---|---|
| `index.html` | equity, cash, realized/unrealized P&L, fills vs. rejections, the five rules under test, recent cycles and equity samples |
| `trades.html` | the full simulated journal: every order, its quote context, its classification, its outcome, and the API row it came from |
| `positions.html` | open positions marked at the published bid, resting simulated orders, orderbook ladders (contracts resting at each price), plus a **live panel** that calls the demo API from the browser |
| `analysis.html` | performance grouped by strategy, topic, side, price band and family; auto-derived trade-type ranking; API politeness counters; disclosed limitations |
| `resolutions.html` | every tracked market that resolved, with the market's own `result` (yes/no), settlement timestamp and the desk's realized P&L |
| `methodology.html` | config in force, one-cycle walkthrough, the official source for each mechanic, flagged items F-EB2-01…07 |
| `sources.html` | replayable API requests, doc register, repo files, universe provenance, exclusions |

## Data provenance

Rendered data comes only from `data/paper/*.json`, written by `trading/paper_engine.py`
against `https://external-api.demo.kalshi.co/trade-api/v2` (public, unauthenticated).
Full source register and the verbatim doc language: [`SOURCES.md`](SOURCES.md).

## Rules used by the build (enforced by `scripts/verify_paper_desk.py`)

1. every table row carries the exact API URL of the record that produced it, or an explicit
   `unverified` marker — values are never back-filled;
2. no absolute `localhost` links, external hosts restricted to official Kalshi / GitHub docs;
3. the "simulated" label and the demo-account caveat appear on every page;
4. `paper-desk/tests/dom.test.mjs` (jsdom, mocked `fetch`) proves the live panel renders a row
   per market, flags a ≥ $0.10 change since the last desk cycle, and shows **no** prices when a
   request fails.

## Rebuild / check locally

```bash
python3 trading/test_paper_engine.py -v          # 25 offline tests, mocked responses
python3 trading/paper_engine.py run               # one live cycle (needs egress to the demo API)
python3 scripts/build_paper_desk.py               # regenerate the pages
python3 scripts/verify_paper_desk.py              # links + per-row sources + JS syntax
node --test paper-desk/tests/dom.test.mjs         # DOM smoke test (npm i jsdom)
```

Automation runs on a schedule in CI (`*/20 * * * *`, default branch). Scheduled workflows do not
run on non-default branches, so pre-merge cycles are started with **Actions → Paper desk
(automated simulated trading) → Run workflow**
([GitHub's schedule doc](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#onworkflow_callsschedule-cron)).
