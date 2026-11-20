"""Offline test of the collector pipeline against a local mock of the Kalshi demo API.

Response shapes mirror the LIVE demo responses captured on 2026-11-20 and the official
docs (docs.kalshi.com/getting_started/quick_start_market_data.md,
docs.kalshi.com/api-reference/market/get-market-candlesticks.md,
docs.kalshi.com/getting_started/orderbook_responses.md). This test verifies the
collector's parsing/filtering/persistence logic only — it does NOT verify the live API.

Run:  python3 collector/test_collect.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

import collect as C  # noqa: E402

EVENTS_PAGE = {
    "cursor": "",
    "events": [
        {  # in scope: crypto
            "event_ticker": "KXBTCD-26DEC31", "series_ticker": "KXBTCD",
            "title": "Bitcoin above $100K on December 31?", "sub_title": "",
            "category": "Crypto Currencies", "mutually_exclusive": False,
            "last_updated_ts": "2026-11-20T10:00:00Z",
            "settlement_sources": [{"name": "CME CF Benchmarks", "url": "https://www.cfbenchmarks.com"}],
        },
        {  # in scope: gas (keyword match)
            "event_ticker": "KXAAAGASM-26DEC", "series_ticker": "KXAAAGASM",
            "title": "Highest US gas price in December?", "sub_title": "",
            "category": "Economic", "mutually_exclusive": True,
            "last_updated_ts": "2026-11-20T10:00:00Z",
            "settlement_sources": [{"name": "AAA", "url": "https://gasprices.aaa.com"}],
        },
        {  # in scope: golf (series prefix match)
            "event_ticker": "KXPGATOUR-26DEC", "series_ticker": "KXPGATOUR",
            "title": "Winner of the PGA tournament?", "sub_title": "",
            "category": "Sports", "mutually_exclusive": True,
            "last_updated_ts": "2026-11-20T10:00:00Z",
            "settlement_sources": [{"name": "PGA Tour", "url": "https://www.pgatour.com"}],
        },
        {  # OUT of scope (must be filtered): weather
            "event_ticker": "KXHIGHNY-26NOV", "series_ticker": "KXHIGHNY",
            "title": "Highest temperature in NYC?", "sub_title": "",
            "category": "Climate and Weather", "mutually_exclusive": True,
            "last_updated_ts": "2026-11-20T10:00:00Z", "settlement_sources": [],
        },
    ],
}

NESTED_MARKETS = {
    "KXBTCD-26DEC31": [{
        "ticker": "KXBTCD-26DEC31-T100000", "event_ticker": "KXBTCD-26DEC31",
        "title": "Bitcoin above $100K on December 31?", "yes_sub_title": "Yes",
        "market_type": "binary", "status": "active", "result": "",
        "yes_bid_dollars": "0.6200", "yes_ask_dollars": "0.6400",
        "no_bid_dollars": "0.3600", "no_ask_dollars": "0.3800",
        "last_price_dollars": "0.6300", "previous_yes_bid_dollars": "0.6100",
        "previous_yes_ask_dollars": "0.6300",
        "volume_fp": "5000.00", "volume_24h_fp": "500.00", "open_interest_fp": "12000.00",
        "yes_bid_size_fp": "120.00", "yes_ask_size_fp": "80.00",
        "open_time": "2026-11-01T00:00:00Z", "close_time": "2026-12-31T23:59:00Z",
        "can_close_early": False, "strike_type": "greater", "rules_primary": "Resolves Yes if...",
    }],
    "KXAAAGASM-26DEC": [{
        "ticker": "KXAAAGASM-26DEC-T4.50", "event_ticker": "KXAAAGASM-26DEC",
        "title": "Highest US gas price ... $4.50 or higher", "yes_sub_title": "$4.50 or higher",
        "market_type": "binary", "status": "active", "result": "",
        "yes_bid_dollars": "0.1000", "yes_ask_dollars": "0.1200",
        "no_bid_dollars": "0.8800", "no_ask_dollars": "0.9000",
        "last_price_dollars": "0.1100", "volume_fp": "900.00", "volume_24h_fp": "90.00",
        "open_interest_fp": "1500.00", "yes_bid_size_fp": "40.00", "yes_ask_size_fp": "25.00",
        "close_time": "2026-12-31T23:59:00Z", "can_close_early": True,
        "strike_type": "greater", "rules_primary": "Resolves Yes if...",
    }],
    "KXHIGHNY-26NOV": [{
        "ticker": "KXHIGHNY-26NOV-T75", "event_ticker": "KXHIGHNY-26NOV",
        "title": "Highest temperature in NYC ... 75F or higher", "yes_sub_title": "75F or higher",
        "market_type": "binary", "status": "active", "result": "",
        "yes_bid_dollars": "0.3000", "yes_ask_dollars": "0.3200",
        "last_price_dollars": "0.3100", "volume_fp": "400.00", "volume_24h_fp": "40.00",
        "open_interest_fp": "900.00", "yes_bid_size_fp": "30.00", "yes_ask_size_fp": "20.00",
        "close_time": "2026-11-20T23:59:00Z", "can_close_early": True,
        "strike_type": "greater", "rules_primary": "Resolves Yes if...",
    }],
    "KXPGATOUR-26DEC": [{
        "ticker": "KXPGATOUR-26DEC-PLAYERA", "event_ticker": "KXPGATOUR-26DEC",
        "title": "Player A", "yes_sub_title": "Player A",
        "market_type": "binary", "status": "active", "result": "",
        "yes_bid_dollars": "0.2500", "yes_ask_dollars": "0.2700",
        "no_bid_dollars": "0.7300", "no_ask_dollars": "0.7500",
        "last_price_dollars": "0.2600", "volume_fp": "800.00", "volume_24h_fp": "80.00",
        "open_interest_fp": "2000.00", "yes_bid_size_fp": "60.00", "yes_ask_size_fp": "50.00",
        "close_time": "2026-12-20T23:59:00Z", "can_close_early": True,
        "strike_type": "custom", "rules_primary": "Resolves Yes if...",
    }],
}

ORDERBOOK = {
    "orderbook_fp": {
        "yes_dollars": [["0.6000", "50.00"], ["0.6100", "30.00"], ["0.6200", "120.00"]],
        "no_dollars": [["0.3600", "20.00"], ["0.3800", "90.00"]],
    }
}


def candles(interval_min: int, n: int) -> dict:
    import time as _t
    now = int(_t.time())
    out = []
    for i in range(n, 0, -1):
        end = now - i * interval_min * 60
        base = 0.60 + 0.001 * (n - i)
        out.append({
            "end_period_ts": end,
            "price": {"open_dollars": f"{base - 0.004:.4f}", "high_dollars": f"{base + 0.002:.4f}",
                      "low_dollars": f"{base - 0.006:.4f}", "close_dollars": f"{base:.4f}"},
            "yes_bid": {"open_dollars": f"{base - 0.005:.4f}", "high_dollars": f"{base + 0.003:.4f}",
                        "low_dollars": f"{base - 0.007:.4f}", "close_dollars": f"{base - 0.001:.4f}"},
            "yes_ask": {"open_dollars": f"{base + 0.005:.4f}", "high_dollars": f"{base + 0.008:.4f}",
                        "low_dollars": f"{base - 0.002:.4f}", "close_dollars": f"{base + 0.001:.4f}"},
            "volume_fp": f"{10 * (n - i + 1)}.00", "open_interest_fp": "1000.00",
        })
    return {"ticker": "KXBTCD-26DEC31-T100000", "candlesticks": out}


class MockAPI(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        if p.startswith("/trade-api/v2/"):
            p = p[len("/trade-api/v2"):]
        if p == "/exchange/status":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"operational"}')
        elif p == "/events":
            self._json(EVENTS_PAGE)
        elif p == "/markets":
            series = q.get("series_ticker", [None])[0]
            status = q.get("status", [None])[0]
            if series == "KXAAAGASM" and status == "settled":
                self._json({"cursor": "", "markets": [{
                    "ticker": "KXAAAGASM-26NOV-T4.00", "event_ticker": "KXAAAGASM-26NOV",
                    "title": "Highest US gas price ... $4.00 or higher",
                    "status": "settled", "result": "yes", "last_price_dollars": "1.0000",
                    "volume_fp": "2100.00", "settled_time": "2026-11-20T05:00:00Z",
                    "close_time": "2026-11-20T05:00:00Z"}]})
                return
            flat = []
            for ev_t, ms in NESTED_MARKETS.items():
                flat.extend(ms)
            self._json({"cursor": "", "markets": flat})
        elif p.startswith("/events/") and q.get("with_nested_markets", ["false"])[0] == "true":
            ticker = p.rsplit("/", 1)[-1]
            if ticker == "KXGAS-OLD-1":  # a settled (resolved) tracked event
                self._json({"event": {
                    "event_ticker": ticker, "title": "Old gas price event",
                    "settlement_sources": [{"name": "AAA", "url": "https://gasprices.aaa.com"}],
                    "markets": [{
                        "ticker": ticker + "-M1", "status": "settled", "result": "yes",
                        "title": "Old gas price event", "close_time": "2026-11-01T00:00:00Z",
                        "settled_time": "2026-11-01T01:00:00Z",
                    }]}})
                return
            ev = dict(next(e for e in EVENTS_PAGE["events"]
                           if e["event_ticker"] == ticker))
            ev["markets"] = NESTED_MARKETS.get(ticker, [])
            self._json({"event": ev})
        elif p.endswith("/orderbook"):
            self._json(ORDERBOOK)
        elif "/candlesticks" in p:
            interval = int(q.get("period_interval", ["1"])[0])
            n = {1: 60, 60: 48, 1440: 30}[interval]
            self._json(candles(interval, n))
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CollectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_dir = tempfile.mkdtemp(prefix="kalshi-data-")
        C.DATA_DIR = cls.data_dir  # point the collector module at the test dir
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockAPI)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}/trade-api/v2"
        # seed a tracked-but-unresolved event so the resolution sweep exercises it
        os.makedirs(cls.data_dir, exist_ok=True)
        with open(os.path.join(cls.data_dir, "tracked.json"), "w") as fh:
            json.dump({"events": {"KXGAS-OLD-1": {
                "first_seen": "2026-11-01T00:00:00Z", "last_seen": "2026-11-01T00:00:00Z",
                "title": "Old gas price event", "series_ticker": "KXGASOLD", "topic": "gas"}}}, fh)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _run(self) -> C.Collector:
        c = C.Collector(api_root=self.base)
        c.collect()
        return c

    def _read(self, rel):
        with open(os.path.join(self.data_dir, rel)) as fh:
            return json.load(fh)

    def test_full_pipeline(self):
        c = self._run()
        events = self._read("events.json")
        # 1. topic filtering keeps exactly the 4 in-scope events, drops weather
        titles = {e["event_ticker"] for e in events["ranked"]}
        self.assertEqual(titles,
                         {"KXBTCD-26DEC31", "KXAAAGASM-26DEC", "KXPGATOUR-26DEC"})
        topics = set(events["topics"].keys())
        self.assertEqual(topics, {"crypto", "gas", "golf"})
        self.assertEqual(events["topic_counts"]["crypto"], 1)
        # 2. ranking: BTC event (5000 x 0.63 = 3150) first
        self.assertEqual(events["ranked"][0]["event_ticker"], "KXBTCD-26DEC31")
        self.assertAlmostEqual(events["ranked"][0]["est_dollar_volume"], 3150.0, places=2)
        # 3. market snapshot fields parsed from fixed-point strings
        m = events["topics"]["crypto"][0]["markets"][0]
        self.assertEqual(m["yes_bid"], 0.62)
        self.assertEqual(m["volume"], 5000.0)
        self.assertEqual(m["yes_bid_size"], 120.0)
        self.assertIn("/events/KXBTCD-26DEC31", m["ticker"] and
                      events["topics"]["crypto"][0]["source_url"])
        # 4. orderbook written with correct best-bid semantics (ascending, last = best)
        ob = self._read("orderbooks/KXBTCD-26DEC31-T100000.json")
        self.assertEqual(ob["best_yes_bid"]["price"], "0.6200")
        self.assertEqual(ob["best_yes_bid"]["contracts"], "120.00")
        # 5. history has 1m/60m/1440m series with parsed floats
        hist = self._read("history/KXBTCD-26DEC31-T100000.json")
        self.assertEqual(len(hist["1m"]), 60)
        self.assertEqual(len(hist["60m"]), 48)
        self.assertEqual(len(hist["1440m"]), 30)
        point = hist["1m"][0]
        self.assertEqual([k for k in (1, 3, 4) ], [1, 3, 4])
        self.assertIsInstance(point[2], float)  # close
        # 6. resolution sweep resolved the seeded tracked event with outcome yes
        res = self._read("resolutions.json")
        self.assertIn("KXGAS-OLD-1", res["resolved"])
        self.assertEqual(res["resolved"]["KXGAS-OLD-1"]["outcome_side"], "yes")
        tracked = self._read("tracked.json")
        self.assertEqual(tracked["events"]["KXGAS-OLD-1"]["resolved"]["outcome_side"], "yes")
        # 7. cors probe written and browser-direct flag computed
        cors = self._read("cors_test.json")
        self.assertEqual(cors["http_status"], 200)
        self.assertTrue(cors["browser_direct_fetch_allowed"])
        # 8. meta written with request accounting and category audit
        meta = self._read("meta.json")
        self.assertGreater(meta["request_count"], 0)
        self.assertEqual(meta["error_count"], 0)
        self.assertIn("Crypto Currencies", meta["category_counts_open_exchange"])
        # weather event had an open market but stayed out of scope
        self.assertNotIn("KXHIGHNY-26NOV", {e["event_ticker"] for e in events["ranked"]})
        # 9. series resolution sweep recorded the settled gas market (topic with no
        #    live events still gets resolution tracking)
        by_market = res["by_market"]
        self.assertIn("KXAAAGASM-26NOV-T4.00", by_market)
        self.assertEqual(by_market["KXAAAGASM-26NOV-T4.00"]["result"], "yes")

    def test_out_of_scope_never_enters(self):
        c = self._run()
        events = self._read("events.json")
        self.assertNotIn("KXHIGHNY-26NOV",
                         {e["event_ticker"] for e in events["ranked"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
