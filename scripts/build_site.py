#!/usr/bin/env python3
"""Generate the static GitHub Pages site in docs/.

All data tables are rendered in the browser from docs/data/verified.json by docs/assets/app.js.
This script only writes the page shells (navigation, headings, and text blocks), so every page
shares one template. Run:  python3 scripts/build_site.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "docs"

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Kalshi demo dashboard</title>
<link rel="stylesheet" href="{root}assets/style.css">
</head>
<body data-root="{root}" data-page="{page}">
<header class="site"><div id="site-nav"></div></header>
<main>
"""

FOOT = """</main>
<footer>Snapshot date (UTC): <span id="snapshot-date">2026-11-20</span>. Data from the public Kalshi Trade API and Kalshi docs.
Every table row links to its source. Blank or flagged values are unverified. Not investment advice.
Source code: <a href="https://github.com/karagemop466-tech/Demo3">github.com/karagemop466-tech/Demo3</a>.</footer>
<script src="{root}assets/app.js" defer></script>
</body>
</html>
"""

LIVE_BANNER = '<div id="live-status" class="banner">Loading live data...</div>'

DETAIL = """
<h2>Price movement and liquidity</h2>
<div class="card" id="detail">
  <div class="controls">
    <select id="detail-pick"><option value="">Choose a market...</option></select>
    <div class="seg controls" style="margin:0">
      <button data-mode="seconds">Seconds</button><button data-mode="minutes">Minutes</button><button data-mode="hours">Hours</button>
    </div>
    <select id="detail-len"></select>
  </div>
  <h3 id="detail-title">Pick a market to chart</h3>
  <p class="note" id="chart-caption"></p>
  <svg class="chart" id="chart" viewBox="0 0 960 320" preserveAspectRatio="xMidYMid meet"></svg>
  <div class="grid" id="detail-stats" style="margin-top:12px"></div>
  <h3>Liquidity: contracts available at each price</h3>
  <div id="liquidity"><p class="muted">Pick a market to see its orderbook.</p></div>
  <p class="note">Seconds mode records a sample every 5 seconds while this page stays open. Minutes and hours use Kalshi candlesticks (1-minute and 60-minute periods).</p>
</div>
"""

