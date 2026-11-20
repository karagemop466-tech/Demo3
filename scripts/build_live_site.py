#!/usr/bin/env python3
"""Build the Live Alert Desk pages in live/ (static HTML, no framework).

Pages are generated so the nav, the source register and the numbers stay
consistent; the interactive parts live in live/assets/*.js and read the JSON in
live/data/. Run:  python3 scripts/build_live_site.py

Every table row on every page carries a link to the official Kalshi API request
or docs page behind it, or is rendered blank with an 'unverified' marker
(scripts/verify_live_site.py enforces this after the build).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE = ROOT / "live"
DATA = LIVE / "data"
API = "https://external-api.demo.kalshi.co/trade-api/v2"
DOCS = "https://docs.kalshi.com"

NAV = [
    ("index.html", "Home"),
    ("dashboard.html", "Dashboard"),
    ("gas.html", "Gas"),
    ("elections.html", "Elections"),
    ("culture.html", "Culture"),
    ("crypto.html", "Crypto"),
    ("golf.html", "Golf"),
    ("graph.html", "Graph &amp; liquidity"),
    ("tracking.html", "Resolution tracking"),
    ("strategies.html", "Strategies"),
    ("portfolio.html", "Simulated portfolio"),
    ("suggestions.html", "Suggestions"),
    ("methodology.html", "Methodology"),
    ("flagged.html", "Flagged for review"),
    ("sources.html", "Sources"),
]

TOPIC_PAGES = {"gas": "gas.html", "elections": "elections.html",
               "culture": "culture.html", "crypto": "crypto.html", "golf": "golf.html"}
TOPIC_LABEL = {"gas": "Gas prices", "elections": "Elections", "culture": "Culture",
               "crypto": "Crypto", "golf": "Golf"}

CSS = "assets/site.css"


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def load(name, default=None):
    p = DATA / name
    if not p.exists():
        return default
    return json.loads(p.read_text())


def shell(title, active, body, scripts=("assets/desk.js",), desc=""):
    nav = "".join(
        '<a href="%s"%s>%s</a>' % (href, ' class="active"' if href == active else "", label)
        for href, label in NAV)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Kalshi Live Alert Desk</title>
<meta name="description" content="{esc(desc or 'Live swing-alert desk for the Kalshi demo exchange: gas, elections, culture, crypto, golf.')}">
<link rel="stylesheet" href="{CSS}">
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="index.html">Kalshi <span>Live Alert Desk</span></a>
<nav class="main">{nav}</nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="wrap">
<p><strong>Kalshi Live Alert Desk</strong> — asks only about the Kalshi <em>demo</em> exchange
(<span class="mono">{API}</span>). Every table row links its official source request; values that
cannot be confirmed are left blank and listed on <a href="flagged.html">Flagged for review</a>.
Simulated trades are labelled SIMULATED everywhere and are never sent to Kalshi.</p>
<p class="small">Official docs:
<a href="{DOCS}/getting_started/demo_env" target="_blank" rel="noopener">demo environment</a> ·
<a href="{DOCS}/getting_started/quick_start_market_data" target="_blank" rel="noopener">market data without auth</a> ·
<a href="{DOCS}/api-reference/market/get-market-candlesticks" target="_blank" rel="noopener">candlesticks</a> ·
<a href="{DOCS}/api-reference/market/get-market-orderbook" target="_blank" rel="noopener">orderbook</a> ·
<a href="{DOCS}/getting_started/market_settlement" target="_blank" rel="noopener">settlement</a>.
Other views in this repo: <a href="../index.html">canonical tracker</a> ·
<a href="../docs/">docs archive</a> · <a href="../demo-desk/">demo desk</a> ·
<a href="../analysis/">analysis</a>.</p>
</footer>
{''.join(f'<script src="{s}"></script>' for s in scripts)}
</body>
</html>
"""


def write(name, title, active, body, scripts=("assets/desk.js",), desc=""):
    (LIVE / name).write_text(shell(title, active, body, scripts, desc))
    return name


def table(headers, rows, caption=None, note=None, cls=""):
    head = "".join(f'<th class="{("num" if h.startswith("#") else "")}">{h.lstrip("#")}</th>'
                   for h in headers)
    body = "".join("<tr>" + "".join(f'<td class="{("num" if h.startswith("#") else "")}">{c}</td>'
                                    for h, c in zip(headers, r)) + "</tr>" for r in rows)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="muted">No rows.</td></tr>'
    cap = f"<caption class=\"small muted\" style=\"text-align:left;padding:6px 0\">{caption}</caption>" if caption else ""
    nt = f'<p class="small muted">{note}</p>' if note else ""
    return (f'<div class="table-scroll"><table class="{cls}">{cap}<thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>{nt}")


def src_link(url, label="source"):
    if not url:
        return '<span class="chip warn">unverified — no source</span>'
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)}</a>'


def meta_card(label, value, note=""):
    return (f'<div class="card tight"><div class="label">{label}</div>'
            f'<div class="stat sm">{value}</div><div class="note">{note}</div></div>')


def cents(x):
    return "—" if x is None else f"{x * 100:.1f}¢"


def dollars(x):
    if x is None:
        return "—"
    a = abs(x)
    if a >= 1e9:
        return f"${x / 1e9:.2f}B"
    if a >= 1e6:
        return f"${x / 1e6:.2f}M"
    if a >= 1e3:
        return f"${x / 1e3:.1f}k"
    return f"${x:.2f}"


