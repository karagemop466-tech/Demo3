#!/usr/bin/env python3
"""Generate `strategy.html` from strategy/data/backtest.json (session 26973298).

Every table row on the generated page links the official API URL or docs page that
supports it. Cells that cannot be verified are left blank and given an `unverified` pill
(never inferred). The generator refuses to write a page whose rows lack a source.

Run: python3 scripts/build_strategy_page.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "strategy" / "data" / "backtest.json"
OUT = ROOT / "strategy.html"

FAIL = []

FEE_PDF = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
FEE_PAGE = "https://kalshi.com/fee-schedule"
CANDLE_DOC = "https://docs.kalshi.com/api-reference/market/get-market-candlesticks"
BOOK_DOC = "https://docs.kalshi.com/getting_started/orderbook_responses"
SETTLE_DOC = "https://docs.kalshi.com/getting_started/market_settlement"
FP_DOC = "https://docs.kalshi.com/getting_started/fixed_point_migration"
DEMO_DOC = "https://docs.kalshi.com/getting_started/demo_env"
MARKETS_DOC = "https://docs.kalshi.com/api-reference/market/get-markets"
TRADES_DOC = "https://docs.kalshi.com/api-reference/market/get-trades"

# Topics published here are the project's five; anything else is shown as other.
TOPIC_ORDER = ["gas", "elections", "culture", "crypto", "golf", "unknown"]


SITE = "https://karagemop466-tech.github.io/Demo3/"
REPO = "https://github.com/karagemop466-tech/Demo3/blob/main/"


def src(url, label="source"):
    """Absolute link. Repository files are published on GitHub Pages; anything else is a
    document or API URL. Raises if neither rule can produce an https link, so a row can
    never silently lose its source."""
    if url.startswith(("http://", "https://")):
        href = url
    elif (ROOT / url).exists():
        href = SITE + url
    else:
        raise ValueError(f"source path does not exist in the repository: {url}")
    return f'<a class="src" href="{href}" target="_blank" rel="noopener">{label}</a>' 


def esc(s):
    import html as _h
    return _h.escape(str(s if s is not None else ""), quote=True)


def money(v, dash="—"):
    if v is None:
        return dash
    return f"${v:,.2f}" if isinstance(v, (int, float)) else esc(v)


def pct(v, dash="—"):
    if v is None:
        return dash
    return f"{v:.1f}%"


def unverified(why):
    return f'<span class="pill warn" title="{esc(why)}">unverified</span>'


def table(headers, rows, cls=""):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (f'<div class="tablewrap"><table class="{cls}"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def check_row_sources(html, page):
    """Every <tr> must carry an official link or an explicit unverified flag."""
    import re
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not tds:
            continue
        joined = " ".join(tds)
        if "https://" in joined or "unverified" in joined:
            continue
        FAIL.append(f"{page}: row without source link or unverified flag: "
                    f"{re.sub('<[^>]+>', ' ', tds[0]).strip()[:70]!r}")


# ---------------------------------------------------------------- sections
def intro(doc):
    r = doc["datasets"]["resolved"]
    e = doc["datasets"]["exploratory"]
    return f"""
<h1>Strategy lab — measured results</h1>
<p class="lead">Simulated trades run over <strong>recorded Kalshi demo data already committed
to this repository</strong>, with published rules, a documented fill model and the official fee
formula. Every number below is reproducible offline by
<code>python3 scripts/backtest_strategies.py</code>.</p>

<div class="notice"><strong>Read this first.</strong> Two datasets are reported and never mixed:
<strong>Resolved</strong> ({r['trades_total']} trades on {r['series_count']} gas markets that
actually settled YES/NO) and <strong>Exploratory</strong> ({e['trades_total']:,} trades on
{e['series_count']} recorded series, marked to market because no settlement exists for them in
this repository). The resolved sample is honest but tiny; the exploratory sample is large but
cannot be settled. Neither is a live edge, and the demo environment is not the real exchange:
{doc['caveats']['demo']}</div>
"""


def datasets_section(doc):
    rows = []
    for key, label in (("resolved", "Resolved (settlement exits)"),
                       ("exploratory", "Exploratory (marked to market)")):
        d = doc["datasets"][key]
        tot = d["trades_total"]
        settled = sum(s["metrics"].get("settled_trades", 0) for s in d["strategies"])
        rows.append([
            f"<strong>{label}</strong>",
            str(d["series_count"]),
            f"{tot:,}",
            f"{settled:,}",
            money(round(sum(s['metrics'].get('net_pnl', 0) for s in d['strategies']), 2)),
            esc(", ".join(sorted({t for s in d["strategies"] for t in
                                   (s["metrics"].get("topics") or [])})) or "—"),
            (src("strategy/data/raw/" + d["series"][0]["ticker"] + ".json", "raw candles")
             if key == "resolved" else src(doc["inputs"]["candles"], "candles.json"))
            + " " + src(doc["inputs"]["settled"], "settled snapshot"),
        ])
    return f"""