PAGES = {
    "index.html": ("Home", "home", "", """
<h1>Kalshi demo dashboard</h1>
<p class="lead">Live tracking, verified data, and analysis for gas prices, elections, culture, crypto, and golf markets on Kalshi.
Every value links to an official source. Anything that could not be confirmed is marked unverified.</p>

<div class="card"><h2 style="margin-top:0">Executive summary</h2>
<ul>
<li>Kalshi publishes a <b>production</b> Trade API (<a href="https://external-api.kalshi.com/trade-api/v2" target="_blank" rel="noopener">external-api.kalshi.com/trade-api/v2</a>) and a separate <b>demo</b> API. Credentials do not cross environments, and Kalshi warns that demo prices may not reflect real markets. <a href="https://docs.kalshi.com/getting_started/api_environments.md" target="_blank" rel="noopener">source</a> <a href="https://docs.kalshi.com/getting_started/demo_env.md" target="_blank" rel="noopener">source</a></li>
<li>Market data (markets, events, orderbooks, candlesticks) is documented as <b>unauthenticated</b>. Portfolio and trading endpoints require an API key and a request signature. <a href="https://docs.kalshi.com/getting_started/quick_start_market_data.md" target="_blank" rel="noopener">source</a> <a href="https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md" target="_blank" rel="noopener">source</a></li>
<li>Each contract pays <b>$1</b> to the winning side. Results are <code>yes</code>, <code>no</code>, or <code>scalar</code>. Three settled gas markets (2026-11-16) all resolved <b>YES</b>. <a href="https://docs.kalshi.com/getting_started/market_settlement.md" target="_blank" rel="noopener">source</a> <a href="https://external-api.kalshi.com/trade-api/v2/markets?series_ticker=KXAAAGASW&amp;status=settled&amp;limit=3" target="_blank" rel="noopener">source</a></li>
<li>The API has <b>no dollar-volume field</b>. The verified snapshot ranks by contracts traded; the automated pipeline ranks by a clearly labelled <b>derived</b> dollar volume (<code>volume_fp &times; notional_value_dollars</code>, both API fields shown per row). The ranking definition is an open question on <a href="questions.html">Questions</a>. <a href="https://docs.kalshi.com/api-reference/market/get-market.md" target="_blank" rel="noopener">source</a></li>
<li>An <b>automated pipeline</b> (GitHub Actions, twice hourly) now collects market data from the <b>demo</b> endpoint recommended in the project brief and re-verifies stored rows against the live API &mdash; see <a href="sources.html">Sources</a> and <a href="../data/latest/meta.json" target="_blank" rel="noopener">the collector request log</a>.</li>
<li>Several culture, golf, and elections series name <b>non-official settlement sources</b>. These are the highest resolution risk. See Flagged for review.</li>
<li><b>Portfolio analysis and trade execution are not done.</b> No demo API key exists in this workspace, and nothing was traded.</li>
<li>The live panels call the public API from your browser. Whether your browser is allowed to read it (CORS) is unverified, and the page shows a banner if it cannot.</li>
</ul></div>

<div data-render="counts"></div>

<h2>Categories</h2>
<div class="grid">
  <a class="tile" href="categories/gas.html">Gas prices<small>AAA-settled weekly markets (Economics)</small></a>
  <a class="tile" href="categories/elections.html">Elections<small>Presidential, state, international</small></a>
  <a class="tile" href="categories/culture.html">Culture<small>Platform and public-figure markets</small></a>
  <a class="tile" href="categories/crypto.html">Crypto<small>BTC, DOGE, SOL, ADA and more</small></a>
  <a class="tile" href="categories/golf.html">Golf<small>Majors, PGA Tour, course records</small></a>
</div>
<div class="grid" style="margin-top:12px">
  <a class="tile" href="dashboard.html">Live dashboard<small>Top markets by volume, price charts, liquidity, tracking</small></a>
  <a class="tile" href="resolved.html">Resolved<small>Final yes/no results with sources</small></a>
  <a class="tile" href="flagged.html">Flagged for review<small>Irregularities and unverified items</small></a>
</div>

<h2>Series by contracts traded (snapshot)</h2>
<p class="note">Ranked from the verified snapshot, 2026-11-20. Volume values change continuously.</p>
<div data-render="volume"></div>
"""),

    "dashboard.html": ("Live dashboard", "dashboard", "", """
<h1>Live dashboard</h1>
<p class="lead">Top open markets across gas prices, elections, culture, crypto, and golf, refreshed every 60 seconds from the public Kalshi API.</p>
""" + LIVE_BANNER + """
<h2>Top live events by dollar volume (demo pipeline snapshot)</h2>
<p class="note">Ranked by <b>derived dollar volume</b> = <code>volume_fp &times; notional_value_dollars</code> (arithmetic on two API fields; every input shown per row). Snapshots are collected twice hourly by GitHub Actions from the official <b>demo</b> Trade API (<code>https://external-api.demo.kalshi.co/trade-api/v2</code>) and each row links to the exact request that produced it. Collector: <code>scripts/collect_kalshi_data.py</code>. Row-level re-verification: <code>scripts/verify_rows.py</code>.</p>
<div data-render="top-events"></div>
<h2>Top open markets</h2>
<div class="card" data-live="gas elections culture crypto golf" data-limit="30"></div>
""" + DETAIL + """
<h2>Tracking until resolved</h2>
<p class="note">Click Track on any market. Tracked markets refresh every 15 seconds and show the final yes/no result once Kalshi reports it.</p>
<div class="card" id="watchlist"></div>
"""),
}

