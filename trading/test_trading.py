"""Offline tests for the trading module against a local mock of the demo API.

Verifies (per official docs.kalshi.com):
- signed-request message format {timestamp}{METHOD}{path-without-query} and that the
  signature verifies with the Ed25519 public key (quick_start_authenticated_requests.md);
- POST /portfolio/events/orders payload shape (quick_start_create_order.md);
- balance cents -> dollars conversion; settle PnL arithmetic ($1 payout per winning
  contract per market_settlement.md);
- trade classification rules.

Run: /path/to/python trading/test_trading.py  (needs `cryptography`)
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "collector"))

import kalshi_trade as T  # noqa: E402
import strategies as S  # noqa: E402
from kalshi_api import KalshiClient  # noqa: E402

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MARKETS = {
    "KXBTCD-26DEC31-T100000": {
        "market": {"ticker": "KXBTCD-26DEC31-T100000", "event_ticker": "KXBTCD-26DEC31",
                   "title": "Bitcoin above $100K on December 31?", "status": "active",
                   "result": "", "last_price_dollars": "0.6000", "volume_fp": "5000.00"},
    },
    "KXGAS-OLD-1-M1": {
        "market": {"ticker": "KXGAS-OLD-1-M1", "event_ticker": "KXGAS-OLD-1",
                   "title": "Old gas price event", "status": "settled", "result": "yes",
                   "last_price_dollars": "0.5500"},
    },
}
PLACED_ORDER = {"order_id": "ord-123", "remaining_count": "5", "status": "resting"}


class MockAuthedAPI(BaseHTTPRequestHandler):
    seen = {}  # class-level capture for assertions

    def log_message(self, *args):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p.startswith("/trade-api/v2/"):
            p = p[len("/trade-api/v2"):]
        if p == "/portfolio/balance":
            self._json({"balance": "1000000"})
        elif p == "/portfolio/positions":
            self._json({"market_positions": [
                {"ticker": "KXBTCD-26DEC31-T100000", "position": "10",
                 "unrealized_pnl": "150", "realized_pnl": "0"}]})
        elif p == "/portfolio/fills":
            self._json({"fills": [{"fill_id": "f1", "ticker": "KXBTCD-26DEC31-T100000"}]})
        elif p == "/portfolio/orders":
            self._json({"orders": [{"order_id": "ord-123", "status": "resting"}]})
        elif p.startswith("/markets/"):
            ticker = p.rsplit("/", 1)[-1]
            self._json(MARKETS.get(ticker, {"market": {"ticker": ticker}}))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        if p.startswith("/trade-api/v2/"):
            p = p[len("/trade-api/v2"):]
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        MockAuthedAPI.seen["post_path"] = p
        MockAuthedAPI.seen["post_body"] = body
        MockAuthedAPI.seen["auth_headers"] = {k.upper(): v for k, v in self.headers.items()
                                              if k.lower().startswith("kalshi-")}
        self.send_response(201)
        self._json(PLACED_ORDER)

    def _json(self, payload):
        b = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


class TradingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_dir = tempfile.mkdtemp(prefix="kalshi-trade-")
        T.DATA_DIR = cls.data_dir
        cls.key = Ed25519PrivateKey.generate()
        cls.pub = cls.key.public_key()
        os.environ["KALSHI_DEMO_API_KEY_ID"] = "test-key-id"
        os.environ["KALSHI_DEMO_PRIVATE_KEY"] = cls.key.private_bytes_raw().hex()  # not used
        # properly: use PEM via client.load_private_key path
        from cryptography.hazmat.primitives import serialization
        pem = cls.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode()
        os.environ["KALSHI_DEMO_PRIVATE_KEY"] = pem

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockAuthedAPI)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}/trade-api/v2"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        os.environ.pop("KALSHI_DEMO_API_KEY_ID", None)
        os.environ.pop("KALSHI_DEMO_PRIVATE_KEY", None)

    def _client(self) -> KalshiClient:
        client = KalshiClient(root=self.base, min_interval=0.0, retries=1)
        client.load_private_key(os.environ["KALSHI_DEMO_PRIVATE_KEY"])
        return client

    def _verify_signed_headers(self, method: str, path_with_query: str):
        headers = MockAuthedAPI.seen["auth_headers"]
        ts = headers.get("KALSHI-ACCESS-TIMESTAMP")
        sig = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
        sign_path = urlparse(path_with_query).path
        message = f"{ts}{method}{sign_path}".encode()
        self.pub.verify(sig, message)  # raises on mismatch
        self.assertEqual(headers.get("KALSHI-ACCESS-KEY"), "test-key-id")
        self.assertTrue(len(ts) >= 13)  # milliseconds

    def test_missing_credentials_exits_3(self):
        os.environ.pop("KALSHI_DEMO_API_KEY_ID", None)
        try:
            rc = T.main(["portfolio"])
            self.assertEqual(rc, T.EXIT_NO_CREDS)
        finally:
            os.environ["KALSHI_DEMO_API_KEY_ID"] = "test-key-id"

    def test_portfolio_snapshot(self):
        client = self._client()
        portfolio = T.cmd_portfolio(client, self.data_dir)
        self.assertEqual(portfolio["account"]["balance_dollars"], 10000.0)
        self.assertEqual(portfolio["position_count"], 1)
        self.assertEqual(portfolio["fills_count"], 1)
        with open(os.path.join(self.data_dir, "portfolio.json")) as fh:
            on_disk = json.load(fh)
        self.assertEqual(on_disk["account"]["balance_dollars"], 10000.0)

    def test_trade_live_order_payload_and_classification(self):
        client = self._client()
        rec = T.cmd_trade(client, self.data_dir, "KXBTCD-26DEC31-T100000",
                          "buy", "yes", 10, 0.62, "limit", "directional", "crypto",
                          dry_run=False)
        body = MockAuthedAPI.seen["post_body"]
        self.assertEqual(MockAuthedAPI.seen["post_path"], "/portfolio/events/orders")
        self.assertEqual(body["side"], "bid")
        self.assertEqual(body["count"], "10")
        self.assertEqual(body["price"], "0.6200")
        self.assertEqual(body["time_in_force"], "good_till_canceled")
        self.assertEqual(body["self_trade_prevention_type"], "taker_at_cross")
        self.assertIn("client_order_id", body)
        self.assertEqual(rec["order_id"], "ord-123")
        self.assertEqual(rec["classification"]["structure"], "directional_favorite")
        self.assertEqual(rec["classification"]["entry_vs_last"], 0.02)
        self._verify_signed_headers("POST", "/trade-api/v2/portfolio/events/orders")

    def test_trade_sell_no_maps_to_ask(self):
        client = self._client()
        T.cmd_trade(client, self.data_dir, "KXBTCD-26DEC31-T100000",
                    "sell", "no", 3, 0.42, "limit", "fade", "crypto", dry_run=True)
        # dry run does not hit the API; verify via a live sell to capture payload
        T.cmd_trade(client, self.data_dir, "KXBTCD-26DEC31-T100000",
                    "sell", "no", 3, 0.42, "limit", "fade", "crypto", dry_run=False)
        self.assertEqual(MockAuthedAPI.seen["post_body"]["side"], "ask")

    def test_settle_realizes_pnl(self):
        client = self._client()
        T.cmd_trade(client, self.data_dir, "KXGAS-OLD-1-M1",
                    "buy", "yes", 10, 0.55, "limit", "directional", "gas", dry_run=False)
        trades = T.cmd_settle(client, self.data_dir)
        rec = [t for t in trades["trades"] if t["ticker"] == "KXGAS-OLD-1-M1"][-1]
        self.assertEqual(rec["result"], "yes")
        self.assertEqual(rec["outcome"], "win")
        self.assertEqual(rec["realized_pnl_dollars"], 4.5)  # (1 - 0.55) * 10

    def test_settle_loss_case(self):
        client = self._client()
        # simulate a losing market by pointing at ticker with settled no
        MARKETS["KXGAS-OLD-1-M1"]["market"]["result"] = "no"
        T.cmd_trade(client, self.data_dir, "KXGAS-OLD-1-M1",
                    "buy", "yes", 10, 0.55, "limit", "directional", "gas", dry_run=False)
        trades = T.cmd_settle(client, self.data_dir)
        rec = [t for t in trades["trades"] if t["ticker"] == "KXGAS-OLD-1-M1"][-1]
        self.assertEqual(rec["realized_pnl_dollars"], -5.5)
        MARKETS["KXGAS-OLD-1-M1"]["market"]["result"] = "yes"

    def test_summary_aggregates_by_topic_and_structure(self):
        client = self._client()
        trades = T.cmd_settle(client, self.data_dir)
        summary = T.summarize(trades["trades"])
        self.assertGreater(summary["settled_trades"], 0)
        self.assertIn("gas", summary["by_topic"])
        self.assertIn("directional_coinflip", summary["by_structure"])

    def test_strategy_classification_rules(self):
        self.assertEqual(S.classify_trade("buy", "yes", 0.95)["structure"], "directional_lock")
        self.assertEqual(S.classify_trade("buy", "yes", 0.30)["structure"], "directional_value")
        self.assertEqual(S.classify_trade("buy", "yes", 0.07)["structure"], "directional_longshot")
        self.assertEqual(S.classify_trade("sell", "yes", 0.08)["structure"], "fade_longshot")
        self.assertEqual(S.classify_trade("sell", "no", 0.92)["structure"], "fade_lock")

    def test_strategy_library_covers_all_topics(self):
        for topic in ("gas", "elections", "culture", "crypto", "golf"):
            self.assertTrue(S.strategy_suggestions(topic), topic)
        self.assertEqual(len(S.strategy_suggestions(None)), len(S.STRATEGY_LIBRARY))


if __name__ == "__main__":
    unittest.main(verbosity=2)
