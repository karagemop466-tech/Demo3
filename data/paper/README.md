# `data/paper/` — simulated trading ledger (machine-written, do not hand-edit)

Written by `trading/paper_engine.py` on a schedule in `.github/workflows/paper-desk.yml`
and rendered by `scripts/build_paper_desk.py` into `paper-desk/`.

Every file records its own provenance: `source_url` / `source_urls` fields carry the exact
`https://external-api.demo.kalshi.co/trade-api/v2/...` request that produced the values.
Anything the exchange did not publish is `null` (rendered as *unverified*), never an estimate.

| File | Contents |
|---|---|
| `state.json` | mode (`simulated-paper`), `data_mode` (`live-api` vs `offline-fixtures`), config in force, cash, open positions, resting simulated orders, last recorded quote per tracked market |
| `trades.json` | the journal: every simulated open / close / settle / reject / rest / cancel with quote context, classification (topic x side x price band x strategy) and realized P&L |
| `equity.json` | one sample per desk cycle: cash, position value at the published bid, equity, realized, unrealized |
| `analysis.json` | totals, group summaries (strategy / topic / side / price band / family / action), auto-derived trade-type ranking, universe coverage, API politeness counters, caveats |
| `resolutions.json` | markets that resolved: the market's own `result` (yes/no), `settlement_ts`, `expiration_value`, the desk side, outcome and realized P&L |
| `books.json` | orderbook snapshots taken at decision time (`GET /markets/orderbooks`), bids-only, best level last |
| `runs.json` | per-cycle operational log (requests, errors, intents, fills, rejects, settlements, equity) |
| `sources.json` | the doc register, api root, universe provenance and the synthetic-series exclusion list |

## Accounting rules actually applied

- fill price: the published best ask (buy) or best bid (sell) for the traded side —
  `yes_ask_dollars` / `yes_bid_dollars` / `no_ask_dollars` / `no_bid_dollars`;
- fill size: never more than `yes_ask_size_fp` / `yes_bid_size_fp` (the documented size at
  the touch) and never more than the per-trade risk cap; if either is 0 the order is a
  **rejection with a reason**, not a fill;
- NO-side size uses the documented YES-bid <-> NO-ask reciprocity
  (`docs.kalshi.com/getting_started/orderbook_responses.md`), not a guess;
- settlement: $1 per winning contract, or `settlement_value_dollars` when published
  (`docs.kalshi.com/getting_started/market_settlement.md`);
- maker orders rest and only fill if a later cycle shows the published ask at or below the
  limit; otherwise they expire after `max_resting_runs` cycles;
- no fees (flagged F-EB2-03), no leverage, no shorting beyond buying the opposite side.

## Reproduce

```bash
python3 trading/paper_engine.py run            # one cycle against the live demo API
python3 trading/paper_engine.py status         # ledger totals
python3 scripts/build_paper_desk.py            # regenerate paper-desk/
```
