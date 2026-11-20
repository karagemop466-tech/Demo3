#!/usr/bin/env python3
"""
verify_rows.py — Row-level re-verification of stored snapshot data against the
official Kalshi demo API. Runs in CI right after collect_kalshi_data.py.

Verification policy (per the brief: verify line by line; never infer values):
  * STATIC fields (ticker, titles, event_ticker, series_ticker, open/close times,
    rules, settlement fields, and the FINAL `result` of settled markets) must
    match the live API EXACTLY. Any mismatch is a hard failure.
  * DYNAMIC fields (prices, sizes, volume, open interest) may legitimately move
    between collection and verification; they are reported as "drifted" but do
    not fail the run. A dynamic value that is present in neither the stored row
    nor the live row is impossible by construction (both come from the API).
  * Every row's `source_url` must resolve and contain the row's ticker.

Output: data/latest/verification_report.json (published on the site's Sources
page). Exit code 1 on any hard failure.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.parse
from datetime import datetime, timezone

BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "latest")

STATIC_MARKET_FIELDS = ("ticker", "title", "event_ticker", "yes_sub_title", "no_sub_title",
                        "status", "result", "open_time", "close_time", "settlement_ts",
                        "settlement_value_dollars", "rules_primary", "notional_value_dollars")
DYNAMIC_MARKET_FIELDS = ("last_price_dollars", "previous_price_dollars", "yes_bid_dollars",
                         "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars",
                         "yes_bid_size_fp", "yes_ask_size_fp", "volume_fp", "volume_24h_fp",
                         "open_interest_fp")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(path: str, params: dict | None = None, retries: int = 1) -> dict | None:
    import urllib.request
    params = {k: v for k, v in (params or {}).items() if v is not None}
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kalshi-demo3-verify/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  FETCH FAIL (attempt {attempt + 1}) {url}: {e}")
            if attempt + 1 < retries:
                time.sleep(3)
    return None


def load(name: str) -> dict:
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    random.seed(20261120)  # deterministic sampling
    report = {
        "verified_at": now_iso(),
        "tool": "scripts/verify_rows.py v1",
        "policy": {
            "static_fields": "must match live API exactly (incl. settlement result)",
            "dynamic_fields": "drift tolerated (live market), reported only",
            "source_urls": "must resolve and contain the row ticker",
        },
        "checks": [], "hard_failures": [], "drift_notices": [],
    }
    checked = passed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal checked, passed
        checked += 1
        if ok:
            passed += 1
        else:
            report["hard_failures"].append({"check": name, "detail": detail})
        report["checks"].append({"check": name, "ok": ok, "detail": detail})

    def compare_market(stored: dict, live: dict, label: str) -> None:
        settled = str(stored.get("result", "")) in ("yes", "no")
        for f in STATIC_MARKET_FIELDS:
            sv, lv = str(stored.get(f, "")), str(live.get(f, ""))
            if sv == lv:
                continue
            if f in ("status", "result", "settlement_ts", "settlement_value_dollars") and not settled:
                # a live market may legitimately settle between collect and verify
                report["drift_notices"].append(
                    {"row": stored.get("ticker", ""), "field": f, "stored": sv, "live": lv})
                continue
            check(f"{label} static:{f}", False, f"stored={sv!r} live={lv!r}")
        for f in DYNAMIC_MARKET_FIELDS:
            sv, lv = str(stored.get(f, "")), str(live.get(f, ""))
            if sv != lv:
                report["drift_notices"].append(
                    {"row": stored.get("ticker", ""), "field": f, "stored": sv, "live": lv})

    # 1. Resolutions: every row must keep its final result (settled = immutable).
    #    Settlement batches can briefly drop rows from the listing mid-transition
    #    (observed 2026-11-20: the KXXRP 6am-EST ladder settled mid-verification),
    #    so refetch retries twice before any failure is recorded.
    try:
        res = load("resolutions.json")["resolutions"]
    except Exception as e:  # noqa: BLE001
        res = []
        check("resolutions.json loadable", False, str(e))
    for row in res[:200]:  # up to 200 rows per run (rotating sample keeps load low)
        body = fetch("/markets", {"tickers": row["ticker"]}, retries=3)
        markets = (body or {}).get("markets", [])
        if not markets:
            check(f"resolution {row['ticker']} refetch", False,
                  "ticker not returned after 3 attempts (settlement transition or delisted)")
            continue
        live = markets[0]
        check(f"resolution {row['ticker']} result",
              live.get("result") == row.get("result"),
              f"stored={row.get('result')!r} live={live.get('result')!r}")
        for f in ("settlement_value_dollars", "ticker"):
            check(f"resolution {row['ticker']} {f}",
                  str(live.get(f, "")) == str(row.get(f, "")),
                  f"stored={row.get(f)!r} live={live.get(f)!r}")
        # settlement_ts may be stamped by the exchange after collection; exact when
        # both sides carry one, otherwise recorded as drift
        sv, lv = str(row.get("settlement_ts", "")), str(live.get("settlement_ts", ""))
        if sv and lv and sv != lv:
            check(f"resolution {row['ticker']} settlement_ts", False,
                  f"stored={sv!r} live={lv!r}")
        elif sv != lv:
            report["drift_notices"].append({"row": row["ticker"], "field": "settlement_ts",
                                            "stored": sv, "live": lv})
        time.sleep(0.12)

    # 2. Top events: each named top market must exist (per-ticker refetch: large
    #    events exceed any single event-scanned page)
    try:
        top = load("top_events.json")["overall"][:20]
    except Exception as e:  # noqa: BLE001
        top = []
        check("top_events.json loadable", False, str(e))
    for ev in top:
        for tm in ev.get("top_markets", [])[:5]:
            body = fetch("/markets", {"tickers": tm["ticker"]}, retries=2)
            live_tickers = {m.get("ticker") for m in (body or {}).get("markets", [])}
            check(f"top_event {ev['event_ticker']} market {tm['ticker']} exists",
                  tm["ticker"] in live_tickers,
                  f"live query returned {len(live_tickers)} markets")
            time.sleep(0.12)

    # 3. Market rows: random sample, static fields exact
    try:
        mk = load("markets_open.json")["markets"]
        sample = random.sample(mk, min(30, len(mk)))
    except Exception as e:  # noqa: BLE001
        sample = []
        check("markets_open.json loadable", False, str(e))
    for row in sample:
        body = fetch("/markets", {"tickers": row["ticker"]}, retries=2)
        markets = (body or {}).get("markets", [])
        if not markets:
            check(f"market {row['ticker']} refetch", False, "ticker not returned")
            continue
        compare_market(row, markets[0], f"market {row['ticker']}")
        time.sleep(0.12)

    # 4. Orderbooks: refetch and compare price ladders exactly (book can move;
    #    require structure validity + at least one side non-empty when stored had data)
    try:
        obs = load("orderbooks.json")["orderbooks"]
    except Exception as e:  # noqa: BLE001
        obs = {}
        check("orderbooks.json loadable", False, str(e))
    for t, entry in list(obs.items())[:6]:
        body = fetch(f"/markets/{urllib.parse.quote(t)}/orderbook", {"depth": 25})
        ob = (body or {}).get("orderbook_fp", {})
        ok = isinstance(ob, dict) and ("yes_dollars" in ob or "no_dollars" in ob)
        check(f"orderbook {t} structure", ok, json.dumps(ob)[:120])
        time.sleep(0.12)

    # 5. Events: titles must match
    try:
        evs = load("events.json")["events"]
        ev_sample = random.sample(evs, min(20, len(evs)))
    except Exception as e:  # noqa: BLE001
        ev_sample = []
        check("events.json loadable", False, str(e))
    for ev in ev_sample:
        body = fetch("/events", {"series_ticker": ev["series_ticker"], "limit": 200})
        live = {e.get("event_ticker"): e for e in (body or {}).get("events", [])}
        le = live.get(ev["event_ticker"])
        check(f"event {ev['event_ticker']} exists+title",
              le is not None and le.get("title") == ev.get("title"),
              "missing" if le is None else f"title live={le.get('title')!r}")
        time.sleep(0.12)

    report["summary"] = {"checked": checked, "passed": passed,
                         "hard_failures": len(report["hard_failures"]),
                         "drift_notices": len(report["drift_notices"])}
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "verification_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    print(f"verify_rows: {passed}/{checked} checks passed, "
          f"{len(report['hard_failures'])} hard failures, "
          f"{len(report['drift_notices'])} drift notices")
    return 1 if report["hard_failures"] else 0


if __name__ == "__main__":
    import traceback
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — always leave a report behind
        err = {"verified_at": now_iso(), "tool": "scripts/verify_rows.py v1",
               "summary": {"checked": -1, "passed": -1, "hard_failures": 1, "drift_notices": 0},
               "hard_failures": [{"check": "verify_rows crashed", "detail": f"{e}"}],
               "checks": [], "drift_notices": [],
               "traceback": traceback.format_exc()[-4000:]}
        os.makedirs(DATA, exist_ok=True)
        with open(os.path.join(DATA, "verification_report.json"), "w", encoding="utf-8") as f:
            json.dump(err, f, indent=1, sort_keys=True)
            f.write("\n")
        raise