def build():
    meta = load("meta.json")
    markets = load("markets.json", {"markets": []})
    alerts = load("alerts.json", {"alerts": []})
    roi = load("alerts_roi.json", {"alerts": []})
    candles = load("candles_index.json", {"markets": {}, "count": 0})
    trades = load("trades.json", {"trades": [], "strategies": []})
    books = load("portfolio.json", {"books": []})
    res = load("resolutions.json", {})
    review = load("review.json", {"flags": [], "verified": []})
    mrows = markets.get("markets", [])
    arows = alerts.get("alerts", [])
    rrows = roi.get("alerts", [])
    built = esc(meta.get("generated_at", ""))
    n_alerts = meta["counts"]["alerts"]
    pages = []

    # ---------------------------------------------------------------- landing
    counts = meta["counts"]
    cov = meta.get("candle_coverage", {})
    biggest = meta.get("largest_move_by_topic", {})
    body = f"""
<h1>Kalshi Live Alert Desk</h1>
<p class="muted">A live desk for the Kalshi <strong>demo</strong> exchange covering five topics only —
<strong>gas prices, elections, culture, crypto, golf</strong>. It ranks the highest-dollar live
events, alerts on any price swing of at least $0.10 in either direction in two scrolling streams,
tracks events until they resolve YES or NO, and runs auto-simulated trades to test strategies
against the same official data.</p>
<div class="banner"><span class="pulse warn"></span><span id="liveStatus">checking the demo API…</span>
<span class="small muted"> — data snapshot built {built}</span></div>
<div class="grid g4" id="statGrid"></div>
<p class="small muted" id="coverageNote"></p>

<div class="card">
<h2>What to look at first</h2>
<div class="grid g2">
<div>
<h3>1 · The two alert streams</h3>
<p class="small">Both stream every swing ≥ $0.10 with the contract, direction, both prices, the
window, volume and links to the exact official candlestick request plus a headline search for that
timestamp.</p>
<ul class="small">
<li><a href="dashboard.html#alerts">All swing alerts</a> — every alert in the five topics.</li>
<li><a href="dashboard.html#alerts">High-ROI alerts</a> — the same events filtered by the
documented EV model (EV ≥ $0.03 per contract and ROI ≥ 10%).</li>
</ul>
<h3>2 · Highest-dollar events by topic</h3>
<p class="small">Each topic has its own page with its events grouped together (see the topic nav).
Dollar volume is <em>derived</em> (contracts × notional) because the trade API publishes no
dollar-volume field — flagged as L-03.</p>
</div>
<div>
<h3>3 · Price graph &amp; liquidity</h3>
<p class="small">The <a href="graph.html">graph page</a> plots contract price against time with
windows from 30 seconds to 30 days, and shows how many contracts are available at each price from
the orderbook.</p>
<h3>4 · Resolution tracking</h3>
<p class="small"><a href="tracking.html">Resolution tracking</a> keeps every event until it settles
and records how it resolved — YES or NO — with the settlement source.</p>
<h3>5 · Simulated strategies</h3>
<p class="small">Three strategies trade automatically on the collected candlesticks
(<a href="strategies.html">strategies</a>, <a href="portfolio.html">portfolio</a>). No credentials
exist in this repo, so nothing is ever sent to Kalshi; every fill says SIMULATED.</p>
</div>
</div>
</div>

<div class="card">
<h2>Live events with the highest derived dollar amount</h2>
<p class="small muted">Top line per topic by derived dollar volume (contracts × notional value).
Ranking is per topic so no single topic crowds out the others.</p>
{table(["Topic", "Top event / contract", "Price", "#Derived $ volume", "Liquidity", "Closes", "Source"],
       [[f'<span class="chip t-{m["topic"]}">{TOPIC_LABEL[m["topic"]]}</span>',
         f'<span class="mono">{esc(m["ticker"])}</span><div class="small muted">{esc(m["sub_title"] or m["title"])}</div>',
         cents(m["price"]), dollars(m["volume_dollars_derived"]),
         f'{int(m["liquidity"]["top_of_book_contracts"] or 0):,}' if m.get("liquidity") else "—",
         esc((m.get("close_time") or "")[:16].replace("T", " ")),
         src_link(m["market_url"], "Get Markets")]
        for m in sorted([x for x in mrows if x.get("is_top_dollar_in_topic")],
                        key=lambda x: list(TOPIC_LABEL).index(x["topic"]))],
       note="Every row's source request returns that exact market from the demo exchange.")}
</div>

<div class="card">
<h2>Live status of this build — what is live and what is a snapshot</h2>
<div class="grid g3">
{meta_card("Snapshot built", f'<span class="mono small">{built}</span>',
           "Built from the committed collector snapshots; the scheduler refreshes them.")}
{meta_card("Swing alerts (≥ $0.10)", f'{counts["alerts"]:,}',
           f'{counts["alerts_high_roi"]:,} passed the high-ROI model filter')}
{meta_card("Contracts with candles", f'{counts["candle_markets"]:,}',
           " · ".join(f"{k}: {v}" for k, v in cov.items()))}
{meta_card("Resolved markets tracked", f'{counts["resolved_markets"]:,}',
           "settled markets in the five topics, YES/NO recorded")}
{meta_card("Simulated trades", f'{counts["simulated_trades"]:,}',
           "across 3 strategies · paper only, nothing sent to Kalshi")}
{meta_card("Alert threshold", f'${meta["threshold_dollars"]:.2f}',
           "step close-to-close or intrabar high-to-low")}
</div>
<p class="small muted">Live polling: the dashboard calls the public demo API from your browser and
says so when it succeeds or is blocked. The committed snapshot is always shown with its timestamp,
never presented as live data. Reason: the browser cannot open an authenticated Kalshi WebSocket
(flag L-10), and some networks block the API (flag L-01).</p>
</div>

<div class="card">
<h2>How this keeps itself honest</h2>
<ul class="small">
<li>Every table row has a source link, or says <span class="chip warn">unverified</span>.</li>
<li>Derived numbers are labelled <em>derived</em>; modelled numbers (ROI model, simulated fills)
say <em>model</em> or <em>SIMULATED</em> and publish their formula on
<a href="methodology.html">Methodology</a>.</li>
<li>Irregularities are published with evidence links on
<a href="flagged.html">Flagged for review</a> — currently {len(review.get("flags", []))} items.</li>
<li>The scripts that rebuild every number are in this repo:
<code>scripts/build_live_candles.py</code>, <code>scripts/build_live_data.py</code>,
<code>scripts/verify_live_site.py</code>.</li>
</ul>
</div>
"""
    pages.append(write("index.html", "Home", "index.html", body,
                       scripts=("assets/desk.js", "assets/dashboard.js")))

    # -------------------------------------------------------------- dashboard
    body = f"""
<h1>Live dashboard</h1>
<p class="muted">Highest-dollar live events in the five topics, two scrolling alert streams, live
swings from browser polling, the price graph with selectable windows, liquidity and resolution
tracking. <span class="small" id="deskVersion"></span></p>
<div class="banner" id="banner"><span class="pulse warn"></span><span id="liveStatus">checking the demo API…</span>
<span class="small" id="liveCount"></span></div>
<p class="small muted" id="thresholdNote"></p>
<p class="small muted" id="roiNote"></p>
<p class="small muted" id="snapshotNote"></p>

<div class="card" id="alerts">
<h2>The two alert streams</h2>
<p class="small muted">Left: every swing ≥ $0.10. Right: the same alerts that pass the model filter.
New alerts are prepended, so the newest is always at the top; both streams pause and resume on
demand and keep the full history in memory for the session.</p>
<div class="chatgrid">
<div id="chatAll"></div>
<div id="chatRoi"></div>
</div>
<div class="toolbar">
<label class="small muted">Filter the left stream by topic
<select id="chatTopicFilter"><option value="all">all topics</option>
<option value="gas">gas</option><option value="elections">elections</option>
<option value="culture">culture</option><option value="crypto">crypto</option>
<option value="golf">golf</option></select></label>
<span class="small muted">Price data: <a href="{DOCS}/api-reference/market/get-market-candlesticks" target="_blank" rel="noopener">candlesticks</a> ·
headline links: <a href="methodology.html#causation">the association is unverified</a></span>
</div>
</div>

<div class="card" id="graph">
<h2>Selected market — price graph (x = time, y = contract price)</h2>
<p id="detailTitle" class="muted">Pick any contract from a topic table below or the dropdown.</p>
<p class="small muted" id="detailMeta"></p>
<div class="toolbar">
<label class="small muted">Ticker
<select id="obTicker"></select></label>
</div>
<div class="seg" id="windowSeg" role="group" aria-label="Chart window"></div>
<canvas id="priceChart" height="270" aria-label="Contract price against time"></canvas>
<p class="small muted" id="chartCaption"></p>
</div>

<div class="card">
<h2>Liquidity — contracts available at each price</h2>
<p class="small muted">Orderbook levels from
<a href="{DOCS}/api-reference/market/get-market-orderbook" target="_blank" rel="noopener">Get Market Orderbook</a>:
the response publishes YES bids and NO bids; a NO bid at price P is a YES ask at (1 − P), which is
how the depth chart is built. Green bars are YES bids, red bars are NO bids shown at their
YES-equivalent price.</p>
<canvas id="depthChart" height="230" aria-label="Orderbook depth by price"></canvas>
<p class="small" id="obSummary"></p>
<div id="obTable"></div>
</div>

<div class="card" id="topics">
<h2>Tracked lines by topic</h2>
<p class="small muted">Topics are kept separate and each topic's events are grouped together.
Rows are the top-dollar lines per topic plus every contract that has committed candlestick history.
Click a ticker to load it in the graph.</p>
<div id="topicTables"></div>
</div>

<div class="card" id="resolutions">
<h2>Resolution tracking (YES / NO)</h2>
<p class="small muted">Open events stay listed until they settle; resolved events show how they
resolved. Full settlement data: <a href="../data-tracking.html">the collector's tracking page</a>.</p>
<div id="resolutionBody"></div>
</div>

<h3>Recent trades</h3>
<div id="tradesTable" class="card"></div>
"""
    pages.append(write("dashboard.html", "Dashboard", "dashboard.html", body,
                       scripts=("assets/desk.js", "assets/dashboard.js")))

    # ------------------------------------------------------------ topic pages
    for tid, page in TOPIC_PAGES.items():
        rows = [m for m in mrows if m["topic"] == tid]
        arows_t = [a for a in arows if a["topic"] == tid]
        rrows_t = [a for a in rrows if a["topic"] == tid]
        resolved = [r for r in res.get("resolved_markets", []) if r["topic"] == tid]
        totals = (res.get("totals_by_topic") or {}).get(tid, {})
        big = biggest.get(tid)
        events = {}
        for m in rows:
            events.setdefault(m.get("event_ticker") or m["ticker"], []).append(m)
        ev_cards = []
        for ev, ms in sorted(events.items(), key=lambda kv: -max(
                (x.get("volume_dollars_derived") or 0) for x in kv[1])):
            ms.sort(key=lambda x: -(x.get("volume_dollars_derived") or 0))
            ev_cards.append(
                f'<div class="card tight"><h3 style="margin-top:0">{esc(ms[0].get("event_title") or ev)}</h3>'
                f'<p class="small muted mono">{esc(ev)} · {len(ms)} markets · closes '
                f'{esc((ms[0].get("close_time") or "")[:16].replace("T", " "))} · '
                f'{src_link(ms[0]["event_url"], "event API")}</p>'
                + table(["Contract", "Price", "#Derived $ volume", "Contracts", "Liquidity", "Source"],
                        [[f'<span class="mono">{esc(x["ticker"])}</span>'
                          f'<div class="small muted">{esc(x["sub_title"] or "")}</div>',
                          cents(x["price"]), dollars(x["volume_dollars_derived"]),
                          f'{int(x.get("volume") or 0):,}', 
                          f'{int((x.get("liquidity") or {}).get("top_of_book_contracts") or 0):,}',
                          src_link(x["market_url"], "market")] for x in ms[:8]])
                + "</div>")
        alert_rows = [[esc(a["ts"]), f'<span class="mono">{esc(a["ticker"])}</span>',
                       f'<span class="chip {"up" if a["delta"] > 0 else "down"}">'
                       f'{"+" if a["delta"] > 0 else "−"}{cents(abs(a["delta"]))}</span>',
                       f'{cents(a["from_price"])} → {cents(a["to_price"])}',
                       esc(a["window"]) + (" " + '<span class="chip warn">no trades</span>'
                                           if a.get("zero_volume") else ""),
                       src_link(a["source_url"], "candles")] for a in arows_t[:80]]
        roi_rows = [[esc(a["ts"]), f'<span class="mono">{esc(a["ticker"])}</span>',
                     esc((a.get("roi") or {}).get("side", "").upper()),
                     cents((a.get("roi") or {}).get("ev")),
                     f'{(a.get("roi") or {}).get("roi_pct")}%',
                     cents((a.get("roi") or {}).get("cost")),
                     src_link(a["source_url"], "candles")] for a in rrows_t[:80]]
        resolved_rows = [[f'<span class="mono">{esc(r["ticker"])}</span>'
                          f'<div class="small muted">{esc(r["sub_title"] or r["title"])}</div>',
                          f'<span class="chip {r["result"]}">{r["result"].upper()}</span>',
                          cents(r["last_price"]), f'{int(r.get("volume_contracts") or 0):,}',
                          esc((r.get("settled_time") or "")[:16].replace("T", " ")),
                          src_link(r["source_url"], "settled market")] for r in resolved[:60]]
        cov = (candles.get("markets") or {})
        cov_rows = [[f'<span class="mono">{esc(t)}</span>',
                     esc(c.get("environment")),
                     " · ".join(f"{k} min: {v:,}" for k, v in (c.get("intervals") or {}).items()),
                     src_link(c.get("source_url"), "candles")] for t, c in cov.items()
                    if any(m["ticker"] == t for m in rows)]
        body = f"""
<h1><span class="chip t-{tid}">{TOPIC_LABEL[tid]}</span> {TOPIC_LABEL[tid]}</h1>
<p class="muted">Every tracked event in this topic, grouped by event, with the highest-dollar lines
first. Alert stream: swings ≥ $0.10 in either direction. Resolution: YES/NO once settled.</p>
<div class="grid g4">
{meta_card("Tracked lines", f"{len(rows)}", "top-dollar lines + candle-history contracts")}
{meta_card("Swing alerts ≥ $0.10", f"{len(arows_t)}", f"{len(rrows_t)} passed the high-ROI filter")}
{meta_card("Resolved markets", f"{totals.get('markets', 0):,}",
           f"{totals.get('yes', 0):,} YES · {totals.get('no', 0):,} NO")}
{meta_card("Largest 1-hour move",
           (f'{"+" if big["delta"] > 0 else "−"}{cents(abs(big["delta"]))}' if big else "—"),
           (f'{esc(big["ticker"])} at {esc(big["ts"])}' if big else "no hourly history"))}
</div>
{f'<div class="banner warn">No swing ≥ $0.10 was recorded for {TOPIC_LABEL[tid]} in the committed candlestick windows. The largest move actually observed is {cents(abs(big["delta"])) if big else "unknown"} on <span class="mono">{esc(big["ticker"])}</span> — shown for context, <strong>not</strong> as an alert. Details: <a href="flagged.html">flag L-12</a>.</div>' if big and abs(big["delta"]) < 0.10 else ''}

<div class="card">
<h2>Events in {TOPIC_LABEL[tid]} (grouped)</h2>
{"".join(ev_cards) or '<p class="muted">No open lines collected for this topic.</p>'}
</div>

<div class="card">
<h2>Alerts ≥ $0.10 — {TOPIC_LABEL[tid]}</h2>
{table(["Time (UTC)", "Contract", "#Move", "Prices", "Window", "Source"], alert_rows,
       note="Each row links the exact official candlestick request the alert was computed from.")}
</div>

<div class="card">
<h2>High-ROI model alerts — {TOPIC_LABEL[tid]}</h2>
{table(["Time (UTC)", "Contract", "Model side", "#EV / contract", "#ROI", "#Cost", "Source"], roi_rows,
       note="EV and ROI come from the documented model on <a href='methodology.html'>Methodology</a>; they are estimates, not guarantees.")}
</div>

<div class="card">
<h2>Resolved in {TOPIC_LABEL[tid]} (YES / NO)</h2>
{table(["Market", "Result", "#Last price", "#Volume", "Settled (UTC)", "Source"], resolved_rows)}
</div>

<div class="card">
<h2>Candlestick coverage for this topic</h2>
{table(["Contract", "Environment", "Candles by interval", "Source"], cov_rows,
       note="'production' rows were collected from the production endpoint and are labelled; the desk targets the demo exchange (flag L-11).")}
</div>
"""
        pages.append(write(page, TOPIC_LABEL[tid], page, body))

    # ------------------------------------------------------------ graph page
    tracked = sorted(mrows, key=lambda m: (list(TOPIC_LABEL).index(m["topic"]),
                                           -(m.get("volume_dollars_derived") or 0)))
    liq_rows = [[f'<span class="chip t-{m["topic"]}">{TOPIC_LABEL[m["topic"]]}</span> '
                 f'<span class="mono">{esc(m["ticker"])}</span>',
                 cents(m["price"]),
                 cents(m.get("yes_bid")), cents(m.get("yes_ask")),
                 f'{int((m.get("liquidity") or {}).get("yes_bid_size") or 0):,}',
                 f'{int((m.get("liquidity") or {}).get("yes_ask_size") or 0):,}',
                 f'{int((m.get("liquidity") or {}).get("open_interest") or 0):,}',
                 src_link(m.get("orderbook_url"), "orderbook")]
                for m in tracked[:120]]
    body = f"""
<h1>Graph &amp; liquidity</h1>
<p class="muted">Contract price against time on the x axis (window selectable from 30 seconds to
30 days; the labels switch to seconds, minutes, hours or days) and contract price in cents on the
y axis. Liquidity is the number of contracts available at each price from the orderbook.</p>

<div class="card">
<h2>Price graph</h2>
<p id="detailTitle" class="muted">Select a contract:</p>
<p class="small muted" id="detailMeta"></p>
<div class="toolbar"><label class="small muted">Ticker <select id="obTicker"></select></label></div>
<div class="seg" id="windowSeg" role="group" aria-label="Chart window"></div>
<canvas id="priceChart" height="300" aria-label="Contract price against time"></canvas>
<p class="small muted" id="chartCaption"></p>
<p class="small muted">Series: committed candlesticks
(<a href="{DOCS}/api-reference/market/get-market-candlesticks" target="_blank" rel="noopener">period_interval
1, 60 or 1440 minutes</a>). A gap in the line means the exchange reported no trade in that period —
it is never interpolated.</p>
</div>

<div class="card">
<h2>Liquidity now — contracts available at each price</h2>
<canvas id="depthChart" height="240" aria-label="Orderbook depth"></canvas>
<p class="small" id="obSummary"></p>
<div id="obTable"></div>
</div>

<div class="card">
<h2>Liquidity and quotes by line</h2>
<p class="small muted">Best quoted sizes and open interest, straight from the collector's snapshot of
<a href="{DOCS}/api-reference/market/get-markets" target="_blank" rel="noopener">Get Markets</a>
(<span class="mono">yes_bid_size_fp</span>, <span class="mono">yes_ask_size_fp</span>,
<span class="mono">open_interest_fp</span>). Blank cells mean the exchange published no value.</p>
{table(["Line", "#Price", "#YES bid", "#YES ask", "#Bid contracts", "#Ask contracts",
        "#Open interest", "Source"], liq_rows)}
</div>
"""
    pages.append(write("graph.html", "Graph and liquidity", "graph.html", body,
                       scripts=("assets/desk.js", "assets/dashboard.js")))

    # -------------------------------------------------------- tracking page
    totals = res.get("totals_by_topic", {})
    open_rows = [[f'<span class="chip t-{g["topic"]}">{TOPIC_LABEL[g["topic"]]}</span> '
                  f'{esc(g.get("event_title") or g.get("event_ticker"))}'
                  f'<div class="small muted mono">{esc(g.get("event_ticker"))}</div>',
                  f'{int(g.get("markets") or 0):,}',
                  esc((g.get("next_close") or "")[:16].replace("T", " ")),
                  src_link(f'{API}/events/{g.get("event_ticker")}', "event API")]
                 for g in (res.get("open_events") or [])[:200]]
    resolved_events = [[f'<span class="chip t-{g["topic"]}">{TOPIC_LABEL[g["topic"]]}</span> '
                        f'{esc(g.get("event_title") or g.get("event_ticker"))}'
                        f'<div class="small muted mono">{esc(g.get("event_ticker"))}</div>',
                        f'<span class="chip {g["outcome_side"]}">{g["outcome_side"].upper()}</span>',
                        f'{g.get("yes_count")} YES / {g.get("no_count")} NO',
                        f'{int(g.get("market_count") or 0):,}',
                        esc((g.get("settled_time") or "")[:16].replace("T", " ")),
                        src_link((g.get("markets") or [{}])[0].get("market_url") or
                                 f'{API}/markets?tickers=', "markets")]
                       for g in (res.get("resolved_events") or [])[:200]]
    rm = [[f'<span class="chip t-{r["topic"]}">{TOPIC_LABEL[r["topic"]]}</span> '
           f'<span class="mono">{esc(r["ticker"])}</span>'
           f'<div class="small muted">{esc(r["sub_title"] or r["title"])}</div>',
           f'<span class="chip {r["result"]}">{r["result"].upper()}</span>',
           cents(r["last_price"]), f'{int(r.get("volume_contracts") or 0):,}',
           esc((r.get("settled_time") or "")[:16].replace("T", " ")),
           src_link(r["source_url"], "settled market")]
          for r in (res.get("resolved_markets") or [])[:200]]
    body = f"""
<h1>Resolution tracking</h1>
<p class="muted">Events stay on this page until they settle. When a market settles the demo
exchange publishes <span class="mono">result</span> = <span class="mono">yes</span> or
<span class="mono">no</span> plus <span class="mono">settlement_ts</span>; that value is copied
verbatim. Settlement rule:
<a href="{DOCS}/getting_started/market_settlement" target="_blank" rel="noopener">$1 per winning
contract</a>.</p>
<div class="grid g4">
{''.join(meta_card(f'{TOPIC_LABEL[t]}', f'{v["markets"]:,}',
                   f'{v["yes"]:,} YES · {v["no"]:,} NO') for t, v in totals.items())}
</div>

<div class="card">
<h2>Open events — tracked until they resolve</h2>
{table(["Event", "#Markets", "Next close (UTC)", "Source"], open_rows,
       note="Grouped by topic then next close time. Each row's source is the official event record.")}
</div>

<div class="card">
<h2>Resolved events — how each event resolved</h2>
{table(["Event", "Outcome", "Market split", "#Markets", "Settled (UTC)", "Source"], resolved_events,
       note="Outcome is the majority result of the event's settled markets; the market split shows the exact YES/NO counts.")}
</div>

<div class="card">
<h2>Resolved markets (newest per topic)</h2>
{table(["Market", "Result", "#Last price", "#Volume", "Settled (UTC)", "Source"], rm,
       caption=esc(res.get("note") or ""))}
</div>
"""
    pages.append(write("tracking.html", "Resolution tracking", "tracking.html", body))

    # ----------------------------------------------------- strategies page
    strat_rows = [[f'<b>{esc(s["id"])}</b> {esc(s["name"])}', esc(s["rule"]),
                   src_link(f"{DOCS}/getting_started/market_settlement", "settlement rules")]
                  for s in trades.get("strategies", [])]
    PROV = (f'<a href="https://github.com/karagemop466-tech/Demo3/blob/main/live/data/portfolio.json" '
            f'target="_blank" rel="noopener">simulated book</a> · '
            f'<a href="{DOCS}/getting_started/market_settlement" target="_blank" rel="noopener">settlement</a>')
    book_rows = []
    for b in books.get("books", []):
        book_rows.append([f'<b>{esc(b["id"])}</b> {esc(b["name"])}', f'{b["trades"]:,}',
                          f'{b["closed"]:,}', f'{b["wins"]:,} / {b["losses"]:,}',
                          f'{b["win_rate_pct"] if b["win_rate_pct"] is not None else "—"}%',
                          dollars(b["realized_pnl"]), dollars(b["total_staked"]),
                          f'{b["return_on_stake_pct"] if b["return_on_stake_pct"] is not None else "—"}%',
                          dollars(b["max_drawdown"]), dollars(b["equity"]), PROV])
    cat_rows = []
    for b in books.get("books", []):
        for c in b.get("by_topic", []):
            cat_rows.append([f'{esc(b["id"])}', f'<span class="chip t-{c["key"]}">{TOPIC_LABEL.get(c["key"], c["key"])}</span>',
                             f'{c["trades"]:,}', f'{c["wins"]:,} / {c["losses"]:,}',
                             dollars(c["pnl"]),
                             f'{(100 * c["pnl"] / c["stake"]):.1f}%' if c.get("stake") else "—",
                             src_link(f"{DOCS}/getting_started/market_settlement", "docs")])
    band_rows = []
    for b in books.get("books", []):
        for c in b.get("by_price_band", []):
            band_rows.append([esc(b["id"]), esc(c["key"]), f'{c["trades"]:,}',
                              f'{c["wins"]:,} / {c["losses"]:,}', dollars(c["pnl"]), PROV])
    series_rows = []
    for b in books.get("books", []):
        for c in b.get("by_series", []):
            series_rows.append([esc(b["id"]), f'<span class="mono">{esc(c["key"])}</span>',
                                f'{c["trades"]:,}', f'{c["wins"]:,} / {c["losses"]:,}',
                                dollars(c["pnl"]), PROV])
    body = f"""
<h1>Strategies &amp; trade categories</h1>
<p class="muted">Three strategies trade the collected candlesticks automatically — there is no
manual input. Everything here is <strong>SIMULATED</strong>: fills are modelled at the quoted price,
exits at ±$0.10 or resolution, and no order is ever sent to Kalshi (no demo credentials exist in
this repository — flag L-07).</p>

<div class="card">
<h2>Strategy definitions</h2>
{table(["Strategy", "Rule (entry and exit)", "Source"], strat_rows,
       note="Rules are this project's, not Kalshi's; only the fill/settlement semantics come from the docs.")}
<details><summary>How a simulated fill is priced</summary>
<pre>entry  : taker at the candle's quoted side price (buy YES at the ask, buy NO at 1 − bid)
exit   : +$0.10 target · −$0.10 stop · or resolution ($1 for the winning side, $0 otherwise)
size   : contracts = $10 risk / $0.10 stop = 100 contracts per position
re-entry: same line and strategy at most once per 6 hours, never while a position is open
fees   : not modelled (no verified demo fee schedule) — flag L-06
source : {DOCS}/getting_started/market_settlement · {DOCS}/api-reference/market/get-market-candlesticks</pre>
</details>
</div>

<div class="card">
<h2>Performance by strategy</h2>
{table(["Strategy", "#Trades", "#Closed", "#W / L", "#Win rate", "#Realized P&L",
        "#Staked", "#Return on stake", "#Max drawdown", "#Equity", "Source"], book_rows,
       note="Equity starts at the simulated bankroll of $10,000 per strategy. P&L is simulated, not account performance.")}
</div>

<div class="card">
<h2>Trade categories — by topic</h2>
{table(["Strategy", "Topic", "#Trades", "#W / L", "#P&L", "#Return", "Source"], cat_rows)}
</div>

<div class="card">
<h2>Trade categories — by entry price band</h2>
{table(["Strategy", "Price band", "#Trades", "#W / L", "#P&L", "Source"], band_rows,
       note="Cheap (<30¢) longshots and expensive (>70¢) locks behave very differently; this table is the evidence.")}
</div>

<div class="card">
<h2>Trade categories — by series</h2>
{table(["Strategy", "Series", "#Trades", "#W / L", "#P&L", "Source"], series_rows)}
</div>
"""
    pages.append(write("strategies.html", "Strategies", "strategies.html", body))

    # ------------------------------------------------------ portfolio page
    trade_rows = [[esc(t["entry_ts"]), f'<span class="chip sim">SIMULATED</span>',
                   esc(t["strategy"]), f'<span class="mono">{esc(t["ticker"])}</span>',
                   f'<span class="chip t-{t["topic"]}">{TOPIC_LABEL.get(t["topic"], t["topic"])}</span>',
                   esc(t["side"].upper()), cents(t["entry_price"]), f'{int(t["contracts"]):,}',
                   dollars(t["stake"]), esc(t["exit_reason"]), cents(t["exit_price"]),
                   dollars(t["pnl"]), src_link(t["market_url"], "market")]
                  for t in trades.get("trades", [])[:400]]
    body = f"""
<h1>Simulated portfolio</h1>
<p class="muted">Portfolios for the three strategies, valued only from simulated fills. The Kalshi
demo <em>account</em> (balance, positions, fills) needs API credentials that this repository does
not have, so those values are left blank rather than invented — see
<a href="flagged.html">flag L-07</a> and the
<a href="{DOCS}/api-reference/portfolio/get-balance" target="_blank" rel="noopener">Get Balance</a>
endpoint that would supply them.</p>

<div class="card">
<h2>Strategy books</h2>
<div class="grid g3">
{''.join(f'''<div class="card tight"><div class="label">{esc(b["id"])} · {esc(b["name"])}</div>
<div class="stat">{dollars(b["equity"])}</div>
<div class="note">start {dollars(b["bankroll"])} · P&L {dollars(b["realized_pnl"])} ·
{esc(str(b["win_rate_pct"]) + "%")} win rate · {b["closed"]:,} closed</div>
<canvas data-equity="{esc(b["id"])}" height="130" aria-label="Equity curve {esc(b["id"])}"></canvas></div>'''
 for b in books.get("books", []))}
</div>
<p class="small muted">Equity curves are drawn from the closed simulated trades in time order
(<code>portfolio.json → books[].equity_curve</code>).</p>
</div>

<div class="card">
<h2>Demo account (unavailable without credentials)</h2>
{table(["Field", "Value", "Why", "Source"],
       [["Demo balance", '<span class="chip warn">unverified — blank</span>', "needs demo API key", src_link(f"{DOCS}/api-reference/portfolio/get-balance", "Get Balance")],
        ["Open positions", '<span class="chip warn">unverified — blank</span>', "needs demo API key", src_link(f"{DOCS}/api-reference/portfolio/get-positions", "Get Positions")],
        ["Fills", '<span class="chip warn">unverified — blank</span>', "needs demo API key", src_link(f"{DOCS}/api-reference/portfolio/get-fills", "Get Fills")],
        ["Orders", '<span class="chip warn">unverified — blank</span>', "needs demo API key", src_link(f"{DOCS}/api-reference/orders/get-orders", "Get Orders")]])}
<p class="small muted">To enable: create demo keys at demo.kalshi.co and add
<code>KALSHI_DEMO_API_KEY_ID</code> and <code>KALSHI_DEMO_PRIVATE_KEY</code> as repository secrets;
the existing <code>trade.yml</code> workflow then pulls the account automatically. This session was
told not to require manual input, and it never guesses account values.</p>
</div>

<div class="card">
<h2>Simulated trade blotter (newest 400)</h2>
{table(["Entry (UTC)", "Mode", "Strategy", "Contract", "Topic", "Side", "#Entry",
        "#Contracts", "#Stake", "Exit reason", "#Exit", "#P&L", "Source"], trade_rows,
       note="Every row is SIMULATED. The source column links the official market record for the contract.")}
</div>
"""
    pages.append(write("portfolio.html", "Simulated portfolio", "portfolio.html", body,
                       scripts=("assets/desk.js", "assets/portfolio.js")))

    # ----------------------------------------------------- suggestions page
    pages.append(write("suggestions.html", "Suggestions", "suggestions.html",
                       suggestions_body(mrows, arows, candles)))

    # ------------------------------------------------------- methodology
    pages.append(write("methodology.html", "Methodology", "methodology.html",
                       methodology_body(meta)))

    # ----------------------------------------------------------- flagged
    body = f"""
<h1>Flagged for review</h1>
<p class="muted">Irregularities, unverified items and modelling assumptions for the Live Alert
Desk. Nothing here blocks use of the desk; everything is published so it can be challenged. Each
row links the official source that was checked.</p>
<div class="grid g4">
{meta_card("Flags", str(len(review.get("flags", []))), "published with evidence links")}
{meta_card("Verified facts", str(len(review.get("verified", []))), "checked against official docs")}
{meta_card("Blank values", "left blank", "never inferred or estimated")}
{meta_card("Built", f'<span class="mono small">{built}</span>', "snapshot timestamp")}
</div>

<div class="card">
<h2>Flags</h2>
{table(["ID", "Area", "Item", "Detail", "Status", "Source(s)"],
       [[esc(f_["id"]), esc(f_["area"]), esc(f_["item"]), esc(f_["detail"]),
         f'<span class="chip warn">{esc(f_["status"])}</span>',
         " · ".join(src_link(u, i + 1) for i, u in enumerate(f_.get("sources") or []))]
        for f_ in review.get("flags", [])])}
</div>

<div class="card">
<h2>Verified against official sources</h2>
{table(["Item", "Value", "Source"],
       [[esc(v["item"]), f'<span class="mono small">{esc(v["value"])}</span>',
         src_link(v["source"], "official")] for v in review.get("verified", [])])}
</div>

<div class="card">
<h2>Repo review 2026-11-20 — findings from this session</h2>
<p class="small muted">Line-by-line review of the files on <code>main</code> against official
documentation, with the full register and the verified-correct list in
<a href="https://github.com/karagemop466-tech/Demo3/blob/main/REVIEW_2026-11-20.md" target="_blank" rel="noopener">REVIEW_2026-11-20.md</a>.
Rows here are the ones a trader could trip over.</p>
{table(["ID", "Finding", "Official source checked", "Status"],
       [["R-91-01", "Root dashboard live-order body uses <code>action</code>/<code>side: yes|no</code>/<code>yes_price</code>; V2 expects <code>side: bid|ask</code>, fixed-point string <code>count</code> and <code>price</code>, and <code>time_in_force</code> values <code>good_till_canceled|immediate_or_cancel|fill_or_kill</code>. Live entry would be rejected as written; inactive because no credentials exist.",
         src_link("https://docs.kalshi.com/api-reference/orders/create-order-v2", "Create Order V2"), '<span class="chip warn">needs review</span>'],
        ["R-91-02", "<code>scripts/kalshi_client.py</code> always signs RSA-PSS; docs now issue Ed25519 keys by default, which must sign the message directly. The newer collector/trading modules handle both.",
         src_link("https://docs.kalshi.com/getting_started/api_keys", "API keys"), '<span class="chip warn">needs review</span>'],
        ["R-91-03", "Root <code>assets/alerts.js</code> high-ROI filter is a disclosed placeholder (≥ $0.10 and ≥ 10%) — not a model. This desk replaces it with a published EV model plus a measured simulated track record.",
         src_link("https://github.com/karagemop466-tech/Demo3/blob/main/assets/alerts.js", "alerts.js"), '<span class="chip warn">needs review</span>'],
        ["R-91-04", "Root alerts only exist while the tab is open (in-browser polling). This desk detects swings from committed candlesticks, so alerts survive reloads.",
         src_link("https://docs.kalshi.com/api-reference/market/get-market-candlesticks", "candlesticks"), '<span class="chip warn">needs review</span>'],
        ["R-91-05", "The analysis archive was collected from the production endpoint; those 12 contracts are labelled production here and never mixed silently.",
         src_link("https://docs.kalshi.com/getting_started/api_environments", "environments"), '<span class="chip warn">needs review</span>'],
        ["R-91-06", "Several parallel dashboards exist (root, docs/, docs/tracker/, demo-desk/, analysis/, live/) plus three open PRs proposing more. Nothing broken; a trader has many doors.",
         src_link("https://github.com/karagemop466-tech/Demo3/pulls", "PR list"), '<span class="chip warn">needs review</span>']])}
<h3>Verified correct (spot-checked line by line)</h3>
<ul class="small">
<li>Demo + WS roots match {src_link("https://docs.kalshi.com/getting_started/demo_env", "demo environments")}.</li>
<li>Orderbook is bids-only, ascending, best = last, YES ask = 1 − best NO bid ({src_link("https://docs.kalshi.com/getting_started/orderbook_responses", "orderbook responses")}); implemented identically here.</li>
<li>Candlestick path and <code>period_interval</code> ∈ {{1, 60, 1440}} ({src_link("https://docs.kalshi.com/api-reference/market/get-market-candlesticks", "candlesticks")}).</li>
<li>$1 per winning contract and zero settlement fee for simple yes/no ({src_link("https://docs.kalshi.com/getting_started/market_settlement", "settlement")}).</li>
<li>Signed message = timestamp + METHOD + path-without-query; Ed25519 direct / RSA-PSS-SHA256 ({src_link("https://docs.kalshi.com/getting_started/api_keys", "API keys")}).</li>
<li>429 backoff for unauthenticated requests ({src_link("https://docs.kalshi.com/getting_started/rate_limits", "rate limits")}).</li>
</ul>
</div>

<div class="card">
<h2>Repo review — earlier sessions' registers</h2>
<p class="small muted">Registers from previous sessions on the same repository remain published at
their canonical URLs; this page covers the Live Alert Desk. Irregularities found while reviewing
this repository line by line on 2026-11-20 for this session are in
<a href="../COORDINATION.md">COORDINATION.md</a> and the repo-level review page below.</p>
<ul class="small">
<li><a href="../flagged.html">Repo-wide flag register (canonical site)</a></li>
<li><a href="../docs/flagged.html">docs/ archive flag register</a></li>
<li><a href="../demo-desk/pages/review.html">demo-desk flag register</a></li>
<li><a href="../analysis/pages/flagged.html">analysis flag register</a></li>
</ul>
</div>
"""
    pages.append(write("flagged.html", "Flagged for review", "flagged.html", body))

    # ------------------------------------------------------------- sources
    pages.append(write("sources.html", "Sources", "sources.html", sources_body(meta)))

    return pages


