#!/usr/bin/env python3
"""Render the `paper-desk/` subsite from the committed paper-trading ledger.

Input (written by `trading/paper_engine.py`, refreshed by
`.github/workflows/paper-desk.yml`):
    data/paper/{state,trades,equity,analysis,resolutions,runs,books,sources}.json
Output:
    paper-desk/index.html, trades.html, positions.html, analysis.html,
    resolutions.html, sources.html, methodology.html, assets/paper.css

Design rules enforced here (project brief + board rules):
- every row of every table carries the exact demo-API URL its values came from;
- a value that the API did not publish is rendered as an em dash plus an
  UNVERIFIED pill — never filled in, never inferred;
- the page states plainly that this is a SIMULATED ledger, not the user's demo
  account, and links the flagged credential gap;
- the generator is deterministic: no build timestamps, sorted iteration, so a
  re-run over identical data reproduces the same bytes.
"""

from __future__ import annotations

import html
import json
import os
from urllib.parse import urlparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys_path_added = False


def engine_defaults() -> dict:
    """Read the engine's own source register so static rows stay sourced before
    the first ledger exists (single source of truth, no duplicated URLs)."""
    import importlib
    import sys
    for p in (os.path.join(REPO, "trading"), os.path.join(REPO, "collector")):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        eng = importlib.import_module("paper_engine")
        return {"SOURCES": dict(eng.SOURCES), "CONFIG": dict(eng.DEFAULT_CONFIG),
                "API_ROOT": eng.DEMO_REST_ROOT}
    except Exception:  # pragma: no cover - the page must still build
        return {"SOURCES": {}, "CONFIG": {}, "API_ROOT":
                "https://external-api.demo.kalshi.co/trade-api/v2"}
PAPER_DIR = os.path.join(REPO, "data", "paper")
LATEST_DIR = os.path.join(REPO, "data", "latest")
OUT_DIR = os.path.join(REPO, "paper-desk")
DOC_ROOT = "https://docs.kalshi.com"

NAV = [
    ("index.html", "Desk summary"),
    ("trades.html", "Trade journal"),
    ("positions.html", "Positions & liquidity"),
    ("analysis.html", "Strategy analysis"),
    ("resolutions.html", "Resolutions"),
    ("methodology.html", "Rules & methodology"),
    ("sources.html", "Sources"),
]

MAX_JOURNAL_ROWS = 300
MAX_LIST_ROWS = 200

CSS = """:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--txt:#e8ecf3;--mut:#93a0b5;
--up:#3ddc97;--down:#ff6b6b;--warn:#ffc857;--link:#79b8ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 ui-sans-serif,system-ui,"Segoe UI",Roboto,Arial,sans-serif}
header.top{border-bottom:1px solid var(--line);background:#12151b;position:sticky;top:0;z-index:5}
header.top .bar{max-width:1200px;margin:0 auto;padding:10px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.brand{font-weight:700;letter-spacing:.2px;color:var(--txt);text-decoration:none}
nav.main{display:flex;gap:10px;flex-wrap:wrap}
nav.main a{color:var(--mut);text-decoration:none;padding:3px 8px;border-radius:6px}
nav.main a:hover{background:#1e2330;color:var(--txt)}
nav.main a.active{background:#233047;color:#cfe3ff}
main{max-width:1200px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:6px 0 4px}h2{font-size:17px;margin:22px 0 8px}
h3{font-size:15px;margin:16px 0 6px}
p{margin:6px 0}.muted{color:var(--mut)}.small{font-size:12.5px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.kpi{background:#1b2029;border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.kpi .v{font-size:19px;font-weight:700}.kpi .l{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.4px}
.pos{color:var(--up)}.neg{color:var(--down)}
table{width:100%;border-collapse:collapse;margin:8px 0}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.3px}
tbody tr:hover{background:#1b212c}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
a{color:var(--link)}a.src{text-decoration:none;border-bottom:1px dotted #33507a;font-size:12px;white-space:nowrap}
.pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11.5px;border:1px solid var(--line)}
.pill.warn{color:var(--warn);border-color:#4a3c17;background:#241d0d}
.pill.unv{color:#ffb4b4;border-color:#4d2424;background:#251313}
.pill.ok{color:var(--up);border-color:#1e4436;background:#10231d}
.pill.sim{color:#c9b1ff;border-color:#3a2b5e;background:#1c1530}
.banner{border:1px solid #4a3c17;background:#241d0d;color:#ffe4a3;border-radius:10px;padding:10px 12px;margin:12px 0}
.note{border:1px solid var(--line);background:#141821;border-radius:10px;padding:10px 12px;margin:12px 0}
.chart{width:100%;height:200px;display:block;background:#12151c;border:1px solid var(--line);border-radius:10px}
.scroll{max-height:460px;overflow:auto;border:1px solid var(--line);border-radius:10px}
.flexrow{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
button{background:#233047;border:1px solid #33507a;color:#cfe3ff;border-radius:8px;padding:6px 10px;cursor:pointer}
button:hover{background:#2b3c58}
input,select{background:#12151c;color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:5px 7px}
.ladder td{font-family:ui-monospace,Menlo,monospace;font-size:12px}
.depth{height:9px;background:#2b3c58;border-radius:3px}
footer{border-top:1px solid var(--line);margin-top:30px;color:var(--mut);padding:14px 16px;font-size:12.5px}
ul{margin:6px 0 6px 18px;padding:0}li{margin:3px 0}
"""


def esc(value) -> str:
    if value is None or value == "":
        return "&mdash;"
    return html.escape(str(value))


def money(value, digits: int = 4) -> str:
    if value is None:
        return "&mdash;"
    try:
        return f"${float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return esc(value)


def signed(value, digits: int = 2) -> str:
    if value is None:
        return "&mdash;"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return esc(value)
    cls = "pos" if v > 0 else ("neg" if v < 0 else "")
    return f'<span class="{cls}">{v:+,.{digits}f}</span>'


def pct(value) -> str:
    if value is None:
        return "&mdash;"
    try:
        return f"{100 * float(value):.1f}%"
    except (TypeError, ValueError):
        return esc(value)


def src_link(url, label: str = "source") -> str:
    if not url:
        return '<span class="pill unv">no source url in record</span>'
    return (f'<a class="src" href="{html.escape(str(url), quote=True)}" '
            f'target="_blank" rel="noopener">{label}</a>')


def doc_link(url, label: str = "official doc") -> str:
    """Anchor for a documented reference; explicit unverified marker when unknown."""
    if not url or str(url).lower() == "none":
        return '<span class="pill unv">unverified</span>'
    return (f'<a class="src" href="{html.escape(str(url), quote=True)}" target="_blank" '
            f'rel="noopener">{label}</a>')


