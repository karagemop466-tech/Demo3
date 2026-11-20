#!/usr/bin/env python3
"""Build two root pages from verified sources only:

  requirements.html — every line of the project brief mapped to the file/page that
                      satisfies it, with a verified / partial / not-possible status.
  model.html        — the high-ROI screen definition and the measured demo statistics
                      behind it, straight out of data/latest/roi_model.json.

Rule enforced here and by scripts/verify_root_site.py: every table row carries an
official source link (docs.kalshi.com or a replayable demo-API/commit URL), or it is
rendered as unverified. Nothing is inferred and no number is hand-typed: the model page
reads only the JSON produced by model/build_roi_model.py.

Run: python3 scripts/build_report_pages.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_root_site import ROOT, DOCS, DEMO, NAV, Table, esc, shell, write_page  # noqa: E402

MODEL_PATH = ROOT / "data" / "latest" / "roi_model.json"
GH = "https://github.com/karagemop466-tech/Demo3/blob/main/"
SITE = "https://karagemop466-tech.github.io/Demo3/"
DOCS_URL = DOCS

D = {
    "get_markets": f"{DOCS_URL}/api-reference/market/get-markets",
    "get_market": f"{DOCS_URL}/api-reference/market/get-market",
    "get_event": f"{DOCS_URL}/api-reference/events/get-event",
    "get_events": f"{DOCS_URL}/api-reference/market/get-events",
    "get_series": f"{DOCS_URL}/api-reference/market/get-series-list",
    "candles": f"{DOCS_URL}/api-reference/market/get-market-candlesticks",
    "orderbook": f"{DOCS_URL}/getting_started/orderbook_responses",
    "trades": f"{DOCS_URL}/api-reference/market/get-trades",
    "settlement": f"{DOCS_URL}/getting_started/market_settlement",
    "demo_env": f"{DOCS_URL}/getting_started/demo_env",
    "api_environments": f"{DOCS_URL}/getting_started/api_environments",
    "api_keys": f"{DOCS_URL}/getting_started/api_keys",
    "rate_limits": f"{DOCS_URL}/getting_started/rate_limits",
    "ws": f"{DOCS_URL}/getting_started/quick_start_websockets",
    "market_data_qs": f"{DOCS_URL}/getting_started/quick_start_market_data",
    "orders": f"{DOCS_URL}/api-reference/orders/create-order-v2",
    "balance": f"{DOCS_URL}/api-reference/portfolio/get-balance",
    "positions": f"{DOCS_URL}/api-reference/portfolio/get-positions",
    "fills": f"{DOCS_URL}/api-reference/portfolio/get-fills",
}


EX_CAP = "First 10 settled markets in the snapshot with |last \u2212 prior| \u2265 $0.10"
RATE_NOTE = ("Every figure is recomputable from the linked API records. A rate is shown only "
           "where n &ge; 25; below that the cell is left as \u201cnot reported\u201d rather than "
           "inferred.")


def v(x, suffix=""):
    """Render a measured value or an explicit blank-with-flag (never a guessed 0)."""
    if x is None or x == "":
        return "<span class='pill warn'>not reported</span>"
    return f"{x}{suffix}"


def pill(kind, text):
    return f"<span class='pill {kind}'>{esc(text)}</span>"


# --------------------------------------------------------------- requirements page
def build_requirements():
    t = Table(["Ref", "Brief requirement (verbatim intent)", "Where it lives",
               "Status"], "requirements.html")

    def row(ref, req, where, status, kind, srcs, note=""):
        t.row([f"<span class='mono'>{ref}</span>", req, where, pill(kind, status) +
               (f"<div class='small muted'>{note}</div>" if note else "")],
              sources=srcs, label=ref)

    row("B-01", "Create an executive summary outlining important details.",
        "<a href='index.html'>Landing &rarr; Executive summary</a> and "
        "<a href='EXECUTIVE_SUMMARY.md'>EXECUTIVE_SUMMARY.md</a>",
        "implemented", "ok", [D["demo_env"], SITE])
    row("B-02", "Dashboard tracks the highest-dollar live events on Kalshi.",
        "<a href='dashboard.html'>Live dashboard</a> &sect;1 discovery &amp; ranking",
        "partial", "warn", [D["get_markets"], DEMO + "/markets?limit=100"],
        "The API reports contract volume (`volume_fp`), not a verified dollar-volume field, so the "
        "ranking column is a labelled derived estimate (contracts x last price), never an "
        "exchange-reported figure.")
    row("B-03", "Focus on gas prices, elections, culture, crypto and golf only.",
        "<a href='gas-prices.html'>Gas</a> / <a href='elections.html'>Elections</a> / "
        "<a href='culture.html'>Culture</a> / <a href='crypto.html'>Crypto</a> / "
        "<a href='golf.html'>Golf</a>",
        "implemented", "ok", [D["get_series"], DEMO + "/series"],
        "Topic assignment is a repo-side classification rule (recorded as `classification_rule` in "
        "each snapshot row); the exchange's event `category` field is deprecated, so it is not used.")
    row("B-04", "Live alerting on sudden swings of >= $0.10 in either direction.",
        "<a href='assets/alerts.js'>assets/alerts.js</a> (`SWING = 0.10`) rendered in "
        "<a href='dashboard.html'>dashboard</a> &sect;6",
        "implemented", "ok", [D["get_markets"], GH + "assets/alerts.js"],
        "Threshold is tested at exactly $0.10 in tests/ (Node + jsdom).")
    row("B-05", "Alerts shown as a simplified scrolling chat, viewable in real time.",
        "<a href='dashboard.html'>dashboard</a> &sect;6 chat panels (`#chatAll`, `#chatROI`)",
        "implemented", "ok", [GH + "assets/alerts.js", GH + "dashboard.html"],
        "Feed re-renders every 2 s and persists in this browser (localStorage) - not a server feed.")
    row("B-06", "Two chats: all events, and a selective filter for events the model likes as high ROI.",
        "`KD.allFeed()` / `KD.roiFeed()` in <a href='assets/alerts.js'>assets/alerts.js</a>; screen in "
        "<a href='model.html'>model.html</a> + <a href='data/latest/roi_model.json'>roi_model.json</a>",
        "implemented", "ok", [GH + "model/build_roi_model.py", D["get_markets"]],
        "The screen is published and deterministic, but its parameters are explicitly UNCALIBRATED: "
        "the demo data cannot fit or validate them (see model.html -> calibration feasibility).")
    row("B-07", "Track live events until they resolve, and how they resolved (yes/no).",
        "Resolution watcher in <a href='assets/alerts.js'>assets/alerts.js</a> (`GET /markets?tickers=…`, "
        "`result` = yes/no) feeding both chats; plus <a href='dashboard.html'>dashboard</a> &sect;3",
        "implemented", "ok", [D["get_markets"], D["get_event"], D["settlement"]],
        "Rows appear only when the exchange returns a result; an unsettled market stays open with no "
        "inferred outcome. In-browser behaviour is verified in jsdom, not from this sandbox "
        "(no network path to kalshi.co).")
    row("B-08", "Automate simulated trades to test different strategies.",
        "<a href='assets/trade.js'>assets/trade.js</a> paper engine + "
        "<a href='trading/'>trading/</a> + <a href='strategy.html'>strategy lab</a>",
        "implemented", "ok", [D["orders"], GH + "scripts/backtest_strategies.py"],
        "Paper/simulated by default; live demo orders need a demo API key, which is owner-side "
        "(never stored in this repo).")
    row("B-09", "Track portfolio performance using the Kalshi demo account.",
        "<a href='portfolio.html'>Portfolio</a> + <a href='data/latest/portfolio.json'>portfolio.json</a> "
        "+ <a href='.github/workflows/kalshi-portfolio.yml'>kalshi-portfolio.yml</a>",
        "blocked (needs credentials)", "warn", [D["api_keys"], D["balance"], D["positions"]],
        "The scheduled puller runs only with repo secrets; without them the page shows the demo-key "
        "path and leaves account values blank rather than inventing them.")
    row("B-10", "Analyse trade results, categorise trades, build strategies by trade type.",
        "<a href='strategy.html'>Strategy lab</a> (measured backtest) + dashboard &sect;5",
        "implemented", "ok", [GH + "strategy/FINDINGS.md", GH + "scripts/backtest_strategies.py"],
        "Published sample sizes are small; the page states what is and is not an edge.")
    row("B-11", "Live interactive graph: x = time (seconds/minutes/hours), y = contract price.",
        "<a href='dashboard.html'>dashboard</a> &sect;2 chart (30 s … 24 h window buttons)",
        "implemented", "ok", [D["candles"], D["market_data_qs"]],
        "Candle granularity from the API stops at 1 minute; sub-minute resolution comes from the "
        "browser's own sample buffer while the page is open.")
    row("B-12", "Current liquidity: how many contracts are available at a given price.",
        "<a href='dashboard.html'>dashboard</a> &sect;2 orderbook table",
        "implemented", "ok", [D["orderbook"], DEMO + "/markets/{ticker}/orderbook"])
    row("B-13", "Suggestions to make the site more live and interactive.",
        "<a href='suggestions.html'>Suggestions</a> register",
        "implemented", "ok", [GH + "SUGGESTIONS.md", GH + "suggestions.html"])
    row("B-14", "Live charts to include events and website links that may have caused a sharp jump (>= $0.10).",
        "Context column of each alert row: official `settlement_sources` from "
        "<a href='dashboard.html'>dashboard</a> &sect;6",
        "partial", "warn", [D["get_event"], DEMO + "/events/{event_ticker}"],
        "The exchange publishes settlement sources, not news causes. Chart-axis annotations still need "
        "a selection hook in assets/dashboard.js (file owned elsewhere); request logged on COORDINATION.md.")
    row("B-15", "Keep topics separate but events inside a topic organised together; keep simplifying.",
        "category pages grouped by `event_ticker`; single nav shared by all pages",
        "implemented", "ok", [D["get_events"], GH + "scripts/build_root_site.py"])
    row("B-16", "No manual input required by the owner.",
        "Scheduled collectors: <a href='.github/workflows/collect.yml'>collect.yml</a>, "
        "<a href='.github/workflows/kalshi-data.yml'>kalshi-data.yml</a>, "
        "<a href='.github/workflows/trade.yml'>trade.yml</a>",
        "implemented", "ok", [GH + ".github/workflows/collect.yml", GH + "collector/collect.py"],
        "The dashboard's optional 'extra series' box is an override, not a requirement; the scan runs "
        "without it.")
    row("B-17", "GitHub Pages site: clean landing + subpages by category, table-first, all findings.",
        "<a href='https://karagemop466-tech.github.io/Demo3/'>live site</a>",
        "implemented", "ok", ["https://api.github.com/repos/karagemop466-tech/Demo3/pages", SITE])
    row("B-18", "Every table row must have a source link; unverified values stay blank and flagged.",
        "<a href='flagged.html'>Flagged for review</a> + the row-source rule in verify_root_site.py",
        "implemented", "ok", [GH + "scripts/verify_root_site.py", GH + "flagged.html"])
    row("B-19", "The brief's WebSocket surface (wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2).",
        "<a href='api-reference.html'>API reference</a> WebSocket rows",
        "not possible in a browser page (verified)", "warn", [D["ws"]],
        "Official docs: the WS handshake requires KALSHI-ACCESS-KEY / -SIGNATURE / -TIMESTAMP headers and "
        "even public channels ride the authenticated session. Browsers cannot set WebSocket headers, so "
        "a static Pages site must poll the public REST endpoints instead (rate limits apply).")

    nav = "".join(f"<li><a href='{h}'>{esc(l)}</a></li>" for h, l in NAV)
    body = f"""
