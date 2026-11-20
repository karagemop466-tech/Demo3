#!/usr/bin/env python3
"""Offline tests for the swing + catalyst layer (no network access required).

Run:  python3 catalysts/tests/test_scan.py -v
      (also wired into .github/workflows/catalysts.yml and the repo Checks job)

A local mock HTTP server stands in for the demo API and for a news feed, so the
tests exercise the real code paths (urllib, XML parsing, decimal comparisons)
without depending on either service being reachable.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

import scan  # noqa: E402

T0 = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def tape_row(ticker, dt, price, **kw):
    row = {"ticker": ticker, "ts": iso(dt), "last_price_dollars": f"{Decimal(price):.4f}",
           "topic": kw.pop("topic", "crypto"), "event_ticker": kw.pop("event", ""),
           "series_ticker": kw.pop("series", ""), "price_field": "last_price_dollars"}
    row.update(kw)
    return row


class MockServer(HTTPServer):
    """Serves the endpoints scan.py calls; records every request path."""

    def __init__(self, handler_cls):
        super().__init__(("127.0.0.1", 0), handler_cls)
        self.port = self.server_address[1]
        self.hits = []


def start_server(handler_cls):
    srv = MockServer(handler_cls)
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    th.start()
    return srv


# --------------------------------------------------------------------- unit tests
class DecimalSwingTests(unittest.TestCase):
    def test_threshold_is_inclusive_at_ten_cents(self):
        rows = [tape_row("T-1", T0, "0.2000"), tape_row("T-1", T0 + timedelta(minutes=5), "0.3000")]
        out = scan.detect_swings(rows, Decimal("0.10"), 0, T0 + timedelta(hours=1), set())
        self.assertEqual(len(out), 1, "exactly $0.10 must alert (>= threshold)")
        self.assertEqual(out[0]["direction"], "up")
        self.assertEqual(out[0]["delta_dollars"], "0.1000")

    def test_below_threshold_is_ignored(self):
        rows = [tape_row("T-1", T0, "0.2000"), tape_row("T-1", T0 + timedelta(minutes=5), "0.2999")]
        out = scan.detect_swings(rows, Decimal("0.10"), 0, T0 + timedelta(hours=1), set())
        self.assertEqual(out, [])

    def test_downward_move_also_alerts(self):
        rows = [tape_row("T-1", T0, "0.8500"), tape_row("T-1", T0 + timedelta(minutes=2), "0.7200")]
        out = scan.detect_swings(rows, Decimal("0.10"), 0, T0 + timedelta(hours=1), set())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["direction"], "down")
        self.assertEqual(out[0]["delta_dollars"], "-0.1300")

    def test_no_float_drift_across_many_ticks(self):
        # 0.1 + 0.2 style traps: 200 alternating cents must stay exact.
        rows, price = [], Decimal("0.0100")
        for i in range(200):
            rows.append(tape_row("T-2", T0 + timedelta(seconds=10 * i), price))
            price += Decimal("0.0100")
        out = scan.detect_swings(rows, Decimal("0.10"), 0, T0 + timedelta(hours=1), set())
        self.assertEqual(out, [], "1-cent steps must never trip a 10-cent alert")

    def test_swing_is_per_ticker_not_across_tickers(self):
        rows = [tape_row("A", T0, "0.1000"), tape_row("B", T0 + timedelta(minutes=1), "0.9000")]
        out = scan.detect_swings(rows, Decimal("0.10"), 0, T0 + timedelta(hours=1), set())
        self.assertEqual(out, [])

    def test_lookback_window_drops_old_swings(self):
        rows = [tape_row("T-1", T0, "0.2000"), tape_row("T-1", T0 + timedelta(minutes=5), "0.4000")]
        old = scan.detect_swings(rows, Decimal("0.10"), 1, T0 + timedelta(hours=5), set())
        self.assertEqual(old, [], "outside the lookback window the row is not re-published")

    def test_known_ids_are_not_republished(self):
        rows = [tape_row("T-1", T0, "0.2000"), tape_row("T-1", T0 + timedelta(minutes=5), "0.4000")]
        first = scan.detect_swings(rows, Decimal("0.10"), 0, T0 + timedelta(hours=1), set())
        again = scan.detect_swings(rows, Decimal("0.10"), 0, T0 + timedelta(hours=1),
                                   {first[0]["id"]})
        self.assertEqual(again, [], "a run must not duplicate an already-published alert")

    def test_missing_or_garbage_prices_are_skipped(self):
        rows = [{"ticker": "X", "ts": iso(T0), "last_price_dollars": ""},
                {"ticker": "X", "ts": iso(T0 + timedelta(minutes=1)), "last_price_dollars": "0.9"},
                {"ticker": "Y", "ts": "not-a-date", "last_price_dollars": "0.5"},
                {"ticker": "Y", "ts": iso(T0), "last_price_dollars": "n/a"}]
        out = scan.detect_swings(rows, Decimal("0.10"), 0, T0 + timedelta(hours=1), set())
        self.assertEqual(out, [], "absent/garbage samples produce nothing rather than a guess")


class FieldParsingTests(unittest.TestCase):
    def test_prefers_fixed_point_dollars_field(self):
        price, field = scan.market_price({"last_price_dollars": "0.6500", "last_price": 65})
        self.assertEqual((str(price), field), ("0.6500", "last_price_dollars"))

    def test_falls_back_to_legacy_cents_and_labels_it(self):
        price, field = scan.market_price({"last_price": 12})
        self.assertEqual(str(price), "0.1200")
        self.assertIn("cents", field, "the field used must be disclosed, never assumed")

    def test_no_price_no_value(self):
        self.assertEqual(scan.market_price({}), (None, None))

    def test_bad_dollar_string_returns_none_not_zero(self):
        self.assertIsNone(scan.parse_dollars("abc"))
        self.assertIsNone(scan.parse_dollars(""))


class CatalystMatchingTests(unittest.TestCase):
    ITEMS = [
        {"title": "Bitcoin jumps after ETF inflations data", "link": "https://ex.com/a",
         "published_ts": iso(T0 - timedelta(minutes=30)), "feed_name": "F", "feed_url": "u"},
        {"title": "Local cat wins best in show", "link": "https://ex.com/b",
         "published_ts": iso(T0 - timedelta(minutes=5)), "feed_name": "F", "feed_url": "u"},
        {"title": "Ethereum slides as bitcoin ETF flows turn positive", "link": "https://ex.com/c",
         "published_ts": iso(T0 + timedelta(minutes=400)), "feed_name": "F", "feed_url": "u"},
    ]

    def test_window_and_keyword_overlap(self):
        res = scan.match_catalyst_items(self.ITEMS, "Bitcoin price on Nov 20? BTC ETF flows",
                                       T0 - timedelta(minutes=10), T0, 180, 60, 3)
        self.assertEqual(res["match_status"], "matched")
        self.assertEqual(len(res["candidates"]), 1)
        got = res["candidates"][0]
        self.assertEqual(got["link"], "https://ex.com/a")
        self.assertTrue(got["in_window_before_swing"])
        self.assertIn("bitcoin", got["matched_keywords"])

    def test_item_outside_window_is_not_used(self):
        res = scan.match_catalyst_items(self.ITEMS, "Ethereum bitcoin ETF flows",
                                       T0 - timedelta(minutes=10), T0, 0, 0, 3)
        self.assertNotIn("https://ex.com/c", [c["link"] for c in res["candidates"]])

    def test_no_overlap_is_reported_as_blank_not_invented(self):
        res = scan.match_catalyst_items(self.ITEMS, "Solana solana", T0 - timedelta(minutes=10),
                                       T0, 180, 60, 3)
        self.assertEqual(res["candidates"], [])
        self.assertEqual(res["match_status"], "items_in_window_but_no_keyword_overlap")

    def test_empty_feed_list_reports_that(self):
        res = scan.match_catalyst_items([], "Bitcoin price", T0, T0, 10, 10, 3)
        self.assertEqual(res["match_status"], "no_feed_item_in_window")
        self.assertEqual(res["items_in_window"], 0)

    def test_items_without_timestamp_are_never_matched(self):
        items = [{"title": "Bitcoin ETF flows", "link": "https://ex.com/x",
                  "published_ts": "", "feed_name": "F", "feed_url": "u"}]
        res = scan.match_catalyst_items(items, "Bitcoin ETF flows", T0 - timedelta(hours=1),
                                       T0, 180, 60, 3)
        self.assertEqual(res["candidates"], [], "undated items cannot be placed in a window")


class FeedParsingTests(unittest.TestCase):
    RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Mock</title>
<item><title>Bitcoin rockets on ETF news</title><link>https://ex.com/one</link>
<pubDate>Fri, 20 Nov 2026 11:30:00 GMT</pubDate></item>
<item><title>Unrelated</title><link>https://ex.com/two</link></item>
</channel></rss>"""
    ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<title>Oil prices fall</title><link href="https://ex.com/atom"/>
