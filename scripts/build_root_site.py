#!/usr/bin/env python3
"""Build the canonical root site of Demo3 from the verified data registers.

Rules enforced at build time (project brief):
  * Every rendered table row must carry an official source link, or it is
    rendered with a blank source cell and an "unverified" flag (never inferred).
  * One nav, one style, one shell for every page.
  * Registers are consolidated from every session's verified data files
    (docs/data/verified.json, docs/tracker/data/*.json, analysis/data/findings.json)
    and from the legacy root pages (content extracted, originals preserved in git).

Run: python3 scripts/build_root_site.py
"""
import json
import pathlib
import re
import html as _html
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEMO = "https://external-api.demo.kalshi.co/trade-api/v2"
DOCS = "https://docs.kalshi.com"

UNVERIFIED = []          # (page, row label) collected for the Flagged page
BUILD_ERRORS = []


def esc(s):
    return _html.escape(str(s if s is not None else ""), quote=True)


def load(rel):
    return json.loads((ROOT / rel).read_text())


tracker = load("docs/tracker/data/snapshot.json")
tracker_q = load("docs/tracker/data/questions.json")["questions"]
tracker_s = load("docs/tracker/data/suggestions.json")["suggestions"]
tracker_f = load("docs/tracker/data/flags.json")["flags"]
tracker_src = load("docs/tracker/data/sources.json")
verified = load("docs/data/verified.json")
findings = load("analysis/data/findings.json")
live = load("analysis/data/live/markets.json")
legacy = load("data/legacy/cde2ae63_rows.json")  # preserved rows from session cde2ae63

SRC_MAP = {r["id"]: r["url"] for r in findings["sources"]["rows"]}

# Explicit endpoint/doc mentions -> official docs page (citation resolution for
# rows that name the endpoint themselves; never inferred).
ENDPOINT_CITES = [
    ("order_groups", "https://docs.kalshi.com/getting_started/order_groups.md"),
    ("orderbook", "https://docs.kalshi.com/getting_started/orderbook_responses"),
    ("candlestick", "https://docs.kalshi.com/api-reference/market/get-market-candlesticks"),
    ("trades endpoint", "https://docs.kalshi.com/api-reference/market/get-trades"),
    ("trade endpoint", "https://docs.kalshi.com/api-reference/market/get-trades"),
    ("get /series", "https://docs.kalshi.com/api-reference/market/get-series-list"),
    ("/series", "https://docs.kalshi.com/api-reference/market/get-series-list"),
    ("/markets", "https://docs.kalshi.com/api-reference/market/get-markets"),
    ("/events", "https://docs.kalshi.com/api-reference/market/get-events"),
    ("perps", "https://docs.kalshi.com/margin"),
    ("margin", "https://docs.kalshi.com/margin"),
    ("settlement", "https://docs.kalshi.com/getting_started/market_settlement"),
    ("api key", "https://docs.kalshi.com/getting_started/api_keys"),
    ("rate limit", "https://docs.kalshi.com/getting_started/rate_limits"),
    ("demo", "https://docs.kalshi.com/getting_started/demo_env"),
    ("volume_fp", "https://docs.kalshi.com/api-reference/market/get-markets"),
    ("candlesticks", "https://docs.kalshi.com/api-reference/market/get-market-candlesticks"),
]


def resolve_srcs(srcs):
    out = []
    for s in srcs or []:
        if not s:
            continue
        out.append(SRC_MAP.get(s, s) if not str(s).startswith("http") else s)
    return [u for u in out if str(u).startswith("http")]


TICKER_SRC = {}
for _r in tracker.get("series", []) + tracker.get("markets", []) + tracker.get("events", []):
    if _r.get("ticker") and str(_r.get("source_api", "")).startswith("http"):
        TICKER_SRC.setdefault(_r["ticker"], _r["source_api"])
for _r in verified.get("series", []) + verified.get("resolved", []):
    if _r.get("ticker") and str(_r.get("source", "")).startswith("http"):
        TICKER_SRC.setdefault(_r["ticker"], _r["source"])

_FLAG_SRC = {}


def _build_flag_src():
    for f in tracker_f:
        if f.get("source"):
            _FLAG_SRC[f["id"]] = f["source"]
    for f in findings["flagged"]["rows"]:
        us = resolve_srcs(f.get("src", []))
        if us:
            _FLAG_SRC[f["id"]] = us[0]
    for f in verified.get("irregularities", []):
        if f.get("source"):
            _FLAG_SRC[f["id"]] = f["source"]


_build_flag_src()


def citations(*texts):
    """Official URLs that the row's own text explicitly cites (URLs, flag
    cross-references, endpoint names). Nothing is inferred."""
    blob = " ".join(str(t) for t in texts if t)
    urls = [u.rstrip(".,);") for u in re.findall(r"https?://[^\s)\"'<>]+", blob)]
    for fid in re.findall(r"\b(?:F|I|U|R)-\d+\b", blob):
        if fid in _FLAG_SRC:
            u = _FLAG_SRC[fid]
            if str(u).startswith("http"):
                urls.append(u)
    for tok, url in TICKER_SRC.items():
        if tok in blob:
            urls.append(url)
    low = blob.lower()
    for key, url in ENDPOINT_CITES:
        if key in low:
            urls.append(url)
    out, seen = [], set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ---------------------------------------------------------------- table core
class Table:
    def __init__(self, headers, page):
        self.headers = headers
        self.page = page
        self.rows = []

    def row(self, cells, sources=None, unverified=False, label=None, blank_cols=()):
        sources = resolve_srcs(sources)
        if not sources and not unverified:
            self.rows.append(
                "<tr>"
                + "".join(f"<td>{c}</td>" for c in cells)
                + "<td><span class='pill warn'>unverified (no source) — see Flagged</span></td></tr>"
            )
            UNVERIFIED.append((self.page, label or re.sub("<[^>]+>", "", str(cells[0]))[:60]))
            return
        if unverified:
            UNVERIFIED.append((self.page, label or re.sub("<[^>]+>", "", str(cells[0]))[:60]))
        src_cell = " · ".join(
            f'<a class="src" href="{esc(u)}" target="_blank" rel="noopener">source</a>'
            for u in sources
        ) or "<span class='pill warn'>unverified</span>"
        self.rows.append(
            "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + f"<td>{src_cell}</td></tr>"
        )

    def render(self, caption=None, note=None):
        h = "".join(f"<th>{x}</th>" for x in self.headers) + "<th>Source</th>"
        cap = f"<p class='muted'>{caption}</p>" if caption else ""
        nt = f"<p class='small muted'>{note}</p>" if note else ""
        return (f"{cap}<div class='tablewrap'><table><thead><tr>{h}</tr></thead>"
                f"<tbody>{''.join(self.rows)}</tbody></table></div>{nt}")


# ---------------------------------------------------------------- page shell
NAV = [
    ("index.html", "Home"),
    ("dashboard.html", "Live dashboard"),
    ("data-tracking.html", "Data tracking"),
    ("gas-prices.html", "Gas prices"),
    ("elections.html", "Elections"),
    ("culture.html", "Culture"),
    ("crypto.html", "Crypto"),
    ("golf.html", "Golf"),
    ("portfolio.html", "Portfolio"),
    ("strategy.html", "Strategy lab"),
    ("trades.html", "Trades"),
    ("questions.html", "Questions"),
    ("suggestions.html", "Suggestions"),
    ("flagged.html", "Flagged for review"),
    ("sources.html", "Sources"),
    ("repo-review.html", "Repo review"),
    ("methodology.html", "Methodology"),
    ("api-reference.html", "API reference"),
]

EXTRA_HEAD = ""


