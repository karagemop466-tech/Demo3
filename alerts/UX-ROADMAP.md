# UX roadmap — swing-alert console

What is shipped, what is deliberately not, and what to build next, in the order that buys the most
trust per hour of work. "Shipped" means it is in `alerts.html` + `assets/alert-console.js` and
covered by a test; "not shipped" means the console does not pretend to do it.

## Shipped in v1 (this branch)

| area | what the user gets | why it was prioritised |
|---|---|---|
| Two chats | every ≥ $0.10 swing on the left, model-approved picks on the right, both scrolling newest-last with auto-scroll + a "jump to latest" button and a "new messages" pill | the brief asked for two feeds; the pair also makes the model's rejections visible instead of hiding them |
| Same rule as the backtest | the browser engine is `assets/swing-core.js`, the identical module the Python scanner mirrors, pinned by reference vectors | an alert you cannot reproduce offline is a demo |
| Per-row provenance | API request link, candlestick-request link, orderbook-request link, labelled candidate-news search | the site-wide rule: a row without a source link fails the build |
| Selected-market panel | candles + live samples on one axis, alert markers, YES-bid ladder with the mirrored NO ask, recent fills, settlement rule verbatim, official settlement sources | "how big was the move and was it tradeable" is one click, not five |
| Resolution register | live re-poll records `result`, `settlement_ts`, `settlement_value_dollars`, once per market, linked | the brief asks for tracking until resolution and how it resolved |
| Backtest table | per-strategy means, gross vs net, hit rate, quotable/unquotable counts, per-bucket best strategy | shows why the ROI chat is empty |
| Honesty rails | rate-limit backoff + hidden-tab pause, `not confirmed` event links, "(estimate)" labels, `unverified` pills, blank cells never filled in | a dashboard that guesses is worse than one that shrugs |
| Sound + desktop notifications | off by default, opt-in, only beep when the tab is hidden for notifications | alerts are useless if you must stare at the page |

## Next, in order

1. **Notification routing rules** — per-topic and per-bucket thresholds, "only when |Δ| > X and depth ≥ Y
   contracts", quiet hours. Today a pick beeps like a rejection on the left chat; the data to separate
   them is already on the row.
2. **Replay of the live window** — a scrubbable timeline over `state.samples` (kept for the session,
   4 000 points/market) so a reviewer can step through the samples that produced an alert and see the
   re-arm band at work. The engine already stores everything needed; only the control is missing.
3. **Cause side-by-side** — the CI already knows each series' `settlement_sources`; the missing piece
   is a fetcher (sandbox has no route, so a workflow step or a user-supplied API key) that snapshots
   the referenced feed and prints the *published value with its timestamp* next to the alert. Until
   then the console says "candidate", and that gap is the honest answer to "find news that explains
   the move".
4. **Depth at the moment of the alert** — order books are only available now, so an alert's executability
   is scored from the nearest book sample; persist the book per poll (ring buffer) and score against the
   sample closest to `ts`, with the lag shown in milliseconds.
5. **Alert grouping** — collapse the same leg repeated across 1-min / 60-min views of one market into
   one row with two sub-lines, instead of two rows that look like double counting.
6. **Mobile density** — the chats are readable at 380 px, the chart + depth pair is not; stack them and
   make the depth ladder a `<details>` on narrow viewports.
7. **Export formats** — "Export session JSON" exists; add CSV for the register and a shareable
   `?state=` link (cfg + tickers, no secrets) so a review can be reproduced by URL.
8. **Accessibility pass** — the feeds are `<ol aria-live="polite">` with text-only colour coding; still
   needed: focus styles on rows, a keyboard path from a chat row to its market panel, and a
   prefers-reduced-motion mode that stops auto-scroll animation.

## Deliberately not built

* **Order placement or any trade action.** The brief is a research console; the demo API would accept
  authenticated order endpoints, and this page holds no key and sends nothing but GETs.
* **A WebSocket feed.** The handshake requires `KALSHI-ACCESS-*` headers a browser cannot attach
  ([WebSockets quick start](https://docs.kalshi.com/getting_started/quick_start_websockets.md)), so the
  console polls REST and states the cadence.
* **A backtester that can be tuned to profit.** The gate uses fixed bucket definitions and a fixed fee
  model; there is no slider for "assumed fill" or "ignore fees". If the numbers say no edge, the ROI
  chat stays empty.
* **News-as-cause.** No headline is ever presented as the reason a price moved; only the exchange's own
  settlement reference is treated as authoritative.
* **Distracting live counters** (animated tickers, sparklines per row). They cost requests for no
  evidence value; the chart in the detail panel already answers "what did the path look like".

## Definition of done for v2 items

Each item above must arrive with: a test in `tests/alert_console.test.js` (jsdom, mocked API) or
`scripts/tests/test_scan_swings.py`; its source link on every affected row; a line in `alerts/SPEC.md`;
and, if it changes any published number, a re-run of `Swing scan` so `data/swings/*.json` and
`alerts/model.json` cannot drift from the code that reads them.