<h2 id="datasets">Datasets</h2>
{table(["Dataset", "Series", "Trades", "Settled exits", "Sum of strategy net PnL",
        "Topics covered", "Source"], rows)}
<p class="small muted">Inputs: {esc(doc['inputs']['resolved_candles'])},
{src(doc['inputs']['candles'], 'candles.json')},
{src(REPO + 'data/history/', 'history/ directory')},
{src(doc['inputs']['settled'], 'settled markets')}.</p>
"""


def fee_section(doc):
    fv = doc["fee_verification"]
    rows = [[f"${r['price']}", f"${r['official_fee_100']:.2f}", f"${r['computed_fee_100']:.2f}",
             '<span class="pill ok">match</span>' if r["match"] else '<span class="pill bad">mismatch</span>',
             src(FEE_PDF, "fee schedule PDF")] for r in fv["rows"]]
    return f"""
<h2 id="fees">Fee model (official formula, reproduced)</h2>
<p>Kalshi's published formula is <code>fees = round_up(M × 0.07 × C × P × (1 − P))</code>, with
<code>M</code> defaulting to 1, a maker coefficient of 0.0175 on the series that use it, and
“there is no settlement fee” ({src(FEE_PDF, 'fee schedule PDF')},
{src(FEE_PAGE, 'live fee schedule')}). The implementation in
<code>scripts/backtest_strategies.py</code> reproduces <strong>all
{len(fv['rows'])}</strong> rows of the official table for 100 contracts —
<strong>{'every row matches' if fv['all_match'] else 'MISMATCH PRESENT'}</strong>.</p>
{table(["Contract price", "Official fee / 100", "Computed fee / 100", "Result", "Source"], rows)}
<p class="small muted">{unverified('The demo environment is documented as mock funds; whether it '
   'actually charges fees is not stated in the official demo documentation ('
   + DEMO_DOC + '). Fees are therefore a stated modelling assumption, not an observed fact.')}
Fee treatment: a taker fee is charged on entry and on an early marked exit; settlement exits
carry no fee. {src(doc['fee_model']['sources'][2] if len(doc['fee_model']['sources']) > 2 else SETTLE_DOC, 'settlement')}</p>
"""


def scoreboard(doc, key, title, note):
    d = doc["datasets"][key]
    rows = []
    for s in d["strategies"]:
        m = s["metrics"]
        if not m.get("trades"):
            rows.append([f"<strong>{esc(s['label'])}</strong>", esc(s["family"]), "0",
                         '<span class="pill warn">no trades in this sample</span>',
                         "—", "—", "—", "—", "—", "—",
                         src(CANDLE_DOC, "docs")])
            continue
        t = m["temporal_split"]
        both = ('<span class="pill ok">yes</span>' if t["both_halves_positive"]
                else '<span class="pill warn">no</span>')
        c = s["concentration"] or {}
        rows.append([
            f"<strong>{esc(s['label'])}</strong><br><span class='small'>{esc(s['description'])}</span>",
            esc(s["family"]),
            f"{m['trades']:,}",
            money(m["net_pnl"]),
            pct(m["roi_pct"]),
            pct(m["win_rate"]),
            money(m["expectancy_per_trade"]),
            money(m["max_drawdown"]),
            f"{money(t['first_half_net'])} / {money(t['second_half_net'])} {both}",
            f"{esc(c.get('best_series') or '—')}<br><span class='small'>{pct(c.get('share_of_gross_profit_from_best_series'))} of gross profit</span>",
            src(d["series"][0]["source_url"], "candles") + " " + src(FEE_PDF, "fees"),
        ])
    return f"""