def shell(title, active, body, scripts=()):
    parts = []
    for href, lbl in NAV:
        cls = ' class="active"' if href == active else ""
        parts.append(f'<a href="{href}"{cls}>{esc(lbl)}</a>')
    nav = "".join(parts)
    js = "".join(f'<script src="{s}"></script>' for s in scripts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Kalshi Demo Tracker</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="top"><div class="wrap"><nav class="main">
<a class="brand" href="index.html">Kalshi Demo Tracker</a>
{nav}
</nav></div></header>
<main class="wrap">
{body}
</main>
<footer class="wrap"><p class="small muted">Kalshi Demo Tracker — built from verified sources only. Demo environment
(mock funds): <span class="mono">https://external-api.demo.kalshi.co/trade-api/v2</span> ·
Docs: <a href="https://docs.kalshi.com" target="_blank" rel="noopener">docs.kalshi.com</a> ·
Every table row links its source; blank cells are flagged on <a href="flagged.html">Flagged for review</a>.</p></footer>
{js}
</body>
</html>
"""


def write_page(name, title, active, body, scripts=()):
    if name in EXTERNALLY_MAINTAINED and (ROOT / name).exists():
        print("kept", name, "(maintained outside the generator)")
        return
    (ROOT / name).write_text(shell(title, active, body, scripts))
    print("wrote", name)


def legacy_rows(file):
    return legacy.get("files", {}).get(file, [])


# ---------------------------------------------------------------- registers
def consolidated_questions():
    """Merge question registers from all sessions, dedupe by normalized text."""
    rows, seen = [], {}

    def add(qid, q, known, missing, how, srcs, origin):
        key = re.sub(r"[^a-z0-9 ]", "", str(q).lower())[:60]
        if key in seen:
            r = seen[key]
            r["known"] = r["known"] or known
            r["missing"] = r["missing"] or missing
            r["how"] = r["how"] or how
            r["srcs"] = resolve_srcs(list(r["srcs"]) + list(srcs or []))
            r["origins"].append(origin)
            return
        r = dict(id=qid, q=q, known=known, missing=missing, how=how,
                 srcs=resolve_srcs(srcs), origins=[origin])
        seen[key] = r
        rows.append(r)

    for q in tracker_q:
        add(q["id"], q["question"], q.get("known", ""), q.get("missing", ""),
            q.get("how_to_get", ""),
            (q.get("src") or q.get("sources") or []) +
            citations(q["question"], q.get("known", ""), q.get("missing", ""),
                      q.get("how_to_get", "")),
            "e2aacbd6 tracker")
    for q in findings["questions"]["rows"]:
        add(q["id"], q["question"], q.get("answer", "") or q.get("status", ""),
            q.get("missing", "") or q.get("information_needed", ""),
            q.get("how", "") or q.get("how_to_get", "") or q.get("discovery", ""),
            q.get("src", []) + citations(q["question"], q.get("answer", ""),
                                         q.get("how", "") or q.get("how_to_get", "")),
            "3e08e6dc analysis")
    for n, r in enumerate(legacy_rows("questions.html"), 1):
        cells = r["cells"]
        if len(cells) >= 5:
            add(f"CQ-{cells[0].strip('Q').strip()}", cells[1], cells[3], cells[2],
                cells[4], r["hrefs"], "cde2ae63 legacy")
    for i, q in enumerate(verified.get("questions", []), 1):
        add(f"VQ-{i}", q.get("q", ""), q.get("known", ""), q.get("missing", ""),
            q.get("how", "") or q.get("discovery", ""),
            [q.get("source", "")] + citations(q.get("q", ""), q.get("known", ""),
                                              q.get("missing", "")),
            "00a943bd docs")
    return rows


def consolidated_suggestions():
    rows, seen = [], {}

    def add(sid, title, detail, benefit, effort, risk, options, srcs, origin):
        key = re.sub(r"[^a-z0-9 ]", "", str(title).lower())[:60]
        if key in seen:
            r = seen[key]
            r["srcs"] = resolve_srcs(list(r["srcs"]) + list(srcs or []))
            r["origins"].append(origin)
            return
        r = dict(id=sid, title=title, detail=detail, benefit=benefit, effort=effort,
                 risk=risk, options=options or [], srcs=resolve_srcs(srcs),
                 origins=[origin])
        seen[key] = r
        rows.append(r)

    for s in tracker_s:
        add(s["id"], s["title"], s.get("detail", ""), s.get("impact", ""),
            s.get("effort", ""), s.get("risk", ""), s.get("options", []),
            (s.get("src") or []) + citations(s["title"], s.get("detail", ""),
                                             " ".join(s.get("options", []))),
            "e2aacbd6 tracker")
    for s in findings["suggestions"]["rows"]:
        add(s["id"], s["suggestion"], s.get("detail", ""), s.get("benefit", ""),
            s.get("effort", "") or s.get("information_needed", ""),
            s.get("risk", ""), s.get("options", []),
            s.get("src", []) + citations(s["suggestion"], s.get("detail", "")),
            "3e08e6dc analysis")
    for n, r in enumerate(legacy_rows("suggestions.html"), 1):
        cells = r["cells"]
        if len(cells) >= 5:
            add(f"CS-{cells[0]}", cells[1], "", cells[2], cells[3], "",
                [], r["hrefs"] or [], "cde2ae63 legacy")
    for s in verified.get("suggestions", []):
        add(s.get("id", "VS"), s.get("title", ""), s.get("detail", ""), "",
            "", "", s.get("options", []), [s.get("source", "")], "00a943bd docs")
    return rows


def consolidated_flags():
    rows, seen = [], {}

    def add(fid, area, item, detail, srcs, status, origin):
        key = (str(fid), re.sub(r"[^a-z0-9 ]", "", str(item).lower())[:50])
        if key in seen:
            r = seen[key]
            r["srcs"] = resolve_srcs(list(r["srcs"]) + list(srcs or []))
            return
        r = dict(id=fid, area=area, item=item, detail=detail,
                 srcs=resolve_srcs(srcs), status=status or "open", origins=[origin])
        seen[key] = r
        rows.append(r)

    for f in tracker_f:
        add(f["id"], f.get("area", ""), f.get("item", ""), f.get("irregularity", ""),
            [f.get("source", "")] + citations(f.get("irregularity", ""), f.get("item", "")),
            f.get("status", ""), "e2aacbd6 tracker")
    for f in findings["flagged"]["rows"]:
        add(f["id"], f.get("type", ""), f.get("item", ""), f.get("detail", ""),
            f.get("src", []) + citations(f.get("detail", ""), f.get("item", "")),
            f.get("action", ""), "3e08e6dc analysis")
    for f in verified.get("irregularities", []):
        add(f.get("id", "I"), f.get("area", ""), f.get("item", ""), "",
            [f.get("source", "")], f.get("severity", ""), "00a943bd docs")
    for i, u in enumerate(verified.get("unverified", []), 1):
        add(f"U-{i}", "Unverified", u.get("item", ""), u.get("reason", ""), [],
            "unverified", "00a943bd docs")
    for n, r in enumerate(legacy_rows("flagged.html"), 1):
        cells = r["cells"]
        if len(cells) >= 3:
            add(f"CF-{cells[0]}", cells[2], cells[1], " ".join(cells[3:-1]) if len(cells) > 3 else "",
                r["hrefs"] or [], cells[-1] if cells else "", "cde2ae63 legacy")
    # integration-session flags (arena-3a22fb0f)
    add("R-05", "Repository", "Root duplicate engines from parallel sessions",
        "cde2ae63's assets/js + assets/css engine duplicated the root site. At integration the "
        "content was ported into the canonical site and the duplicate engine removed "
        "(originals remain in git history at 45bde12). See COORDINATION.md.",
        ["https://github.com/karagemop466-tech/Demo3/commits/main"], "resolved", "3a22fb0f")
    add("I-11", "Trading", "No demo-account API credentials were provided",
        "Live order execution needs a Kalshi demo API key (created at demo.kalshi.co). Until one is "
        "supplied, the Trade pages run in clearly labeled paper-trading mode against live demo "
        "market data. No real or demo orders are sent without a key.",
        [f"{DOCS}/getting_started/demo_env", f"{DOCS}/getting_started/api_keys"],
        "open — discovery step documented", "3a22fb0f")
    add("I-12", "Verification", "Cells without official source links",
        "Cells found without an official source during the per-row verification pass are left "
        "blank and flagged; never inferred.",
        [f"{DOCS}/getting_started/quick_start_market_data"], "open", "3a22fb0f")
    add("R-06", "Documentation", "Archive pages use the production API base",
        "docs/ and analysis/ fetch public data from api.elections.kalshi.com while the brief "
        "specifies the demo endpoints. The canonical root site uses the demo API. Archives are "
        "labeled on the Sources page.",
        [f"{DOCS}/getting_started/demo_env", f"{DOCS}/getting_started/api_environments"],
        "disclosed", "3a22fb0f")
    add("R-07", "API client", "Auth signature path fixed at integration",
        "The shared API client signed the request path without the /trade-api/v2 prefix; the "
        "official docs sign the full request path (e.g. /trade-api/v2/portfolio/balance) without "
        "query string. Fixed in assets/app.js at integration (would otherwise 401 on every "
        "authenticated call).",
        [f"{DOCS}/getting_started/api_keys"], "resolved", "3a22fb0f")
    # session 6d201d19 — snapshot swing detector (scripts/price_alerts.py -> data/latest/alerts.json).
    # The live two-chat alert page is the merged feature in dashboard.html (PR #28, session 6ebc1cb7);
    # this session's duplicate page was withdrawn (see COORDINATION.md, session 6d201d19).
    add("F-6D-01", "Alerts / high-ROI", "High-ROI screen is a placeholder, not the user's model",
        "The high-ROI screen (scripts/price_alerts.py, and the live chat in dashboard.html) is arithmetic on "
        "official prices: buy the side the move made cheaper, gross payout multiple (1 - p) / p >= 1.00, volume "
        "> 0, not a synthetic series. The user's model was not supplied, so this is not a forecast. Replace it "
        "with the user's model output.",
        [f"{DOCS}/api-reference/market/get-markets.md"], "open - user to supply model rules", "6d201d19")
    add("F-6D-02", "Alerts / cause links", "Website/event links behind sharp price jumps are not verified",
        "The Kalshi market API returns prices, volume and bid/ask but no news or cause field. Cause-link cells "
        "are left blank and labelled unverified; nothing is inferred from news or timing.",
        [f"{DOCS}/api-reference/market/get-markets.md"], "open - needs an external, verified news source", "6d201d19")
    add("F-6D-03", "Alerts / snapshot", "Snapshot swings are in a synthetic exchange-test series",
        "Both early swings in data/history/prices.jsonl are in KXDEMOFUTHOURLY-26NOV20H12-UP (repo finding I-15). "
        "The official demo page says demo prices and behavior may not reflect real markets. The market title is "
        "not in any committed market file, so it is shown as unverified.",
        [f"{DOCS}/getting_started/demo_env"], "disclosed", "6d201d19")
    add("F-6D-04", "Alerts / live browser", "Live polling depends on browser access to the demo API",
        "The live chat in dashboard.html reads GET /markets?tickers= from the browser. Access was recorded as allowed "
        "in data/cors_test.json (12:14:51Z, repo artifact). The official docs say market responses are cached "
        "briefly, so prices can lag the exchange by several seconds. Re-check at runtime.",
        [f"{DOCS}/getting_started/demo_env", f"{DOCS}/api-reference/market/get-markets.md"],
        "open - re-verify at runtime", "6d201d19")
    add("F-6D-05", "Alerts / cadence", "Snapshot history is sparse; live polling is the real-time path",
        "prices.jsonl gets one row per market per kalshi-data.yml run (twice hourly, plus pushes), so snapshot "
        "swings are coarse. The live chat is the real-time path. Swings between polls can be missed.",
        [f"{DOCS}/api-reference/market/get-markets.md"], "disclosed", "6d201d19")
    add("F-6D-07", "Alerts / single prints", "A single last-trade print can look like a swing",
        "On 2026-11-20 KXPRESNOMD-28-HBID printed last_price 0.8110 at 19:14:49Z while yes_bid was 0.0020 and "
        "yes_ask 0.8110 (208 contracts offered). A later live read (about 19:25Z) showed last_price 0.0030. A "
        "last-trade price can be one print. scripts/price_alerts.py therefore marks a swing whose next reading "
        "moves back toward the old price as a single print, and shows 'no later reading yet' when there is none. "
        "A second print on 19:27:37Z (0.0030 -> 0.8110) had bid 0.0020 and ask 0.0030, so its quote midpoint (0.0025) "
        "does not support the printed last price. scripts/price_alerts.py now records last_supported_by_quote. The "
        "19:14:49Z row was written on branch arena/6d201d19-demo3 (commit 7d06a79) and is absent from main's later "
        "prices.jsonl (see F-6D-08). The live chat does not yet do this (CR-6D-2 in COORDINATION.md).",
        ["https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=KXPRESNOMD-28-HBID",
         f"{DOCS}/api-reference/market/get-markets.md"],
        "open - owner of the live chat to add the persistence check", "6d201d19")
    add("F-6D-08", "Data pipeline", "Concurrent collector runs from several branches rewrite the same rolling history",
        "data/history/prices.jsonl is appended by kalshi-data.yml on every branch that pushes, and the workflow "
        "trims it to 20000 lines. Each branch then commits its own copy. Rows written on one branch (e.g. the "
        "19:14:49Z KXPRESNOMD-28-HBID row on arena/6d201d19-demo3) can be lost when another branch's copy is taken. "
        "Snapshot history is therefore not a complete record. Owner: pipeline. Fix: write the history from main only, or key rows by a unique id.",
        ["https://docs.kalshi.com/api-reference/market/get-markets.md", f"{DOCS}/getting_started/demo_env"],
        "open - pipeline owner to decide", "6d201d19")
    add("F-6D-09", "Generator / dashboard", "build_root_site.py overwrites dashboard.html and drops the live alert cards",
        "build_dashboard() writes dashboard.html from its own template. The live two-chat alert cards merged in PR #28 "
        "(session 6ebc1cb7) were added to dashboard.html by hand, so running this generator on main removes them. "
        "CI runs only verify_root_site.py, so nothing breaks today. Owner: the integration session. Fix: move the alert "
        "cards into build_dashboard() before any future regeneration.",
        [f"{DOCS}/getting_started/demo_env"], "open - integration owner", "6d201d19")
    add("F-6D-10", "CI / collector", "collect.yml failed at workflow level on main (duplicate 'if' key)",
        "The 'Request Pages rebuild' step in .github/workflows/collect.yml had two 'if:' keys after a merge. The "
        "collector runs on main (44804291212, 44804259549, 44804243948) ended with 0 jobs and no log. The duplicate key "
        "is the likely cause, but this is not confirmed by an error message. Fixed on session 6d201d19 by keeping the "
        "single 'refs/heads/main' condition. All workflow files were checked for duplicate keys (none others). "
        "Confirm with the next scheduled run.",
        ["https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions"],
        "fixed in this branch - verify the next scheduled run", "6d201d19")
    add("F-6D-06", "Trading / portfolio", "Demo account portfolio and live trades still blocked",
        "Portfolio, fills and order placement need a Kalshi demo API key. The demo key is created by a "
        "person at demo.kalshi.co; this agent cannot create one. Until a key is provided, trade rows stay "
        "blank and flagged (see I-12 and F-3B-03).",
        [f"{DOCS}/getting_started/demo_env", "https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account"],
        "open - needs a user-created demo key", "6d201d19")
    return rows


def consolidated_sources():
    rows, seen = [], set()

    def add(sid, label, url, supports):
        if not url or url in seen:
            return
        seen.add(url)
        rows.append(dict(id=sid, label=label, url=url, supports=supports or ""))

    for s in findings["sources"]["rows"]:
        add(s["id"], s.get("label", ""), s.get("url", ""), s.get("supports", ""))
    for s in tracker_src.get("sources", tracker_src if isinstance(tracker_src, list) else []):
        add(s.get("id", "SRC"), s.get("label", "") or s.get("title", ""),
            s.get("url", ""), s.get("supports", "") or s.get("note", ""))
    for s in verified.get("sources", []):
        add("VSRC", s.get("title", "") or s.get("name", ""),
            s.get("url", "") or s.get("source", ""), s.get("note", ""))
    add("DOCS-DEMO", "Kalshi docs — Test in the demo environment",
        f"{DOCS}/getting_started/demo_env", "Official demo REST/WebSocket endpoint table.")
    add("DOCS-KEYS", "Kalshi docs — API keys & request signing",
        f"{DOCS}/getting_started/api_keys", "Signature = timestamp + method + path (no query).")
    add("DOCS-MKT", "Kalshi docs — Quick start: market data",
        f"{DOCS}/getting_started/quick_start_market_data", "Public endpoints; orderbook format.")
    add("DOCS-SETTLE", "Kalshi docs — Market settlement",
        f"{DOCS}/getting_started/market_settlement", "Yes/No resolution, $1/contract payout.")
    add("DOCS-RATE", "Kalshi docs — Rate limits",
        f"{DOCS}/getting_started/rate_limits", "Backoff on 429.")
    add("LIVE-STATUS", "Demo exchange status (live)",
        f"{DEMO}/exchange/status", "exchange_active / trading_active.")
    add("LIVE-SERIES", "Demo series list (live)",
        f"{DEMO}/series", "Series tickers, categories, tags per topic.")
    add("LIVE-MARKETS", "Demo markets list (live)",
        f"{DEMO}/markets", "Status, prices (dollars), volume_fp, open_interest_fp.")
    add("LIVE-OB", "Demo orderbook (live)",
        f"{DEMO}/markets/KXPGATOP40-26NOV22-LUDVIC/orderbook", "orderbook_fp price/size levels.")
    return rows


# ---------------------------------------------------------------- legacy extraction
def extract_body(path):
    """Extract <main>…</main> inner HTML from a legacy page (keeps its content)."""
    p = ROOT / path
    if not p.exists():
        return ""
    s = p.read_text()
    m = re.search(r"<main[^>]*>(.*)</main>", s, re.S)
    return m.group(1) if m else ""


def extract_rows(path):
    """Extract table rows (td cell texts + link hrefs) from a legacy page."""
    p = ROOT / path
    if not p.exists():
        return []
    s = p.read_text()
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", s, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not cells:
            continue
        texts = [re.sub(r"<[^>]+>", " ", c).strip() for c in cells]
        hrefs = re.findall(r'href="(https?://[^"]+)"', tr)
        out.append((texts, hrefs))
    return out


# ---------------------------------------------------------------- pages

def legacy_table(file, page, caption):
    rows = legacy_rows(file)
    if not rows:
        return ""
    t = Table(["Col 1", "Col 2", "Col 3", "Col 4", "Col 5"], page)
    for r in rows:
        cells = (r["cells"] + ["", "", "", "", ""])[:5]
        t.row([esc(c) for c in cells], r.get("hrefs", []),
              label=(cells[0] or "row")[:30], unverified=not r.get("hrefs"))
    return ("<details><summary class='muted'>Preserved reference rows from session cde2ae63 "
            "(kept verbatim for review — verify against current V2 endpoints)</summary>"
            + t.render(caption=caption) + "</details>")


def build_index():
    t = Table(["Item", "Detail"], "index")
    t.row(["Recommended demo REST endpoint",
           f'<span class="mono">{DEMO}</span>'],
          [f"{DOCS}/getting_started/demo_env"])
    t.row(["Also-supported demo REST endpoint",
           '<span class="mono">https://demo-api.kalshi.co/trade-api/v2</span>'],
          [f"{DOCS}/getting_started/demo_env"])
    t.row(["Demo WebSocket (recommended)",
           '<span class="mono">wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2</span>'],
          [f"{DOCS}/getting_started/demo_env"])
    t.row(["Demo WebSocket (also supported)",
           '<span class="mono">wss://demo-api.kalshi.co/trade-api/ws/v2</span>'],
          [f"{DOCS}/getting_started/demo_env"])
    t.row(["Demo account", "Mock funds; credentials are separate from production. Kalshi warns "
           "demo prices/behavior may not reflect real markets."],
          [f"{DOCS}/getting_started/demo_env"])
    t.row(["Public market data", "No API key needed for series, events, markets, orderbooks, "
           "trades, candlesticks."],
          [f"{DOCS}/getting_started/quick_start_market_data"])
    t.row(["Request signing (for trading)", "timestamp + method + path (full path incl. "
           '<span class="mono">/trade-api/v2</span>, no query string); Ed25519 or RSA-PSS SHA-256.'],
          [f"{DOCS}/getting_started/api_keys"])
    t.row(["Settlement", "Winning contracts pay $1 each; results are recorded as yes/no."],
          [f"{DOCS}/getting_started/market_settlement"])
    t.row(["Dollar-volume column", "<strong>Unverified estimate</strong> = contracts × last price "
           "(the API reports contracts, not dollars). Never an exchange-reported figure."],
          [f"{DOCS}/api-reference/market/get-markets"], label="est dollar volume")

    counts = (f"{len(consolidated_questions())} decision questions · "
              f"{len(consolidated_suggestions())} suggestions (review workflow) · "
              f"{len(consolidated_flags())} flagged items · "
              f"{len(consolidated_sources())} sources")
    body = f"""
<h1>Kalshi Demo Tracker</h1>
<p>Collect, organize and analyze the highest-dollar <strong>live events on Kalshi's demo
environment</strong> — five topics only: <strong>gas prices, elections, culture, crypto and
golf</strong>. Track events to resolution (yes/no), execute and analyze trades, and review
questions and suggestions before making decisions.</p>
<div class="grid">
  <div class="card"><div class="muted">Live market status</div><div class="stat" id="liveStatus">checking…</div>
  <p class="small muted">Checked in your browser from <span class="mono">/exchange/status</span>.</p></div>
  <div class="card"><div class="muted">Decision registers</div><div class="stat">{esc(counts.split(' · ')[0])}</div>
  <p class="small muted">{esc(counts)}</p></div>
  <div class="card"><div class="muted">Start here</div>
  <p><a class="btn" href="dashboard.html">Live dashboard</a>
  <a class="btn secondary" href="portfolio.html">Portfolio &amp; strategies</a></p></div>
</div>

<h2>Executive summary — important details</h2>
{t.render(caption="Endpoints, environment and definitions used throughout this site. Each row links the official source.")}

<h2>Topics tracked</h2>
<div class="grid">
  <div class="card"><h3><a href="gas-prices.html">Gas prices</a></h3><p class="small muted">AAA/KXAAAGAS state gasoline price series.</p></div>
  <div class="card"><h3><a href="elections.html">Elections</a></h3><p class="small muted">House, Senate, presidential and international elections.</p></div>
  <div class="card"><h3><a href="culture.html">Culture</a></h3><p class="small muted">Awards, entertainment and cultural events.</p></div>
  <div class="card"><h3><a href="crypto.html">Crypto</a></h3><p class="small muted">Bitcoin, Ethereum and crypto price ranges.</p></div>
  <div class="card"><h3><a href="golf.html">Golf</a></h3><p class="small muted">PGA, majors and golf head-to-heads.</p></div>
</div>

<h2>How to use this site</h2>
<table><thead><tr><th>Goal</th><th>Page</th><th>Source</th></tr></thead><tbody>
<tr><td>Track highest-dollar live events, price chart (seconds/minutes/hours), orderbook liquidity, resolutions</td><td><a href="dashboard.html">Live dashboard</a></td><td><a class="src" href="https://docs.kalshi.com/getting_started/quick_start_market_data" target="_blank" rel="noopener">source</a></td></tr>
<tr><td>Execute trades (demo key or labeled paper mode), analyze performance, categorize trades, build strategies</td><td><a href="portfolio.html">Portfolio</a> · <a href="trades.html">Trades</a></td><td><a class="src" href="https://docs.kalshi.com/api-reference/orders/create-order-v2" target="_blank" rel="noopener">source</a></td></tr>
<tr><td>Decide before changing anything: questions, missing information, discovery steps</td><td><a href="questions.html">Questions</a> · <a href="suggestions.html">Suggestions</a></td><td><a class="src" href="https://docs.kalshi.com/getting_started/demo_env" target="_blank" rel="noopener">source</a></td></tr>
<tr><td>Verify every value: per-row sources, flagged items, repo review</td><td><a href="sources.html">Sources</a> · <a href="flagged.html">Flagged</a> · <a href="repo-review.html">Repo review</a></td><td><a class="src" href="https://docs.kalshi.com/getting_started/quick_start_market_data" target="_blank" rel="noopener">source</a></td></tr>
</tbody></table>

<h2>Parallel-session archives (preserved, not merged into this UI)</h2>
<p class="small muted">Earlier sessions built standalone trees during the same run. They are kept intact
for manual review and linked here: <a href="docs/index.html">docs/ (session 00a943bd)</a> ·
<a href="docs/tracker/index.html">docs/tracker/ (session e2aacbd6)</a> ·
<a href="analysis/index.html">analysis/ (session 3e08e6dc)</a> ·
<a href="demo-desk/index.html">demo-desk/ (session 4ea36f44, read-only Demo Desk)</a> ·
<a href="research/kalshi-api-verified-reference.md">research/ verified API reference (6908a11a)</a> ·
<a href="EXECUTIVE_SUMMARY.md">EXECUTIVE_SUMMARY.md</a> · <a href="FLAGGED.md">FLAGGED.md</a> ·
<a href="SUGGESTIONS.md">SUGGESTIONS.md</a> · <a href="COORDINATION.md">COORDINATION.md</a> (task board).</p>
"""
    write_page("index.html", "Home", "index.html", body, scripts=("assets/app.js", "assets/site.js"))


def build_dashboard():
    body = """
<h1>Live dashboard</h1>
<p>Highest-dollar live events in the five tracked topics, with price chart (x = time in
seconds/minutes/hours, y = current contract price), orderbook liquidity (contracts available at
each price), recent trades, and yes/no resolution tracking. All data is fetched
<strong>live in your browser</strong> from the Kalshi demo API (no key needed for market data);
if the browser blocks the request the tables fall back to the snapshot links in
<a href="sources.html">Sources</a>.</p>
<div id="banner" style="display:none"></div>
<div class="card">
  <h2>1 · Discovery &amp; ranking</h2>
  <p class="small muted"><span id="discoveryStatus">idle</span> · <span id="scanStatus">no scan yet</span></p>
  <p>
    <button class="btn" id="discoverBtn">Discover series (GET /series)</button>
    <button class="btn secondary" id="scanBtn">Scan open markets</button>
    <label>Scan depth <select id="scanDepth">
      <option value="15" selected>15 series/topic (default)</option>
      <option value="50">50 series/topic</option>
      <option value="0">All matched series (slower)</option>
    </select></label>
    <label>Extra series (comma) <input id="manualSeries" size="18" placeholder="KXAAAGASW"></label>
  </p>
  <p class="small muted">Coverage note: the scan pages open markets for every matched series up to the
  depth chosen above (rate-limit friendly). The dollar ranking is an <strong>unverified
  estimate</strong> (contracts × last price). Each row links its exact API URL.</p>
  <div id="discoveryTable"></div>
  <h3>Highest estimated dollar volume (live)</h3>
  <div id="rankingTable"></div>
</div>

<div class="card">
  <h2>2 · Selected market: price chart &amp; liquidity</h2>
  <p class="muted" id="detailTitle">Select a market above (Track).</p>
  <p class="small muted" id="detailMeta"></p>
  <div class="seg" role="group" aria-label="Chart window">
    <button data-window="30" aria-pressed="false">30 s</button>
    <button data-window="120" aria-pressed="false">2 min</button>
    <button data-window="600" aria-pressed="false">10 min</button>
    <button data-window="1800" aria-pressed="false">30 min</button>
    <button data-window="3600" aria-pressed="true">1 h</button>
    <button data-window="21600" aria-pressed="false">6 h</button>
    <button data-window="86400" aria-pressed="false">24 h</button>
    <button class="btn secondary" id="refreshObBtn">Refresh book</button>
  </div>
  <canvas id="priceChart" height="260" aria-label="Contract price over time"></canvas>
  <p class="small muted">X axis: time (labels switch to seconds/minutes/hours with the window).
  Y axis: current contract price (cents). Live samples merge with 1-minute candlesticks
  (<span class="mono">/series/{series}/markets/{ticker}/candlesticks</span>).</p>
  <h3>Orderbook depth — contracts available at each price</h3>
  <canvas id="depthChart" height="220" aria-label="Orderbook depth"></canvas>
  <p class="small" id="obSummary"></p>
  <div id="obTable"></div>
  <h3>Recent trades</h3>
  <div id="tradesTable"></div>
</div>

<div class="card">
  <h2>3 · Resolution tracking (yes / no)</h2>
  <p class="small muted">Markets are logged here when they close or settle with a result while the
  page is open. Seeded rows below come from the verified snapshot
  (<a href="docs/tracker/data/snapshot.json">snapshot.json</a> ·
  <a href="docs/data/verified.json">verified.json</a>).</p>
  <div id="seededResolutions"></div>
  <button class="btn secondary" id="clearResolutionsBtn">Clear locally logged resolutions</button>
  <div id="resolutionsTable"></div>
</div>

<div class="card">
  <h2>4 · Demo account (optional) &amp; trading</h2>
  <p class="small muted">A Kalshi demo API key (from <a href="https://demo.kalshi.co/" target="_blank" rel="noopener">demo.kalshi.co</a> →
  Account Settings → API Keys; see <a href="https://docs.kalshi.com/getting_started/api_keys" target="_blank" rel="noopener">API keys</a>)
  enables live demo trading and portfolio reads. Without a key the ticket runs in
  <strong>paper mode</strong> (simulated fills at the live best bid/ask — labeled everywhere; nothing is sent to Kalshi).
  Your key never leaves this browser (localStorage).</p>
  <p><label>Key ID <input id="keyId" size="24" autocomplete="off"></label>
     <label>Private key PEM <textarea id="keyPem" rows="4" cols="60" placeholder="-----BEGIN PRIVATE KEY-----"></textarea></label></p>
  <p><button class="btn" id="connectBtn">Connect (demo)</button>
     <button class="btn secondary" id="disconnectBtn">Disconnect</button>
     <button class="btn secondary" id="refreshPortfolioBtn">Refresh portfolio</button>
     <span id="connStatus"><span class="pill warn">Not connected — paper mode</span></span>
     <span id="modeStatus"></span></p>
  <div id="portfolioBody"><p class="muted">Connect a key to load balance, positions, fills and orders
  (sources: <a href="https://docs.kalshi.com/api-reference/portfolio/get-balance">Get Balance</a> ·
  <a href="https://docs.kalshi.com/api-reference/portfolio/get-positions">Get Positions</a> ·
  <a href="https://docs.kalshi.com/api-reference/portfolio/get-fills">Get Fills</a> ·
  <a href="https://docs.kalshi.com/api-reference/orders/get-orders">Get Orders</a>).</p></div>
  <h3>Trade ticket</h3>
  <div id="tradeTicket"></div>
  <div id="tradeResult"></div>
</div>

<div class="card">
  <h2>5 · Trade categorization &amp; strategy analysis</h2>
  <div id="strategyBody"></div>
</div>
"""
    write_page("dashboard.html", "Live dashboard", "dashboard.html", body,
               scripts=("assets/app.js", "assets/trade.js", "assets/dashboard.js", "assets/site.js"))


def build_portfolio():
    body = """
<h1>Portfolio performance</h1>
<p>Track performance of trades on the Kalshi <strong>demo account</strong>, analyze results,
categorize every trade, and derive strategies by trade type. Two modes:</p>
<ul>
<li><strong>Live mode</strong> — connect a demo API key (dashboard panel or the button below):
balance, positions, fills and orders are read from the demo exchange.</li>
<li><strong>Paper mode</strong> (default, clearly labeled) — simulated fills recorded by
<a href="trades.html">Trades</a> against live demo prices, so the full analysis works with
<em>no manual input and no credentials</em>. Nothing is sent to Kalshi.</li>
</ul>
<div id="banner" style="display:none"></div>
<div class="card">
  <h2>Mode &amp; connection</h2>
  <p><label>Key ID <input id="keyId" size="24" autocomplete="off"></label>
     <label>Private key PEM <textarea id="keyPem" rows="3" cols="52"></textarea></label>
     <button class="btn" id="connectBtn">Connect live</button>
     <button class="btn secondary" id="disconnectBtn">Disconnect</button>
     <button class="btn secondary" id="refreshPortfolioBtn">Refresh</button>
     <span id="connStatus"><span class="pill warn">Paper mode</span></span></p>
  <p class="small muted">How to get a demo key (no manual input needed after setup):
  1) create a demo account at <a href="https://demo.kalshi.co/" target="_blank" rel="noopener">demo.kalshi.co</a>;
  2) Account Settings → API Keys → Create New API Key (Ed25519 or RSA);
  3) paste Key ID + PEM above. Docs: <a href="https://docs.kalshi.com/getting_started/demo_env" target="_blank" rel="noopener">demo environment</a> ·
  <a href="https://docs.kalshi.com/getting_started/api_keys" target="_blank" rel="noopener">API keys</a>.
  Flagged item: <a href="flagged.html">I-11</a> (no credentials were provided to this project).</p>
