"""
publish_snapshot.py — assemble the single JSON document the dashboard reads.

Every section is copied from an already-verified artifact and carries its own provenance block
(source URL + observation time). This script adds no facts of its own: it merges, labels and
validates. If a required section is missing it writes `null` for that section and records a
problem, so the UI shows a blank + "unverified" rather than a stale or invented value.

  in   data/live_snapshot.json       collector output (exchange status, universe, events, markets)
       data/snapshot.json             session captures (full taxonomy with tags, tape/book/candle samples)
       data/tape_analysis.json        machine-derived dollar-volume aggregates (aggregate_capture.py)
       data/portfolio_ledger.json     portfolio model output (portfolio.py)
       data/analysis.json             trade categorisation of the ledger (analyze.py)
       data/analysis_tape.json        trade categorisation of the public tape (analyze.py --from-tape)
       data/resolutions.json          resolution ledger
       data/orders.json               raw order log
  out    site/data/live_snapshot.json  (what every page fetches)
         data/published_manifest.json  section -> provenance, for the Sources page

Run:  python3 scripts/publish_snapshot.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE_DATA = os.path.join(ROOT, "site", "data")
OUT = os.path.join(SITE_DATA, "live_snapshot.json")
MANIFEST = os.path.join(DATA, "published_manifest.json")

REPO = "https://github.com/karagemop466-tech/Demo3/blob/main"


def load(path: str):
    p = os.path.join(ROOT, path)
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def main() -> int:
    live = load("data/live_snapshot.json")
    if not live:
        print("data/live_snapshot.json is required", file=sys.stderr)
        return 1
    sess = load("data/snapshot.json") or {}
    tape = load("data/tape_analysis.json") or {}
    ledger = load("data/portfolio_ledger.json")
    analysis = load("data/analysis.json")
    tape_analysis = load("data/analysis_tape.json")
    resolutions = load("data/resolutions.json")
    orders = load("data/orders.json")

    def normalise_problem(p: dict, i: int) -> dict:
        """The collector writes stage/detail; the site's table reads id/severity/where/finding.
        Normalise at publish time so a differently-shaped note can never disappear silently."""
        out = dict(p)
        out.setdefault("id", out.get("id") or f"collector-{i + 1:02d}")
        out.setdefault("where", out.get("stage") or out.get("where") or "collector")
        out.setdefault("finding", out.get("detail") or out.get("finding") or "unspecified note")
        out.setdefault("severity", "info")
        for k in ("stage", "detail"):
            out.pop(k, None)
        return out

    problems = [normalise_problem(p, i) for i, p in enumerate(live.get("problems") or [])]
    doc = dict(live)
    prov: dict[str, dict] = {}

    def put(key, value, *, source, observed, produced_by, note=None, required=False):
        doc[key] = value
        prov[key] = {"source": source, "observed_at_utc": observed, "produced_by": produced_by}
        if note:
            prov[key]["note"] = note
        if value is None:
            problems.append({
                "id": f"publish-{key}", "severity": "blocker" if required else "warning",
                "where": f"data section `{key}`",
                "finding": ("the upstream artifact that produces this section is missing, so the section is "
                            "published as null and the UI will show blank cells"),
                "artifact": produced_by,
            })

    tax = (sess.get("categories") or {})
    put("taxonomy_detail", {
        "tags_by_categories": tax.get("tags_by_categories"),
        "source": tax.get("source"),
        "doc": tax.get("doc"),
        "note": tax.get("note"),
        "observed_at_utc": tax.get("observed_at_utc"),
    } if tax else None, source=tax.get("source") or "https://docs.kalshi.com/api-reference/search/get-tags-for-series-categories.md",
        observed=tax.get("observed_at_utc"), produced_by="captured read stored in data/snapshot.json")

    put("tape_analysis", tape or None,
        source=(tape or {}).get("_meta", {}).get("capture", {}).get("sources", [None])[0],
        observed=(tape or {}).get("_meta", {}).get("generated_at_utc"),
        produced_by="scripts/aggregate_capture.py",
        note="derived aggregates; every figure is recomputed from data/raw/trades-capture.json, never typed")

    # override hand-copied event aggregates with the machine-computed ones
    by_ev = {e["event_ticker"]: e for e in (tape or {}).get("events", [])}
    for ev in doc.get("ranked_events", []) or []:
        comp = by_ev.get(ev.get("event_ticker"))
        if comp:
            ev["dollar_volume_window"] = comp["dollar_volume"]
            ev["contracts_window"] = comp["contracts"]
            ev["trades_window"] = comp["trades"]
            ev["block_trades_window"] = comp.get("block_trades", 0)
            ev["yes_side_dollars"] = comp["yes_dollars"]
            ev["no_side_dollars"] = comp["no_dollars"]
            ev["flow_imbalance"] = comp["flow_imbalance"]
            ev["avg_fill_notional_dollars"] = comp.get("avg_fill_notional_dollars")
            ev["tape_window_seconds"] = comp.get("window_seconds")
            ev["last_trade_time"] = comp.get("last_trade_time")
            ev["classification"] = {"by": comp.get("classified_by"), "provisional": comp.get("provisional")}
        else:
            ev["dollar_volume_window"] = 0.0
            ev["trades_window"] = 0
            ev["flow_imbalance"] = None
            ev["window_note"] = ("no fills for this event in the captured tape window; the dollar figure is 0 "
                                 "because nothing was observed, not because nothing exists")
            problems.append({"id": f"no-tape-{ev.get('event_ticker')}", "severity": "info",
                             "where": f"event {ev.get('event_ticker')}",
                             "finding": "listed in the verified universe but no fill appeared in the capture window",
                             "resolution": "widen --window-minutes on scripts/collect.py"})
    prov["ranked_events"] = {
        "source": "https://external-api.demo.kalshi.co/trade-api/v2/markets/trades?limit=120",
        "observed_at_utc": (tape or {}).get("_meta", {}).get("capture", {}).get("last_trade_time"),
        "produced_by": "scripts/collect.py (events, markets) + scripts/aggregate_capture.py (windows)",
        "note": "every dollar figure is derived; the formula string is stored per event as dollar_volume_formula",
    }

    put("topics_summary", (tape or {}).get("by_topic") or None,
        source="computed from data/raw/trades-capture.json", observed=(tape or {}).get("_meta", {}).get("generated_at_utc"),
        produced_by="scripts/aggregate_capture.py")
    put("unmapped_trades", (tape or {}).get("unmapped_trades") or [],
        source="data/raw/trades-capture.json", observed=(tape or {}).get("_meta", {}).get("generated_at_utc"),
        produced_by="scripts/aggregate_capture.py",
        note="tape rows whose series is outside the five topics; listed so the exclusion is auditable")

    put("portfolio", ledger or None, source=f"{REPO}/data/portfolio_ledger.json",
        observed=(ledger or {}).get("collected_at_utc"), produced_by="scripts/portfolio.py",
        note="source_mode='paper' means simulated fills; 'demo-live' means read from /portfolio/*", required=False)
    put("trade_analysis", analysis or None, source=f"{REPO}/data/analysis.json",
        observed=(analysis or {}).get("_meta", {}).get("generated_at_utc"), produced_by="scripts/analyze.py")
    put("tape_trade_analysis", tape_analysis or None, source=f"{REPO}/data/analysis_tape.json",
        observed=(tape_analysis or {}).get("_meta", {}).get("generated_at_utc"), produced_by="scripts/analyze.py --from-tape",
        note="categorisation of OTHER participants' tape fills — market structure, not this account's trades")
    put("resolutions", (resolutions or {}).get("resolutions") or [],
        source=(resolutions or {}).get("_meta", {}).get("field_semantics"),
        observed=(resolutions or {}).get("_meta", {}).get("updated_at_utc"),
        produced_by="scripts/collect.py --resolutions-only (append-only ledger)")
    put("order_log", (orders or {}).get("orders") or [], source=f"{REPO}/data/orders.json",
        observed=(orders or {}).get("_meta", {}).get("updated_at_utc") if orders else None,
        produced_by="scripts/trade_engine.py",
        note="every create/amend/cancel recorded locally; mode='paper' entries were never sent to Kalshi")
    put("scenario", {
        "path": "data/scenarios/paper-first-pass.json",
        "spec": (load("data/scenarios/paper-first-pass.json") or {}).get("_meta"),
        "orders": (load("data/scenarios/paper-first-pass.json") or {}).get("orders") or [],
        "skipped": (load("data/scenarios/paper-first-pass.json") or {}).get("skipped") or [],
    }, source="scripts/gen_scenario.py", observed=live.get("_meta", {}).get("generated_at_utc"),
        produced_by="scripts/gen_scenario.py",
        note="which markets could not be priced from the capture is recorded, not dropped")

    samples = {k: sess.get(k) for k in ("exchange_status", "live_trade_sample", "orderbook_sample",
                                        "candlesticks_sample", "settled_market_example",
                                        "open_market_shape", "provisional_multivariate_shape",
                                        "series_volume_observations") if k in sess}
    put("raw_samples", samples or None,
        source="https://external-api.demo.kalshi.co/trade-api/v2/", observed=(sess.get("_meta") or {}).get("observed_at_utc"),
        produced_by="verbatim API responses copied into data/snapshot.json during the session",
        note="kept so a reader can compare the shaped rows the site shows against the raw response")

    doc["problems"] = problems
    doc["_meta"] = dict(doc.get("_meta") or {})
    doc["_meta"]["published_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc["_meta"]["published_by"] = "scripts/publish_snapshot.py"
    doc["_meta"]["provenance"] = prov
    doc["_meta"]["sections"] = sorted(prov)

    os.makedirs(SITE_DATA, exist_ok=True)
    def write_json(path: str, obj) -> None:
        # allow_nan=False: json.dump happily writes NaN/Infinity, and JSON.parse in the browser
        # then throws on the whole file. Fail loudly here instead of shipping a broken page.
        with open(path, "w") as fh:
            json.dump(obj, fh, indent=2, allow_nan=False)

    write_json(OUT, doc)
    write_json(MANIFEST, {"_meta": {"generated_at_utc": doc["_meta"]["published_at_utc"],
                             "generator": "scripts/publish_snapshot.py",
                             "purpose": "section -> provenance for the published document; "
                                        "site/sources.html renders data/sources.json instead"},
                   "sections": prov, "problems": problems})
    print(json.dumps({"published": os.path.relpath(OUT, ROOT),
                      "sections": len(prov), "events": len(doc.get("ranked_events", [])),
                      "markets": sum(len(e.get("markets", [])) for e in doc.get("ranked_events", [])),
                      "problems": {"blocker": sum(1 for p in problems if p.get("severity") == "blocker"),
                                   "warning": sum(1 for p in problems if p.get("severity") == "warning"),
                                   "info": sum(1 for p in problems if p.get("severity") == "info")},
                      "bytes": os.path.getsize(OUT)}, indent=2))
    blockers = [p for p in problems if p.get("severity") == "blocker"]
    if blockers:
        print("BLOCKERS (publication is allowed but every blocker is surfaced on flagged.html):", file=sys.stderr)
        for b in blockers:
            print("  - " + b.get("where", "?") + ": " + b.get("finding", "")[:140], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
