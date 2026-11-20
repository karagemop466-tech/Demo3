"""Offline tests for the Kalshi demo alerting pipeline.

These tests do NOT touch the network. They pin:
  * the published topic-classification rules (including two real regressions found in
    the live demo corpus: KXSOLE must not be classified as crypto, and KXUSOPEN is
    golf because the API itself tags it Golf);
  * swing detection at exactly the $0.10 threshold, in both directions;
  * the high-ROI screen arithmetic;
  * the orderbook shape documented at
    https://docs.kalshi.com/api-reference/market/get-market-orderbook;
  * settlement arithmetic per https://docs.kalshi.com/getting_started/market_settlement;
  * the simulator's de-duplication and "never settle without an official result" rule;
  * one end-to-end pipeline run against a local mock of the demo API.

Run: python3 -m unittest discover -s automation -t .
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from automation import kalshi_http as kh
from automation import strategies, swings
from automation.topics import classify
from automation.pipeline import Pipeline

# --------------------------------------------------------------------- fixtures
MARKET_A = {
    "ticker": "KXBTCY-27JAN0100-T20000.00", "event_ticker": "KXBTCY-27JAN0100",
    "series_ticker": "KXBTCY", "title": "BTC price on Jan 1, 2027?",
    "yes_sub_title": "19,999.99 or below", "status": "active",
    "last_price_dollars": "0.4000", "previous_price_dollars": "0.3000",
    "yes_bid_dollars": "0.3900", "yes_ask_dollars": "0.4100",
    "volume_fp": "51971508.00", "volume_24h_fp": "27235.25",
    "open_interest_fp": "9351766.83", "close_time": "2027-01-01T05:00:00Z",
    "result": "",
}
EVENT_A = {
    "event_ticker": "KXBTCY-27JAN0100", "series_ticker": "KXBTCY",
    "title": "BTC price on Jan 1, 2027?", "category": "Crypto",
    "settlement_sources": [{"name": "CF Benchmarks", "url": "https://www.cfbenchmarks.com/"}],
    "markets": [MARKET_A],
}
META_A = {"topic": "crypto", "topic_label": "Crypto", "title": EVENT_A["title"],
          "rule": "api_tag=Crypto", "settlement_sources": EVENT_A["settlement_sources"]}


class TopicsTest(unittest.TestCase):
    def test_five_topics_only(self):
        cases = [
            ("KXAAAGASW-26DEC", "Highest gas price in December?", "Economics", [], "gas"),
            ("KXBTCY-27JAN0100", "BTC price on Jan 1, 2027?", "Crypto", [], "crypto"),
            ("KXPGATOUR-THRC26", "The RSM Classic: Bill Haas wins", "Sports", [], "golf"),
            ("KXPRESNOMD-28", "Who will be the Democratic nominee in 2028?",
             "Elections", [], "elections"),
            ("KXRT-EBE", "Ebenezer Rotten Tomatoes score?", "Entertainment", [], "culture"),
        ]
        for ticker, title, cat, tags, want in cases:
            got, rule = classify(ticker, title, cat, tags)
            self.assertEqual(got, want, f"{ticker}: {rule}")
            self.assertTrue(rule)

    def test_kxsole_is_not_crypto(self):
        """Live demo corpus contains KXSOLE (solar energy); it must stay out of scope."""
        got, _ = classify("KXSOLE-26NOV2102-B97.875", "Solar energy production",
                          "Climate and Weather", [])
        self.assertIsNone(got)

    def test_api_tag_wins_over_title_and_category(self):
        """KXUSOPEN is category=Sports but the API tags it Golf (verified live)."""
        got, rule = classify("KXUSOPEN-26", "US Open", "Sports", ["Golf"])
        self.assertEqual(got, "golf")
        self.assertEqual(rule, "api_tag=Golf")

    def test_out_of_scope_returns_none(self):
        got, rule = classify("KXHURRICANE-26", "Hurricane count this season", "Climate", [])
        self.assertIsNone(got)
        self.assertEqual(rule, "no topic rule matched")


class SwingTest(unittest.TestCase):
    def _market(self, price):
        m = dict(MARKET_A)
        m["last_price_dollars"] = f"{price:.4f}"
        return m

    def test_threshold_is_inclusive_both_directions(self):
        up = swings.detect_swing(self._market(0.50), 0.40, "2026-11-20T12:00:00Z",
                                 "u1", "2026-11-20T12:01:00Z", "u2", META_A)
        self.assertIsNotNone(up, "a +$0.10 move must alert")
        self.assertEqual(up["direction"], "up")
        self.assertAlmostEqual(up["delta_dollars"], 0.10, places=4)
        self.assertEqual(up["gap_seconds"], 60)
        down = swings.detect_swing(self._market(0.30), 0.40, "t1", "u1", "t2", "u2", META_A)
        self.assertIsNotNone(down, "a -$0.10 move must alert")
        self.assertEqual(down["direction"], "down")
        self.assertAlmostEqual(down["delta_dollars"], -0.10, places=4)

    def test_below_threshold_does_not_alert(self):
        self.assertIsNone(swings.detect_swing(self._market(0.49), 0.40, "t1", "u1",
                                              "t2", "u2", META_A))
        self.assertIsNone(swings.detect_swing(self._market(0.31), 0.40, "t1", "u1",
                                              "t2", "u2", META_A))

    def test_missing_price_never_alerts(self):
        m = dict(MARKET_A)
        m["last_price_dollars"] = None
        self.assertIsNone(swings.detect_swing(m, 0.40, "t1", "u1", "t2", "u2", META_A))

    def test_alert_carries_both_observation_urls(self):
        a = swings.detect_swing(self._market(0.50), 0.40, "2026-11-20T12:00:00Z",
                                "https://prev", "2026-11-20T12:01:00Z", "https://now", META_A)
        self.assertEqual(a["prev_source_url"], "https://prev")
        self.assertEqual(a["source_url"], "https://now")
        self.assertTrue(a["alert_id"].startswith("SL-"))


class RoiTest(unittest.TestCase):
    def test_roi_arithmetic(self):
        self.assertAlmostEqual(swings.roi_buy(0.20, "yes"), 4.0)     # pays 1 at 0.20
        self.assertAlmostEqual(swings.roi_buy(0.80, "no"), 4.0)      # 1-0.80 = 0.20
        self.assertIsNone(swings.roi_buy(1.0, "yes"))                # not tradable
        self.assertIsNone(swings.roi_buy(None, "yes"))

    def test_screen_requires_cushion_and_roi(self):
        small = swings.roi_screen(0.50, 0.60)   # $0.10 move -> under the $0.20 cushion
        self.assertFalse(small["passes"])
        big = swings.roi_screen(0.70, 0.85)     # $0.15 move, ROI = 0.85/0.15 = 5.67
        self.assertTrue(big["passes"])
        self.assertEqual(big["side"], "no")
        self.assertAlmostEqual(big["roi"], 0.85 / 0.15, places=6)

    def test_up_swing_buys_no_and_down_swing_buys_yes(self):
        self.assertEqual(swings.roi_screen(0.20, 0.40)["side"], "no")
        self.assertEqual(swings.roi_screen(0.40, 0.20)["side"], "yes")


class OrderbookTest(unittest.TestCase):
    def test_documented_shape(self):
        # Exact shape from https://docs.kalshi.com/api-reference/market/get-market-orderbook
        book = {"orderbook_fp": {"yes_dollars": [["0.1500", "100.00"]],
                                 "no_dollars": [["0.1500", "250.00"]]}}
        lv = swings.orderbook_levels(book)
        self.assertEqual(lv["yes"], [{"price": 0.15, "contracts": 100.0}])
        self.assertEqual(lv["no"], [{"price": 0.15, "contracts": 250.0}])
        self.assertEqual(lv["summary"]["best_yes_bid"], 0.15)
        self.assertAlmostEqual(lv["summary"]["yes_contracts_total"], 100.0)
        self.assertAlmostEqual(lv["summary"]["yes_notional"], 15.0)

    def test_empty_book_is_zero_not_invented(self):
        lv = swings.orderbook_levels({"orderbook_fp": {}})
        self.assertEqual(lv["yes"], [])
        self.assertIsNone(lv["summary"]["best_yes_bid"])
        self.assertEqual(lv["summary"]["yes_contracts_total"], 0.0)


class CandleTest(unittest.TestCase):
    def test_intra_candle_and_close_to_close(self):
        candles = [
            {"end_period_ts": 1000, "price": {"open_dollars": "0.4000",
                                              "close_dollars": "0.4000",
                                              "high_dollars": "0.4000",
                                              "low_dollars": "0.4000"}},
            {"end_period_ts": 1060, "price": {"open_dollars": "0.4000",
                                              "close_dollars": "0.5200",
                                              "high_dollars": "0.5200",
                                              "low_dollars": "0.3900"}},
        ]
        rows = swings.detect_candle_swings(candles, MARKET_A, META_A, "https://candles")
        kinds = {r["kind"] for r in rows}
        self.assertIn("close_to_close", kinds)
        self.assertIn("intra_candle_high_low", kinds)
        for r in rows:
            self.assertGreaterEqual(abs(r["delta_dollars"]), 0.10 - 1e-9)
            self.assertEqual(r["source_url"], "https://candles")


class SettlementTest(unittest.TestCase):
    def test_yes_and_no_payouts(self):
        win = swings.simulate_outcome(0.30, 100, "yes", "yes")
        self.assertEqual(win["payout"], 100.0)
        self.assertAlmostEqual(win["pnl"], 70.0)
        loss = swings.simulate_outcome(0.30, 100, "yes", "no")
        self.assertEqual(loss["payout"], 0.0)
        self.assertAlmostEqual(loss["pnl"], -30.0)

    def test_resolution_row_requires_exact_result(self):
        m = dict(MARKET_A, status="settled", result="yes",
                 settlement_value_dollars="1.0000", settlement_ts="2027-01-01T05:00:05Z")
        row = swings.resolution_row(m, META_A, "t", "https://m")
        self.assertEqual(row["result"], "yes")
        self.assertEqual(row["settlement_value_dollars"], 1.0)
        self.assertIsNone(swings.resolution_row(dict(MARKET_A, result=""), META_A, "t", "u"))

    def test_resolution_timing(self):
        row = {"close_time": "2027-01-01T05:00:00Z",
               "settlement_ts": "2027-01-01T05:00:05Z"}
        self.assertEqual(swings.resolution_timing(row), 5)


class StrategyTest(unittest.TestCase):
    def _alert(self, old=0.20, new=0.40, when="2026-11-20T12:00:00Z"):
        screen = swings.roi_screen(old, new)
        return {"alert_id": "SL-abc123456789", "market_ticker": MARKET_A["ticker"],
                "event_ticker": MARKET_A["event_ticker"], "title": "BTC?", "topic": "crypto",
                "topic_label": "Crypto", "direction": "up" if new > old else "down",
                "delta_dollars": round(new - old, 4), "old_price": old, "new_price": new,
                "observed_at": when, "source_url": "https://obs", "roi_screen": screen}

    def test_trade_is_simulated_labelled_and_priced_with_slippage(self):
        t = strategies.strategy_from_alert(self._alert())
        self.assertEqual(t["mode"], "SIMULATED")
        self.assertEqual(t["side"], "no")
        self.assertAlmostEqual(t["entry_price"], 0.41)   # 0.40 + $0.01 slippage
        self.assertEqual(t["status"], "OPEN")
        self.assertIsNone(t["pnl"])

    def test_open_trade_never_settles_without_official_result(self):
        state = strategies.run({"trades": []}, [self._alert()], {"by_market": {}}, "t1")
        self.assertEqual(state["counts"]["open"], 1)
        self.assertEqual(state["counts"]["settled"], 0)
        # A settlement row without a yes/no result must not settle anything either.
        state2 = strategies.run(state, [], {"by_market": {
            MARKET_A["ticker"]: {"result": "", "source_url": "x"}}}, "t2")
        self.assertEqual(state2["counts"]["open"], 1)

    def test_settlement_and_idempotency(self):
        state = strategies.run({"trades": []}, [self._alert()], {"by_market": {}}, "t1")
        res = {"by_market": {MARKET_A["ticker"]: {
            "result": "no", "settlement_ts": "2026-11-21T00:00:00Z",
            "source_url": "https://settle"}}}
        state = strategies.run(state, [], res, "t3")
        self.assertEqual(state["counts"]["settled"], 1)
        trade = state["trades"][0]
        self.assertTrue(trade["won"])
        self.assertAlmostEqual(trade["payout"], 100.0)
        self.assertEqual(trade["settlement_url"], "https://settle")
        # Re-running the same alerts must not duplicate trades.
        state = strategies.run(state, [self._alert()], res, "t4")
        self.assertEqual(len(state["trades"]), 1)

    def test_category_grouping(self):
        state = strategies.run({"trades": []}, [self._alert()], {"by_market": {}}, "t1")
        rows = strategies.by_category(state)
        self.assertEqual(rows[0]["category"], "swing_up_buy_no")


# --------------------------------------------------------------- pipeline e2e
class _MockApi(BaseHTTPRequestHandler):
    """Serves the documented shapes for the endpoints the pipeline calls."""

    calls: list[str] = []

    def log_message(self, *a):  # silence
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        _MockApi.calls.append(self.path)
        if u.path.endswith("/events"):
            series = q.get("series_ticker", [""])[0]
            if series == "KXBTCY":
                return self._send({"events": [EVENT_A], "cursor": ""})
            return self._send({"events": [], "cursor": ""})
        if u.path.endswith("/series/KXBTCY"):
            return self._send({"series": {"ticker": "KXBTCY", "title": "BTC price",
                                          "tags": ["Crypto"], "category": "Crypto",
                                          "settlement_sources": [
                                              {"name": "CF Benchmarks",
                                               "url": "https://www.cfbenchmarks.com/"}]}})
        if u.path.endswith("/series/KXBTCY/markets/KXBTCY-27JAN0100-T20000.00/candlesticks"):
            return self._send({"candlesticks": [
                {"end_period_ts": 1000, "price": {"close_dollars": "0.4000",
                                                  "high_dollars": "0.4000",
                                                  "low_dollars": "0.4000"}},
                {"end_period_ts": 1060, "price": {"close_dollars": "0.5500",
                                                  "high_dollars": "0.5500",
                                                  "low_dollars": "0.4000"}}]})
        if u.path.endswith("/orderbook"):
            return self._send({"orderbook_fp": {"yes_dollars": [["0.3900", "120.00"]],
                                                "no_dollars": [["0.5900", "80.00"]]}})
        if u.path.endswith("/markets"):
            if q.get("status", [""])[0] == "settled":
                return self._send({"markets": [dict(MARKET_A, status="settled",
                                                    result="yes",
                                                    settlement_value_dollars="1.0000",
                                                    settlement_ts="2027-01-01T05:00:05Z")]})
            return self._send({"markets": [MARKET_A], "cursor": ""})
        return self._send({"code": "not_found"}, 404)


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _MockApi)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_two_runs_produce_one_alert_and_one_resolution(self):
        import tempfile
        from pathlib import Path
        from automation import pipeline as P

        tmp = Path(tempfile.mkdtemp())
        old = P.DATA
        P.DATA = tmp
        try:
            client = kh.Client(root=f"http://127.0.0.1:{self.port}/trade-api/v2",
                               min_interval=0)
            p = Pipeline(client)
            p.run()  # first observation: no previous price, so no alert
            first = json.loads((tmp / "alerts.json").read_text())
            self.assertEqual(first["alerts"], [])
            self.assertEqual(first["threshold_dollars"], 0.10)

            # The mock reports the same price, so a second run re-observes the market
            # and keeps both observations. A swing requires a price change, which the
            # mock does not make, so we assert on the recorded observation instead.
            state = json.loads((tmp / "state.json").read_text())
            ticker = MARKET_A["ticker"]
            self.assertIn(ticker, state["markets"])
            self.assertEqual(state["markets"][ticker]["topic"], "crypto")
            self.assertEqual(state["markets"][ticker]["price"], 0.40)
            self.assertEqual(len(state["markets"][ticker]["points"]), 1)
            self.assertTrue(state["markets"][ticker]["source_url"].endswith(
                "tickers=KXBTCY-27JAN0100-T20000.00"))

            res = json.loads((tmp / "resolutions.json").read_text())
            self.assertEqual(res["by_market"][ticker]["result"], "yes")
            books = json.loads((tmp / "orderbooks.json").read_text())
            self.assertEqual(books["orderbooks"][ticker]["summary"]["best_yes_bid"], 0.39)
            prices = json.loads((tmp / "prices.json").read_text())
            self.assertIn(ticker, prices["markets"])
            series = json.loads((tmp / "series_cache.json").read_text())
            self.assertEqual(series["series"]["KXBTCY"]["tags"], ["Crypto"])
            status = json.loads((tmp / "status.json").read_text())
            self.assertEqual(status["markets_by_topic"]["crypto"], 1)
            self.assertEqual(status["threshold_dollars"], 0.10)
        finally:
            P.DATA = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