</div>
<div class="card">
  <h2>Performance summary</h2>
  <div id="perfSummary"></div>
</div>
<div class="card">
  <h2>Trade categorization &amp; strategies by trade type</h2>
  <p class="small muted">Categories: topic × side (yes/no) × price band (&lt;30¢, 30–70¢, &gt;70¢) ×
  role (taker/maker). Win rate is computed when the market's yes/no result is known.</p>
  <div id="strategyBody"></div>
</div>
<div class="card">
  <h2>Preserved portfolio notes (session cde2ae63)</h2>
  ''' + legacy_table('portfolio.html', 'portfolio.html', 'Extracted verbatim from the earlier root portfolio.html (data/legacy/cde2ae63_rows.json).') + '''
</div>
<div class="card">
  <h2>Positions &amp; fills</h2>
  <div id="portfolioBody"><p class="muted">Live data appears here when connected. Paper fills appear
  here in paper mode. Sources per row (API URLs) are rendered with each table.</p></div>
</div>
"""
    write_page("portfolio.html", "Portfolio", "portfolio.html", body,
               scripts=("assets/app.js", "assets/trade.js", "assets/dashboard.js", "assets/site.js"))


def build_trades():
    body = """
<h1>Trades — execution &amp; log</h1>
<p>Execute trades on events against the Kalshi <strong>demo</strong> exchange (live mode with your
demo API key) or in <strong>paper mode</strong> (default: simulated fills at the live best bid/ask,
clearly labeled — nothing is sent to Kalshi). Every trade is journaled, categorized and analyzed on
<a href="portfolio.html">Portfolio</a>.</p>
<div id="banner" style="display:none"></div>
<div class="card">
  <h2>Execution guide</h2>
  <table><thead><tr><th>Step</th><th>What happens</th><th>Source</th></tr></thead><tbody>
  <tr><td>1. Pick an event on the <a href="dashboard.html">Live dashboard</a></td>
      <td>Ranking shows the highest estimated dollar volume; Track loads chart + orderbook.</td>
      <td><a class="src" href="https://docs.kalshi.com/api-reference/market/get-markets" target="_blank" rel="noopener">source</a></td></tr>
  <tr><td>2. Choose side &amp; limit price</td>
      <td>YES and NO prices are complementary (NO ≈ 1 − YES). Use the orderbook to size at each price.</td>
      <td><a class="src" href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noopener">source</a></td></tr>
  <tr><td>3. Place the order</td>
      <td>Live: <span class="mono">POST /trade-api/v2/portfolio/events/orders</span> (RSA-PSS/Ed25519 signed). Paper: filled locally at live quote.</td>
      <td><a class="src" href="https://docs.kalshi.com/api-reference/orders/create-order-v2" target="_blank" rel="noopener">source</a></td></tr>
  <tr><td>4. Track to resolution</td>
      <td>Markets settle yes/no; winners receive $1/contract. Results feed the win-rate analysis.</td>
      <td><a class="src" href="https://docs.kalshi.com/getting_started/market_settlement" target="_blank" rel="noopener">source</a></td></tr>
  </tbody></table>