def suggestions_body(mrows, arows, candles):
    """25 concrete suggestions, each tied to something visible in this build."""
    S = [
        ("Keep the two-stream design", "Live", "1",
         "All-events and model-filtered streams stay side by side so a trader can compare the raw "
         "noise level with the filtered signal count before trusting the filter.",
         "dashboard.html#alerts"),
        ("Add a live-only toggle", "Live", "1",
         "A switch that hides snapshot alerts and shows only swings detected in the current browser "
         "session, so the trader sees what is moving right now.",
         "dashboard.html#alerts"),
        ("Throttle the chat to the trader's topic", "Live", "2",
         "The topic filter already exists; remember the last selection in localStorage so the desk "
         "opens on the trader's market.", "dashboard.html#alerts"),
        ("Pin a contract to the top of the stream", "Live", "2",
         "Pinning a focused contract keeps its alerts visible while the rest scroll past.",
         "dashboard.html#graph"),
        ("Colour-code by topic as well as direction", "UI", "2",
         "Direction uses red/green; a topic stripe makes scanning across five topics faster without "
         "fighting the direction colour.", "dashboard.html"),
        ("Sortable tables everywhere", "UI", "2",
         "Volume, liquidity and price columns should sort on click; the desk is read with the mouse.",
         "dashboard.html#topics"),
        ("Persist chart window per contract", "Graph", "3",
         "Trader who always looks at 30 minutes should not re-pick it for every contract.",
         "graph.html"),
        ("Overlay the $0.10 bands on the chart", "Graph", "3",
         "Two dashed lines at ±$0.10 from the last price make 'how close to an alert am I' obvious at "
         "a glance.", "graph.html"),
        ("Overlay trade prints", "Graph", "4",
         "Print recent trades from the public trades endpoint on the price line so quote moves and "
         "traded moves are visually distinct.",
         "https://docs.kalshi.com/api-reference/market/get-trades"),
        ("Add a cumulative depth (VWAP-to-size) view", "Liquidity", "4",
         "Walking-the-book cost for 100 / 1,000 / 10,000 contracts answers 'can I actually get "
         "filled', which raw levels do not.",
         "https://docs.kalshi.com/api-reference/market/get-market-orderbook"),
        ("Show spread history", "Liquidity", "5",
         "Spreads widen around events; a spread line explains sudden quote-driven alerts.",
         "graph.html"),
        ("Surface stale snapshots loudly", "Trust", "1",
         "If the snapshot is older than the scheduler interval, the banner should switch to amber "
         "and say the age in minutes.", "index.html"),
        ("Per-row freshness badge", "Trust", "2",
         "Each table row could show the retrieval time of the snapshot it came from.",
         "dashboard.html#topics"),
        ("Expand candle coverage before raising the threshold logic", "Data", "5",
         "Coverage is the binding constraint today: gas, crypto and golf had no $0.10 move in the "
         "collected windows. More history first, cleverer rules second.", "flagged.html"),
        ("Backfill seven days of one-minute candles per tracked line", "Data", "5",
         "One-minute candles make the 30-second to 10-minute windows meaningful instead of "
         "interpolated.",
         "https://docs.kalshi.com/api-reference/market/get-market-candlesticks"),
        ("Score alerts by dollar impact, not just cents", "Model", "3",
         "A 10¢ move on 500k contracts matters more than a 10¢ move on 20 contracts; the derived "
         "impact field is already computed.", "methodology.html"),
        ("Show the model's own hit rate", "Model", "4",
         "S3's simulated book is the model's track record; link it next to every high-ROI alert so "
         "the filter is judged by results.", "strategies.html"),
        ("Add a walk-forward split", "Model", "5",
         "Fit on the first half of the history and report performance on the second half to avoid "
         "reading noise as edge.", "strategies.html"),
        ("Model fees before trusting ROI", "Model", "5",
         "Until the demo fee schedule is verified, ROI figures are gross and optimistic (flag L-06).",
         "flagged.html"),
        ("Add an event calendar view", "UX", "2",
         "Group upcoming closes by hour so the trader knows what resolves next.",
         "tracking.html"),
        ("Alert on resolution as well as price", "Live", "3",
         "A system message when a tracked market settles keeps the stream useful between moves.",
         "tracking.html"),
        ("Keyboard shortcuts", "UX", "4",
         "J/K to move between alerts, space to pause the stream, G to focus the graph.",
         "dashboard.html"),
        ("Export the filtered stream", "UX", "4",
         "Download the current high-ROI stream as JSON/CSV for offline review.",
         "dashboard.html#alerts"),
        ("Server-side alerting", "Architecture", "5",
         "Move swing detection into the scheduled collector so alerts exist even when nobody has the "
         "page open, and the browser only renders them.", "methodology.html"),
        ("Signed WebSocket proxy for true streaming", "Architecture", "5",
         "A small server that signs the KALSHI-ACCESS headers would replace polling with real-time "
         "push (flag L-10).",
         "https://docs.kalshi.com/getting_started/quick_start_websockets"),
    ]
    rows = [[f'<b>{esc(t)}</b>', esc(a), esc(p), esc(d),
             src_link(u if u.startswith("http") else
                      "https://github.com/karagemop466-tech/Demo3/blob/main/live/" + u.lstrip("./"),
                      u)]
            for (t, a, p, d, u) in S]
    live_topics = sorted({m["topic"] for m in mrows})
    return f"""
<h1>Suggestions to make the desk more live and interactive</h1>
<p class="muted">Twenty-five concrete changes, ordered by impact on the trader's loop. Each one is
tied to a part of the current build (link in the last column) so it can be judged against something
real. Priority 1 = do next, 5 = bigger project.</p>
<div class="grid g4">
{meta_card("Suggestions", "25", "each tied to a live page")}
{meta_card("Topics covered", str(len(live_topics)), " · ".join(live_topics))}
{meta_card("Alerts in the stream now", f"{len(arows):,}", "swings ≥ $0.10")}
{meta_card("Contracts with candles", f"{candles.get('count', 0)}", "coverage is the real constraint")}
</div>
<div class="card">
{table(["Suggestion", "Area", "#Priority", "Why it helps a trader decide", "Where"], rows)}
</div>
<div class="card">
<h2>The three changes that matter most</h2>
<ol class="small">
<li><strong>Server-side alerting</strong> — alerts must exist before the page opens, otherwise the
desk is only live while someone is watching it.</li>
<li><strong>Deeper one-minute history</strong> — the $0.10 rule needs dense candles; today's
coverage cannot produce alerts in gas, crypto or golf even though those markets move.</li>
<li><strong>Fee-aware ROI</strong> — a model that ignores fees will flatter itself; once fees are
verified the high-ROI filter becomes actionable rather than indicative.</li>
</ol>
</div>
"""


