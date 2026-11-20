# Official sources and verification register

Checked: 2026-11-20 (UTC). Primary evidence is limited to Kalshi's official developer documentation, official API responses, and Kalshi Help Center pages. No third-party market commentary or guessed market values are used.

| ID | What this source verifies | Official source |
|---|---|---|
| S1 | Recommended and supported demo REST and WebSocket base URLs; separate demo/production credentials; request signing path rules. | [API Environments and Endpoints](https://docs.kalshi.com/getting_started/api_environments) |
| S2 | Public market-data requests do not require authentication; example use of JavaScript `fetch`, events, markets, and orderbook. | [Quick Start: Market Data](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| S3 | Event `category`, `settlement_sources`, nested markets, event-status filters, cursor pagination, and the fact the status filter matches child markets. | [Get Events](https://docs.kalshi.com/api-reference/events/get-events) |
| S4 | Market fields, contract-count volume fields, prices, status filters, pagination, and market rules/results in the response schema. | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) |
| S5 | A single-market lookup and the market response fields, including prices, volume, open interest, result, rules, and settlement timestamps. | [Get Market](https://docs.kalshi.com/api-reference/market/get-market) |
| S6 | Public aggregated YES/NO bid price levels and contract counts; `depth=0` means all levels. | [Get Market Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) |
| S7 | Official candlestick endpoint, OHLC price fields, and supported interval values of 1, 60, or 1440 minutes. | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) |
| S8 | REST market lifecycle statuses and meanings; `open` filter maps to `active`; `closed`/`determined` are not yet finalized; `finalized` is terminal; result can be YES, NO, or scalar. | [Market Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle) |
| S9 | YES/NO settlement outcomes, payout timing variability, and settlement rules. | [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement) |
| S10 | Market ticker WebSocket fields including `dollar_volume` and `dollar_open_interest`, and the requirement to authenticate the WebSocket connection. | [Market Ticker WebSocket](https://docs.kalshi.com/websockets/market-ticker) |
| S11 | WebSocket handshake authentication requirement, even when using a channel carrying public market data. | [WebSocket Connection](https://docs.kalshi.com/websockets/websocket-connection) |
| S12 | REST/WebSocket request-signing requirements, API-key handling, private-key storage warnings, scopes, and permissions. | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |
| S13 | End-to-end signed-request example for the demo account and balance endpoint. | [Quick Start: Authenticated Requests](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests) |
| S14 | Create-order endpoint, required signed headers, `write::trade` scope, and the V2 order request/response fields. | [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2) |
| S15 | Demo portfolio balance endpoint and balance/portfolio-value response fields. | [Get Balance](https://docs.kalshi.com/api-reference/portfolio/get-balance) |
| S16 | Demo portfolio positions endpoint, settled/unsettled filters, and position P&L/exposure fields. | [Get Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions) |
| S17 | Demo portfolio fills endpoint and fill fields, including quantity, side, price, fee, and creation time. | [Get Fills](https://docs.kalshi.com/api-reference/portfolio/get-fills) |
| S18 | Demo portfolio settlement records and market result fields. | [Get Settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements) |
| S19 | Official demo account is separate from production and uses mock funds; setup is an account-owner action. | [Creating and using a demo account](https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account) |
| S20 | Market-specific rules and the authoritative outcome-verification source must be checked for each contract. | [Market Rules](https://help.kalshi.com/en/articles/13823822-market-rules) |
| S21 | Close time is not necessarily determination time; official-source confirmation and contract rules govern settlement. | [Market FAQs](https://help.kalshi.com/en/articles/13823821-market-faqs) |
| S22 | A direct read-only spot check of the official demo event endpoint with nested markets. This is a live endpoint, not a stored dataset. | [Demo API: open events](https://external-api.demo.kalshi.co/trade-api/v2/events?limit=2&status=open&with_nested_markets=true) |
| S23 | A direct read-only spot check of the official demo market endpoint. This is a live endpoint, not a stored dataset. | [Demo API: open markets](https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=1&status=open) |

## Verification notes

- The demo API base URLs in the official documentation match the demo URLs supplied in the request. The recommended REST host is `https://external-api.demo.kalshi.co/trade-api/v2`; the supported alternative is `https://demo-api.kalshi.co/trade-api/v2`. The recommended WebSocket host is `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`; the supported alternative is `wss://demo-api.kalshi.co/trade-api/ws/v2` (S1).
- Official public-market-data documentation demonstrates unauthenticated GET requests and browser `fetch` (S2). This supports the read-only market-data design. It does not prove that every browser/origin is allowed by Kalshi's current CORS policy; browser-origin connectivity remains explicitly flagged until tested from the deployed Pages origin.
- `GET /markets` documents volume and open-interest fields as fixed-point contract quantities. Its documented response schema does not define a REST `dollar_volume` or `dollar_open_interest` field (S4, S5). The documented ticker WebSocket message does include dollar-denominated volume/open-interest fields (S10), but establishing the WebSocket connection requires signed API-key authentication (S11). Therefore the public static dashboard does not invent or display dollar-volume ranks.
- The market lifecycle guide clarifies a possible naming trap: the request filter `status=open` returns REST market status `active`; `closed` and `determined` are not the same as terminal `finalized` settlement (S8). A YES/NO result should only be labeled resolved after the market is finalized and its `result` is YES or NO. Scalar results are not mislabeled as YES/NO (S8).
- Kalshi's candlestick endpoint is documented for 1-minute, 1-hour, and 1-day periods (S7). The optional seconds-scale graph is therefore a local sample of REST observations, not an official second-level exchange candle. The graph must disclose its polling/sampling cadence.
- The official demo API spot checks (S22, S23) were read-only, taken 2026-11-20 UTC, and are not included as static table values. Market availability and values can change after the check.
- The repository initially contained only a one-line README and no application, data tables, tests, configuration, or deployment workflow. There was no pre-existing implementation to verify line-by-line.
