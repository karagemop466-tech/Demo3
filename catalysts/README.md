# Swing &amp; catalyst ledger (`catalysts/`)

Implements one brief line that nothing else on the site covers:

> "Live charts should include events and website links that may have caused a sharp jump in
> contract price, greater than or equal to $0.10 in either direction."

`main` had swing *alert chats* (added by PR #28) and a price chart, but no link between a swing and
anything that may have caused it — `grep -ril catalyst` returned nothing before this directory was
added, and the competing PR #27 explicitly declined to build it. This layer builds it, and keeps
every attribution auditable.

## Layout

| Path | What it is |
|---|---|
| `scan.py` | Detection + enrichment + catalyst matching + strategy scoring. stdlib only. |
| `feeds.json` | News-feed allowlist. Every entry is `pending_ci_probe` until a run parses items from it. |
| `index.html`, `assets/*` | The page: run status, live watch, filters, price chart with swing markers, ledger, strategy table, feed health, endpoint probe, flags. |
| `data/` | Artifacts written by the scan and committed so the page renders without any network access. |
| `tests/test_scan.py` | 36 offline unit/integration tests against a mock demo API + mock feed. |
| `tests/check_page.py` | Publish gate: exact-decimal re-check of every published swing, link provenance, broken-local-link check, strategy arithmetic. |
| `tests/smoke.mjs` | jsdom render test of the page, including the browser-side ≥ $0.10 rule and the "no verdict below the sample floor" rule. |
| `../.github/workflows/catalysts.yml` | Runs tests, probes, scan every 15 min; commits `data/`; asks Pages to rebuild. |

## What "may have caused" is allowed to mean here

1. **Swing** — consecutive samples of the *same* market, `|last − previous| ≥ $0.10`, exact decimal
   dollars (`Decimal`), either direction. Float arithmetic is never used for the threshold.
2. **Window** — a news item only qualifies if its publish timestamp falls inside
   `[swing start − 180 min, swing end + 60 min]` (configurable: `CATALYST_WINDOW_PRE_MIN`,
   `CATALYST_WINDOW_POST_MIN`).
3. **Relevance** — the item title must share ≥ 2 significant words with the market/series title, or
   one word of ≥ 6 letters. The matched words are published with the link, so the reader judges the
   hit; the code never calls it a cause.
4. **Fail closed** — no qualifying item ⇒ empty cell plus a machine-readable reason
   (`items_in_window_but_no_keyword_overlap`, `no_feed_item_in_window`, `no_feed_items_available`,
   `feeds_not_polled_offline`). A feed that a run could not parse contributes nothing and is listed
   as *not usable* in the health table. Nothing is back-filled from memory or from a previous run.
5. **Provenance per row** — each swing links its market record
   (`GET /markets/{ticker}`), its event (`GET /events/{event_ticker}`) and its series
   (`GET /series/{series_ticker}`); the series' own `settlement_sources` — the outlets Kalshi itself
   cites for that series — are shown separately from the news candidates.
6. **Resolution** — a market is polled until the API reports `status: finalized/settled` with
   `result: yes|no`; the result and `settlement_value_dollars` are published and the market is then
   dropped from the watchlist (`data/watch_state.json`).

## Verified live against the official demo API (this session, 2026-11-20)

| Request | Result |
|---|---|
| `GET /exchange/status` | HTTP 200 — `exchange_active: true`, `trading_active: true`, shards "Default / Demo shard 1 / Demo shard 2" all trading. |
| `GET /markets/KXDEMOFUTHOURLY-26NOV20H12-UP?include_historical_prices=false` | HTTP 200 — `status: "finalized"`, `result: "no"`, `last_price_dollars: "0.6500"`, `settlement_value_dollars: "0.0000"`, `volume_fp: "8220.00"`, `open_interest_fp: "30.00"`, `title: "Demo BTC at or above 61985.83 USD"`. This is the market the seeded ledger row came from, so the row's `to` price (0.6500) and its NO result are confirmed against the exchange record, not just against the tape. |
| `GET /markets?tickers=A,B` (one existing, one not) | HTTP 200 — only the existing ticker is returned; missing tickers are silently omitted, which is why the scan re-queries them with `status=settled` instead of assuming. |
| `GET /events?event_tickers=KXDEMOFUTHOURLY-26NOV20H12&with_nested_markets=false` | HTTP 200 but **the filter is ignored** — unrelated events (e.g. `KXELONMARS-99`) came back. Flagged as F-cat-05; no code path relies on that filter. |
| `GET /series?limit=3&category=Crypto` | HTTP 200, **`limit` not honoured** (the whole category page came back). Corroborates F9 from session `6908a11a`; flagged as F-cat-06. Series objects do carry `settlement_sources`, which the layer publishes. |

Docs pages used for the field and endpoint semantics:
[demo environment](https://docs.kalshi.com/getting_started/demo_env) ·
[API environments](https://docs.kalshi.com/getting_started/api_environments) ·
[market data, no auth](https://docs.kalshi.com/getting_started/quick_start_market_data) ·
[Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) ·
[Get Market](https://docs.kalshi.com/api-reference/market/get-market) ·
[Get Events](https://docs.kalshi.com/api-reference/market/get-events) ·
[Get Series](https://docs.kalshi.com/api-reference/market/get-series) ·
[Get Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) ·
[Market settlement](https://docs.kalshi.com/getting_started/market_settlement) ·
[fixed-point fields](https://docs.kalshi.com/getting_started/fixed_point_migration) ·
[WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets)

## Running it

```bash
python3 catalysts/tests/test_scan.py -v      # offline, mock demo API + mock feed
python3 catalysts/scan.py --offline          # tape-only (works with no egress)
python3 catalysts/scan.py                    # live: poll demo API, probe feeds, refresh links
python3 catalysts/scan.py --probe-endpoints  # record official-endpoint statuses for the page
python3 catalysts/tests/check_page.py        # publish gate
npm ci && node catalysts/tests/smoke.mjs     # headless render test
```

`--offline` is not a mock: it is the real detection path over the committed price tape
(`data/history/prices.jsonl`, written by the repo collector every 10 minutes), with enrichment from
the committed demo-API snapshots (`data/latest/topic_*.json`, `data/resolutions.json`). Rows keep
their snapshot's `source_url`, so an offline artifact is still traceable to an official request.

## Limits a reviewer must know (see the page's Flagged section, F-cat-01…07)

* Detection is bounded by the sampling gap; the WebSocket channel would close it but its handshake
  needs `KALSHI-ACCESS-*` headers a browser cannot send, so this stays polling-based.
* The demo exchange is a testing environment (officially: prices/behaviour may not reflect real
  markets), so a demo "jump" may have no real-world cause at all. Links remain candidates.
* The feed allowlist could not be probed from the build sandbox (its egress allowlist is
  github.com / npmjs.org / pypi.org only), which is why nothing here claims a feed works — the
  scheduled probe decides, and the health table shows the truth.
* Simulated strategy figures are gross of fees/spread and are marked *not evaluable* below 30
  trades per category.