def methodology_body(meta):
    src = meta["sources"]
    f = meta["formulas"]
    fs = {"mid_price": src["get_markets"], "derived_volume": src["get_markets"],
          "roi_model": src["get_candlesticks"], "swing_alert": src["get_candlesticks"],
          "simulated_trade": src["market_settlement"]}
    rows = [[esc(k.replace("_", " ")), f'<span class="mono small">{esc(v)}</span>',
             src_link(fs.get(k, src["get_markets"]), "docs")] for k, v in f.items()]
    return f"""
<h1>Methodology &amp; verification</h1>
<p class="muted">Every number on this site is one of four things, and each is labelled:
<strong>published</strong> (copied from the API), <strong>derived</strong> (a published formula over
published fields), <strong>modelled</strong> (this project's assumption) or
<strong>simulated</strong> (paper trading). Nothing else is shown.</p>

<div class="card">
<h2>1 · Where the data comes from</h2>
<table><tbody>
<tr><th>Exchange</th><td>Kalshi <strong>demo</strong> — <span class="mono">{esc(meta["api_base"])}</span>
({src_link(src["api_environments"], "environments")} · {src_link(src["demo_env"], "demo env")})</td></tr>
<tr><th>Auth</th><td>None for market data ({src_link(src["market_data_no_auth"], "docs")}); no
credentials exist in this repo, so nothing authenticated is shown ({src_link(src["get_balance"], "Get Balance")}).</td></tr>
<tr><th>Markets</th><td>{src_link(src["get_markets"], "Get Markets")} — snapshot from the scheduled
collector, committed in <span class="mono">data/latest/</span>.</td></tr>
<tr><th>Candlesticks</th><td>{src_link(src["get_candlesticks"], "Get Market Candlesticks")} —
<span class="mono">period_interval</span> 1, 60 or 1440 minutes. Fields used:
<span class="mono">price.open/high/low/close_dollars</span>, <span class="mono">volume_fp</span>.</td></tr>
<tr><th>Orderbook</th><td>{src_link(src["get_orderbook"], "Get Market Orderbook")} —
<span class="mono">orderbook_fp.yes_dollars / no_dollars</span> as
<span class="mono">[price_dollars, contract_count]</span>.</td></tr>
<tr><th>Settlement</th><td>{src_link(src["market_settlement"], "Market settlement")} — $1 per
winning contract; <span class="mono">result</span> ∈ {{yes, no}}.</td></tr>
<tr><th>Fixed-point fields</th><td>{src_link(src["fixed_point"], "Fixed-point migration")} —
<span class="mono">*_fp</span> fields are decimal strings; they are parsed, never rounded to cents.</td></tr>
<tr><th>Rate limits</th><td>{src_link(src["rate_limits"], "Rate limits")} — the dashboard spaces
requests and backs off on 429.</td></tr>
</tbody></table>
</div>

<div class="card">
<h2>2 · Computed values (published formula)</h2>
{table(["Value", "Formula (this project's, published)", "Source"], rows)}
</div>

<div class="card" id="causation">
<h2>3 · Alerts and the "what caused it" question</h2>
<p class="small">An alert fires when a committed candlestick shows an absolute move of at least
$0.10 either close-to-close over the window, or high-to-low inside a single candle. Each alert links:</p>
<ul class="small">
<li>the exact candlestick request that produced the numbers (official),</li>
<li>the market record for the contract (official),</li>
<li>a Google News search for the contract's subject around that date.</li>
</ul>
<p class="small">The headline link is a <strong>search</strong>, not an established cause. Proving
that a headline caused a move would need article-level timestamps and an event study with a
baseline; the desk does not claim that, and says so in flag L-08.</p>
</div>

<div class="card">
<h2>4 · Simulated trading</h2>
<p class="small">No order is ever sent. Fills are modelled at quoted prices, exits are ±$0.10 or
resolution, and results are computed with the documented settlement arithmetic. The three
strategies and their exact rules are on <a href="strategies.html">Strategies</a>. Fees are not
modelled (flag L-06). The simulation is deterministic: rebuilding from the same committed data
produces the same trades.</p>
</div>

<div class="card">
<h2>5 · What this build does not do</h2>
<ul class="small">
<li>It cannot open an authenticated WebSocket from a static page ({src_link(src["websockets_auth"], "WS auth")}).</li>
<li>It does not report a demo account balance, positions or fills — no credentials (flag L-07).</li>
<li>It does not claim a dollar-volume field exists; the ranking is derived (flag L-03).</li>
<li>It does not fill gaps in the candles or interpolate missing prices.</li>
<li>It does not assert that news caused a move (flag L-08).</li>
</ul>
</div>

<div class="card">
<h2>6 · Reproduce it</h2>
<pre>python3 scripts/build_live_candles.py   # candlestick store from committed official payloads
python3 scripts/build_live_data.py      # alerts, model, simulation, registers
python3 scripts/build_live_site.py      # these pages
python3 scripts/verify_live_site.py     # links, per-row sources, JSON shape, JS syntax</pre>
<p class="small muted">The dev sandbox for this session had no HTTPS egress to the Kalshi API (TLS
handshake refused), so candlestick payloads were reused from the repository's committed collector
artifacts rather than re-fetched. GitHub Actions runners do have egress; the scheduled collector
keeps refreshing <span class="mono">data/</span>.</p>
</div>
"""