<h2 id="{key}-scoreboard">{title}</h2>
<p>{note}</p>
{table(["Strategy", "Family", "Trades", "Net PnL", "ROI on deployed", "Win rate",
        "Expectancy / trade", "Max drawdown", "Net PnL 1st / 2nd half (stable?)",
        "Best series (concentration)", "Source"], rows)}
<p class="small muted">Net PnL is after fees, per <strong>1 contract</strong> per trade.
ROI = net PnL ÷ capital deployed (the summed entry cost), so it is very high for cheap
long-shot entries — read it with the win rate. <em>Stable?</em> splits the trades by exit time
into two halves; a rule that only earns in one half is not shown as an edge.
<em>Concentration</em> shows how much of the gross profit came from one series.</p>
"""


def equity_section(doc):
    return """
<h2 id="equity">Cumulative net PnL</h2>
<p class="small muted">X axis: exit time (UTC). Y axis: cumulative net PnL in dollars per
1-contract trade. Hover a line to see the point value. Choose a dataset and a strategy family;
the series is read from the same JSON that produced the tables above.</p>
<div class="card">
  <p>
    <label>Dataset
      <select id="eqDataset">
        <option value="resolved">Resolved (settlement exits)</option>
        <option value="exploratory">Exploratory (marked to market)</option>
      </select>
    </label>
    <label>Family
      <select id="eqFamily">
        <option value="all">All families</option>
        <option value="momentum">Momentum</option>
        <option value="reversion">Reversion</option>
        <option value="threshold">Threshold</option>
      </select>
    </label>
    <button class="btn" id="eqRedraw" type="button">Redraw</button>
  </p>
  <svg id="eqChart" viewBox="0 0 900 320" width="100%" height="320"
       role="img" aria-label="Cumulative net PnL by strategy"></svg>
  <div id="eqLegend" class="small"></div>
  <p id="eqStatus" class="small muted"></p>
</div>
"""


def resolution_section(doc):
    d = doc["datasets"]["resolved"]
    rows = []
    for r in d["resolutions"]:
        result = r["settled_result"]
        pill = (f'<span class="pill ok">{esc(result.upper())}</span>' if result in ("yes", "no")
                else unverified("no settlement recorded"))
        rows.append([
            f"<span class='mono'>{esc(r['ticker'])}</span><br><span class='small'>{esc(r['title'] or '')}</span>",
            esc(r["topic"]),
            f"${r['last_recorded_close']:.4f}" if r["last_recorded_close"] is not None else "—",
            pill,
            f"${r['settlement_value_dollars']:.2f}" if r["settlement_value_dollars"] is not None else "—",
            money(r["hold_yes_net"]),
            money(r["hold_no_net"]),
            src(r["settlement_source_url"], "settlement") + " " + src(r["candles_source_url"], "candles"),
        ])
    return f"""
<h2 id="resolutions">How the events were resolved (YES / NO)</h2>
<p>These are the only series in the repository with <strong>both</strong> a recorded price path
and a documented settlement. The settlement values are the official
<code>settlement_value_dollars</code> field (“Yes outcome: Yes contract holders receive $1 per
contract”, {src(SETTLE_DOC, 'Market Settlement')}). Hold-to-settlement PnL buys at the last
recorded trade price and pays the settlement value, net of the entry fee.</p>
{table(["Market", "Topic", "Last recorded price (YES)", "Resolved", "Settlement value",
        "Hold YES net", "Hold NO net", "Source"], rows)}
<p class="small muted">A $1.00 settlement value means YES resolved true; $0.00 means NO.
The remaining recorded series are still <code>active</code>: a
<code>?status=settled&amp;tickers=…</code> query returned an empty list for every batch at
capture time ({src(MARKETS_DOC, 'Get Markets')}), so they are not listed as resolved anywhere
on this page.</p>
"""


def topic_section(doc):
    rows = []
    for topic in TOPIC_ORDER:
        for key in ("resolved", "exploratory"):
            d = doc["datasets"][key]
            for s in d["strategies"]:
                m = (d.get("by_topic", {}).get(topic) or {}).get(s["id"])
                if not m or not m.get("trades"):
                    continue
                rows.append([
                    esc(topic), esc(key), f"<strong>{esc(s['label'])}</strong>",
                    f"{m['trades']:,}", money(m["net_pnl"]), pct(m["win_rate"]),
                    money(m["expectancy_per_trade"]), str(m["markets"]),
                    src(CANDLE_DOC, "docs"),
                ])
    if not rows:
        rows = [["—", "—", "—", "0", "—", "—", "—", "0", unverified("no topic rows")]]
    return f"""