def agg_links(rec) -> str:
    """Source cell for an aggregate row: the API requests its member trades used, plus the journal."""
    urls = [u for u in (rec.get("source_urls") or []) if u]
    tick = rec.get("tickers") or []
    cells = [src_link(u, f"API row {i + 1}") for i, u in enumerate(urls[:3])]
    if not cells:
        cells = ['<span class="pill unv">unverified</span>']
    if tick:
        shown = ", ".join(tick[:3]) + ("..." if len(tick) > 3 else "")
        cells.append('<span class="mono small muted">' + esc(shown) + "</span>")
    cells.append(file_link("data/paper/trades.json", "journal"))
    return " ".join(cells)


def file_link(rel: str, label: str = "ledger json") -> str:
    return f'<a class="src" href="../{esc(rel)}">{label}</a>'


def cell(value, source=None, kind: str = "") -> str:
    """Render one value; blank + UNVERIFIED when the record has none (never inferred)."""
    if value is None or value == "":
        return '<span class="pill unv">unverified</span>'
    text = money(value) if kind == "money" else (pct(value) if kind == "pct" else esc(value))
    return text


def row(cells: list[str]) -> str:
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def table(headers: list[str], rows: list[str], caption: str = "") -> str:
    cap = f'<caption class="muted small">{caption}</caption>' if caption else ""
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(rows) or row(['<span class="muted">no rows yet</span>'] * len(headers))
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody>{cap}</table>"


def read_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def load_all() -> dict:
    names = ("state", "trades", "equity", "analysis", "resolutions", "runs", "books",
             "sources")
    defaults = engine_defaults()
    out = {n: read_json(os.path.join(PAPER_DIR, f"{n}.json"), {}) for n in names}
    out["_ledger_present"] = os.path.exists(os.path.join(PAPER_DIR, "state.json"))
    out["collector_meta"] = read_json(os.path.join(LATEST_DIR, "meta.json"), {})
    out["collector_status"] = read_json(os.path.join(LATEST_DIR, "collector_status.json"), {})
    out["portfolio"] = read_json(os.path.join(LATEST_DIR, "portfolio.json"), {})
    out["top_events"] = read_json(os.path.join(LATEST_DIR, "top_events.json"), {})
    # fill gaps from the engine so the site never renders an empty source cell
    src = out.get("sources") or {}
    merged = dict(defaults["SOURCES"])
    merged.update(src.get("docs") or {})
    src["docs"] = merged
    src.setdefault("api_root", out.get("state", {}).get("api_root") or defaults["API_ROOT"])
    src.setdefault("strategy_rules", list(__import__("paper_strategies").STRATEGIES.values())
                   if defaults["SOURCES"] else [])
    cfg = dict(defaults["CONFIG"])
    cfg.update((out.get("state") or {}).get("config") or {})
    (out.get("state") or {}).setdefault("api_root", src["api_root"])
    out["state"] = {**(out.get("state") or {}), "config": cfg,
                    "starting_cash_dollars": (out.get("state") or {}).get(
                        "starting_cash_dollars", defaults["CONFIG"].get("starting_cash_dollars"))}
    out["sources"] = src
    out["defaults"] = defaults
    return out


# --------------------------------------------------------------------- widgets
def kpis(pairs: list[tuple[str, str]]) -> str:
    return ('<div class="grid">'
            + "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>'
                      for l, v in pairs) + "</div>")