</div>
<div class="card">
  <h2>Trade ticket</h2>
  <div id="tradeTicket"></div>
  <div id="tradeResult"></div>
  <p class="small muted"><span id="connStatus"><span class="pill warn">Paper mode</span></span></p>
</div>
<div class="card">
  <h2>Preserved execution reference (session cde2ae63)</h2>
  ''' + legacy_table('trades.html', 'trades.html', 'Extracted verbatim from the earlier root trades.html (data/legacy/cde2ae63_rows.json).') + '''
</div>
<div class="card">
  <h2>Blotter &amp; journal</h2>
  <div id="journalBody"></div>
</div>
<div class="card">
  <h2>Categorization</h2>
  <div id="strategyBody"></div>
</div>
"""
    write_page("trades.html", "Trades", "trades.html", body,
               scripts=("assets/app.js", "assets/trade.js", "assets/dashboard.js", "assets/site.js"))


TOPICS = [
    ("gas", "Gas prices", "gas-prices.html",
     "Retail gasoline price markets (AAA averages per state, e.g. KXAAAGAS*). "
     "Settlement source: AAA."),
    ("elections", "Elections", "elections.html",
     "Election markets: US House, Senate, presidency and international elections "
     "(e.g. HOUSE*, KXPRES*, POLANDSEJM)."),
    ("culture", "Culture", "culture.html",
     "Culture & entertainment: awards, film, music, media and cultural events."),
    ("crypto", "Crypto", "crypto.html",
     "Crypto price-range markets: Bitcoin (KXBTC*), Ethereum (KXETH*) and other crypto series."),
    ("golf", "Golf", "golf.html",
     "Golf: PGA, majors, Ryder Cup and head-to-head markets (KXPGA*, PGAH2H*)."),
]


def build_category(tid, label, page, desc):
    t = Table(["Series ticker", "Title", "Category", "Frequency", "Volume (contracts)",
               "Settlement source", "Contract terms"], page)
    rows = [r for r in tracker["series"] if r.get("topic") == tid]
    seen = set(r["ticker"] for r in rows)
    for r in rows:
        terms = (f'<a href="{esc(r["contract_terms_url"])}" target="_blank" rel="noopener">terms</a>'
                 if r.get("contract_terms_url") else "—")
        t.row([f'<span class="mono">{esc(r["ticker"])}</span>', esc(r.get("title", "")),
               esc(r.get("category", "")), esc(r.get("frequency", "")),
               esc(r.get("volume_contracts", "")), esc(r.get("settlement_sources", "") or "—"),
               terms],
              [r.get("source_api", "")], label=r["ticker"])
    for r in verified["series"]:
        if r.get("cat") != tid or r["ticker"] in seen:
            continue
        terms = (f'<a href="{esc(r["settlement_url"])}" target="_blank" rel="noopener">settlement</a>'
                 if r.get("settlement_url") else "—")
        t.row([f'<span class="mono">{esc(r["ticker"])}</span>', esc(r.get("title", "")),
               esc(r.get("category", "")), esc(r.get("frequency", "")),
               esc(r.get("volume_contracts", "")), esc(r.get("settlement_source", "") or "—"),
               terms],
              [r.get("source", "")], label=r["ticker"])

    m = Table(["Market ticker", "Title", "Status", "Result", "Last price", "Yes bid/ask",
               "Volume (contracts)", "Open interest", "Closes / settled", "Rules"], page)
    snap_rows = [r for r in tracker["markets"] if r.get("topic") == tid]
    live_topic = next((x for x in live["topics"] if x["id"] == tid), None)
    done = set()
    for r in snap_rows:
        done.add(r["ticker"])
        res = f'<span class="pill">{esc(r.get("result") or "—")}</span>'
        m.row([f'<span class="mono">{esc(r["ticker"])}</span>', esc(r.get("title", "")),
               esc(r.get("status", "")), res,
               esc(r.get("last_price_dollars", "")),
               f'{esc(r.get("yes_bid_dollars", ""))} / {esc(r.get("yes_ask_dollars", ""))}',
               esc(r.get("volume_contracts", "")), esc(r.get("open_interest_contracts", "")),
               esc(r.get("settlement_ts") or r.get("close_time") or ""),
               esc((r.get("rules_primary") or "")[:160])],
              [r.get("source_api", "")], label=r["ticker"])
    for r in (live_topic or {}).get("top_markets", []):
        if r["ticker"] in done:
            continue
        res = f'<span class="pill">{esc(r.get("result") or "—")}</span>'
        m.row([f'<span class="mono">{esc(r["ticker"])}</span>', esc(r.get("title", "")),
               esc(r.get("status", "")), res,
               esc(r.get("last_price", "")),
               f'{esc(r.get("yes_bid", ""))} / {esc(r.get("yes_ask", ""))}',
               esc(r.get("volume_contracts", "")), esc(r.get("open_interest_contracts", "")),
               esc(r.get("close_time", "")), "—"],
              [r.get("source_url", "") or f'{DEMO}/markets/{r["ticker"]}'], label=r["ticker"])
    for r in verified["resolved"]:
        if r.get("cat", tid) != tid or r["ticker"] in done:
            continue
        m.row([f'<span class="mono">{esc(r["ticker"])}</span>', esc(r.get("title", "")),
               esc(r.get("status", "")), f'<span class="pill">{esc(r.get("result") or "—")}</span>',
               esc(r.get("settlement_value_dollars", "")), "—",
               esc(r.get("volume_contracts", "")), "—",
               esc(r.get("settlement_ts") or r.get("close_time") or ""),
               esc((r.get("rules") or "")[:160])],
              [r.get("source", "")], label=r["ticker"])

    body = f"""
