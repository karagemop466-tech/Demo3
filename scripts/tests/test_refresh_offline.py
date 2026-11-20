#!/usr/bin/env python3
"""Offline test for scripts/refresh_kalshi.py.

Starts a local mock of the Kalshi Trade API endpoints the job uses, runs the job
against it, and checks the output files. It does not contact Kalshi.
Run:  python3 scripts/tests/test_refresh_offline.py
"""
import http.server
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "scripts" / "config.json").read_text())
SERIES = [s for t in CONFIG["topics"] for s in t["series"]]
PAGE_CURSOR = "page2"


def market(series, i, status, result=""):
    return {
        "ticker": f"{series}-T{i}", "event_ticker": f"{series}-E", "title": f"**Test** {series} #{i}",
        "yes_sub_title": f"Outcome {i}", "status": status, "result": result,
        "last_price_dollars": "0.4200", "yes_bid_dollars": "0.4100", "yes_ask_dollars": "0.4300",
        "yes_bid_size_fp": "10.00", "yes_ask_size_fp": "20.00", "volume_fp": str(1000 * (i + 1)),
        "volume_24h_fp": "5.00", "open_interest_fp": "50.00", "notional_value_dollars": "1.0000",
        "close_time": "2026-12-31T00:00:00Z", "expected_expiration_time": "2026-12-31T12:00:00Z",
        "settlement_ts": "2026-11-19T12:05:24.101765Z" if status == "finalized" else None,
        "expiration_value": "",
    }


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        p = url.path
        if p == "/trade-api/v2/exchange/status":
            return self._send({"exchange_active": True, "trading_active": True})
        if p == "/trade-api/v2/markets":
            series = q.get("series_ticker")
            if q.get("status") == "open":
                if q.get("cursor") == PAGE_CURSOR:
                    return self._send({"cursor": "", "markets": [market(series, 3, "active"), market(series, 4, "active")]})
                return self._send({"cursor": PAGE_CURSOR, "markets": [market(series, 0, "active"), market(series, 1, "active"), market(series, 2, "active")]})
            if q.get("status") == "settled":
                return self._send({"cursor": "", "markets": [market(series, 9, "finalized", "no")]})
            return self._send({"cursor": "", "markets": []}, 400)
        if p.endswith("/orderbook"):
            return self._send({"orderbook_fp": {"yes_dollars": [["0.4100", "10.00"], ["0.4000", "5.00"]], "no_dollars": [["0.5600", "7.00"], ["0.5700", "9.00"]]}})
        if "/candlesticks" in p:
            end = int(q["end_ts"])
            candles = [{"end_period_ts": end - 3600 * k, "price": {"open_dollars": "0.40", "high_dollars": "0.45", "low_dollars": "0.39", "close_dollars": "0.42"}, "volume_fp": "3.00", "open_interest_fp": "9.00"} for k in range(3)]
            return self._send({"ticker": p.split("/")[-2], "candlesticks": candles})
        return self._send({"error": "not found"}, 404)


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    out = pathlib.Path(tempfile.mkdtemp(prefix="kalshi-test-"))
    env = dict(os.environ, KALSHI_BASE=f"http://127.0.0.1:{port}/trade-api/v2", KALSHI_SLEEP="0", KALSHI_OUT=str(out))
    failures = []
    for run in (1, 2):
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "refresh_kalshi.py")], env=env, capture_output=True, text=True, timeout=600)
        if res.returncode != 0:
            failures.append(f"run {run} exit {res.returncode}: {res.stderr[-800:]}")
    server.shutdown()

    markets = json.loads((out / "markets.json").read_text())
    resolutions = json.loads((out / "resolutions.json").read_text())
    books = json.loads((out / "orderbooks.json").read_text())
    candles = json.loads((out / "candles.json").read_text())
    meta = json.loads((out / "meta.json").read_text())

    for topic in markets["topics"]:
        vols = [m["volume_contracts"] for m in topic["top_markets"]]
        if vols != sorted(vols, reverse=True):
            failures.append(f"{topic['id']}: top markets not sorted by volume")
        if topic["open_markets_fetched"] != 5 * len(topic["series"]):
            failures.append(f"{topic['id']}: expected 5 open markets per series (pagination), got {topic['open_markets_fetched']}")
        for m in topic["top_markets"]:
            if not m["source_url"].startswith("http://127.0.0.1"):
                failures.append("row without source_url")
            if "max_payout_usd" in m:
                failures.append("derived field stored")
    if len(resolutions["items"]) != len(SERIES):
        failures.append(f"resolutions: expected {len(SERIES)} unique items after 2 runs (merge), got {len(resolutions['items'])}")
    if any(r["result"] not in ("yes", "no") for r in resolutions["items"]):
        failures.append("resolution without yes/no result")
    if len(books["books"]) != sum(min(CONFIG["orderbook_markets_per_topic"], 5) for _ in CONFIG["topics"]):
        failures.append(f"orderbooks: got {len(books['books'])}")
    first_book = next(iter(books["books"].values()))
    if [b["price"] for b in first_book["yes_bids"]] != [0.41, 0.4]:
        failures.append("yes bids not sorted best-first")
    if len(candles["series"]) == 0:
        failures.append("no candles stored")
    if meta["calls_failed"] != 0 or meta["errors"]:
        failures.append(f"meta reports failures: {meta['calls_failed']} {meta['errors'][:2]}")

    print(f"output dir: {out}")
    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("offline refresh test passed:", {k: meta[k] for k in ("calls_ok", "calls_failed", "resolved_markets_stored", "orderbooks_stored", "candle_series_stored")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
