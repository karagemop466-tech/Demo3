# `paper-desk/` — automated simulated trading desk (source register)

Subsite of the Kalshi demo project. Everything on these pages is either (a) a value the
official Kalshi **demo** REST API returned, or (b) arithmetic on such values, performed by
`trading/paper_engine.py`. The ledger is **simulated** — it is not a Kalshi account, and no
order is ever sent.

## Data flow

```
data/latest/top_events.json      (collector snapshot; five focus topics)
        │  universe: top events per topic × top markets per event
        ▼
trading/paper_engine.py ── GET /markets?tickers=…  (live demo quotes, batched)
        │                   GET /markets/{ticker}/orderbook?depth=6 (at decision time)
        ├── trading/paper_strategies.py  (five deterministic rules + exits)
        ▼
data/paper/{state,trades,equity,analysis,resolutions,runs,books,sources}.json
        ▼
scripts/build_paper_desk.py → paper-desk/*.html   (published by GitHub Pages)
        ▼
scripts/verify_paper_desk.py  (links, per-row sources, JS syntax)
paper-desk/tests/dom.test.mjs (jsdom + mocked fetch: the live panel never invents values)
```

Automation: `.github/workflows/paper-desk.yml` (cron `*/20 * * * *` on the default branch,
plus `workflow_dispatch`).

## Official sources for every mechanic (all fetched 2026-11-20)

| # | Claim on the site | Official source | What the source says (verbatim, abridged) |
|---|---|---|---|
| 1 | Demo REST root used by the desk | <https://docs.kalshi.com/getting_started/demo_env.md> | "Demo's recommended Trade API root is `https://external-api.demo.kalshi.co/trade-api/v2`." Also: "The price and behavior of markets in the demo environment may not be reflective of those in real markets." |
| 2 | Public market data needs no key | <https://docs.kalshi.com/getting_started/quick_start_market_data.md> | `# Get the first open market (no auth required for public market data)` |
| 3 | `tickers=` returns every match in one response | <https://docs.kalshi.com/api-reference/market/get-markets.md> | "When `event_ticker` or `tickers` is the only filter … every matching market is returned in one response, in no guaranteed order. `limit` is not applied and the returned `cursor` is empty." |
| 4 | Quotes can lag the exchange | <https://docs.kalshi.com/api-reference/market/get-markets.md> | "Responses are cached for a short time, so prices, sizes and `status` can lag the exchange by several seconds." |
| 5 | Bid/ask/size field meanings | <https://docs.kalshi.com/api-reference/market/get-markets.md> | `yes_bid_dollars` "Price for the highest YES buy offer …"; `yes_ask_dollars` "Price for the lowest YES sell offer …"; `yes_bid_size_fp` "Total contract size of orders to buy YES at the best bid price"; `yes_ask_size_fp` "…to sell YES at the best ask price"; `last_price_dollars` "Price for the last traded YES contract" |
| 6 | `previous_*` fields are one-day references | <https://docs.kalshi.com/api-reference/market/get-market.md> | `previous_yes_bid_dollars` / `previous_yes_ask_dollars` / `previous_price_dollars` — each "…on this market **a day ago** in dollars" |
| 7 | Status enum vs query enum | <https://docs.kalshi.com/api-reference/market/get-markets.md> | Response `status`: `initialized, inactive, active, closed, determined, disputed, amended, finalized`; the `status` **query** filter: `unopened, open, paused, closed, settled` |
| 8 | `result` values | <https://docs.kalshi.com/api-reference/market/get-markets.md> | `result` enum: `'yes' \| 'no' \| scalar \| ''` |
| 9 | Orderbook is bids-only, ascending, best = last | <https://docs.kalshi.com/getting_started/orderbook_responses.md> | "Arrays are sorted by price in **ascending order**; The **highest** bid (best bid) is the **last** element"; an empty book returns empty arrays (200, not 404) |
| 10 | YES-bid ⇄ NO-ask reciprocity (used to size NO entries) | <https://docs.kalshi.com/getting_started/orderbook_responses.md> | "A **YES BID** at price X is equivalent to a **NO ASK** at price (\$1.00 − X)"; "Best YES ask: \$1.00 − (Highest price in the `no_dollars` array)" |
| 11 | Settlement payout rule | <https://docs.kalshi.com/getting_started/market_settlement.md> | "Yes outcome: Yes contract holders receive \$1 per contract. No outcome: No contract holders receive \$1 per contract." / "Settlement fees are zero for simple yes/no determinations" |
| 12 | `notional_value_dollars`, `settlement_value_dollars`, `settlement_ts` | <https://docs.kalshi.com/api-reference/market/get-market.md> | "The total value of a single contract at settlement in dollars" / "The settlement value of the YES/LONG side … Only filled after determination" |
| 13 | Contract/price number format | <https://docs.kalshi.com/getting_started/fixed_point_migration.md> via the schemas in <https://docs.kalshi.com/api-reference/market/get-market.md> | `FixedPointDollars`: string, "responses emit up to 6" decimals; `FixedPointCount`: "responses always emit 2 decimals … minimum granularity is 0.01 contracts" |
| 14 | Valid order prices per market | <https://docs.kalshi.com/api-reference/market/get-markets.md> | `price_ranges` — "Valid price ranges for orders on this market"; a price off that grid would be rejected as `invalid_price` (<https://docs.kalshi.com/getting_started/quick_start_create_order.md>) |
| 15 | Candlestick path, granularity, limits | <https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md> | `/series/{series_ticker}/markets/{ticker}/candlesticks`; `period_interval` "Valid values: 1 (1 minute), 60 (1 hour), 1440 (1 day)"; "One request can span at most 5,000 periods"; `start_ts`/`end_ts` in **seconds** |
| 16 | `series_ticker` needed for candles comes from the event | <https://external-api.demo.kalshi.co/trade-api/v2/events/KXPRESNOMD-28> (live response, 2026-11-20) | `event.series_ticker: "KXPRESNOMD"`, `event.category: "Elections"`, `settlement_sources[].url` |
| 17 | Rate-limit policy this desk follows | <https://docs.kalshi.com/getting_started/rate_limits.md> | "Unauthenticated public requests are subject to separate limits. Authenticate requests where supported and back off on `429`." No public number for unauthenticated traffic is published, so none is claimed here |
| 18 | Order shape mirrored by the simulation (nothing is sent) | <https://docs.kalshi.com/getting_started/quick_start_create_order.md> | `POST /portfolio/events/orders` with `{"ticker","side":"bid"|"ask","count":"1","price":"0.0100","time_in_force":"good_till_canceled","self_trade_prevention_type":"taker_at_cross","client_order_id":…}`; "A `201` means the order was accepted, not that it is resting: check `remaining_count`" |
| 19 | Demo account creation / keys (why account data is still blank) | <https://docs.kalshi.com/getting_started/demo_env.md>, <https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account>, <https://docs.kalshi.com/getting_started/api_keys.md> | Demo account + API key are created by a person in the demo site; "credentials are not shared between this environment and production" |
| 20 | GitHub: scheduled workflows run on the default branch | <https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#onworkflow_callsschedule-cron> | "The `schedule` workflow triggers on the default branch" |
| 21 | GitHub: Pages rebuild request after a bot push | <https://docs.github.com/en/rest/pages/pages#request-a-github-pages-build> | `POST /repos/{owner}/{repo}/pages/builds` (used because `GITHUB_TOKEN` pushes do not trigger the legacy Pages build) |