CATEGORY = {
    "gas": ("Gas prices", "Weekly AAA gas-price markets. The confirmed series is KXAAAGASW, in the Economics category.",
            """<div class="card"><h3 style="margin-top:0">Series in the verified snapshot</h3><div data-render="series" data-cat="gas"></div></div>
<h2>Settled markets (yes/no results)</h2><div data-render="resolved" data-cat="gas"></div>
<h2>Analysis</h2><ul>
<li>All three settled 2026-11-16 markets resolved YES, and each strike sat below the recorded expiration value of 3.8118. <a href="https://external-api.kalshi.com/trade-api/v2/markets?series_ticker=KXAAAGASW&amp;status=settled&amp;limit=3" target="_blank" rel="noopener">source</a></li>
<li>Flagged: settlement timestamps (13:58Z) fall before the expected expiration (15:00Z). Confirm against AAA methodology (I-05). <a href="https://external-api.kalshi.com/trade-api/v2/markets?series_ticker=KXAAAGASW&amp;status=settled&amp;limit=3" target="_blank" rel="noopener">source</a></li>
<li>Only one gas series was confirmed. The Energy and Commodities category returned no series, so other gas series are unverified. <a href="https://external-api.kalshi.com/trade-api/v2/series?category=Energy%20and%20Commodities&amp;include_volume=true" target="_blank" rel="noopener">source</a></li>
</ul>"""),
    "elections": ("Elections", "Presidential, state, and international election markets from the Elections category.",
            """<div class="card"><h3 style="margin-top:0">Series in the verified snapshot</h3><div data-render="series" data-cat="elections"></div></div>
<h2>Analysis</h2><ul>
<li>Ohio presidential winner (PRESPARTYOH) has the largest contract volume of any series in the snapshot. <a href="https://external-api.kalshi.com/trade-api/v2/series?category=Elections&amp;include_volume=true" target="_blank" rel="noopener">source</a></li>
<li>Flagged: source name does not match its URL (I-03). Zambia lists a generic kalshi.com link (I-03). POPVOTEDJTFL has a non-descriptive title (I-04). <a href="https://external-api.kalshi.com/trade-api/v2/series?category=Elections&amp;include_volume=true" target="_blank" rel="noopener">source</a></li>
</ul>"""),
    "culture": ("Culture", "Platform, AI, and public-figure markets from the Culture category.",
            """<div class="card"><h3 style="margin-top:0">Series in the verified snapshot</h3><div data-render="series" data-cat="culture"></div></div>
<h2>Analysis</h2><ul>
<li><b>Highest resolution risk.</b> Both culture series list google.com search links, a blank-name placeholder, and an individual's X profile as settlement sources (I-01). <a href="https://external-api.kalshi.com/trade-api/v2/series?category=Culture&amp;include_volume=true" target="_blank" rel="noopener">source</a></li>
<li>Recommendation: treat culture markets as unverified for strategy testing until their sources are reviewed.</li>
</ul>"""),
    "crypto": ("Crypto", "Bitcoin, Dogecoin, Solana, Cardano, and other crypto price markets from the Crypto category.",
            """<div class="card"><h3 style="margin-top:0">Series in the verified snapshot</h3><div data-render="series" data-cat="crypto"></div></div>
<h2>Analysis</h2><ul>
<li>Most crypto series name CF Benchmarks or CoinGecko as the settlement source. Those are named providers, not the exchange itself. <a href="https://external-api.kalshi.com/trade-api/v2/series?category=Crypto&amp;include_volume=true" target="_blank" rel="noopener">source</a></li>
<li>Four of nine snapshot crypto series show zero contracts traded. <a href="https://external-api.kalshi.com/trade-api/v2/series?category=Crypto&amp;include_volume=true" target="_blank" rel="noopener">source</a></li>
<li>BOA stablecoin relies on a 14-outlet news list, which needs a clearer resolution rule (flagged in the table).</li>
</ul>"""),
    "golf": ("Golf", "Major championships, PGA Tour actions, birdies, course records, and US Open markets (category Sports, tag Golf).",
            """<div class="card"><h3 style="margin-top:0">Series in the verified snapshot</h3><div data-render="series" data-cat="golf"></div></div>
<h2>Analysis</h2><ul>
<li>Golf series in the snapshot have high contract volume, led by KXBRYSONCOURSERECORDS and KXGOLFMAJOR. <a href="https://external-api.kalshi.com/trade-api/v2/series?category=Sports&amp;tags=Golf&amp;include_volume=true" target="_blank" rel="noopener">source</a></li>
<li>Flagged: KXBRYSONCOURSERECORDS settles on an individual's YouTube channel (I-02). <a href="https://external-api.kalshi.com/trade-api/v2/series?category=Sports&amp;tags=Golf&amp;include_volume=true" target="_blank" rel="noopener">source</a></li>
</ul>"""),
}

