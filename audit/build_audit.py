#!/usr/bin/env python3
"""Render audit/rows.json into the static audit page audit/index.html.

Standard library only. Run from anywhere:  python3 audit/build_audit.py
Every table row comes from rows.json; nothing is typed into the HTML by hand.
"""
import html
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROWS = HERE / "rows.json"
OUT = HERE / "index.html"

BADGE = {
    "Verified": "ok",
    "Partly verified": "part",
    "Contradicted": "bad",
    "Flagged": "flag",
    "Not reproduced": "nr",
}


def esc(s):
    return html.escape(str(s), quote=True)


def links(items):
    if not items:
        return '<span class="none">none (see note)</span>'
    out = []
    for it in items:
        out.append(
            f'<li><a href="{esc(it["url"])}" target="_blank" rel="noopener">{esc(it["label"])}</a></li>'
        )
    return "<ul class=\"links\">" + "".join(out) + "</ul>"


def row_html(r):
    badge = BADGE.get(r["result"], "nr")
    return (
        f'<tr id="{esc(r["id"])}">'
        f'<td class="id">{esc(r["id"])}</td>'
        f'<td>{esc(r["claim"])}</td>'
        f'<td class="where">{esc(r["where"])}</td>'
        f'<td>{links(r["official"])}</td>'
        f'<td>{links(r["evidence"])}</td>'
        f'<td><span class="badge {badge}">{esc(r["result"])}</span></td>'
        f'<td class="note">{esc(r["note"])}</td>'
        "</tr>"
    )


def section_html(s):
    head = (
        '<tr><th>ID</th><th>Claim or item</th><th>Where it appears</th>'
        '<th>Official source</th><th>Live or repo evidence</th><th>Result</th><th>Notes</th></tr>'
    )
    body = "\n".join(row_html(r) for r in s["rows"])
    return (
        f'<section class="card" id="sec-{esc(s["id"])}"><h2>{esc(s["title"])}</h2>'
        f'<div class="tablewrap"><table><thead>{head}</thead><tbody>\n{body}\n</tbody></table></div></section>'
    )


def flagged_html(rows):
    items = []
    for r in rows:
        badge = BADGE.get(r["result"], "nr")
        src = r["official"][0] if r["official"] else None
        src_link = (
            f'<a href="{esc(src["url"])}" target="_blank" rel="noopener">{esc(src["label"])}</a>'
            if src
            else "no source"
        )
        items.append(
            f'<li><a href="#{esc(r["id"])}"><strong>{esc(r["id"])}</strong></a> '
            f'<span class="badge {badge}">{esc(r["result"])}</span> {esc(r["claim"])} '
            f'<span class="src">Source: {src_link}</span></li>'
        )
    return "\n".join(items)


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202b;--muted:#5a6675;--line:#dfe3e8;--ok:#0f7b4b;--part:#8a6100;--bad:#b42318;--flag:#6b3fb0;--nr:#56606d}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#0f2540;color:#fff;padding:22px 28px}header h1{margin:0 0 4px;font-size:22px}header p{margin:0;color:#c9d6e6}
nav{padding:10px 28px;background:#fff;border-bottom:1px solid var(--line);font-size:14px}nav a{margin-right:16px;color:#0b5cad;text-decoration:none}
main{padding:20px 28px;max-width:1500px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:18px}
.card h2{margin:0 0 10px;font-size:17px}
.summary{display:flex;flex-wrap:wrap;gap:12px}.stat{flex:1 1 150px;border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:#fbfcfd}
.stat b{display:block;font-size:22px}.stat span{color:var(--muted);font-size:13px}
.flagbox{border-left:5px solid var(--flag)}.flagbox ol,.flagbox ul{padding-left:20px;margin:6px 0}.flagbox li{margin:6px 0}
.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{border-bottom:1px solid var(--line);padding:8px 8px;text-align:left;vertical-align:top}
th{background:#f1f4f8;position:sticky;top:0;font-weight:600}
td.id{white-space:nowrap;font-weight:600}td.where{color:var(--muted);min-width:140px}td.note{min-width:220px}
ul.links{margin:0;padding-left:16px}ul.links li{margin:2px 0}a{color:#0b5cad}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;color:#fff;white-space:nowrap}
.badge.ok{background:var(--ok)}.badge.part{background:var(--part)}.badge.bad{background:var(--bad)}.badge.flag{background:var(--flag)}.badge.nr{background:var(--nr)}
.none{color:var(--muted);font-style:italic}.src{color:var(--muted);font-size:13px}
.legend li{margin:3px 0}code{background:#eef2f6;padding:1px 4px;border-radius:4px}
"""


def build():
    data = json.loads(ROWS.read_text(encoding="utf-8"))
    meta = data["meta"]
    all_rows = [r for s in data["sections"] for r in s["rows"]]
    counts = {k: 0 for k in BADGE}
    for r in all_rows:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    flagged = [r for r in all_rows if r["result"] in ("Contradicted", "Flagged")]

    stats = "".join(
        f'<div class="stat"><b>{counts.get(k, 0)}</b><span>{esc(k)}</span></div>'
        for k in ["Verified", "Partly verified", "Contradicted", "Flagged", "Not reproduced"]
    )
    legend = "".join(
        f"<li><strong>{esc(k)}</strong>: {esc(v)}</li>" for k, v in data["results_legend"].items()
    )
    sections = "\n".join(section_html(s) for s in data["sections"])

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Source audit: executive summary and published data (d7d7a733)</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Source audit: executive summary and published data</h1>
  <p>Session {esc(meta["session"])} · checked {esc(meta["checked_on"])} (UTC) · {len(all_rows)} rows · every row links to an official Kalshi source or to the repo file it cites</p>
</header>
<nav>
  <a href="../index.html">Home</a>
  <a href="../dashboard.html">Dashboard</a>
  <a href="../flagged.html">Flagged (site)</a>
  <a href="https://github.com/karagemop466-tech/Demo3/blob/main/COORDINATION.md" target="_blank" rel="noopener">Coordination board</a>
  <a href="https://github.com/karagemop466-tech/Demo3/blob/main/EXECUTIVE_SUMMARY.md" target="_blank" rel="noopener">Executive summary (source)</a>
</nav>
<main>
  <section class="card"><h2>Summary</h2><div class="summary">{stats}</div>
    <p class="src" style="margin-top:10px">Scope: {esc(meta["scope"])}</p>
  </section>

  <section class="card flagbox" id="flagged"><h2>Flagged for Review</h2>
    <p>These items are contradicted by current data or are irregularities. They do not block anything. Each links to its source so you can check it yourself.</p>
    <ol>
    {flagged_html(flagged)}
    </ol>
  </section>

  {sections}

  <section class="card"><h2>Method and result definitions</h2>
    <p>{esc(meta["method"])}</p>
    <ul class="legend">{legend}</ul>
    <p class="src">Live values were read through the fetch tool on {esc(meta["checked_on"])}. Market values change continuously, so a live value is evidence of what the API returned at that moment, not a quote. Not investment advice.</p>
  </section>
</main>
</body>
</html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(HERE.parent)} with {len(all_rows)} rows, {len(flagged)} flagged")


if __name__ == "__main__":
    build()
