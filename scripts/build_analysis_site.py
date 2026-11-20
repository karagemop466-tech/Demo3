#!/usr/bin/env python3
"""Generate the static analysis site under analysis/ (index.html and pages/*.html).

Data is NOT baked into the HTML. Each page loads analysis/data/live/*.json and
analysis/data/findings.json at run time through assets/app.js, so re-running the
refresh job updates the tables without rebuilding the pages.

Usage:  python3 scripts/build_analysis_site.py      (run from the repository root)
"""
import pathlib, html

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "analysis"   # all generated pages live here (other sessions own the root and docs/)

def esc(t):
    return html.escape(t, quote=True)

def page(path, title, h1, lead, page_id, topic=None, intro=""):
    # pages/*.html sit one level down: assets and sibling links need a ../ prefix from the root.
    in_pages = path.startswith("pages/")
    prefix = "../" if in_pages else ""
    pg = (lambda f: f) if in_pages else (lambda f: "pages/" + f)
    body_attr = f' data-page="{page_id}"' + (f' data-topic="{topic}"' if topic else "")
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · Kalshi market dashboard</title>
<link rel="stylesheet" href="{prefix}assets/style.css">
</head>
<body{body_attr}>
<div class="layout">
<aside id="site-nav" class="sidebar"></aside>
<main class="main">
<h1>{esc(h1)}</h1>
<p class="lead">{lead}</p>
{intro}
<div id="content"></div>
<footer>Data: Kalshi public API and official sources listed on the <a href="{pg('sources.html')}">Sources</a> page. Values not confirmed from an official response are left blank and flagged on <a href="{pg('flagged.html')}">Flagged for Review</a>. Demo trading is not active (see <a href="{pg('portfolio.html')}">Demo portfolio</a>).</footer>
</main>
</div>
<script src="{prefix}assets/app.js"></script>
</body>
</html>
"""
    out = SITE / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return str(out.relative_to(ROOT))

AAA = "https://gasprices.aaa.com/"
API = "https://api.elections.kalshi.com/trade-api/v2"
ZBAU = f"{API}/markets/KXPGATOUR-THRC26-ZBAU"
GASD = f"{API}/markets?series_ticker=KXAAAGASD&status=settled&limit=7"
POPE = f"{API}/markets?series_ticker=KXNEWPOPE&status=open&limit=7"
BTC = f"{API}/markets?series_ticker=KXBTCD&status=open&limit=7"
CULT = f"{API}/markets?series_ticker=KXXBANNEDGROK&status=open&limit=7"
DEMO = "https://docs.kalshi.com/getting_started/demo_env.md"

index_intro = f"""
<h2>Executive summary</h2>
<ul class="sum">
<li><strong>What this is.</strong> A read-only dashboard of public Kalshi market data for five topics: gas prices, elections, culture, crypto and golf. Snapshot taken 2026-11-20 (about 11:30 UTC). Data comes from the <a href="{API}/markets">Kalshi markets API</a>; tables link to the exact query each row came from.</li>
<li><strong>Gas.</strong> AAA's national average regular price was $3.6898 on 11/20/26 and $3.7212 on 11/19 (<a href="{AAA}">AAA</a>). All five captured daily gas markets for Nov 19 settled "no", and Kalshi's expiration_value of 3.7212 matches AAA's Nov 19 figure (<a href="{GASD}">API</a>).</li>
<li><strong>Largest captured market.</strong> "The RSM Classic: Zachary Bauchou wins" (KXPGATOUR-THRC26-ZBAU): volume_fp 174,280.04, open interest 169,689.49, last price $0.0030 (<a href="{ZBAU}">API</a>). Volume units are not yet confirmed, so this is ranked by contract count, not dollars.</li>
<li><strong>Elections.</strong> The captured "Next Pope" markets (KXNEWPOPE) were last updated 2026-10-23, so they may be stale (<a href="{POPE}">API</a>). Pietro Parolin has the largest captured volume_fp, 26,231.02.</li>
<li><strong>Crypto.</strong> The captured BTC hourly strikes (KXBTCD-26NOV2007) show zero volume and zero open interest. Their quotes are indicative only (<a href="{BTC}">API</a>).</li>
<li><strong>Culture.</strong> The culture series captured returned no open markets (<a href="{CULT}">API</a>).</li>
<li><strong>Resolutions.</strong> Nine settled or finalized markets captured so far, all with result "no". No YES outcome has been captured yet (<a href="{GASD}">API</a>).</li>
<li><strong>Demo account and trading.</strong> Blocked. No demo API credentials are available, so no portfolio, trade or P&amp;L data exists, and no trades were placed. The demo host is documented at <a href="{DEMO}">Kalshi demo environment</a>, which warns that demo prices may not match real markets.</li>
<li><strong>Review.</strong> Irregularities and unverified items are on <a href="pages/flagged.html">Flagged for Review</a>. Improvement ideas wait on <a href="pages/suggestions.html">Suggestions</a>, and open questions are on <a href="pages/questions.html">Questions</a>. Nothing is implemented without your approval.</li>
</ul>
<h2>Status</h2>
<p class="lead">Live refresh: the refresh job (<code>scripts/refresh_kalshi.py</code>) is written and tested offline. Its scheduled run depends on whether GitHub Actions can reach the Kalshi API, which is not yet verified. Until a run succeeds, the tables show the 2026-11-20 snapshot. Second-level price charts need the WebSocket feed and are not built.</p>
"""

written = []
written.append(page("index.html", "Overview", "Kalshi market dashboard", "Read-only analysis of public Kalshi markets in gas prices, elections, culture, crypto and golf, with source links on every row.", "index", intro=index_intro))

written.append(page("pages/markets.html", "All open markets", "Open markets by volume", "Highest-volume open markets captured in each topic. Ranking is by volume_fp (contracts, unit not confirmed). Click a column heading to sort.", "markets"))
cats = [
 ("gas","Gas prices","AAA national average regular gas. Monthly markets (KXAAAGASM) are open; daily markets (KXAAAGASD) for Nov 19 are settled. Monthly markets resolve on the AAA reading for Nov 30, 2026 (see Flagged F-06)."),
 ("elections","Elections","Next Pope markets (KXNEWPOPE) captured on 2026-11-20 with updated_time 2026-10-23, so they may be stale. The settlement source varies by market and is not verified per market (Flagged F-02)."),
 ("culture","Culture","No open culture markets were returned by the series checked (KXXBANNEDGROK, KXXBANNEDMURRAYHILLGUY1 are listed but not open). Coverage is empty in this snapshot (Flagged F-16)."),
 ("crypto","Crypto","Hourly BTC markets (KXBTCD-26NOV2007) settle on the CF Benchmarks Bitcoin Real-Time Index, 60-second average before 7 AM EST. Captured strikes show zero volume and zero open interest (Flagged F-10)."),
 ("golf","Golf","PGA Tour RSM Classic winner markets (KXPGATOUR-THRC26). Golfer-withdrawal rules are in Questions Q-04. Bauchou's market has the largest captured volume_fp."),
]
for cid, label, note in cats:
    written.append(page(f"pages/{cid}.html", label, label, esc(note), "markets", topic=cid))

written.append(page("pages/resolutions.html", "Resolutions", "Resolved markets (yes / no)", "Every settled or finalized market captured, with the result as the API reports it and the published expiration value. Result column: YES or NO.", "resolutions"))
written.append(page("pages/price-history.html", "Price history", "Price history", "Candle close price over time for markets with stored candles. Choose a market and candle size.", "price-history"))
written.append(page("pages/liquidity.html", "Liquidity", "Liquidity and contracts at each price", "Resting orders from the official orderbook: YES bids and, converted to implied YES asks, NO bids.", "liquidity"))
written.append(page("pages/portfolio.html", "Demo portfolio", "Demo account portfolio and trades", "Demo account tracking needs demo API credentials. None are available in this session, so every portfolio value below is blank and flagged.", "portfolio"))
written.append(page("pages/strategies.html", "Strategies", "Trade categorization and strategy analysis", "No trades exist, so no strategy results are reported. This page lists the fields each trade record needs.", "strategies"))
written.append(page("pages/suggestions.html", "Suggestions", "Suggestions for your review", "Improvement ideas for you to approve, defer or reject. Nothing here is implemented until you decide.", "suggestions"))
written.append(page("pages/questions.html", "Questions", "Questions, known and missing information", "What the dashboard knows, what is still missing, and how to find it.", "questions"))
written.append(page("pages/repo-review.html", "Repo review", "Repository review", "Line-by-line checks of the repository against official sources and git history.", "repo-review"))
written.append(page("pages/flagged.html", "Flagged for Review", "Flagged for Review", "Irregularities and unverified items. Flagged items do not block the merge.", "flagged"))
written.append(page("pages/sources.html", "Sources", "Sources", "Every source the findings cite, with what it was used to support and whether it was read in this session.", "sources"))

for w in written:
    print("wrote", w)
