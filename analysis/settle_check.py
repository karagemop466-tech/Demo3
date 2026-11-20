#!/usr/bin/env python3
"""
Resolution tracker: turns the accumulated settled-market rows into the "how did it resolve"
view, and reconciles it against the order/strategy log.

Inputs:
  data/resolutions-compact.json   trimmed settled markets (built by analysis/build.py)
  data/trade-log.jsonl            append-only log of orders/fills (only when demo keys exist)

Output:
  data/resolutions-summary.json

Nothing is inferred. A settled row's `result` is Kalshi's own field. Rows where `result` is
empty are kept and counted as `blank` rather than assumed.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TOPIC_LABELS = {"gas": "Gas prices", "elections": "Elections", "culture": "Culture",
                "crypto": "Crypto", "golf": "Golf"}


def main() -> int:
    rows_path = DATA / "resolutions-compact.json"
    if not rows_path.exists():
        print("resolutions-compact.json missing; run analysis/build.py first")
        return 1
    data = json.loads(rows_path.read_text(encoding="utf-8"))
    rows = data.get("rows") or []

    by_topic: dict[str, Counter] = defaultdict(Counter)
    by_series: dict[str, Counter] = defaultdict(Counter)
    monthly: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        result = r.get("result") or "blank"
        for t in r.get("topics") or []:
            by_topic[t][result] += 1
        if r.get("series_ticker"):
            by_series[r["series_ticker"]][result] += 1
        if r.get("settlement_ts"):
            monthly[r["settlement_ts"][:7]][result] += 1

    # reconcile against executed demo orders, if any exist
    log_path = DATA / "trade-log.jsonl"
    settled_tickers = {r.get("ticker") for r in rows}
    reconciled = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ticker = (entry.get("request") or {}).get("ticker")
            if ticker and ticker in settled_tickers:
                match = next(r for r in rows if r.get("ticker") == ticker)
                reconciled.append({
                    "ticker": ticker,
                    "outcome": match.get("result"),
                    "order": entry.get("request"),
                    "http_status": entry.get("status"),
                    "settlement_value_dollars": match.get("settlement_value_dollars"),
                    "source": match.get("source"),
                })

    summary = {
        "meta": {
            "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rows": len(rows),
            "sources": {
                "settled_markets": "GET https://external-api.kalshi.com/trade-api/v2/markets"
                                   "?status=settled&series_ticker=...",
                "settlement_rules": "https://docs.kalshi.com/getting_started/market_settlement.md",
                "result_field": "`result` on the Market object: yes | no | scalar | ''",
            },
            "note": "Counts of Kalshi's own `result` field per topic. `blank` means the API "
                    "returned an empty result (typically a scalar or voided market); it is never "
                    "guessed into yes/no.",
        },
        "by_topic": {t: {"label": TOPIC_LABELS.get(t, t), **dict(c)} for t, c in by_topic.items()},
        "totals": dict(Counter(r.get("result") or "blank" for r in rows)),
        "by_month": {m: dict(c) for m, c in sorted(monthly.items())},
        "top_series": [
            {"series_ticker": s, "counts": dict(c), "settled": sum(c.values())}
            for s, c in sorted(by_series.items(), key=lambda kv: sum(kv[1].values()), reverse=True)[:25]
        ],
        "executed_orders_reconciled": reconciled,
    }
    (DATA / "resolutions-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "by_topic": summary["by_topic"],
                      "reconciled_orders": len(reconciled)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