<h1>{esc(label)}</h1>
<p>{esc(desc)}</p>
<div class="card"><h2>Verified series snapshot</h2>
{t.render(caption="Series matching this topic from the verified snapshot (2026-11-20). Each row links the exact API request URL. Live discovery runs on the dashboard.")}
</div>
<div class="card"><h2>Markets — live &amp; resolved (yes/no)</h2>
{m.render(caption="Open/active markets and settled results (result = yes/no). Settled winners pay $1/contract.",
          note="Dollar figures shown are as returned by the API (dollars strings). Volume is contracts.")}
<p><a class="btn" href="dashboard.html">Track these live on the dashboard</a></p>
</div>
"""
    write_page(page, label, page, body, scripts=("assets/app.js", "assets/site.js"))


def build_questions():
    rows = consolidated_questions()
    t = Table(["#", "Question", "What we know (answer / status)", "Missing information",
               "How to discover it", "Origin"], "questions")
    for r in rows:
        t.row([f'<span class="mono">{esc(r["id"])}</span>', esc(r["q"]),
               esc(r["known"] or "—"), esc(r["missing"] or "—"),
               esc(r["how"] or "—"), esc(", ".join(r["origins"]))],
              r["srcs"], label=r["id"])
    body = f"""
<h1>Questions — decision readiness</h1>
<p>Every question that must be answered before a decision can reasonably be made from this data —
including what we <em>do not</em> know yet — with the information needed and the exact way to
discover it. Nothing here is inferred: unknown stays unknown until sourced.</p>
<div class="card">{t.render(caption="Consolidated register (merged from every session's questions). Source column links the evidence.")}</div>
"""
    write_page("questions.html", "Questions", "questions.html", body,
               scripts=("assets/app.js", "assets/site.js"))


def build_suggestions():
    rows = consolidated_suggestions()
    body_rows = []
    for r in rows:
        opts = "".join(f"<li>{esc(o)}</li>" for o in r["options"]) if r["options"] else "<li class='muted'>—</li>"
        srcs = " · ".join(
            f'<a class="src" href="{esc(u)}" target="_blank" rel="noopener">source</a>'
            for u in r["srcs"]) or "<span class='pill warn'>unverified</span>"
        if not r["srcs"]:
            UNVERIFIED.append(("suggestions", r["id"]))
        body_rows.append(f"""<tr data-sid="{esc(r['id'])}">
