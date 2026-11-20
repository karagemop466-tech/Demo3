#!/usr/bin/env python3
"""Generate the static HTML shells for the Kalshi Demo Tracker (docs/tracker/).

The page content is rendered in the browser from docs/tracker/data/*.json by
docs/tracker/assets/app.js and docs/tracker/assets/live.js, so the JSON files are the single source of truth.

Usage:  python3 scripts/tracker_build.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "tracker"

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Kalshi Demo Tracker</title>
<meta name="description" content="{desc}">
<link rel="stylesheet" href="{root}assets/style.css">
<script src="{root}assets/app.js" defer></script>
{extra_script}
</head>
<body data-root="{root}" data-page="{page}"{extra_attr}>
<main id="app"></main>
{body_extra}
</body>
</html>
"""

DASHBOARD_BODY = """<main>
<h1>Live dashboard</h1>
<p class="lead">Live prices and liquidity for open Kalshi <b>demo</b> markets, read directly from the public demo API in your browser. Pick a topic, click a market, and choose the time window for the price chart.</p>
<div class="toolbar">
  <label>Topic <select id="topic"></select></label>
  <label>Chart window <select id="win">
    <option value="1h">1 hour</option>
    <option value="6h">6 hours</option>
    <option value="24h" selected>24 hours</option>
    <option value="7d">7 days</option>
    <option value="30d">30 days</option>
  </select></label>
  <label><input type="checkbox" id="auto" checked> Auto-refresh (15 s)</label>
  <button id="refresh" class="primary">Refresh now</button>
</div>
<div id="status" class="notice"></div>
<h2>Open markets, ranked by volume (contracts)</h2>
<p class="small muted">Click a row to load its chart and orderbook. Volume is a count of contracts; Kalshi does not report dollars in this list (<a href="flagged.html">F-16</a>).</p>
<div id="markets"></div>
<h2 id="sel-title">Select a market above</h2>
<div class="grid2">
  <div>
    <p id="chart-meta" class="small muted"></p>
    <div id="chart"></div>
    <p id="chart-src" class="small"></p>
  </div>
  <div>
    <h3 style="margin:0 0 6px;font-size:16px">Liquidity: contracts resting at each price</h3>
    <div id="book"></div>
  </div>
</div>
<div class="box small">
  <b>Limits of this view.</b> The chart uses 1-minute candles at most, so seconds-level movement needs the WebSocket API (not implemented; see <a href="suggestions.html">SG-02</a>). Last prices and quotes can lag the exchange by several seconds (Kalshi markets docs). Demo prices may not reflect real markets. If the browser cannot reach the demo API the page shows the verified snapshot instead (<a href="flagged.html">F-19</a>).
</div>
</main>"""

PAGES = [
    # (path, root, page, title, description, topic)
    ("index.html", "", "home", "Home", "Kalshi demo markets: verified tracker for gas, elections, culture, crypto and golf.", None),
    ("dashboard.html", "", "dashboard", "Live dashboard", "Live price chart, market list and orderbook liquidity for Kalshi demo markets.", None),
    ("categories/gas.html", "../", "category", "Gas prices", "Gas-price series and markets on the Kalshi demo API.", "gas"),
    ("categories/elections.html", "../", "category", "Elections", "Election series and markets on the Kalshi demo API.", "elections"),
    ("categories/culture.html", "../", "category", "Culture", "Culture series and markets on the Kalshi demo API.", "culture"),
    ("categories/crypto.html", "../", "category", "Crypto", "Crypto series and markets on the Kalshi demo API.", "crypto"),
    ("categories/golf.html", "../", "category", "Golf", "Golf series and markets on the Kalshi demo API.", "golf"),
    ("resolutions.html", "", "resolutions", "Resolutions", "Finalized Kalshi demo markets with YES or NO results.", None),
    ("findings.html", "", "findings", "Findings and analysis", "What the verified data shows and what it cannot show yet.", None),
    ("portfolio.html", "", "portfolio", "Portfolio and trades", "Portfolio, trade execution and strategy analysis status (blocked: needs demo API key).", None),
    ("suggestions.html", "", "suggestions", "Suggestions", "Decision board of improvements. Nothing is implemented without a choice.", None),
    ("questions.html", "", "questions", "Questions", "Questions, known facts, missing information and how to get it.", None),
    ("flagged.html", "", "flagged", "Flagged for Review", "Irregularities and unverified items with source links.", None),
    ("sources.html", "", "sources", "Sources", "Official Kalshi docs and API responses used on this site.", None),
]


def render(path, root, page, title, desc, topic):
    extra_attr = f' data-topic="{topic}"' if topic else ""
    body_extra = ""
    extra_script = ""
    if page == "dashboard":
        extra_script = f'<script src="{root}assets/live.js" defer></script>'
    html = HEAD.format(
        title=title,
        desc=desc,
        root=root,
        page=page,
        extra_attr=extra_attr,
        extra_script=extra_script,
        body_extra=body_extra,
    )
    if page == "dashboard":
        html = html.replace('<main id="app"></main>', DASHBOARD_BODY)
    out = DOCS / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main():
    written = [render(*p) for p in PAGES]
    for w in written:
        print("wrote", w.relative_to(ROOT))


if __name__ == "__main__":
    main()