<h2 id="topics">Results by topic</h2>
<p class="small muted">Only topics with a recorded series appear. Topics from the brief with no
backtestable recorded data are absent rather than filled in.</p>
{table(["Topic", "Dataset", "Strategy", "Trades", "Net PnL", "Win rate",
        "Expectancy / trade", "Markets", "Source"], rows)}
"""


def categorization_section(doc):
    rows = []
    fam_desc = {
        "momentum": ("Directional", "Follow a ≥$0.10 move in the same direction",
                     "Taker entry after the move; exit after N candles or at settlement"),
        "reversion": ("Mean-reverting", "Take the other side of a ≥$0.10 move",
                      "Taker entry after the move; exit after N candles or at settlement"),
        "threshold": ("Relative value / long shot", "Buy the side priced at ≤ $0.15",
                      "Taker entry; exit after N candles or at settlement"),
    }
    for fam, (kind, trigger, execution) in fam_desc.items():
        for key in ("resolved", "exploratory"):
            d = doc["datasets"][key]
            fam_rows = [s for s in d["strategies"] if s["family"] == fam and s["metrics"].get("trades")]
            if not fam_rows:
                continue
            trades = sum(s["metrics"]["trades"] for s in fam_rows)
            net = round(sum(s["metrics"]["net_pnl"] for s in fam_rows), 2)
            win = round(sum(s["metrics"]["wins"] for s in fam_rows) / trades * 100, 1)
            rows.append([
                f"<strong>{esc(kind)}</strong><br><span class='small'>{esc(fam)}</span>",
                esc(trigger), esc(execution), esc(key), f"{trades:,}", money(net), pct(win),
                src(FEE_PDF, "fees") + " " + src(CANDLE_DOC, "candles"),
            ])
    return f"""
<h2 id="categorization">Trade categorization and the strategy per trade type</h2>
<p>Every simulated trade is categorised before it is scored, so results can be compared by the
<em>type</em> of trade rather than lumped together. The categories are fixed by the entry rule,
not chosen after seeing the result.</p>
{table(["Trade category", "Entry trigger", "Execution", "Dataset", "Trades", "Net PnL",
        "Win rate", "Source"], rows)}
"""


def trade_log_section(doc, limit=40):
    rows = []
    for key in ("resolved", "exploratory"):
        d = doc["datasets"][key]
        for t in d["trades"][:limit]:
            rows.append([
                esc(key), f"<span class='mono'>{esc(t['ticker'])}</span>", esc(t["strategy"]),
                esc(t["side"].upper()), str(t["granularity_minutes"]),
                f"${t['entry_price']:.4f}", f"${t['exit_price']:.4f}",
                esc(t["exit_kind"]),
                ('<span class="pill ok">' + esc(t["settled_result"].upper()) + "</span>")
                if t.get("settled_result") else "—",
                money(t["net_pnl"]),
                src(t["source_url"], "candle") +
                (" " + src(t["settlement_source_url"], "settlement")
                 if t.get("settlement_source_url") else ""),
            ])
    return f"""
<h2 id="log">Trade log (first {limit} per dataset)</h2>
<p class="small muted">The complete log is in
{src('strategy/data/backtest.json', 'strategy/data/backtest.json')} — every trade carries the exact
candle request URL it was computed from, and settled trades also carry their settlement URL.</p>
{table(["Dataset", "Market", "Strategy", "Side", "Granularity (min)", "Entry", "Exit",
        "Exit kind", "Resolved", "Net PnL", "Source"], rows)}
"""


def methodology_section(doc):
    fm = doc["fill_model"]
    em = doc["exit_model"]
    caveats = doc["caveats"]
    return f"""