def sources_body(meta):
    src = meta["sources"]
    docs_rows = [[esc(k), src_link(u, "official page")] for k, u in sorted(src.items())]
    ep_rows = [
        ["Markets (demo)", f'<span class="mono">{API}/markets</span>', src_link(f"{API}/markets?limit=1", "live request")],
        ["Events (demo)", f'<span class="mono">{API}/events</span>', src_link(f"{API}/events?limit=1", "live request")],
        ["Series (demo)", f'<span class="mono">{API}/series</span>', src_link(f"{API}/series?limit=1", "live request")],
        ["Candlesticks (demo)", f'<span class="mono">{API}/series/{{series}}/markets/{{ticker}}/candlesticks</span>',
         src_link(f"{DOCS}/api-reference/market/get-market-candlesticks", "docs")],
        ["Orderbook (demo)", f'<span class="mono">{API}/markets/{{ticker}}/orderbook</span>',
         src_link(f"{DOCS}/api-reference/market/get-market-orderbook", "docs")],
        ["Trades (demo)", f'<span class="mono">{API}/markets/trades</span>',
         src_link(f"{DOCS}/api-reference/market/get-trades", "docs")],
        ["Exchange status (demo)", f'<span class="mono">{API}/exchange/status</span>',
         src_link(f"{API}/exchange/status", "live request")],
    ]
    BUILDER = "https://github.com/karagemop466-tech/Demo3/blob/main/scripts/build_live_data.py"
    files = [[f'<span class="mono">live/data/{esc(p2.name)}</span>',
              f"{p2.stat().st_size / 1024:.0f} KB",
              f'{src_link(BUILDER, "builder script")} · '
              f'{src_link("https://github.com/karagemop466-tech/Demo3/blob/main/live/data/" + p2.name, "raw file")}']
             for p2 in sorted(DATA.glob("*.json"))]
    return f"""
<h1>Sources</h1>
<p class="muted">Every value on this site traces to one of these. Official documentation first, then
the exact API requests the data was read from.</p>
<div class="card">
<h2>Official Kalshi documentation</h2>
{table(["Topic", "Official page"], docs_rows)}
</div>
<div class="card">
<h2>Demo API endpoints used</h2>
{table(["Endpoint", "Path", "Source"], ep_rows,
       note="Public market data needs no key; account endpoints are not used because no credentials exist.")}
</div>
<div class="card">
<h2>Committed data files behind these pages</h2>
{table(["File", "Size", "Source"], files,
       note="Rebuilt by scripts/build_live_data.py from data/latest/ and data/history/ (collector artifacts) and analysis/data/live/candles.json (production archive, labelled).")}
</div>
<div class="card">
<h2>Regularities and irregularities of the underlying data</h2>
<p class="small">Two things about the demo exchange are worth knowing before reading any table:</p>
<ul class="small">
<li><strong>Synthetic self-test series.</strong> KXDEMOFUTHOURLY ("Demo BTC at or above …") and
KXQUICKSETTLE are exchange tests. They rank high by volume and are excluded here
({src_link(f"{API}/series/KXDEMOFUTHOURLY", "series record")}).</li>
<li><strong>Placeholder candles.</strong> When a market does not trade in a period the API can emit a
candle with <span class="mono">previous_dollars</span> and no <span class="mono">close_dollars</span>.
Those are stored as gaps, not prices ({src_link(f"{DOCS}/api-reference/market/get-market-candlesticks", "docs")}).</li>
</ul>
</div>
"""


if __name__ == "__main__":
    pages = build()
    print("wrote:", ", ".join(pages))