CAT_LIVE = {
    "gas": "Gas prices", "elections": "Elections", "culture": "Culture", "crypto": "Crypto", "golf": "Golf"}

PAGES_OTHER = {
    "resolved.html": ("Resolved", "resolved", "", """
<h1>Resolved markets</h1>
<p class="lead">Final results as reported by the Kalshi API. Each contract pays $1 to the side that wins. Markets that are still open are tracked on the live dashboard until they resolve.</p>
<h2>Settled markets in the snapshot</h2>
<div data-render="resolved"></div>
<h2>Resolution tracker (automated pipeline, all five topics)</h2>
<p class="note">Every settled market in scope (gas, elections, culture, crypto, golf) is recorded with its final <code>result</code> (<b>yes</b> or <b>no</b>) and settlement timestamp, collected twice hourly from the official demo API and accumulated across runs. Rows re-verified against the live API by <code>scripts/verify_rows.py</code> (settlement results must match exactly).</p>
<div data-render="pipeline-resolved"></div>
<h2>How results are recorded</h2>
<ul>
<li>The <code>result</code> field is <code>yes</code>, <code>no</code>, or <code>scalar</code>, set once the market is determined. <a href="https://docs.kalshi.com/getting_started/market_lifecycle.md" target="_blank" rel="noopener">source</a></li>
<li>Settled markets move to the <code>finalized</code> status, and settlement pays out positions. <a href="https://docs.kalshi.com/getting_started/market_lifecycle.md" target="_blank" rel="noopener">source</a></li>
</ul>
<h2>Status of other categories</h2>
<p>The verified snapshot above recorded settled results for the gas series (KXAAAGASW) only. The automated pipeline section covers settled markets across all five topics on every run since it started, so the combined table grows over time. Tracked markets on the <a href="dashboard.html">dashboard</a> show their final result once Kalshi reports it.</p>
"""),

    "findings.html": ("Findings", "findings", "", """
<h1>Findings and analysis</h1>
<p class="lead">Conclusions drawn only from values in the verified snapshot. Each point links to the source it came from.</p>
<h2>Key findings</h2>
<div data-render="findings"></div>
<h2>Series by contracts traded (snapshot)</h2>
<div data-render="volume"></div>
<h2>Categories at a glance</h2>
<div class="grid">
  <a class="tile" href="categories/gas.html">Gas prices</a><a class="tile" href="categories/elections.html">Elections</a>
  <a class="tile" href="categories/culture.html">Culture</a><a class="tile" href="categories/crypto.html">Crypto</a>
  <a class="tile" href="categories/golf.html">Golf</a>
</div>
<h2>Strategy analysis</h2>
<div class="card"><p>No strategies can be tested against live trades yet: strategy analysis needs the demo trade history, which requires a demo API key (see <a href="portfolio.html">Portfolio &amp; trades</a>), or a historical backtest over candlesticks. A proposed <b>strategy playbook</b> keyed to the trade-type taxonomy now sits on the <a href="portfolio.html">portfolio page</a> for review; it is not implemented or auto-executed. Backtesting remains an open item in <a href="questions.html">Questions</a>.</p></div>
"""),

    "portfolio.html": ("Portfolio and trades", "portfolio", "", """
<h1>Portfolio and trades</h1>
<p class="lead">Performance tracking, trade categorisation, and strategy analysis for the Kalshi demo account.</p>
<div class="banner">
<b>Not connected.</b> Portfolio and order endpoints need a demo API key ID and private key, then a signed request for each call
(<a href="https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md" target="_blank" rel="noopener">source</a>).
No credentials exist in this workspace, so no balances, positions, fills, or orders were read, and no trades were placed.
</div>
<div class="card"><h3 style="margin-top:0">Status</h3>
<table><tbody>
<tr><td>Demo account connected</td><td><span class="flag unv">no</span></td></tr>
<tr><td>Trades executed</td><td class="num">0</td></tr>
<tr><td>Portfolio performance</td><td><span class="flag unv">unverified - no data</span></td></tr>
<tr><td>Strategies</td><td><span class="flag unv">none - needs trade data</span></td></tr>
</tbody></table></div>
<h2>Demo account state (automated pull)</h2>
<p class="note">A scheduled GitHub Actions workflow pulls balance, positions, orders, and fills from the official demo API when credentials are configured as repository secrets (<code>KALSHI_KEY_ID</code>, <code>KALSHI_PRIVATE_KEY</code>). Until then the tables below stay blank and flagged &mdash; values are never inferred. Implementation: <code>scripts/kalshi_client.py</code> (signing traced line-by-line from the <a href="https://github.com/Kalshi/kalshi-starter-code-python" target="_blank" rel="noopener">official starter code</a>), <code>scripts/portfolio_pull.py</code>, <code>.github/workflows/kalshi-portfolio.yml</code>.</p>
<div data-render="portfolio-state"></div>
<h2>Strategy playbook (proposed &mdash; review before use)</h2>
<p class="note">Strategies derived from the trade-type taxonomy below. <b>None are implemented or auto-executed.</b> Choose a path on <a href="suggestions.html">Suggestions</a> before anything runs with real (demo) funds.</p>
<div data-render="strategies"></div>
<h2>Order ticket (dry run)</h2>
<p class="note">Compose an order and see the exact request the official API expects. Nothing is sent from this page. Execution path: <code>scripts/trade_runner.py</code> with demo credentials (see its header for the safety rules). Order shape verified against <a href="https://docs.kalshi.com/getting_started/quick_start_create_order.md" target="_blank" rel="noopener">Quick Start: Create your first order</a>.</p>
<div data-render="order-ticket"></div>
<h2>How trades will be categorised</h2>
<p class="note">Fields below are defined in the Kalshi API. Each one comes from the market object, so it can be recorded for every trade once data is available.</p>
<div data-render="schema"></div>
<h2>Next steps</h2>
<ul>
<li>Create a demo API key in the demo account (a one-time step by the account owner). <a href="https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md" target="_blank" rel="noopener">source</a></li>
<li>Connect read-only first (balance, positions, fills), then add trading only after analysis is reviewed. See <a href="suggestions.html">Suggestions</a>.</li>
</ul>
"""),

    "questions.html": ("Questions", "questions", "", """
<h1>Questions, information, and answers</h1>
<p class="lead">What must be answered before any decision can reasonably be made. For each question: what the verified data already shows, what is still missing, and the source.</p>
<div data-render="questions"></div>
<h2>Ways to find the missing information</h2>
<ul>
<li>Open the live dashboard from a browser and check the status banner to confirm CORS access. <a href="https://docs.kalshi.com/getting_started/quick_start_market_data.md" target="_blank" rel="noopener">source</a></li>
<li>Read the fee schedule PDF and record fee amounts per category. <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank" rel="noopener">source</a></li>
<li>Enumerate all gas series with a series-list query, and record each one. <a href="https://docs.kalshi.com/api-reference/market/get-series-list.md" target="_blank" rel="noopener">source</a></li>
<li>Compare settled AAA gas markets with the AAA source page to test the timing question (I-05). <a href="https://gasprices.aaa.com/" target="_blank" rel="noopener">source</a></li>
</ul>
"""),

    "suggestions.html": ("Suggestions", "suggestions", "", """
<h1>Suggestions</h1>
<p class="lead">Ways to improve the site and the decision process. <b>Nothing here has been implemented.</b> Choose an option for each item. Your choices are saved in this browser only.</p>
<div data-render="decisions"></div>
<div class="controls"><button id="copy-decisions">Copy my decisions (JSON)</button></div>
"""),

    "flagged.html": ("Flagged for review", "flagged", "", """
<h1>Flagged for review</h1>
<div class="banner"><b>Published for your review.</b> These items do not block publishing. Each has a source link so you can check it and request changes.</div>
<h2>Irregularities in the data</h2>
<div data-render="irregularities"></div>
<h2>Unverified items</h2>
<p class="note">Blank or unverified values are left empty, never inferred.</p>
<div data-render="unverified"></div>
<h2>Repository review</h2>
<div data-render="repo"></div>
<h2>Automated pipeline notes and irregularities</h2>
<p class="note">Findings from building and verifying the automated data pipeline against the official demo API and docs (session 4d10aedf, 2026-11-20). Full log in <a href="https://github.com/karagemop466-tech/Demo3/blob/main/COORDINATION.md" target="_blank" rel="noopener">COORDINATION.md</a>.</p>
<div data-render="pipeline-flags"></div>
"""),

    "sources.html": ("Sources", "sources", "", """
<h1>Sources</h1>
<p class="lead">Official Kalshi pages and API responses used in this site, with the date they were checked (2026-11-20 UTC).</p>
<div data-render="sources"></div>
<h2>Automated data pipeline sources</h2>
<p class="note">Endpoints and documentation used by the twice-hourly collector (<code>scripts/collect_kalshi_data.py</code>) and the row-level verifier (<code>scripts/verify_rows.py</code>). The collector's full request log for the latest run is published at <a href="../data/latest/meta.json" target="_blank" rel="noopener">data/latest/meta.json</a>.</p>
<div data-render="pipeline-sources"></div>
<h2>Row re-verification report (latest CI run)</h2>
<p class="note">Static fields and settlement results must match the live API exactly; price drift between collection and verification is reported but tolerated (markets move). Report file: <a href="../data/latest/verification_report.json" target="_blank" rel="noopener">data/latest/verification_report.json</a>.</p>
<div data-render="verify-report"></div>
"""),
}