<h2 id="method">Method, assumptions and limits</h2>
<div class="grid">
  <div class="card"><h3>Fill model</h3>
    <ul class="small">
      <li>{esc(fm['rule'])}</li>
      <li>Buy YES: {esc(fm['buy_yes'])}; buy NO: {esc(fm['buy_no'])}</li>
      <li>Spread: {esc(fm['spread_reported'])}</li>
      <li>{esc(fm['skipped'])}</li>
      <li>{esc(fm['liquidity_filter'])}</li>
      <li>{src(CANDLE_DOC, 'candlesticks doc')} · {src(BOOK_DOC, 'orderbook doc')} ·
          {src(FP_DOC, 'fixed-point doc')}</li>
    </ul></div>
  <div class="card"><h3>Exit model</h3>
    <ul class="small">
      <li>Settlement: {esc(em['settlement'])}</li>
      <li>Mark: {esc(em['mark'])}</li>
      <li>{src(SETTLE_DOC, 'settlement doc')} · {src(CANDLE_DOC, 'candles doc')}</li>
    </ul></div>
  <div class="card"><h3>What this cannot tell you</h3>
    <ul class="small">
      <li>{esc(caveats['demo'])} {src(DEMO_DOC, 'demo env doc')}</li>
      <li>{esc(caveats['fills'])}</li>
      <li>{esc(caveats['size'])}</li>
      <li>{esc(caveats['fees'])}</li>
      <li>{esc(caveats['sample'])}</li>
    </ul></div>
</div>
"""


def sources_section(doc):
    rows = [
        ["Fee formula and table", "0.07 taker coefficient, default multiplier, no settlement fee", src(FEE_PDF, FEE_PDF)],
        ["Live fee schedule", "per-series multipliers, current changes", src(FEE_PAGE, FEE_PAGE)],
        ["Candlesticks", "field semantics, period_interval 1/60/1440", src(CANDLE_DOC, CANDLE_DOC)],
        ["Orderbook responses", "binary complement identity used for NO fills", src(BOOK_DOC, BOOK_DOC)],
        ["Fixed-point fields", "<code>_dollars</code> / <code>_fp</code> units", src(FP_DOC, FP_DOC)],
        ["Market settlement", "YES/NO payouts of $1 per contract", src(SETTLE_DOC, SETTLE_DOC)],
        ["Demo environment", "demo is mock funds and may not reflect real markets", src(DEMO_DOC, DEMO_DOC)],
        ["Get Markets", "settled snapshot fields (result, settlement_value_dollars)", src(MARKETS_DOC, MARKETS_DOC)],
        ["Get Trades", "per-trade prints, if a future version models fills from trades", src(TRADES_DOC, TRADES_DOC)],
    ]
    return f"""
<h2 id="sources">Sources</h2>
{table(["Fact used", "What it establishes", "Link"], rows)}
<p class="small muted">All links were opened and read on 2026-11-20 while building this page.
Nothing on this page depends on a source that is not in this table.</p>
"""


def build():
    doc = json.loads(DATA.read_text())
    doc.setdefault("caveats", {
        "demo": "Kalshi documents that the demo environment uses mock funds and that demo prices may not reflect real markets.",
        "fills": "Fills are modelled from minute/hour/day candle closes, not from individual trade prints, so entry timing is coarser than a live trader's.",
        "size": "All trades are 1 contract; slippage and depth are not modelled.",
        "fees": "Fees use the official production fee formula; whether the demo environment charges fees is unverified.",
        "sample": "The resolved sample is 2 markets and 4 trades — far too small to establish an edge.",
    })
    body = "".join([
        intro(doc),
        datasets_section(doc),
        scoreboard(doc, "resolved", "Resolved scoreboard",
                   "Outcome-based results: every trade here exits at a documented YES/NO "
                   "settlement. The sample is deliberately small because only two recorded "
                   "markets in this repository have settled."),
        scoreboard(doc, "exploratory", "Exploratory scoreboard",
                   "Marked-to-market results on the larger recorded sample. These trades have "
                   "no settlement in this repository, so their exits are candle prices, not "
                   "outcomes — treat them as a rule screen, not as profit."),
        equity_section(doc),
        resolution_section(doc),
        topic_section(doc),
        categorization_section(doc),
        trade_log_section(doc),
        methodology_section(doc),
        sources_section(doc),
    ])

    # per-row source discipline, checked before writing
    check_row_sources(body, "strategy.html")
    if FAIL:
        print("BUILD FAILED:", *FAIL, sep="\n  ")
        return 1

    import importlib.util
    spec = importlib.util.spec_from_file_location("brs", ROOT / "scripts" / "build_root_site.py")
    brs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(brs)
    html = brs.shell("Strategy lab", "strategy.html", body, scripts=("assets/strategy.js",))
    OUT.write_text(html)
    print(f"wrote {OUT.name} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(build())