<updated>2026-11-20T11:00:00Z</updated></entry></feed>"""

    def test_rss_items_parsed_with_timestamps(self):
        items = scan.parse_feed(self.RSS, {"name": "Mock", "url": "u"})
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Bitcoin rockets on ETF news")
        self.assertEqual(items[0]["published_ts"], "2026-11-20T11:30:00Z")

    def test_cdata_and_tags_are_stripped(self):
        xml = ('<?xml version="1.0"?><rss><channel><item>'
               '<title><![CDATA[<b>Gas</b> prices rise]]></title>'
               '<link>https://ex.com/g</link></item></channel></rss>')
        items = scan.parse_feed(xml, {"name": "M", "url": "u"})
        self.assertEqual(items[0]["title"], "Gas prices rise")

    def test_atom_entries_parsed(self):
        items = scan.parse_feed(self.ATOM, {"name": "Mock", "url": "u"})
        self.assertEqual(items[0]["link"], "https://ex.com/atom")
        self.assertEqual(items[0]["published_ts"], "2026-11-20T11:00:00Z")

    def test_broken_xml_yields_no_items(self):
        self.assertEqual(scan.parse_feed("<rss><channel>", {"name": "M", "url": "u"}), [])

    def test_feed_config_is_probe_gated(self):
        cfg = json.load(open(os.path.join(scan.HERE, "feeds.json"), encoding="utf-8"))
        self.assertTrue(cfg["feeds"], "allowlist must not be empty")
        for f in cfg["feeds"]:
            self.assertTrue(f.get("url", "").startswith("https://"), "https only")
            if f.get("enabled", True):
                self.assertEqual(f.get("status"), "pending_ci_probe",
                                 f"{f['name']}: no feed may claim verification it has not earned")


class SeriesDerivationTests(unittest.TestCase):
    def test_series_key_is_only_a_lookup_key(self):
        self.assertEqual(scan.derive_series("KXDEMOFUTHOURLY-26NOV20H12"), "KXDEMOFUTHOURLY")
        self.assertEqual(scan.derive_series("NODASH"), "")
        self.assertEqual(scan.derive_series(""), "")

    def test_classify_covers_the_five_topics(self):
        cases = [({"series_ticker": "KXAAAGASM"}, "gas"),
                 ({"series_ticker": "KXPRESNOMD"}, "elections"),
                 ({"series_ticker": "KXBTCD"}, "crypto"),
                 ({"series_ticker": "KXPGATOUR"}, "golf"),
                 ({"series_ticker": "KXOSCARBESTPIC", "category": "Culture"}, "culture")]
        for market, want in cases:
            self.assertEqual(scan.classify(market), want, market)


class EnrichTests(unittest.TestCase):
    def test_resolved_market_stops_tracking(self):
        s = {"ticker": "M-1", "from": {"ts": iso(T0)}, "to": {"ts": iso(T0)},
             "topic": "crypto"}
        mkt = {"ticker": "M-1", "title": "Demo BTC", "status": "finalized", "result": "no",
               "event_ticker": "E-1", "series_ticker": "S-1",
               "_single_source_url": "https://x/markets/M-1"}
        scan.enrich(s, mkt, None, "https://x")
        self.assertTrue(s["resolved"])
        self.assertEqual(s["tracking"], "stopped_resolved")
        self.assertEqual(s["resolution_label"], "NO")
        self.assertEqual(s["links"]["market_api_url"], "https://x/markets/M-1")

    def test_open_market_keeps_tracking(self):
        s = {"ticker": "M-2", "from": {"ts": iso(T0)}, "to": {"ts": iso(T0)}, "topic": "gas"}
        scan.enrich(s, {"ticker": "M-2", "status": "active", "result": "",
                        "event_ticker": "E-2"}, None, "https://x")
        self.assertFalse(s["resolved"])
        self.assertEqual(s["tracking"], "active")
        self.assertEqual(s["resolution_label"], "")

    def test_missing_market_record_stays_blank(self):
        s = {"ticker": "M-3", "from": {"ts": iso(T0)}, "to": {"ts": iso(T0)}, "topic": "other"}
        scan.enrich(s, None, None, "https://x")
        self.assertEqual(s["status"], "")
        self.assertEqual(s["result"], "")
        self.assertEqual(s["title"], "")
        self.assertEqual(s["title_source"], "blank_no_market_record")


class TapeTests(unittest.TestCase):
    def test_append_and_dedupe_and_trim(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tape.jsonl")
            rows = [tape_row("A", T0, "0.10"), tape_row("A", T0 + timedelta(minutes=1), "0.25")]
            self.assertEqual(scan.append_tape(path, rows), 2)
            again = scan.load_tape([path])
            self.assertEqual(len(again), 2)
            scan.append_tape(path, [rows[0]])          # duplicate row
            self.assertEqual(len(scan.load_tape([path])), 2, "duplicate samples are dropped")

    def test_load_tape_skips_unusable_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.jsonl")
            with open(path, "w") as fh:
                fh.write("{bad json\n")
                fh.write(json.dumps(tape_row("A", T0, "0.30")) + "\n")
                fh.write(json.dumps({"ticker": "A", "ts": iso(T0)}) + "\n")   # no price
            rows = scan.load_tape([path])
            self.assertEqual(len(rows), 1)


class HttpLayerTests(unittest.TestCase):
    """End-to-end against a mock demo API + mock feed."""

    @staticmethod
    def make_handler(markets, feed_items):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):            # silence
                pass

            def do_GET(self):                     # noqa: N802
                path = self.path
                self.server.hits.append(path)
                if path.startswith("/exchange/status"):
                    body, ctype = json.dumps({"exchange_active": True}), "application/json"
                elif path.startswith("/markets"):
                    body = json.dumps({"markets": markets, "cursor": ""})
                    ctype = "application/json"
                elif path.startswith("/series"):
                    body = json.dumps({"series": {
                        "ticker": "KXMOCK", "title": "Mock series", "category": "Crypto",
                        "frequency": "hourly", "contract_terms_url": "https://terms.example",
                        "settlement_sources": [{"name": "Mock Index",
                                                "url": "https://index.example/data"}]}})
                    ctype = "application/json"
                elif path.endswith(".xml"):
                    items = "".join(
                        f"<item><title>{i['title']}</title><link>{i['link']}</link>"
                        f"<pubDate>{i['rfc822']}</pubDate></item>" for i in feed_items)
                    body = f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'
                    ctype = "application/rss+xml"
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        return H

    def test_live_run_detects_swing_and_attaches_catalyst(self):
        swing_mkt = {
            "ticker": "KXMOCK-26NOV2012-A", "event_ticker": "KXMOCK-26NOV2012",
            "series_ticker": "KXMOCK", "title": "Bitcoin above 100k at noon?",
            "status": "active", "result": "", "last_price_dollars": "0.8000",
            "volume_fp": "1500.00", "open_interest_fp": "900.00", "close_time": "",
            "settlement_ts": "", "settlement_value_dollars": "",
        }
        now = datetime.now(timezone.utc)
        # a fresh sample is written by the run, so yesterday's tape row would fall
        # outside the lookback window; keep the baseline just minutes old.
        prior = tape_row("KXMOCK-26NOV2012-A", now - timedelta(minutes=6), "0.6500",
                         event="KXMOCK-26NOV2012", series="KXMOCK")
        feed_item = {"title": "Bitcoin rallies past 100k as ETF inflows surge",
                     "link": "https://news.example/bitcoin-100k",
                     "rfc822": (now - timedelta(minutes=3)).strftime("%a, %d %b %Y %H:%M:%S GMT")}
        srv = start_server(HttpLayerTests.make_handler([swing_mkt], [feed_item]))
        root = f"http://127.0.0.1:{srv.port}"
        try:
            with tempfile.TemporaryDirectory() as d:
                os.makedirs(os.path.join(d, "data", "history"))
                with open(os.path.join(d, "data", "history", "prices.jsonl"), "w") as fh:
                    fh.write(json.dumps(prior) + "\n")
                feeds = {"feeds": [{"name": "Mock feed", "url": f"{root}/feed.xml",
                                    "topics": ["crypto"], "enabled": True}]}
                feeds_path = os.path.join(d, "feeds.json")
                with open(feeds_path, "w") as fh:
                    json.dump(feeds, fh)
                out_dir = os.path.join(d, "catalysts")
                rc = scan.main(["--root", root, "--repo", d, "--feeds", feeds_path,
                                "--data-dir", out_dir, "--lookback-hours", "6", "--quiet"])
                self.assertEqual(rc, 0)
                out = json.load(open(os.path.join(out_dir, "swings.json")))
                self.assertEqual(len(out["swings"]), 1, out)
                s = out["swings"][0]
                self.assertEqual(s["direction"], "up")
                self.assertEqual(s["abs_delta_dollars"], "0.1500")
                self.assertEqual(s["title"], "Bitcoin above 100k at noon?")
                self.assertEqual(s["links"]["market_api_url"],
                                 f"{root}/markets/KXMOCK-26NOV2012-A")
                self.assertEqual(s["record_source"], "GET /markets?tickers= (demo API, this run)")
                self.assertEqual(s["series"]["settlement_sources"][0]["url"],
                                 "https://index.example/data")
                links = [c["link"] for c in s["catalysts"]]
                self.assertEqual(links, ["https://news.example/bitcoin-100k"],
                                 f"expected the in-window headline; got {s['catalysts']}")
                self.assertIn("bitcoin", s["catalysts"][0]["matched_keywords"])
                status = json.load(open(os.path.join(out_dir, "status.json")))
                self.assertEqual(status["mode"], "live")
                self.assertGreaterEqual(status["requests"], 3)
                self.assertEqual(status["swings_with_catalyst_links"], 1)
                health = json.load(open(os.path.join(out_dir, "feed_health.json")))
                self.assertTrue(health["feeds"][0]["ok"], "probe must confirm the feed")
                self.assertEqual(health["feeds"][0]["items_parsed"], 1)
                # the tape file keeps the new sample for the next run
                tape_rows = open(os.path.join(out_dir, "tape.jsonl")).read().splitlines()
                self.assertEqual(len(tape_rows), 1)
                self.assertEqual(json.loads(tape_rows[0])["ticker"], "KXMOCK-26NOV2012-A")
                # endpoints probe ran in live mode and recorded real statuses
                eps = json.load(open(os.path.join(out_dir, "endpoints.json")))
                self.assertTrue(all(e["http_status"] in (200, 404) for e in eps["endpoints"]))
        finally:
            srv.shutdown()
            threading.Thread(target=srv.server_close, daemon=True).start()

    def test_resolved_market_stops_being_tracked(self):
        swing_mkt = {"ticker": "KXMOCK-26NOV2012-B", "event_ticker": "KXMOCK-26NOV2012",
                     "series_ticker": "KXMOCK", "title": "Bitcoin at noon?",
                     "status": "finalized", "result": "yes",
                     "last_price_dollars": "1.0000", "volume_fp": "10.00",
                     "open_interest_fp": "0.00", "close_time": "2026-11-20T12:00:00Z",
                     "settlement_ts": "2026-11-20T12:01:00Z",
                     "settlement_value_dollars": "1.0000"}
        now = datetime.now(timezone.utc)
        prior = tape_row("KXMOCK-26NOV2012-B", now - timedelta(minutes=4), "0.5000",
                         event="KXMOCK-26NOV2012", series="KXMOCK")
        srv = start_server(HttpLayerTests.make_handler([swing_mkt], []))
        root = f"http://127.0.0.1:{srv.port}"
        try:
            with tempfile.TemporaryDirectory() as d:
                os.makedirs(os.path.join(d, "data", "history"))
                with open(os.path.join(d, "data", "history", "prices.jsonl"), "w") as fh:
                    fh.write(json.dumps(prior) + "\n")
                feeds_path = os.path.join(d, "feeds.json")
                with open(feeds_path, "w") as fh:
                    json.dump({"feeds": []}, fh)
                out_dir = os.path.join(d, "catalysts")
                scan.main(["--root", root, "--repo", d, "--feeds", feeds_path,
                           "--data-dir", out_dir, "--lookback-hours", "6", "--quiet"])
                out = json.load(open(os.path.join(out_dir, "swings.json")))
                s = out["swings"][0]
                self.assertTrue(s["resolved"])
                self.assertEqual(s["resolution_label"], "YES")
                self.assertEqual(s["tracking"], "stopped_resolved")
                watch = json.load(open(os.path.join(out_dir, "watch_state.json")))
                self.assertTrue(watch["markets"]["KXMOCK-26NOV2012-B"]["resolved"])
        finally:
            srv.shutdown()
            threading.Thread(target=srv.server_close, daemon=True).start()

    def test_unreachable_api_falls_back_to_offline_without_inventing(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "data", "history"))
            row = tape_row("KXGONE-1", T0, "0.2000")
            row2 = tape_row("KXGONE-1", T0 + timedelta(minutes=1), "0.5500")
            with open(os.path.join(d, "data", "history", "prices.jsonl"), "w") as fh:
                fh.write(json.dumps(row) + "\n" + json.dumps(row2) + "\n")
            feeds_path = os.path.join(d, "feeds.json")
            with open(feeds_path, "w") as fh:
                json.dump({"feeds": []}, fh)
            rc = scan.main(["--root", "http://127.0.0.1:1", "--repo", d, "--feeds", feeds_path,
                            "--offline", "--data-dir", os.path.join(d, "out"), "--quiet",
                            "--lookback-hours", "0"])
            self.assertEqual(rc, 0)
            out = json.load(open(os.path.join(d, "out", "swings.json")))
            self.assertEqual(len(out["swings"]), 1)
            s = out["swings"][0]
            self.assertEqual(s["catalysts"], [])
            self.assertEqual(s["catalyst_match"]["match_status"], "feeds_not_polled_offline")
            self.assertEqual(s["title"], "", "no market record means no title, ever")
            self.assertEqual(s["links"]["market_api_url"],
                             "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXGONE-1")


class StrategyStudyTests(unittest.TestCase):
    """The strategy table may only publish arithmetic that reproduces from stored fields."""

    def swing(self, entry="0.6500", settle="1.0000", topic="crypto", direction="up",
              resolved=True, ticker="KXMOCK-1-A"):
        return {"id": ticker, "ticker": ticker, "topic": topic, "direction": direction,
                "resolved": resolved, "settlement_value_dollars": settle,
                "settlement_ts": "2026-11-20T12:01:19Z" if settle else "",
                "to": {"ts": "2026-11-20T11:58:42Z", "last_price_dollars": entry},
                "links": {"market_api_url":
                          f"{scan.DEMO_REST_ROOT}/markets/{ticker}"}}

    def test_pnl_from_published_fields_only(self):
        out = scan.strategy_study([self.swing()], [])
        row = out["results"][0]
        self.assertEqual(row["strategy"], "s1_hold_to_resolution")
        self.assertEqual(row["n"], 1)
        self.assertEqual(row["wins"], 1)
        self.assertEqual(row["net_pnl_dollars_per_contract"], "0.3500")
        self.assertEqual(row["mean_pnl_dollars_per_contract"], "0.3500")
        self.assertFalse(row["evaluable"], "one trade must never be called a result")
        self.assertEqual(out["trade_count"], 1)

    def test_missing_settlement_value_is_skipped_not_derived(self):
        out = scan.strategy_study([self.swing(settle="")], [])
        self.assertEqual(out["results"], [], "no payout field means no simulated trade")
        self.assertEqual(out["skipped_observations"]["s1_hold_to_resolution"], 1)

    def test_sample_floor_lifts_once_enough_trades_exist(self):
        swings = [self.swing(ticker=f"KXMOCK-1-{i}", settle="1.0000" if i % 2 else "0.0000")
                  for i in range(scan.STRATEGY_MIN_N)]
        out = scan.strategy_study(swings, [])
        row = next(r for r in out["results"] if r["strategy"] == "s1_hold_to_resolution")
        self.assertEqual(row["n"], scan.STRATEGY_MIN_N)
        self.assertTrue(row["evaluable"])
        self.assertEqual(row["wins"] + row["losses"], row["n"])
        net = Decimal(row["net_pnl_dollars_per_contract"])
        self.assertEqual(net / row["n"], Decimal(row["mean_pnl_dollars_per_contract"]))

    def test_flat_exit_uses_next_sample_of_the_same_market(self):
        later = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=1)
        tape = [{"ticker": "KXMOCK-1-A", "ts": iso(later), "last_price_dollars": "0.8000"},
                {"ticker": "OTHER-1", "ts": iso(later), "last_price_dollars": "0.1000"}]
        out = scan.strategy_study([self.swing(resolved=False, settle="")], tape)
        rows = [r for r in out["results"] if r["strategy"] == "s2_flat_at_next_sample"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["net_pnl_dollars_per_contract"], "0.1500")


    def test_portfolio_accumulates_from_the_published_bankroll(self):
        swings = [self.swing(ticker=f"KXMOCK-{i}", settle="1.0000") for i in range(3)]
        out = scan.strategy_study(swings, [])
        book = out["portfolio"]["books"]["s1_hold_to_resolution"]
        from decimal import Decimal
        stake = Decimal("0.6500") * scan.CONTRACTS
        # each win pays (1.00 - entry) x contracts
        per_trade = (Decimal("1.0000") - Decimal("0.6500")) * scan.CONTRACTS
        self.assertEqual(book["n"], 3)
        self.assertEqual(Decimal(book["realized_pnl_dollars"]), per_trade * 3)
        self.assertEqual(Decimal(book["ending_equity_dollars"]),
                         scan.BANKROLL + per_trade * 3)
        self.assertEqual(book["wins"], 3)
        self.assertEqual(book["by_topic"]["crypto"]["n"], 3)
        self.assertEqual(len(book["equity_curve"]), 3)

    def test_duplicate_alerts_on_one_market_do_not_inflate_the_book(self):
        same = [self.swing(ticker="KXMOCK-SAME", settle="1.0000", entry="0.6500"),
                self.swing(ticker="KXMOCK-SAME", settle="1.0000", entry="0.5500")]
        out = scan.strategy_study(same, [])
        book = out["portfolio"]["books"]["s1_hold_to_resolution"]
        self.assertEqual(book["n"], 1, "one position per market per strategy")
        self.assertEqual(book["deduped_duplicates"], 1)
        self.assertEqual(len(out["results"]), 1, "the category count must match the book")


if __name__ == "__main__":
    unittest.main(verbosity=2)
