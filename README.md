# Kalshi Demo Market Monitor

A GitHub Pages-friendly, read-only dashboard blueprint for Kalshi's **demo** Trade API. It monitors live markets in five requested themes, keeps resolved-market outcomes visible when the API returns them, and documents what is and is not verifiable before trading decisions.

## Executive summary

- **Official demo REST base:** `https://external-api.demo.kalshi.co/trade-api/v2`; Kalshi also documents `https://demo-api.kalshi.co/trade-api/v2` as supported.
- **Official demo WebSocket:** `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`; the supported legacy host is `wss://demo-api.kalshi.co/trade-api/ws/v2`.
- Public market data is fetched directly from the documented demo REST API when the browser/network allows it. The site makes no claims about live data until a fetch succeeds; it shows a connection/error state otherwise. GitHub Pages is static and does not provide a server-side proxy.
- Market price, market status, event category/title, settlement result and order-book price-level sizes are displayed only when supplied by the API. The category mapping uses event metadata/text and is a discovery filter—not a verified taxonomy. Category matches must be reviewed.
- The “largest” board is ranked by the official 24-hour contract-volume field (contracts), **not by dollar turnover**. A defensible dollar-volume ranking is not confirmed from the fields used here; it is flagged rather than inferred. Event-level aggregates are also not substituted for market-level data.
- The chart samples the official latest market price during this page session. It is not a backfilled historical time series; browser refresh clears the captured series. Interval and visible history are user-selectable.
- Portfolio, fills, strategy performance and order execution require authenticated demo-account access. This static site deliberately does not request/store API private keys in the browser and does not place orders. An authenticated server-side signing service, account authorization, least-privilege key management, trade limits, and explicit human trade approval are required before those features can safely exist.

## Run / publish

Open `index.html` locally. GitHub's Pages API currently reports this repository is configured to publish the root of `main` using its legacy branch build, at [karagemop466-tech.github.io/Demo3](https://karagemop466-tech.github.io/Demo3/). The dashboard and `executive-summary.html` will be served by that existing configuration after the changes reach `main`; no Actions deployment workflow is added, to avoid conflicting with the repository's current Pages mode. The `executive-summary.html` page provides an on-site summary with a linked official-source index.

The live-data browser requests may be blocked by CORS, network policy, or demo service availability. If so, use the error state and consult the official API directly; no fabricated sample market rows are included.

## Official references checked

| Reference | What it verifies |
|---|---|
| [API environments and endpoints](https://docs.kalshi.com/getting_started/api_environments) | Demo REST and WebSocket host names; separate demo and production environments/credentials. |
| [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) | Market status and market fields including price, volume, result, and timestamps. |
| [Get Events](https://docs.kalshi.com/api-reference/events/get-events) | Event title and category fields. |
| [Get Market Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) | YES/NO bid price levels and fixed-point contract quantities; no order counts. |
| [Quick Start: Market Data](https://docs.kalshi.com/getting_started/quick_start_market_data) | Public REST market-data examples and order-book field shapes. |
| [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) | WebSocket handshake authentication and market-data channel behavior. |
| [Get Balance](https://docs.kalshi.com/api-reference/portfolio/get-balance) | Authenticated balance and portfolio-value endpoint. |
| [Get Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions) | Authenticated positions and position fields. |
| [Get Fills](https://docs.kalshi.com/api-reference/portfolio/get-fills) | Authenticated fills endpoint. |
| [Quick Start: Create your first order](https://docs.kalshi.com/getting_started/quick_start_create_order) | Authenticated order creation flow. |

API contracts can change; re-check linked documentation before implementation or any trading. This dashboard is for demo-market observation, not investment advice.
