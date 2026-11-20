#!/usr/bin/env python3
"""Offline tests for scripts/price_alerts.py (session 6d201d19). Run: python3 scripts/tests/test_price_alerts.py"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import price_alerts as pa  # noqa: E402


def row(ticker, ts, price, vol="10.00", topic="elections"):
    return {"ticker": ticker, "ts": ts, "last_price_dollars": price, "volume_fp": vol, "topic": topic}


class DetectSwings(unittest.TestCase):
    def test_threshold_is_inclusive_at_exactly_0_10(self):
        a = pa.detect_swings([row("T-A", "t1", "0.3500"), row("T-A", "t2", "0.4500")])
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["delta_dollars"], "+0.1000")
        self.assertEqual(a[0]["direction"], "up")

    def test_just_under_threshold_is_not_an_alert(self):
        self.assertEqual(pa.detect_swings([row("T-A", "t1", "0.3500"), row("T-A", "t2", "0.4499")]), [])

    def test_downward_swing_detected(self):
        a = pa.detect_swings([row("T-A", "t1", "0.5500"), row("T-A", "t2", "0.4000")])
        self.assertEqual(a[0]["direction"], "down")
        self.assertEqual(a[0]["delta_dollars"], "-0.1500")

    def test_single_print_is_flagged_when_next_reading_reverts(self):
        a = pa.detect_swings([row("T-A", "t1", "0.0040"), row("T-A", "t2", "0.8110"), row("T-A", "t3", "0.0030")])
        self.assertEqual(len(a), 2)  # the up print and the snap-back down move are both swings
        self.assertEqual(a[0]["direction"], "up")
        self.assertTrue(a[0]["reverted_next_reading"])
        self.assertEqual(a[0]["next_reading_dollars"], "0.0030")
        self.assertFalse(a[1]["reverted_next_reading"])  # nothing after the last reading

    def test_sustained_move_is_not_flagged_as_reverted(self):
        a = pa.detect_swings([row("T-A", "t1", "0.2000"), row("T-A", "t2", "0.4000"), row("T-A", "t3", "0.4200")])
        self.assertFalse(a[0]["reverted_next_reading"])

    def test_no_next_reading_means_not_reverted_and_blank_next(self):
        a = pa.detect_swings([row("T-A", "t1", "0.2000"), row("T-A", "t2", "0.4000")])
        self.assertFalse(a[0]["reverted_next_reading"])
        self.assertEqual(a[0]["next_reading_dollars"], "")

    def test_bid_ask_carried_from_the_swing_reading(self):
        r2 = row("T-A", "t2", "0.8110"); r2["yes_bid_dollars"] = "0.0020"; r2["yes_ask_dollars"] = "0.8110"
        a = pa.detect_swings([row("T-A", "t1", "0.0040"), r2])
        self.assertEqual((a[0]["to_bid_dollars"], a[0]["to_ask_dollars"]), ("0.0020", "0.8110"))

    def test_first_sample_only_sets_baseline(self):
        self.assertEqual(pa.detect_swings([row("T-A", "t1", "0.9000")]), [])

    def test_no_float_drift_on_decimal_strings(self):
        a = pa.detect_swings([row("T-A", "t1", "0.5500"), row("T-A", "t2", "0.6500")])
        self.assertEqual(len(a), 1)

    def test_tickers_are_compared_independently(self):
        rows = [row("T-A", "t1", "0.20"), row("T-B", "t1", "0.20"), row("T-A", "t2", "0.20"), row("T-B", "t2", "0.45")]
        a = pa.detect_swings(rows)
        self.assertEqual([x["ticker"] for x in a], ["T-B"])

    def test_source_url_is_exact_official_request(self):
        a = pa.detect_swings([row("KX-1", "t1", "0.20"), row("KX-1", "t2", "0.35")])
        self.assertEqual(a[0]["source_url"], f"{pa.DEMO}/markets?tickers=KX-1")

    def test_cause_fields_are_never_inferred(self):
        a = pa.detect_swings([row("KX-1", "t1", "0.20"), row("KX-1", "t2", "0.35")])
        self.assertEqual(a[0]["cause_link"], "")
        self.assertEqual(a[0]["cause_status"], "unverified - not inferred")

    def test_titles_come_only_from_supplied_lookup(self):
        a = pa.detect_swings([row("KX-1", "t1", "0.20"), row("KX-1", "t2", "0.35")])
        self.assertEqual(a[0]["title"], "")
        b = pa.detect_swings([row("KX-1", "t1", "0.20"), row("KX-1", "t2", "0.35")],
                             {"KX-1": {"title": "Example?", "event_ticker": "KX-E"}})
        self.assertEqual(b[0]["title"], "Example?")
        self.assertEqual(b[0]["event_ticker"], "KX-E")


class RoiScreen(unittest.TestCase):
    def test_up_move_buys_yes_at_new_price(self):
        ok, side, bought, mult = pa.roi_screen(pa.dec("0.2000"), pa.dec("5"), "KX-1", +1)
        self.assertEqual((ok, side, str(bought)), (True, "YES", "0.2000"))
        self.assertEqual(str(mult), "4.0000")

    def test_down_move_buys_no_at_complement(self):
        ok, side, bought, mult = pa.roi_screen(pa.dec("0.3000"), pa.dec("5"), "KX-1", -1)
        self.assertEqual((side, str(bought)), ("NO", "0.7000"))
        self.assertFalse(ok)  # 0.3/0.7 = 0.4286 < 1.00

    def test_multiple_at_or_above_one_passes(self):
        ok, *_ = pa.roi_screen(pa.dec("0.5000"), pa.dec("5"), "KX-1", +1)
        self.assertTrue(ok)  # (1-0.5)/0.5 = 1.00 exactly

    def test_zero_volume_fails(self):
        ok, *_ = pa.roi_screen(pa.dec("0.2000"), pa.dec("0"), "KX-1", +1)
        self.assertFalse(ok)

    def test_synthetic_series_never_passes(self):
        ok, *_ = pa.roi_screen(pa.dec("0.2000"), pa.dec("5"), "KXDEMOFUTHOURLY-26NOV20H12-UP", +1)
        self.assertFalse(ok)

    def test_out_of_range_price_fails(self):
        ok, side, *_ = pa.roi_screen(pa.dec("1.0000"), pa.dec("5"), "KX-1", +1)
        self.assertFalse(ok)
        self.assertIsNone(side)


if __name__ == "__main__":
    unittest.main(verbosity=2)