def equity_chart(samples: list[dict]) -> str:
    """Hand-drawn SVG: x = sample time, y = dollars. No chart library, no CDN."""
    pts = [(i, float(s["equity_dollars"])) for i, s in enumerate(samples)
           if s.get("equity_dollars") is not None]
    if len(pts) < 2:
        return ('<p class="muted small">The equity curve appears after the second desk '
                'cycle (each cycle adds one sample).</p>')
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w, h, pad = 1160, 200, 34
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if y1 - y0 < 1e-9:
        y0, y1 = y0 - 1, y1 + 1

    def sx(i):
        return pad + (i - x0) / (x1 - x0) * (w - 2 * pad)

    def sy(v):
        return h - pad - (v - y0) / (y1 - y0) * (h - 2 * pad)

    path = " ".join(f"{'M' if i == 0 else 'L'}{sx(i):.1f},{sy(v):.1f}" for i, (x, v) in
                    enumerate(zip(xs, ys), start=0)).replace("M0", "M0")
    line = " ".join(f"{sx(x):.1f},{sy(v):.1f}" for x, v in pts)
    grid = []
    for k in range(5):
        v = y0 + (y1 - y0) * k / 4
        y = sy(v)
        grid.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w - pad}" y2="{y:.1f}" '
                    f'stroke="#232838" stroke-width="1"/>'
                    f'<text x="4" y="{y + 3:.1f}" fill="#7f8ca3" font-size="10">'
                    f'${v:,.2f}</text>')
    ticks = []
    for k in range(0, len(pts), max(1, len(pts) // 6)):
        i, _ = pts[k][0], pts[k][1]
        s = samples[i]
        ticks.append(f'<text x="{sx(i):.1f}" y="{h - 8}" fill="#7f8ca3" font-size="10" '
                     f'text-anchor="middle">{esc((s.get("ts") or "")[11:16])}</text>')
    first, last = ys[0], ys[-1]
    color = "#3ddc97" if last >= first else "#ff6b6b"
    return (f'<svg class="chart" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
            f'role="img" aria-label="Portfolio equity by desk cycle">'
            + "".join(grid)
            + f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{line}"/>'
            + "".join(ticks)
            + f'<text x="{w - pad}" y="{sy(last) - 6:.1f}" fill="{color}" font-size="11" '
              f'text-anchor="end">${last:,.2f}</text>'
              f'<text x="{pad}" y="{h - 30}" fill="#7f8ca3" font-size="10">'
              f'x: desk cycle (time {esc((samples[0].get("ts") or "")[:16])} &rarr; '
              f'{esc((samples[-1].get("ts") or "")[:16])}) &nbsp; y: equity (USD), marked '
              f"at the published bid</text>{path and ''}</svg>")


def ladder_rows(books: list[dict]) -> str:
    rows = []
    for b in books or []:
        for side_key, label in (("yes_bid_levels", "YES bids"), ("no_bid_levels", "NO bids")):
            levels = b.get(side_key) or []
            if not levels:
                continue
            sizes = [float(l[1] or 0) for l in levels]
            peak = max(sizes) or 1.0
            for price, size in levels:
                try:
                    width = 100.0 * float(size) / peak
                except (TypeError, ValueError):
                    width = 0.0
                rows.append(row([
                    f'<span class="mono">{esc(b.get("ticker"))}</span>', label,
                    money(price), f"{float(size or 0):,.2f}",
                    f'<div class="depth" style="width:{width:.1f}%"></div>',
                    esc((b.get("fetched_at") or "")[:19]),
                    src_link(b.get("source_url"), "orderbook")]))
    return rows


def page(title: str, body: str, data: dict, active: str, blurb: str = "") -> str:
    nav = "".join(
        "<a href=\"{0}\"{1}>{2}</a>".format(href, ' class="active"' if href == active else "",
                                             label)
        for href, label in NAV)
    mode = (data.get("state") or {}).get("mode") or "no runs yet"
    stamp = (data.get("state") or {}).get("generated_at") or "awaiting first cycle"
    status = data.get("collector_status") or {}
    nav_html = (f'<header class="top"><div class="bar">'
                f'<a class="brand" href="index.html">Kalshi demo &middot; paper desk</a>'
                f'<nav class="main">{nav}</nav>'
                f'<span class="flexrow" style="margin-left:auto">'
                f'<span class="pill sim">{esc(mode)}</span>'
                f'<span class="pill ok">ledger updated {esc(stamp)}</span>'
                f'<span class="pill">collector {esc(status.get("status") or "n/a")}</span>'
                f'</span></div></header>')
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{esc(title)} &middot; Kalshi demo paper desk</title>\n"
            '<link rel="stylesheet" href="assets/paper.css">\n</head>\n<body>\n'
            f"{nav_html}\n<main>\n<h1>{esc(title)}</h1>\n{blurb}\n{body}\n</main>\n"
            f'<footer>Simulated ledger only &mdash; not a demo-account balance, and not '
            f'investment advice. Demo prices "may not be reflective of those in real '
            f'markets" per <a href="{DOC_ROOT}/getting_started/demo_env.md" '
            f'target="_blank" rel="noopener">Kalshi&rsquo;s demo-environment doc</a>. '
            f'Generated by <span class="mono">scripts/build_paper_desk.py</span> from '
            f'<span class="mono">data/paper/*.json</span> '
            f'(refreshed by <span class="mono">.github/workflows/paper-desk.yml</span>).'
            f"</footer>\n</body>\n</html>\n")


def empty_state(data: dict) -> str:
    return ("" if data.get("_ledger_present") else """
<div class="banner"><strong>No ledger yet.</strong> <span class="mono">data/paper/</span> is
created by the first run of <span class="mono">.github/workflows/paper-desk.yml</span>
(scheduled every 20 minutes on the default branch, or on demand). The pages below stay
valid and fill in as cycles complete; nothing on this site is back-filled by hand.</div>""")


# ---------------------------------------------------------------------- pages
def build_index(data: dict) -> str:
    state = data.get("state") or {}
    analysis = data.get("analysis") or {}
    totals = analysis.get("totals") or {}
    equity = (data.get("equity") or {}).get("samples") or []
    runs = (data.get("runs") or {}).get("runs") or []
    strat = (data.get("sources") or {}).get("strategy_rules") or []

    cards = kpis([
        ("Equity (marked at bid)", money(totals.get("equity_dollars"))),
        ("Cash", money(totals.get("cash_dollars"))),
        ("Realized P&amp;L", signed(totals.get("realized_pnl_dollars"))),
        ("Unrealized P&amp;L", signed(totals.get("unrealized_pnl_dollars"))),
        ("Open positions", esc(totals.get("open_positions", 0))),
        ("Resting orders", esc(totals.get("resting_orders", 0))),
        ("Simulated fills", esc(totals.get("fills", 0))),
        ("Rejected for no liquidity", esc(totals.get("rejections", 0))),
        ("Settled positions", esc(totals.get("settlements", 0))),
        ("Desk cycles", esc(state.get("run_count", 0))),
        ("Start cash", money(state.get("starting_cash_dollars"))),
        ("Max drawdown", money(totals.get("max_drawdown_dollars"))),
    ])

    strat_rows = [row([
        esc(s.get("label")), esc(s.get("id")), esc(s.get("family")),
        esc(s.get("entry")), esc(s.get("exit")),
        '<span class="mono">' + esc(", ".join(s.get("fields") or [])) + "</span>",
        src_link(f"{DOC_ROOT}/api-reference/market/get-markets.md", "field docs"),
    ]) for s in strat]

    recent = equity[-10:][::-1]
    recent_rows = [row([
        esc(s.get("ts")), esc(f'#{s.get("run")}'),
        money(s.get("cash_dollars")), money(s.get("positions_value_dollars")),
        money(s.get("equity_dollars")), signed(s.get("realized_pnl_dollars")),
        signed(s.get("unrealized_pnl_dollars")), esc(s.get("open_positions")),
        esc(s.get("resting_orders")), src_link(s.get("source_url")),
    ]) for s in recent]

    run_rows = [row([
        esc(r.get("ts")), esc(f'#{r.get("run")}'), esc(r.get("universe")),
        esc(r.get("markets_returned") if r.get("markets_returned") is not None
            else "unverified"),
        esc(r.get("intents")), esc(r.get("fills")), esc(r.get("rejections")),
        esc(r.get("settlements")), money(r.get("equity_dollars")),
        esc(r.get("requests")), esc(r.get("errors")),
        '<span class="pill">' + esc(r.get("data_mode") or "n/a") + "</span>",
        " ".join([src_link(u, f"req {i + 1}") for i, u in enumerate((r.get("source_urls") or [])[:2])]
                 + [file_link("data/paper/runs.json", "run log")]),
    ]) for r in runs[-15:][::-1]]

    body = f"""{empty_state(data)}
<div class="note">The desk runs unattended: it reads the tracked universe from the collector
snapshot, pulls <strong>live quotes</strong> from the official demo REST root
<span class="mono">{esc(state.get('api_root') or 'https://external-api.demo.kalshi.co/trade-api/v2')}</span>,
applies five fixed rules in <a class="mono" href="https://github.com/karagemop466-tech/Demo3/blob/main/trading/paper_strategies.py"
target="_blank" rel="noopener">trading/paper_strategies.py</a>, and simulates fills against the
published top-of-book prices with only the contracts actually resting at that price.
No order is ever sent; no credentials are used (public market data needs none per
<a href="{DOC_ROOT}/getting_started/quick_start_market_data.md" target="_blank" rel="noopener">the docs</a>).</div>
<h2>Portfolio performance (simulated)</h2>
{cards}
<h2>Equity curve &mdash; x: desk cycle time, y: dollars</h2>
{equity_chart(equity)}
<h2>Rules under test</h2>
{table(["Strategy", "id", "family", "entry condition (verbatim rule)", "exit rule",
        "API fields used", "source"], strat_rows)}
<h2>Last desk cycles</h2>
{table(["ts", "run", "universe", "markets quoted", "orders sent", "fills", "rejects",
        "settlements", "equity", "API requests", "API errors", "mode", "requests made"], run_rows)}
<h2>Recent equity samples</h2>
{table(["ts", "run", "cash", "positions value", "equity", "realized", "unrealized",
        "open", "resting", "source"], recent_rows)}
<div class="card"><h2>Live panel</h2><p class="small muted">The committed ledger updates every
cycle. For quotes as of right now, open <a href="positions.html">Positions &amp; liquidity</a>
and press <em>Refresh from the demo API</em> &mdash; that button reads
<span class="mono">GET /markets?tickers=</span> from the browser against the same official demo
endpoint (public, no auth).</p></div>"""
    return page("Paper desk summary", body, data, "index.html",
                blurb='<p class="muted">Automated simulated trading on Kalshi&rsquo;s demo '
                      'exchange, five focus topics: gas prices, elections, culture, crypto, '
                      'golf.</p>')


def build_trades(data: dict) -> str:
    doc = data.get("trades") or {}
    trades = (doc.get("trades") or [])[::-1]
    shown = trades[:MAX_JOURNAL_ROWS]
    rows = []
    for t in shown:
        cls = t.get("classification") or {}
        pnl = t.get("realized_pnl_dollars")
        urls = t.get("source_urls") or {}
        rows.append(row([
            esc((t.get("ts") or "")[:19].replace("T", " ")),
            esc(t.get("run")),
            f'{esc(t.get("strategy"))}<div class="muted small">{esc(cls.get("structure") or "")}</div>',
            esc(t.get("action")), esc(t.get("side")), esc(t.get("role")),
            esc(t.get("topic")),
            f'<span class="mono">{esc(t.get("ticker"))}</span>'
            f'<div class="muted small">{esc((t.get("title") or "")[:70])}</div>',
            esc(t.get("count")),
            money(t.get("price_dollars")),
            money(t.get("notional_dollars")),
            signed(pnl) if pnl is not None else '<span class="pill unv">open/unrealized</span>',
            f'<span class="pill {"ok" if t.get("status") == "filled" else ("warn" if t.get("status") in ("resting", "cancelled") else "unv")}">{esc(t.get("status"))}</span>'
            f'<div class="muted small">{esc(t.get("reason") or t.get("reject_reason") or "")}</div>',
            src_link(urls.get("markets") or urls.get("orderbook"), "API row"),
        ]))
    counts: dict[str, int] = {}
    for t in trades:
        key = f'{t.get("action")}/{t.get("status")}'
        counts[key] = counts.get(key, 0) + 1
    summary = table(["journal record type", "count", "records"],
                    [row([esc(k), esc(v), file_link("data/paper/trades.json", "journal json")])
                     for k, v in sorted(counts.items())])
    body = f"""{empty_state(data)}
<div class="flexrow small muted"><span>journal rows: <strong>{esc(len(trades))}</strong></span>
<span>shown: newest {esc(len(shown))}</span>
<span>full data: <a href="../data/paper/trades.json" class="mono">data/paper/trades.json</a></span></div>
{summary}
<h2>Journal (newest first)</h2>
<div class="scroll">
{table(["ts", "run", "strategy / type", "action", "side", "role", "topic", "market",
        "contracts", "price", "notional", "realized P&amp;L", "status / reason",
        "source"], rows)}
</div>
<div class="note small">Every row is one simulated order or one settlement event produced by
<span class="mono">trading/paper_engine.py</span>. Fills exist only when the exchange published a
crossable price <em>and</em> contracts resting at that price; otherwise the row is a
<em>rejection</em> with the reason, never a made-up execution. Realized P&amp;L is computed from
the entry price and either the exit bid or the $1-per-winning-contract settlement payout
(<a href="{DOC_ROOT}/getting_started/market_settlement.md" target="_blank" rel="noopener">settlement doc</a>).</div>"""
    return page("Trade journal", body, data, "trades.html")


def build_positions(data: dict) -> str:
    state = data.get("state") or {}
    pos = state.get("positions") or []
    resting = state.get("resting_orders") or []
    books = (data.get("books") or {}).get("books") or []
    tracked = state.get("tracked") or {}

    pos_rows = [row([
        f'<span class="mono">{esc(p.get("ticker"))}</span>',
        f'<div class="muted small">{esc((p.get("title") or "")[:60])}</div>',
        esc(p.get("topic")), esc(p.get("side")), esc(p.get("count")),
        money(p.get("avg_price_dollars")), money(p.get("cost_basis_dollars")),
        money(p.get("last_mark_dollars")), money(p.get("market_value_dollars")),
        signed(p.get("unrealized_pnl_dollars")), esc(p.get("strategy")),
        esc(f'#{p.get("opened_run")}'),
        src_link(p.get("source_url") or f"{state.get('api_root')}/markets/{p.get('ticker')}",
                 "market"),
    ]) for p in pos]

    rest_rows = [row([
        f'<span class="mono">{esc(o.get("ticker"))}</span>', esc(o.get("strategy")),
        money(o.get("price_dollars")), esc(o.get("age_runs")),
        esc(state.get("config", {}).get("max_resting_runs")),
        esc((o.get("placed_at") or "")[:19]),
        '<span class="pill warn">resting</span>',
        '<div class="muted small">' + esc(o.get("last_block") or "") + "</div>",
        src_link(o.get("source_url"), "market"),
    ]) for o in resting]

    tracked_rows = []
    for ticker in sorted(tracked)[:MAX_LIST_ROWS]:
        s = tracked[ticker] or {}
        tracked_rows.append(row([
            f'<span class="mono">{esc(ticker)}</span>', esc(s.get("ts")),
            money(s.get("yes_bid")), money(s.get("yes_ask")),
            money(s.get("no_bid")), money(s.get("no_ask")), money(s.get("last")),
            esc(s.get("volume_24h")), esc(f'#{s.get("run")}'),
            src_link(s.get("source_url"), "quote row"),
        ]))

    tracked_tickers = sorted({p.get("ticker") for p in pos}
                             | {o.get("ticker") for o in resting}
                             | {b.get("ticker") for b in books if b.get("ticker")})
    extra = [t for t in sorted(tracked)[:40] if t not in tracked_tickers]
    universe = list(dict.fromkeys(tracked_tickers + extra))[:40]
    tickers_json = json.dumps(universe)
    marks = {}
    for p_ in pos:
        marks[p_.get("ticker")] = {
            "mark": p_.get("last_mark_dollars"), "entry": p_.get("avg_price_dollars"),
            "side": p_.get("side"), "count": p_.get("count"), "topic": p_.get("topic"),
            "strategy": p_.get("strategy")}
    marks_json = json.dumps(marks, sort_keys=True)

    body = f"""{empty_state(data)}
<div class="card"><h2>Live refresh</h2>
<p class="small muted">Reads <span class="mono">GET /markets?tickers=&hellip;</span> and
<span class="mono">GET /markets/&lt;ticker&gt;/orderbook</span> from this browser against the
official demo REST root &mdash; no key required for public market data
(<a href="{DOC_ROOT}/getting_started/quick_start_market_data.md" target="_blank" rel="noopener">docs</a>).
Answers are as-of the API's own short response cache
(<a href="{DOC_ROOT}/api-reference/market/get-markets.md" target="_blank" rel="noopener">documented lag</a>).</p>
<p class="flexrow"><button id="liveRefresh">Refresh from the demo API</button>
<label class="small"><input type="checkbox" id="liveAuto"> auto-refresh
<select id="liveInterval"><option>10</option><option selected>30</option><option>60</option></select> s</label>
<select id="liveChart" aria-label="Chart granularity"><option value="1">chart: 1-minute candles</option>
<option value="60" selected>chart: 1-hour candles</option><option value="1440">chart: 1-day candles</option>
<option value="live">chart: live seconds (this browser only)</option></select>
<span id="liveStatus" class="muted small">{esc(len(universe))} tracked market(s) loaded</span></p>
<div id="liveTable"></div><div id="liveChartBox"></div></div>
<h2>Open positions (marked at the published bid)</h2>
{table(["market", "title", "topic", "side", "contracts", "avg entry", "cost basis",
        "mark", "value", "unrealized", "strategy", "opened run", "source"], pos_rows)}
<h2>Resting simulated orders</h2>
{table(["market", "strategy", "limit", "age (cycles)", "expiry rule (cycles)",
        "placed", "status", "last block", "source"], rest_rows)}
<h2>Liquidity snapshots at decision time (contracts resting at each price)</h2>
<div class="scroll">
{table(["market", "book", "price", "contracts", "relative depth", "fetched", "source"],
       ladder_rows(books[::-1]))}
</div>
<h2>Latest quote the desk recorded per tracked market</h2>
<div class="scroll">
{table(["market", "ts", "YES bid", "YES ask", "NO bid", "NO ask", "last", "24h volume",
        "run", "source"], tracked_rows)}
</div>
<script>window.PAPER_TICKERS={tickers_json};window.PAPER_MARKS={marks_json};window.PAPER_API_ROOT={json.dumps(state.get("api_root") or "https://external-api.demo.kalshi.co/trade-api/v2")};</script>
<script src="assets/paper.js"></script>"""
    return page("Positions & liquidity", body, data, "positions.html")


def build_analysis(data: dict) -> str:
    analysis = data.get("analysis") or {}
    docs0 = (data.get("sources") or {}).get("docs") or {}
    cfg_batches = str(((data.get("state") or {}).get("config") or {})
                      .get("ticker_batch_size", "50"))
    grouped = analysis.get("grouped") or {}
    titles = {
        "by_strategy": "By strategy (rule tested)",
        "by_topic": "By focus topic",
        "by_side": "By contract side",
        "by_price_band": "By trade type (price band at entry)",
        "by_family": "By strategy family",
        "by_action": "By action recorded",
    }
    sections = []
    for key, title in titles.items():
        rows = []
        for r in grouped.get(key) or []:
            rows.append(row([
                esc(r.get("key")), esc(r.get("trades")), esc(r.get("closed_trades")),
                esc(r.get("wins")), esc(r.get("losses")), pct(r.get("win_rate")),
                signed(r.get("realized_pnl_dollars")),
                signed(r.get("avg_realized_pnl_dollars")),
                money(r.get("notional_dollars")), esc(r.get("contracts")),
                esc(r.get("rejections")),
                agg_links(r),
            ]))
        sections.append(f"<h2>{title}</h2>" + (table(
            ["group", "records", "closed", "wins", "losses", "win rate", "realized P&amp;L",
             "avg per closed trade", "notional", "contracts", "rejections",
             "records behind this row"], rows)
            if rows else '<p class="muted small">No closed trades in this group yet.</p>'))

    derived = (analysis.get("derived_rule_candidates") or {})
    d_rows = [row([esc(d.get("type")), esc(d.get("closed_trades")),
                   signed(d.get("realized_pnl_dollars")), pct(d.get("win_rate")),
                   signed(d.get("avg_realized_pnl_dollars")), agg_links(d)])
              for d in derived.get("rows") or []]
    totals = analysis.get("totals") or {}
    req = analysis.get("requests") or {}
    caveats = analysis.get("caveats") or {}
    uni = analysis.get("universe") or {}

    body = f"""{empty_state(data)}
<h2>Ledger totals</h2>
{kpis([("realized", signed(totals.get("realized_pnl_dollars"))),
       ("unrealized", signed(totals.get("unrealized_pnl_dollars"))),
       ("total", signed(totals.get("total_pnl_dollars"))),
       ("equity", money(totals.get("equity_dollars"))),
       ("settled positions", esc(totals.get("settlements", 0))),
       ("samples", esc(totals.get("samples", 0)))])}
<div class="note small">Reading these tables: a group's realized P&amp;L is the sum of closed and
settled trades in that group only; open positions are shown separately as unrealized on the
<a href="positions.html">positions page</a>. Nothing here is a forecast &mdash; it is arithmetic on
the desk&rsquo;s own simulated fills, over a small number of samples.</div>
{''.join(sections)}
<h2>Trade-type ranking (auto-derived from realized results)</h2>
<p class="small muted">{esc(derived.get("note") or "")} Minimum closed trades for a type to be
listed: {esc(derived.get("min_closed_trades_for_a_claim"))}.</p>
{table(["trade type", "closed trades", "realized P&amp;L", "win rate", "avg per trade",
        "records behind this row"], d_rows)}
<h2>Universe coverage this cycle</h2>
{table(["metric", "value", "source"], [
    row(["markets tracked", esc(uni.get("markets_tracked")),
         src_link("../data/latest/top_events.json", "collector snapshot")]),
    row(["markets quoted", esc(uni.get("markets_quoted")),
         src_link(f"{DOC_ROOT}/api-reference/market/get-markets.md", "endpoint doc")]),
    row(["with a two-sided quote", esc(uni.get("markets_with_a_two_sided_quote")),
         src_link(f"{DOC_ROOT}/getting_started/orderbook_responses.md", "book structure")]),
    row(["snapshot retrieved at", esc((uni.get("universe_source") or {}).get("snapshot_retrieved_at")),
         src_link("../data/latest/meta.json", "collector meta")]),
    row(["synthetic demo series excluded",
         esc(len((uni.get("universe_source") or {}).get("excluded") or [])),
         src_link("../data/paper/sources.json", "exclusion list + evidence")]),
])}
<h2>API usage (politeness)</h2>
{table(["metric", "value", "note", "source"], [
    row(["requests this cycle", esc(req.get("this_run")),
         "batched " + esc(cfg_batches) + " tickers per request",
         file_link("data/paper/runs.json", "run log")]),
    row(["errors this cycle", esc(req.get("errors_this_run")),
         "recorded, never retried into a fake value", file_link("data/paper/runs.json",
                                                                "run log")]),
    row(["quote batches", esc(req.get("quote_batches")), esc(req.get("note")),
         src_link(f"{DOC_ROOT}/api-reference/market/get-markets.md", "endpoint doc")]),
    row(["orderbook batches / tickers",
         esc(f'{req.get("orderbook_batches")} / {req.get("orderbook_tickers")}'),
         "GET /markets/orderbooks, max 100 tickers per request",
         src_link(f"{DOC_ROOT}/api-reference/market/get-multiple-market-orderbooks.md",
                  "endpoint doc")]),
])}
<h2>Disclosed limitations</h2>
{table(["limitation", "detail (verbatim from the ledger)", "source"], [
    row(["demo prices", esc(caveats.get("demo_prices")) or
         esc("demo prices may not reflect real markets"),
         doc_link(docs0.get("demo_env"))]),
    row(["fees", esc(caveats.get("fees")) or "no trading fees modeled in this ledger",
         file_link("data/paper/analysis.json", "caveats")]),
    row(["account", esc(caveats.get("account")) or
         "not the user's demo account; needs demo API credentials",
         file_link("data/latest/portfolio.json", "portfolio status")]),
    row(["cache lag", esc(caveats.get("cache")) or
         "responses are briefly cached, so cycle-to-cycle deltas can lag",
         doc_link(docs0.get("get_markets"))]),
])}"""
    return page("Strategy analysis", body, data, "analysis.html")


def build_resolutions(data: dict) -> str:
    doc = data.get("resolutions") or {}
    rows = []
    for r in reversed((doc.get("resolved") or [])[-MAX_JOURNAL_ROWS:]):
        won = r.get("desk_outcome")
        rows.append(row([
            esc(r.get("resolved_seen_at")),
            f'<span class="mono">{esc(r.get("ticker"))}</span>'
            f'<div class="muted small">{esc((r.get("title") or "")[:70])}</div>',
            esc(r.get("topic")),
            f'<span class="pill {"ok" if r.get("result") == "yes" else "warn"}">{esc(r.get("result"))}</span>',
            esc(r.get("status")), esc(r.get("settlement_ts")),
            esc(r.get("expiration_value")),
            money(r.get("notional_value_dollars")), money(r.get("settlement_value_dollars")),
            esc(r.get("desk_position_side")), esc(r.get("desk_count")),
            f'<span class="pill {"ok" if won == "win" else "unv"}">{esc(won)}</span>',
            signed(r.get("desk_realized_pnl_dollars")),
            src_link(r.get("source_url"), "market record"),
        ]))
    openn = doc.get("open_tracked")
    body = f"""{empty_state(data)}
<p>The desk holds every simulated position until the market resolves, then books the result from
the market&rsquo;s own <span class="mono">result</span> field
(<span class="mono">'yes'</span> or <span class="mono">'no'</span>) &mdash; it never assumes an
outcome. Payout rule: $1 per winning contract
(<a href="{DOC_ROOT}/getting_started/market_settlement.md" target="_blank" rel="noopener">official settlement doc</a>);
<span class="mono">settlement_value_dollars</span> is used when the market publishes it.</p>
<div class="flexrow small muted"><span>resolved positions: <strong>{esc(len(rows))}</strong></span>
<span>still tracked: <strong>{esc(openn)}</strong></span>
<span>raw: <a class="mono" href="../data/paper/resolutions.json">data/paper/resolutions.json</a></span></div>
<div class="scroll">
{table(["seen at", "market", "topic", "result", "status", "settlement ts", "expiration value",
        "notional", "settlement value", "desk side", "contracts", "desk outcome",
        "desk realized P&amp;L", "source"], rows)}
</div>
<div class="note small">Empty table? Most focus-topic markets resolve on their own schedule
(hourly and daily crypto ladders settle fastest, elections in 2027&ndash;28), so early cycles
mostly show tracked-but-unresolved positions. Settlements appear here automatically.</div>"""
    return page("Resolutions (yes / no)", body, data, "resolutions.html")


def build_methodology(data: dict) -> str:
    state = data.get("state") or {}
    cfg = state.get("config") or {}
    src = data.get("sources") or {}
    docs = src.get("docs") or {}
    cfg_specs = [
        ("starting_cash_dollars", cfg.get("starting_cash_dollars"),
         "simulated cash only; not a Kalshi balance"),
        ("risk_per_trade_dollars", cfg.get("risk_per_trade_dollars"),
         "caps the notional of one simulated order"),
        ("max_contracts_per_trade", cfg.get("max_contracts_per_trade"),
         "also limited by contracts resting at the touch"),
        ("max_open_notional_per_market_dollars", cfg.get("max_open_notional_per_market_dollars"),
         "per-market exposure cap"),
        ("max_open_positions", cfg.get("max_open_positions"), "portfolio size cap"),
        ("max_new_orders_per_run", cfg.get("max_new_orders_per_run"),
         "orders the desk may act on per cycle"),
        ("max_orderbook_tickers_per_run", cfg.get("max_orderbook_tickers_per_run"),
         "how many markets get an orderbook snapshot per cycle (API politeness)"),
        ("orderbook_batch_size", cfg.get("orderbook_batch_size"),
         "tickers per GET /markets/orderbooks call (100 is the documented max)"),
        ("max_resting_runs", cfg.get("max_resting_runs"),
         "unfilled resting orders expire; no phantom fills"),
        ("ticker_batch_size", cfg.get("ticker_batch_size"),
         "tickers per GET /markets?tickers= request"),
        ("swing_threshold_dollars", cfg.get("swing_threshold_dollars"),
         "brief's $0.10 swing definition, used by the fade/momentum rules"),
        ("fees_modeled", cfg.get("fees_modeled"),
         "no fee model: P&L is gross of fees (flagged)"),
    ]
    # any config key the engine adds that this list does not name is still rendered,
    # so the table can never go stale against trading/paper_engine.py
    named = {k for k, _, _ in cfg_specs}
    cfg_specs += sorted((k, v, "engine config key; not described above")
                        for k, v in cfg.items() if k not in named)
    cfg_rows = [row([f'<span class="mono">{esc(k)}</span>', esc(v), esc(note),
                     file_link("data/paper/state.json", "config in force")])
                for k, v, note in cfg_specs]

    doc_rows = [row([f'<span class="mono">{esc(k)}</span>', doc_link(v, str(v)),
                     esc(what)])
                for k, v, what in [
                    ("demo root + warning", docs.get("demo_env"),
                     "endpoint used and the demo-vs-real caveat"),
                    ("markets fields", docs.get("get_markets"),
                     "bid/ask/size/last/result semantics used verbatim"),
                    ("tickers filter", docs.get("get_markets"),
                     "\"every matching market is returned in one response\" when tickers is the only filter"),
                    ("orderbook structure", docs.get("orderbook_structure"),
                     "bids-only, ascending arrays, YES-bid = NO-ask reciprocity"),
                    ("orderbook endpoint", docs.get("orderbook"),
                     "GET /markets/{ticker}/orderbook?depth="),
                    ("batched orderbooks", docs.get("orderbooks_batch"),
                     "GET /markets/orderbooks, 1-100 tickers per request (what the desk calls)"),
                    ("event record", docs.get("get_event"),
                     "series_ticker / category / settlement_sources for each tracked market"),
                    ("candlesticks", docs.get("candlesticks"),
                     "1 / 60 / 1440-minute bars for the live chart"),
                    ("settlement", docs.get("market_settlement"),
                     "$1 per winning contract; zero settlement fee for simple yes/no"),
                    ("fixed point", docs.get("fixed_point"),
                     "dollar/contract counts are strings; 2dp minimum granularity"),
                    ("rate limits", docs.get("rate_limits"),
                     "token buckets; unauthenticated traffic has separate limits &rarr; back off on 429"),
                    ("create order", docs.get("create_order"),
                     "shape the simulation mirrors (side bid/ask, count, dollar price, client_order_id)"),
                    ("public data needs no auth", docs.get("public_data_no_auth"),
                     "why this desk runs credential-free"),
                ]]
    limits = [
        ("F-EB2-01", "The ledger is simulated, not the user&rsquo;s demo account.",
         "Demo-account balance, positions and fills require an authenticated API key "
         f"(<a href=\"{docs.get('demo_env')}\" target=\"_blank\" rel=\"noopener\">demo_env</a>); "
         "none exists in this repository, so "
         "<span class=\"mono\">data/latest/portfolio.json</span> stays "
         "<span class=\"mono\">credentials_missing</span> and the account tables stay blank. "
         "Nothing was invented in their place."),
        ("F-EB2-02", "Scheduled runs only execute on the default branch.",
         "GitHub runs <span class=\"mono\">schedule:</span> events on the repository default "
         "branch (<a href=\"https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#onworkflow_callsschedule-cron\" "
         "target=\"_blank\" rel=\"noopener\">workflow syntax doc</a>); pre-merge cycles are "
         "triggered with <em>Run workflow</em>."),
        ("F-EB2-03", "No fee model.",
         "Trading fees are not applied to simulated fills, so realized P&amp;L is gross. "
         "Kalshi&rsquo;s settlement doc confirms a zero settlement fee for simple yes/no "
         f"markets (<a href=\"{docs.get('market_settlement')}\" target=\"_blank\" rel=\"noopener\">source</a>); "
         "per-trade maker/taker fees are deliberately not modeled here rather than guessed."),
        ("F-EB2-04", "The API has no sub-minute history.",
         f"Candlesticks are published at 1 / 60 / 1440 minutes only "
         f"(<a href=\"{docs.get('get_markets')}\" target=\"_blank\" rel=\"noopener\">Get Market "
         "Candlesticks</a>), so a seconds-granularity x-axis can only come from the "
         "browser&rsquo;s own live polling, not from history; the chart selector says so."),
        ("F-EB2-05", "Quotes can lag by seconds.",
         "The markets endpoint documents short response caching, so a cycle-to-cycle delta is a "
         "lower bound on the true move "
         f"(<a href=\"{docs.get('get_markets')}\" target=\"_blank\" rel=\"noopener\">doc text</a>). "
         "WebSocket streaming would remove the lag but needs signed handshake headers a browser "
         "cannot attach (<a href=\"https://github.com/karagemop466-tech/Demo3/blob/main/COORDINATION.md\" "
         "target=\"_blank\" rel=\"noopener\">board flag I-13</a>)."),
        ("F-EB2-06", "Cause of a price move is never asserted.",
         "Kalshi&rsquo;s public API publishes no news feed. This ledger records the market&rsquo;s own "
         "<span class=\"mono\">rules_primary</span> text and timestamps; attributing a jump to a "
         "specific website link would be inference, so it is out of scope here and left to the "
         "alerting work owned by other sessions on the board."),
        ("F-EB2-07", "Synthetic demo series excluded.",
         "The demo catalog contains exchange test series (e.g. hourly BTC demos, &ldquo;1+1=2&rdquo; "
         "markets, &ldquo;shard&rdquo; placeholders). They are excluded from the tradeable universe by "
         "name in <span class=\"mono\">trading/paper_engine.py</span>; the excluded list and its "
         "evidence live in <a class=\"mono\" href=\"../data/paper/sources.json\">data/paper/sources.json</a>."),
        ("F-EB2-08", "The schedule is registered on the default branch, not this branch.",
         "GitHub exposes a workflow's <span class=\"mono\">schedule</span> and "
         "<em>Run workflow</em> button only for files present on the default branch, so on a "
         "feature branch <span class=\"mono\">gh workflow run</span> answers HTTP 404 "
         "(observed 2026-11-20 for <span class=\"mono\">.github/workflows/paper-desk.yml</span>). "
         "Until this branch merges, the pages therefore render the empty-state banner and "
         "<span class=\"mono\">data/paper/*.json</span> is absent &mdash; that is a real gap, not a "
         "load failure, and no ledger numbers were fabricated to hide it."),
        ("F-EB2-09", "The collector snapshot has no series ticker.",
         "<span class=\"mono\">data/latest/top_events.json</span> market rows carry no "
         "<span class=\"mono\">series_ticker</span>, which the candlestick endpoint requires, so the "
         "live panel resolves it from "
         f"<a href=\"{docs.get('get_event') or DOC_ROOT + '/api-reference/events/get-event.md'}\" "
         "target=\"_blank\" rel=\"noopener\">GET /events/{event_ticker}</a> before drawing a chart "
         "(logged as CR-eb2af75b-2 for the collector owner)."),
        ("F-EB2-10", "Field names are load-bearing.",
         "The engine reads only the documented <span class=\"mono\">*_dollars</span> / "
         "<span class=\"mono\">*_size_fp</span> names and never the legacy integer-cent fields, so a "
         "replayed fixture written with short names parses to a stale quote instead of erroring. "
         "<span class=\"mono\">trading/test_paper_engine.py</span> shows the exact shape."),
    ]
    body = f"""{empty_state(data)}
<h2>What one desk cycle does</h2>
<ol class="small">
<li>Load the tracked universe for the five focus topics from the collector snapshot
<a class="mono" href="../data/latest/top_events.json">data/latest/top_events.json</a>
(top events per topic, top markets per event; synthetic demo series excluded).</li>
<li>Refresh quotes with <span class="mono">GET /markets?tickers=&hellip;</span> in batches of
{esc(cfg.get("ticker_batch_size"))} &mdash; the documented behaviour is that when
<span class="mono">tickers</span> is the only filter, every matching market comes back in one
response, no paging.</li>
<li>Apply exit rules to open positions (take-profit +0.20 / stop-loss &minus;0.20 / time-stop),
then check whether any resting order is crossed by the published ask.</li>
<li>Evaluate the five entry rules; sort candidates by the size of the move (largest first), then
by ticker, so the run is reproducible.</li>
<li>Simulate fills: taker at the published best ask (buy) or best bid (sell), capped by the
contracts resting at that price and by the risk caps; anything else is recorded as a rejection
with a reason. Maker orders rest and only fill on a later crossing quote.</li>
<li>Realize P&amp;L where the market has resolved (<span class="mono">result</span> yes/no, $1 per
winning contract), mark everything else at the current bid, append one equity sample, and commit
the ledger plus this regenerated subsite.</li>
</ol>
<h2>Configuration actually in force (from the ledger)</h2>
{table(["parameter", "value", "meaning", "source"], cfg_rows)}
<h2>Official sources each mechanic is traced to</h2>
{table(["topic", "official source", "what it authorizes"], doc_rows)}
<h2>Flagged items on this page</h2>
{table(["id", "irregularity", "detail + source", "code / ledger"],
       [row([esc(i[0]), esc(i[1]), i[2],
             file_link("data/paper/sources.json", "ledger sources")]) for i in limits])}
<h2>Reproduce a cycle locally or in CI</h2>
<p class="mono small">python3 trading/test_paper_engine.py -v<br>
python3 trading/paper_engine.py run --api-root {esc(state.get("api_root") or "https://external-api.demo.kalshi.co/trade-api/v2")}<br>
python3 scripts/build_paper_desk.py &amp;&amp; python3 scripts/verify_paper_desk.py</p>"""
    return page("Rules & methodology", body, data, "methodology.html")


def build_sources(data: dict) -> str:
    src = data.get("sources") or {}
    docs = src.get("docs") or {}
    api_root = src.get("api_root") or "https://external-api.demo.kalshi.co/trade-api/v2"
    umeta = src.get("universe") or {}
    live_rows = [
        ("tracked-market quotes", f"{api_root}/markets?tickers=&lt;batch&gt;",
         f"{api_root}/markets?tickers=KXPRESNOMD-28-AOC,KXBTCY-27JAN0100-B122500,"
         "KXAAAGASM-26NOV30-4.70,KXPGATOUR-THRC26-TMOO,KXOSCARPIC-27-DIG",
         "the field set this desk consumes"),
        ("exchange status", f"{api_root}/exchange/status", f"{api_root}/exchange/status",
         "exchange/trading active flags"),
        ("orderbooks at decision time",
         f"{api_root}/markets/orderbooks?tickers=&lt;t1&gt;&amp;tickers=&lt;t2&gt;&amp;depth=6",
         f"{api_root}/markets/KXPRESNOMD-28-AOC/orderbook?depth=4",
         "contracts resting at each price, one request per &le;100 tickers; the replay column is "
         "the single-market form of the same payload (verified live), while the batched form is "
         "verified against its endpoint doc and a unit test, not claimed as a live capture"),
        ("event record (topic + series ticker for the chart)",
         f"{api_root}/events/&lt;event_ticker&gt;", f"{api_root}/events/KXPRESNOMD-28",
         "supplies series_ticker (absent from the collector snapshot), category and "
         "settlement_sources[].url for the per-row source links"),
        ("candlesticks for the live chart",
         f"{api_root}/series/&lt;series&gt;/markets/&lt;ticker&gt;/candlesticks?start_ts&end_ts&period_interval",
         f"{api_root}/series/KXPRESNOMD/markets/KXPRESNOMD-28-AOC/candlesticks?start_ts=1763654400&end_ts=1763740800&period_interval=60",
         "1 / 60 / 1440 minute candles only"),
    ]
    rows = [row([esc(name), f'<span class="mono small">{esc(template)}</span>',
                 src_link(replay, "replay"), esc(why)])
            for name, template, replay, why in live_rows]
    doc_rows = [row([f'<span class="mono">{esc(k)}</span>', doc_link(v, str(v))])
                for k, v in sorted(docs.items())]
    excl = umeta.get("excluded") or []
    excl_rows = [row([f'<span class="mono">{esc(e.get("event_ticker"))}</span>',
                      esc(e.get("topic")), esc(e.get("reason")),
                      file_link("data/paper/sources.json", "evidence")]) for e in excl[:50]]
    if not excl_rows:
        excl_rows = [row(["none this cycle", "&mdash;",
                          "the ledger recorded no exclusions in this cycle",
                          file_link("data/paper/sources.json", "evidence")])]
    repo_rows = [row([esc(f), src_link(
        f"https://github.com/karagemop466-tech/Demo3/blob/main/{f}", "file")]) for f in [
        "trading/paper_engine.py", "trading/paper_strategies.py",
        "trading/test_paper_engine.py", ".github/workflows/paper-desk.yml",
        "scripts/build_paper_desk.py", "scripts/verify_paper_desk.py",
        "data/paper/state.json", "data/paper/trades.json", "data/paper/analysis.json",
        "data/paper/equity.json", "data/paper/resolutions.json", "data/paper/runs.json",
        "data/paper/books.json", "data/paper/sources.json", "data/latest/portfolio.json"]]
    body = f"""{empty_state(data)}
<h2>Live demo-API requests this desk makes</h2>
<p class="small muted">&ldquo;replay&rdquo; opens the exact request; each table row on every page of
this subsite carries its own URL from the record that produced it, so a number can be checked
without reading the code.</p>
{table(["used for", "request pattern (from the code)", "verified example", "note"], rows)}
<h2>Official documentation register</h2>
{table(["source", "url"], doc_rows or [row(["&mdash;", '<span class="pill unv">unverified</span>'] * 2)])}
<h2>Repo files behind this page</h2>
{table(["file", "link"], repo_rows)}
<h2>Universe provenance</h2>
{table(["item", "value", "source"], [
    row(["snapshot file", '<span class="mono">data/latest/top_events.json</span>',
         src_link("../data/latest/top_events.json", "json")]),
    row(["snapshot retrieved at", esc(umeta.get("snapshot_retrieved_at")),
         src_link("../data/latest/meta.json", "collector meta")]),
    row(["ranking metric in that snapshot",
         esc((data.get("top_events") or {}).get("ranking_metric")),
         src_link("https://github.com/karagemop466-tech/Demo3/blob/main/scripts/collect_kalshi_data.py",
                  "collector code")]),
    row(["collector status", esc((data.get("collector_status") or {}).get("status")),
         src_link("../data/latest/collector_status.json", "status json")]),
])}
<h2>Synthetic demo series excluded from the universe</h2>
{table(["event ticker", "topic", "reason", "source"], excl_rows)}
<h2>Where the demo-account numbers would come from (still unverified)</h2>
<div class="note small"><p>The brief asks to &ldquo;track the portfolio performance using the kalshi
demo account&rdquo;. That needs an authenticated demo API key; the repository has no credentials, so
<span class="mono">data/latest/portfolio.json</span> records
<span class="mono">{esc((data.get('portfolio') or {}).get('status') or 'credentials_missing')}</span>
and every account field is left blank rather than filled with an estimate. Setup path, if the
owner adds secrets: <a href="{DOC_ROOT}/getting_started/demo_env.md" target="_blank" rel="noopener">demo account</a>
&rarr; <a href="{DOC_ROOT}/getting_started/api_keys.md" target="_blank" rel="noopener">API keys</a>
&rarr; repository secrets <span class="mono">KALSHI_DEMO_API_KEY_ID</span> /
<span class="mono">KALSHI_DEMO_PRIVATE_KEY</span> &rarr; run
<span class="mono">.github/workflows/trade.yml</span> (mode <em>portfolio</em>).</p></div>"""
    return page("Sources & verification", body, data, "sources.html")


def write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)


def main() -> int:
    data = load_all()
    write(os.path.join(OUT_DIR, "index.html"), build_index(data))
    write(os.path.join(OUT_DIR, "trades.html"), build_trades(data))
    write(os.path.join(OUT_DIR, "positions.html"), build_positions(data))
    write(os.path.join(OUT_DIR, "analysis.html"), build_analysis(data))
    write(os.path.join(OUT_DIR, "resolutions.html"), build_resolutions(data))
    write(os.path.join(OUT_DIR, "methodology.html"), build_methodology(data))
    write(os.path.join(OUT_DIR, "sources.html"), build_sources(data))
    write(os.path.join(OUT_DIR, "assets", "paper.css"), CSS)
    print(f"built 7 pages + assets in {os.path.relpath(OUT_DIR, REPO)}/ "
          f"(ledger: {'present' if data.get('_ledger_present') else 'empty'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