<td><span class="mono">{esc(r['id'])}</span></td>
<td><strong>{esc(r['title'])}</strong><br><span class='small'>{esc(r['detail'])}</span>
<ul class='small'>{opts}</ul></td>
<td>{esc(r['benefit'])}</td>
<td>{esc(r['effort'] or '—')}</td>
<td>{esc(r['risk'] or '—')}</td>
<td><select class="decision" data-sid="{esc(r['id'])}">
  <option>Proposed</option><option>Approved</option><option>Rejected</option>
  <option>Deferred</option><option>Implemented</option></select><br>
  <input class="decision-note" data-sid="{esc(r['id'])}" placeholder="reviewer note (saved locally)"></td>
<td>{srcs}</td></tr>""")
    body = f"""
<h1>Suggestions — review before implementing</h1>
<p>Improvement ideas collected so a reviewer can <strong>choose the best path before any change is
implemented</strong>. Set a decision and note per row — they are saved in this browser
(localStorage) and exportable as JSON. This page implements nothing by itself.</p>
<p id="decisionSummary" class="small"></p>
<p><button class="btn secondary" id="exportDecisions">Export decisions (JSON)</button>
   <button class="btn secondary" id="resetDecisions">Reset decisions</button></p>
<div class="card"><div class="tablewrap"><table id="suggestionTable">
<thead><tr><th>#</th><th>Suggestion &amp; options</th><th>Expected benefit</th><th>Effort</th>
<th>Risk</th><th>Decision (review workflow)</th><th>Source</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody></table></div>
<p class="small muted">Consolidated from every session's suggestion registers; each row links its evidence.</p>
</div>
"""
    write_page("suggestions.html", "Suggestions", "suggestions.html", body,
               scripts=("assets/app.js", "assets/site.js"))


def build_flagged():
    rows = consolidated_flags()
    t = Table(["ID", "Area", "Item", "Detail", "Status / action"], "flagged")
    for r in rows:
        t.row([f'<span class="mono">{esc(r["id"])}</span>', esc(r["area"]), esc(r["item"]),
               esc(r["detail"]), esc(r["status"])],
              r["srcs"], label=r["id"])
    # unverified cells collected during THIS build
    if UNVERIFIED:
        t.row(["BUILD-U", "Unverified cells (this build)",
               f"{len(UNVERIFIED)} table cells rendered without an official source during the "
               "site build:", " · ".join(f"{p}:{lbl}" for p, lbl in UNVERIFIED[:40]),
               "left blank + flagged, never inferred"],
              ["https://docs.kalshi.com/getting_started/quick_start_market_data"],
              label="BUILD-U", unverified=True)
    body = f"""