<h1>Requirements traceability</h1>
<p class="muted">Every line of the project brief, mapped to the file or page that satisfies it, with
the official source used to verify it. Statuses are deliberately conservative: <em>partial</em> means
the code exists but a constraint is disclosed on the page, <em>not possible (verified)</em> means the
brief asks for something the platform or the API does not allow, with the documentation linked.
Nothing on this site is claimed as done without a source; blank or flagged values are never filled in.</p>
{t.render(caption="Brief requirement -> implementation -> verification",
          note="Sources: Kalshi official documentation (docs.kalshi.com), replayable demo-API URLs on "
               "external-api.demo.kalshi.co, and the repository files on GitHub. "
               "Generated by scripts/build_report_pages.py.")}
<div class="card"><h2>Navigation</h2><ul class="small">{nav}</ul></div>
"""
    write_page("requirements.html", "Requirements traceability", "requirements.html", body)


# ------------------------------------------------------------------- model page
def fmt_rate(x):
    return "—" if x is None else f"{x:.4f}"


def build_model():
    model = json.loads(MODEL_PATH.read_text())
    meas = model["measured"]
    inp = model["inputs"]["settled_snapshot"]
    prov = (f"snapshot `data/latest/markets_settled.json` (sha256 {inp['sha256'][:16]}…), "
            f"retrieved_at {esc(inp['retrieved_at'])}")

    src = Table(["Parameter", "Value", "Where it comes from"], "model.html")
    p = model["screen"]["params"]
    src.row([f"<span class='mono'>{esc(model['screen']['id'])}</span>",
             f"|swing| &ge; <strong>${p['min_abs_swing_dollars']:.2f}</strong> in either direction",
             "Hard condition from the project brief (the alert threshold).",
             ], sources=[DEMO + "/markets?limit=100", D["get_markets"]], label="swing")
    src.row([f"<span class='mono'>{esc(model['screen']['id'])}</span>",
             f"move &ge; <strong>{round(p['min_move_pct_of_prior']*100)}%</strong> of the prior price",
             "Stated choice, not a fitted value: it stops a 1c&rarr;11c longshot jump ranking like a "
             "45c&rarr;55c move on a coin flip. Marked uncalibrated because the recorded data cannot "
             "fit it (see calibration below).",
             ], sources=[GH + "model/build_roi_model.py"], label="pct", unverified=True)
    src.row(["Status", f"<strong>{esc(model['screen']['status'])}</strong>",
             esc(model["screen"]["status_note"]),
             ], sources=[GH + "data/latest/roi_model.json", D["get_markets"]], label="status")

    uni = Table(["Measured quantity", "Value", "Reading"], "model.html")
    uni.row(["Settled records in snapshot", v(meas["universe"]["n_records_in_file"]),
             "Rows of <span class='mono'>markets_settled.json</span>.",
             ], sources=[inp["official_endpoint"], D["get_markets"]], label="n_records")
    uni.row(["Usable (result + both prices)", v(meas["universe"]["n_usable"]),
             "Rows skipped for a missing field are counted, not filled in: "
             f"no result {meas['universe']['skipped']['no_result']}, no last price "
             f"{meas['universe']['skipped']['no_last']}, no prior price "
             f"{meas['universe']['skipped']['no_previous']}.",
             ], sources=[inp["official_endpoint"], D["get_markets"]], label="n_usable")
    br = meas["base_rate_all_settled"]
    uni.row(["Base P(resolves YES)", v(fmt_rate(br["p_yes"])),
             f"n = {br['n']} settled markets in the five-topic + other universe.",
             ], sources=[inp["official_endpoint"], D["settlement"]], label="base_p_yes")
    sw = meas["swing_market_counts"]
    uni.row([f"Swings &ge; ${sw['swing_threshold_dollars']:.2f}", v(sw["n_swing"]),
             f"{v(sw['share_of_settled'],' of settled markets')} — i.e. how chatty the $0.10 feed can be "
             "on recorded demo data (a share of the settled file, not a live rate).",
             ], sources=[inp["official_endpoint"], D["get_markets"]], label="n_swing")
    for name, key in (("after an up-swing of >= $0.10", "up_swing"),
                      ("after a down-swing of >= $0.10", "down_swing")):
        g = meas[key]
        uni.row([f"P(resolves YES) {name}", v(fmt_rate(g["p_yes"]) if g["n"] else None),
                 f"n = {g['n']} · median entry ${v(g['median_entry_dollars'])} · mean ROI of buying YES "
                 f"at the last print {v(fmt_rate(g['mean_roi_buy_yes']))}. Descriptive of the snapshot "
                 "only — that entry price is not an achievable fill.",
                 ], sources=[inp["official_endpoint"], D["settlement"]], label=key)

    band = Table(["Prior price band ($)", "n", "P(YES)", "Mean ROI if you had bought YES at the last print",
                  "Reported?"], "model.html")
    for b in meas["up_swing_by_prior_band"]:
        band.row([f"{b['prior_band'][0]:.2f} – {b['prior_band'][1]:.2f}", v(b["n"]),
                  v(fmt_rate(b["p_yes"]) if b["reported"] else None),
                  v(fmt_rate(b["mean_roi_buy_yes"]) if b["reported"] else None),
                  "yes" if b["reported"] else f"no — n &lt; 25",
                  ], sources=[inp["official_endpoint"]], label=f"band {b['prior_band']}")

    top = Table(["Topic", "Settled markets", f"Swings &ge; $0.10", "P(YES) among those swings",
                 "Mean ROI (YES at last print)"], "model.html")
    for r in meas["by_topic"]:
        top.row([f"<span class='mono'>{esc(r['topic'])}</span>", v(r["n_settled"]), v(r["n_swing"]),
                 v(fmt_rate(r["p_yes"]) if r["reported"] else None),
                 v(fmt_rate(r["mean_roi_buy_yes"]) if r["reported"] else None)],
                sources=[inp["official_endpoint"], D["get_markets"]], label=f"topic {r['topic']}")
    top.row([f"all other topics", v(meas["n_other_topic_settled"]), v(meas["n_other_topic_swing"]),
             "not tracked by this site", "—"],
            sources=[inp["official_endpoint"]], label="other topics")

    ex = Table(["Ticker", "Topic", "Prior $", "Last $", "Move", "Result", "Settled at $"],
               "model.html")
    for r in model["examples"]:
        ex.row([f"<span class='mono'>{esc(r['ticker'])}</span>", esc(r["topic"]), v(r["prev"]),
                v(r["last"]), v(r["change"]), pill("up" if r["result"] == "yes" else "down",
                r["result"].upper()), v(r["settlement_value_dollars"])],
               sources=[r["source_url"]], label=r["ticker"])

    cf = model["calibration_feasibility"]
    caveats = "".join(f"<li>{esc(c)}</li>" for c in model["caveats"])
    body = f"""