## Live captures taken while building this (replayable)

| Captured 2026-11-20 | URL | What it proves |
|---|---|---|
| Batch quotes | <https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=KXPRESNOMD-28-AOC,KXBTCY-27JAN0100-B122500,KXAAAGASM-26NOV30-4.70,KXPGATOUR-THRC26-TMOO,KXOSCARPIC-27-DIG> | five markets returned in one unpaged response; two-sided quotes with sizes exist on elections/golf, while the crypto/gas rows show `yes_ask_dollars 1.0000` with `0.00` size → the desk must reject, not fill |
| Orderbook | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-AOC/orderbook?depth=4> | `orderbook_fp.yes_dollars` / `no_dollars` `[price, size]` pairs, ascending |
| Hourly candles | <https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-AOC/candlesticks?start_ts=1795182000&end_ts=1795203600&period_interval=60> | six candles, `price.close_dollars`, `yes_bid`/`yes_ask` OHLC, `volume_fp`, `open_interest_fp` |
| Empty candle window | <https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-AOC/candlesticks?start_ts=1763654400&end_ts=1763740800&period_interval=60> | `{"candlesticks":[],"ticker":…}` with HTTP 200 — an empty chart is a real answer, so the page says "the exchange published no candles for this window" |
| Event record | <https://external-api.demo.kalshi.co/trade-api/v2/events/KXPRESNOMD-28> | `event.series_ticker`, `category`, `settlement_sources[].url` |
| Exchange status | <https://external-api.demo.kalshi.co/trade-api/v2/exchange/status> | `exchange_active: true`, `trading_active: true`, shards 0–3 |

## Explicitly NOT claimed

- No Kalshi endpoint publishes dollar volume; the snapshot's `volume_dollars_derived` is a
  labelled derivation (`volume_fp × notional_value_dollars`) inherited from the collector — the
  desk uses it only to order the universe, never as a performance figure.
- No news/catalyst attribution: the public API has no causal feed, so the desk records the
  market's own `rules_primary` and `settlement_sources` only (flag F-EB2-06).
- No fees: `fees_modeled: false`; realized P&L is gross (flag F-EB2-03).
- No demo-account data: balance/positions/fills stay blank while no demo API credentials exist
  (`data/latest/portfolio.json` → `credentials_missing`, flag F-EB2-01).
- Seconds-granularity history does not exist in the API (1/60/1440-minute candles only), so the
  "live seconds" chart is explicitly browser-sampled (flag F-EB2-04).