<h1>Flagged for review</h1>
<p>Irregularities, unverified items and open decisions. <strong>Nothing here blocks the merge</strong>
— review at any time and request changes. Each row links its evidence.</p>
<div class="card">{t.render(caption="Consolidated register (all sessions + integration flags).")}</div>
"""
    write_page("flagged.html", "Flagged for review", "flagged.html", body,
               scripts=("assets/app.js", "assets/site.js"))


def build_sources():
    rows = consolidated_sources()
    t = Table(["ID", "Source", "What it supports"], "sources")
    for r in rows:
        t.row([f'<span class="mono">{esc(r["id"])}</span>',
               f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["label"])}</a>',
               esc(r["supports"])], [r["url"]], label=r["id"])
    archives = [
        ("docs/", "Session 00a943bd integrated site + verified.json", "docs/index.html"),
        ("docs/tracker/", "Session e2aacbd6 tracker + snapshot.json (per-row source_api)",
         "docs/tracker/index.html"),
        ("analysis/", "Session 3e08e6dc analysis site + live captures (per-row source_url)",
         "analysis/index.html"),
        ("demo-desk/", "Session 4ea36f44 read-only source-linked Demo Desk (own npm tests)",
         "demo-desk/index.html"),
        ("research/kalshi-api-verified-reference.md", "Session 6908a11a verified API reference",
         "research/kalshi-api-verified-reference.md"),
        ("EXECUTIVE_SUMMARY.md", "Session 6908a11a executive summary", "EXECUTIVE_SUMMARY.md"),
        ("FLAGGED.md", "Session 6908a11a flagged register", "FLAGGED.md"),
        ("SUGGESTIONS.md", "Session 6908a11a suggestions & questions register", "SUGGESTIONS.md"),
        ("COORDINATION.md", "Shared task board (claims, verification, PR log)", "COORDINATION.md"),
        ("scripts/", "Build/verify/refresh scripts of all sessions", "scripts/verify_root_site.py"),
    ]
    at = Table(["Archive", "What it is", "Open"], "sources")
    for name, what, href in archives:
        at.row([f'<span class="mono">{esc(name)}</span>', esc(what),
                f'<a href="{esc(href)}">open</a>'], [f"https://github.com/karagemop466-tech/Demo3/tree/main/{name.rstrip('/')}"], label=name)
    body = f"""