<h1>High-ROI screen &mdash; definition and measured demo context</h1>
<p class="muted">The second scrolling chat on the <a href="dashboard.html">live dashboard</a> is meant to
show "events that our model likes as high ROI". No model was defined in this repo, so this page publishes
the screen actually used, plus every number measured from the committed demo snapshots that backs it.
It is a ranking aid for what to look at first, <strong>not</strong> a return forecast.</p>

<div class="card"><h2>1 &middot; Screen definition</h2>
<p class="small muted">{esc(model['screen']['description'])}</p>
{src.render()}
<p class="small muted">Generated by <span class="mono">model/build_roi_model.py</span> from {prov}.
Rebuild: <span class="mono">python3 model/build_roi_model.py</span>; the committed JSON is
re-verified with <span class="mono">--check</span> in CI.</p>
</div>

<div class="card"><h2>2 &middot; What the recorded demo data actually shows</h2>
{uni.render(caption="Counts and rates computed from the settled snapshot only",
            note=RATE_NOTE)}
{band.render(caption="Up-swings split by prior price (the band a live alert would fall in)")}
{top.render(caption="Per tracked topic — events stay grouped by topic across this site")}
</div>

<div class="card"><h2>3 &middot; Calibration feasibility (read this before trusting any ROI number)</h2>
<p><strong>{esc(cf['conclusion'])}</strong></p>
<p class="small muted">Candle windows are recorded for {cf['candle_markets_available']} market(s) in
<span class="mono">data/latest/candles.json</span> (field semantics:
<a href="{D['candles']}" target="_blank" rel="noopener">Get Market Candlesticks</a>); the minimum used
here for any fit claim is {cf['min_series_for_calibration']} series with a pre-settlement price path.</p>
</div>

<div class="card"><h2>4 &middot; Example qualifying rows (all five topics, replayable)</h2>
{ex.render(caption=EX_CAP,
            note="Each row links the exact demo-API URL that returned it, so the ranking can be checked "
                 "one row at a time.")}
</div>

<div class="card"><h2>5 &middot; Caveats and limits</h2><ul class="small">{caveats}</ul>
<p class="small muted">Open items are also published on <a href="flagged.html">Flagged for review</a>;
the requirement each one belongs to is on <a href="requirements.html">Requirements</a>.</p>
</div>
"""
    write_page("model.html", "High-ROI screen", "model.html", body)


def main():
    build_requirements()
    build_model()
    print("done")


if __name__ == "__main__":
    main()