def page(name: str, title: str, page_key: str, body: str) -> str:
    depth = name.count("/")
    root = "../" * depth if depth else ""
    return HEAD.format(title=title, root=root, page=page_key) + body + "\n" + FOOT.format(root=root)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "categories").mkdir(exist_ok=True)
    out = {}
    for name, (title, key, _root, body) in PAGES.items():
        out[name] = (title, key, body)
    for key, (label, desc, body) in CATEGORY.items():
        live = f'''
<h1>{label}</h1>
<p class="lead">{desc}</p>
<div id="live-status" class="banner">Loading live data...</div>
<h2>Top open markets (live)</h2>
<div class="card" data-live="{key}" data-limit="25"></div>
<h2>Pipeline snapshot (official demo API, collected twice hourly)</h2>
<p class="note">Rows collected by <code>scripts/collect_kalshi_data.py</code>; each links to the exact API request that produced it. The topic label is a deterministic classification (rules on the <a href="../sources.html">Sources</a> page).</p>
<div data-render="pipeline-markets" data-cat="{key}"></div>
<h2>Verified snapshot</h2>
{body}
{DETAIL}
'''
        out[f"categories/{key}.html"] = (label, key, live)
    for name, (title, key, _root, body) in PAGES_OTHER.items():
        out[name] = (title, key, body)

    for name, (title, key, body) in out.items():
        (ROOT / name).write_text(page(name, title, key, body), encoding="utf-8")
        print("wrote", name)
    (ROOT / ".nojekyll").write_text("", encoding="utf-8")


if __name__ == "__main__":
    main()