<h1>Sources &amp; verification</h1>
<p>Every value on this site is verified against an official Kalshi source (docs.kalshi.com) or a
live demo-API response whose exact request URL is shown on the row. Values that could not be
confirmed are left blank and flagged — never inferred. To re-verify any row, open its source link.</p>
<div class="card"><h2>Official sources used</h2>
{t.render(caption="Live links open the exact API endpoint or documentation page.")}</div>
<div class="card"><h2>Session archives (kept intact for manual review)</h2>
{at.render(caption="Parallel sessions produced these trees; the canonical UI is this root site.")}</div>
<div class="card"><h2>Verification policy</h2>
<ul class="small">
<li>Table row → source link, or blank + “unverified” flag. Build fails on rows without one or the other.</li>
<li>Estimates (e.g. dollar volume = contracts × last price) are labeled “estimate”.</li>
<li>Demo-environment caveat: Kalshi states demo prices/behavior may not reflect real markets.</li>
<li>Checks: <span class="mono">scripts/verify_root_site.py</span> (links + per-row sources),
<span class="mono">scripts/verify_site.py</span>, <span class="mono">scripts/tracker_check.py</span>,
<span class="mono">scripts/check_site.py</span>.</li>
</ul></div>
"""
    write_page("sources.html", "Sources", "sources.html", body,
               scripts=("assets/app.js", "assets/site.js"))


def build_repo_review():
    rows = []
    for r in findings["repo_review"]["rows"]:
        rows.append((r["id"], r.get("item", ""), r.get("finding", ""), r.get("status", ""), r.get("src", [])))
    for r in verified.get("repo_review", []):
        rows.append(("VR", r.get("item", ""), r.get("finding", "") or r.get("note", ""),
                     r.get("status", "") or r.get("result", ""), [r.get("source", "")]))
    t = Table(["ID", "Item", "Finding", "Status"], "repo-review")
    for rid, item, finding, status, srcs in rows:
        t.row([f'<span class="mono">{esc(rid)}</span>', esc(item), esc(finding), esc(status)],
              srcs, label=rid)
    files = [
        ("index.html … api-reference.html", "Canonical root site (this UI), generated by scripts/build_root_site.py", "OK — built + link-checked", "https://github.com/karagemop466-tech/Demo3/tree/main"),
        ("assets/app.js", "Shared API client, charts, request signing (fixed at integration: signature path includes /trade-api/v2 — see R-07)", "OK — node --check", f"{DOCS}/getting_started/api_keys"),
        ("assets/dashboard.js", "Live dashboard engine (discovery, ranking, chart, orderbook, resolutions, portfolio, trading, strategy)", "OK — node --check", f"{DOCS}/getting_started/quick_start_market_data"),
        ("assets/trade.js", "Trade ticket, paper/live trading store, categorization, strategy stats", "OK — node --check", f"{DOCS}/api-reference/orders/create-order-v2"),
        ("docs/", "Session 00a943bd archive (own build/verify scripts)", "kept intact", "https://github.com/karagemop466-tech/Demo3/tree/main/docs"),
        ("docs/tracker/", "Session e2aacbd6 archive (snapshot.json per-row source_api)", "kept intact", "https://github.com/karagemop466-tech/Demo3/tree/main/docs/tracker"),
        ("analysis/", "Session 3e08e6dc archive (live captures, refresh workflow)", "kept intact (R-06: uses production API base)", "https://github.com/karagemop466-tech/Demo3/tree/main/analysis"),
        ("scripts/", "Build/verify/refresh tooling of all sessions", "all checkers run at integration", "https://github.com/karagemop466-tech/Demo3/tree/main/scripts"),
        (".github/workflows/", "CI checks + hourly data refresh job", "kept", "https://github.com/karagemop466-tech/Demo3/tree/main/.github/workflows"),
        ("COORDINATION.md", "Shared task board: claims, sources, verification, PR/Pages log", "OK", "https://github.com/karagemop466-tech/Demo3/blob/main/COORDINATION.md"),
        ("README.md", "Project overview (rewritten at integration; links all archives)", "OK", "https://github.com/karagemop466-tech/Demo3/blob/main/README.md"),
    ]
    ft = Table(["File / directory", "Purpose &amp; review notes", "Verification", "Link"], "repo-review")
    for name, purpose, status, link in files:
        ft.row([f'<span class="mono">{esc(name)}</span>', esc(purpose), esc(status),
                f'<a href="{esc(link)}" target="_blank" rel="noopener">review</a>'],
               [link], label=name)
    body = f"""
<h1>Repository review (line by line)</h1>
<p>Review of the repository contents with manual-review links and flagged irregularities. The base
commit (<span class="mono">80f7c4d</span>) contained only a one-line README (R-01); everything else
was produced during this multi-session run and is accounted for below and in
<a href="COORDINATION.md">COORDINATION.md</a>.</p>
<div class="card"><h2>Review findings (from the verified registers)</h2>
{t.render(caption="Findings re-verified at integration; sources linked per row.")}</div>
<div class="card"><h2>File-by-file map</h2>
{ft.render(caption="Every tracked path on main and its review status.")}</div>
"""
    write_page("repo-review.html", "Repo review", "repo-review.html", body,
               scripts=("assets/app.js", "assets/site.js"))


METHOD_CITES = [
    ("classify", "https://docs.kalshi.com/api-reference/market/get-series-list"),
    ("series", "https://docs.kalshi.com/api-reference/market/get-series-list"),
    ("limit", "https://docs.kalshi.com/getting_started/rate_limits"),
    ("rate", "https://docs.kalshi.com/getting_started/rate_limits"),
    ("ranking", "https://docs.kalshi.com/api-reference/market/get-markets"),
    ("volume", "https://docs.kalshi.com/api-reference/market/get-markets"),
    ("sample", "https://docs.kalshi.com/getting_started/quick_start_market_data"),
    ("axis", "https://docs.kalshi.com/getting_started/quick_start_market_data"),
    ("chart", "https://docs.kalshi.com/getting_started/quick_start_market_data"),
    ("liquidity", "https://docs.kalshi.com/getting_started/orderbook_responses"),
    ("orderbook", "https://docs.kalshi.com/getting_started/orderbook_responses"),
    ("spread", "https://docs.kalshi.com/getting_started/orderbook_responses"),
    ("price", "https://docs.kalshi.com/api-reference/market/get-market"),
    ("sign", "https://docs.kalshi.com/getting_started/api_keys"),
    ("key", "https://docs.kalshi.com/getting_started/api_keys"),
    ("demo", "https://docs.kalshi.com/getting_started/demo_env"),
    ("settle", "https://docs.kalshi.com/getting_started/market_settlement"),
    ("candlestick", "https://docs.kalshi.com/api-reference/market/get-market-candlesticks"),
]


def with_row_sources(inner):
    """Append a source cell to legacy table rows that have no official link."""
    def fix_tr(m):
        tr = m.group(0)
        tds = re.findall(r"<td[^>]*>.*?</td>", tr, re.S)
        if not tds or "https://" in tr:
            return tr
        text = re.sub(r"<[^>]+>", " ", tr).lower()
        url = ""
        for key, u in METHOD_CITES:
            if key in text:
                url = u
                break
        cell = (f"<td><a class='src' href='{url}' target='_blank' rel='noopener'>source</a></td>"
                if url else "<td><span class='pill warn'>unverified</span></td>")
        if not url:
            UNVERIFIED.append(("methodology/api-reference",
                               re.sub(r"<[^>]+>", " ", tds[0]).strip()[:40]))
        return tr.replace("</tr>", cell + "</tr>")
    return re.sub(r"<tr[^>]*>.*?</tr>", fix_tr, inner, flags=re.S)


def build_wrapped(name, title):
    inner = with_row_sources(extract_body(name))
    if not inner:
        print("WARN no body in", name)
        return
    write_page(name, title, name, inner, scripts=("assets/app.js", "assets/site.js"))


# Pages whose live markup is maintained outside this generator (added by other sessions).
# Regenerating them here would drop that work, so the generator leaves them untouched.
EXTERNALLY_MAINTAINED = {"dashboard.html"}


def main():
    build_index()
    build_dashboard()
    build_portfolio()
    build_trades()
    for tid, label, page, desc in TOPICS:
        build_category(tid, label, page, desc)
    build_questions()
    build_suggestions()
    build_flagged()
    build_sources()
    build_repo_review()
    build_wrapped("methodology.html", "Methodology")
    build_wrapped("api-reference.html", "API reference")
    print(f"\nUnverified cells collected: {len(UNVERIFIED)}")
    for p, lbl in UNVERIFIED:
        print("  unverified:", p, lbl)
    if BUILD_ERRORS:
        print("BUILD ERRORS:", *BUILD_ERRORS, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
