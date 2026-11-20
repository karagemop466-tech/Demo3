#!/usr/bin/env python3
"""Tests for scripts/scan_swings.py — the data pipeline behind the alert console.

No network is used: the end-to-end case runs the scanner in --offline mode against the
committed collector snapshot into a temp directory. The reference vectors are the same ones
asserted from the browser side in tests/swing_core.test.js, and one case shells out to node
to prove the two implementations agree on identical input.

Run: python3 scripts/tests/test_scan_swings.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import scan_swings as S  # noqa: E402

# Published "General Trading Fees Table" rows, price -> fee for 100 contracts
# https://kalshi.com/docs/kalshi-fee-schedule.pdf
FEE_TABLE = [("0.01", 0.07), ("0.05", 0.34), ("0.10", 0.63), ("0.15", 0.90),
             ("0.20", 1.12), ("0.25", 1.32), ("0.30", 1.47), ("0.35", 1.60),
             ("0.40", 1.68), ("0.45", 1.74), ("0.50", 1.75), ("0.55", 1.74),
             ("0.60", 1.68), ("0.65", 1.60), ("0.70", 1.47), ("0.75", 1.32),
             ("0.80", 1.12), ("0.85", 0.90), ("0.90", 0.63), ("0.95", 0.34),
             ("0.99", 0.07)]

VECTORS = [5000, 5200, 5400, 5600, 5800, 6000, 6100, 7300, 7400, 6500,
           7600, 8700, 6400, 6300, 7200, 6000, 5100, 4000]
EXPECTED = [(5, "up", 5000, 6000, 1000),      # +$0.10 off the window low
            (17, "down", 8700, 4000, 4700)]   # -$0.47 off the window high


def rows_from_vectors(vectors=VECTORS):
    return [{"ts": i * 600, "close": p, "open": p, "high": p, "low": p,
             "yes_bid_close": p - 100, "yes_bid_open": p - 100,
             "yes_ask_close": p + 100, "yes_ask_open": p + 100,
             "volume_fp": 10.0, "open_interest_fp": 100.0}
            for i, p in enumerate(vectors)]


class TestFees(unittest.TestCase):
    def test_fee_table(self):
        """Both legs reproduce Kalshi's published table exactly (integer cent alignment)."""
        for price, expected in FEE_TABLE:
            bits = S.bits(price)
            buy_fee = round(S.buy_cost_dollars(bits, 100) - 100 * (bits / S.BIT), 2)
            sell_fee = round(100 * (bits / S.BIT) - S.sell_proceeds_dollars(bits, 100), 2)
            self.assertEqual(buy_fee, expected, f"buy leg at {price}")
            self.assertEqual(sell_fee, expected, f"sell leg at {price}")

    def test_model_fee_matches_formula(self):
        for price in ("0.10", "0.37", "0.50", "0.80"):
            bits = S.bits(price)
            p = bits / S.BIT
            self.assertAlmostEqual(S._model_fee(bits, 100), 0.07 * 100 * p * (1 - p), places=9)


class TestDetection(unittest.TestCase):
    def test_reference_vectors(self):
        hits = S.detect_swings(rows_from_vectors(), 3600)
        self.assertEqual([(h["index"], h["direction"], h["from"], h["to"], h["delta_bits"])
                          for h in hits], EXPECTED)

    def test_boundary_is_inclusive_at_ten_cents(self):
        """Brief says "greater than or equal to $0.10" -- $0.0999 must not fire."""
        under = [{"ts": 0, "close": 5000}, {"ts": 600, "close": 5099}]
        self.assertEqual(S.detect_swings(under, 3600), [])
        exact = [{"ts": 0, "close": 5000}, {"ts": 600, "close": 6000}]
        hits = S.detect_swings(exact, 3600)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["delta_bits"], S.THRESHOLD_BITS)

    def test_rearm_suppresses_a_one_way_run(self):
        """A monotonic climb is ONE alert, not one per candle, until price re-arms."""
        rows = [{"ts": i * 60, "close": 3000 + i * 400} for i in range(40)]
        hits = S.detect_swings(rows, 600)
        self.assertEqual(len(hits), 1, f"expected a single leg alert, got {len(hits)}")
        self.assertEqual(hits[0]["direction"], "up")
        self.assertGreater(hits[0]["index"], 0)

    def test_anchors_are_the_window_extremes(self):
        """Up is measured off the window LOW, down off the window HIGH; the larger leg wins
        when both clear the bar, so a round trip counts as the move a trader would name."""
        rows = [{"ts": 0, "close": 5000}, {"ts": 60, "close": 6500}, {"ts": 120, "close": 5000},
                {"ts": 180, "close": 4000}]
        hits = S.detect_swings(rows, 6000)
        self.assertEqual([(h["direction"], h["from"], h["to"], h["delta_bits"]) for h in hits],
                         [("up", 5000, 6500, 1500), ("down", 6500, 4000, 2500)])


class TestOutcomes(unittest.TestCase):
    def test_measure_reports_reversion_and_no_invented_fills(self):
        rows = rows_from_vectors()
        hits = S.detect_swings(rows, 3600)
        out = S.measure(rows, hits[0], interval_min=10)
        self.assertIn(out["reversion_hit"], (True, False))
        self.assertEqual(out["horizon_minutes"], 60)
        # every strategy key always exists -- a missing measurement is stated, not omitted
        self.assertEqual(set(out["strategies"]), set(S.STRATEGY_NAMES))
        for name in S.STRATEGY_NAMES:
            s = out["strategies"][name]
            if s["status"] == "simulated-fill":
                self.assertIsNotNone(s["net_dollars"])
                self.assertIn("fees_dollars", s)          # per contract, like net_dollars
                self.assertIn("fees_block_dollars", s)   # per 100-contract block
                self.assertIn("gross_dollars", s)
                self.assertGreaterEqual(s["horizon_minutes_actual"], 1)
            else:
                # never a silent zero: unquotable / unmeasurable legs are reported as such
                self.assertIn(s["status"], ("not-quotable", "not-measurable"))
                self.assertIn("note", s)

    def test_binary_mirror_legs(self):
        """NO fills come from the documented YES-quote mirror: no ask = 1 - yes bid."""
        rows = [{"ts": 0, "close": 4000, "yes_bid_open": 3800, "yes_ask_open": 4200,
                 "yes_bid_close": 3700, "yes_ask_close": 4300, "volume_fp": 5.0,
                 "open_interest_fp": 5.0, "open": 4000, "high": 4000, "low": 4000}]
        legs = S._fill_legs("up", rows[0], rows[0], "no")
        self.assertEqual(legs, (S.BIT - 3800, S.BIT - 4300))


class TestBuckets(unittest.TestCase):
    def test_bucket_key_shape(self):
        self.assertEqual(S.bucket_key("elections", 0.003, 8200, 17227.6),
                         "elections|0-5c|>40c|>14d")
        self.assertEqual(S.bucket_key(None, None, 1200, None),
                         "unclassified|unclassified|10-20c|unclassified")

    def test_shrinkage_pulls_small_samples_to_the_prior(self):
        # (1 + 4*0.5) / (1 + 4) = 0.6 -- a single observation cannot read as a 100% edge
        self.assertAlmostEqual(S.shrink(1, 1, 0.5, k=4), 0.6)
        self.assertAlmostEqual(S.shrink(70, 100, 0.5, k=4), (70 + 2) / 104, places=6)  # rounded to 6dp by design


class TestParityWithBrowser(unittest.TestCase):
    """The live poller (JS) and this backtest (Python) must produce identical alerts."""

    @unittest.skipIf(shutil.which("node") is None, "node not available")
    def test_js_python_same_vectors(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "parity.mjs")
            with open(script, "w") as fh:
                fh.write(
                    "import fs from 'node:fs';import vm from 'node:vm';\n"
                    f"const src=fs.readFileSync({json.dumps(os.path.join(ROOT, 'assets', 'swing-core.js'))},'utf8');\n"
                    "const ctx=vm.createContext({});vm.runInContext(src,ctx);\n"
                    "const C=ctx.KalshiSwingCore;\n"
                    f"const v={json.dumps(VECTORS)};\n"
                    "const hits=C.detectSwings(v.map((p,i)=>({ts:i*600,price:p})),{windowMinutes:60});\n"
                    "const t=C.createTracker(60);\n"
                    "const live=[];\n"
                    "v.forEach((p,i)=>{const a=C.observe(t,'K',{ts:i*600000,price:p});if(a)live.push({index:a.ts/600000,direction:a.direction,from:a.fromBits,to:a.toBits,delta_bits:a.deltaBits});});\n"
                    "console.log(JSON.stringify({hist:hits.map(h=>({index:h.ts/600,direction:h.direction,from:h.fromBits,to:h.toBits,delta_bits:h.deltaBits})),live}));\n")
            out = subprocess.run(["node", script], capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            data = json.loads(out.stdout.strip())
            expect = [{"index": i, "direction": d, "from": f, "to": t, "delta_bits": dl}
                      for i, d, f, t, dl in EXPECTED]
            self.assertEqual(data["hist"], expect, "JS detectSwings diverged from Python")
            self.assertEqual(data["live"], expect, "JS live tracker diverged from Python")


class TestOfflineEndToEnd(unittest.TestCase):
    def test_reversion_is_horizon_bounded(self):
        """A later drift must not count as a 60-minute reversion (that bug inflated the rate)."""
        def row(ts, close, bid, ask):
            return {"ts": ts, "close": close, "open": close, "high": close, "low": close,
                    "yes_bid_close": bid, "yes_bid_open": bid, "yes_ask_close": ask,
                    "yes_ask_open": ask, "volume_fp": 1.0, "open_interest_fp": 1.0}
        rows = [row(0, 5000, 4900, 5100)]
        # spike prints at t=60s, holds high through t=900s, reverts only from t=960s.
        # With a 1-minute measurement horizon the reversion must NOT count; "ever" must.
        rows += [row(60 * k, 6200, 6100, 6300) for k in range(1, 16)]        # t=60..900
        rows += [row(60 * k, 5100, 5000, 5200) for k in range(16, 24)]        # t=960..1380
        sw = {"index": 1, "direction": "up", "anchor": 5000, "delta_bits": 1200,
              "from": 5000, "to": 6200, "anchor_index": 0}
        out = S.measure(rows, sw, interval_min=1, horizon_min=1)   # 1-minute horizon
        self.assertEqual(out["candles_in_horizon"], 1)
        self.assertIs(out["reversion_hit"], False)                 # not inside the horizon
        self.assertIs(out["reversion_hit_ever"], True)             # but it did come back
        self.assertGreater(out["retrace_dollars_ever"], out["retrace_dollars_horizon"] or 0)

    def test_offline_run_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "scan_swings.py"), "--offline",
                 "--out", d],
                capture_output=True, text=True, cwd=d, timeout=300)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            swings = json.load(open(os.path.join(d, "swings.json")))
            strat = json.load(open(os.path.join(d, "strategies.json")))
            events = json.load(open(os.path.join(d, "events.json")))
            self.assertEqual(swings["meta"]["threshold_dollars"], 0.10)
            self.assertGreaterEqual(len(swings["swings"]), 1)
            for row in swings["swings"]:
                self.assertTrue(str(row["source_url"]).startswith(
                    "https://external-api.demo.kalshi.co/trade-api/v2/"),
                    f"row lacks an official source url: {row['id']}")
                self.assertGreaterEqual(row["delta_dollars"], 0.10, row["id"])
                self.assertIn(row["direction"], ("up", "down"))
                kinds = {l["kind"] for l in row["links"]}
                self.assertIn("official-api", kinds)
                self.assertIn("candidate-news-search", kinds)
                news = [l for l in row["links"] if l["kind"] == "candidate-news-search"][0]
                self.assertIs(news["verified"], False, "news links must never be marked verified")
                self.assertEqual(set(row["strategies"]), set(S.STRATEGY_NAMES))
                for s in row["strategies"].values():
                    self.assertIn(s["status"], ("simulated-fill", "not-quotable", "not-measurable"))
            self.assertIn("fade60", strat["strategies"])
            for key, b in strat["buckets"].items():
                self.assertIn("best_strategy", b)
                self.assertIn("reversion_rate_within_horizon_minutes", b)
                self.assertEqual(b["reversion_rate_within_horizon_minutes"], 60)
            for key, b in strat["buckets"].items():
                self.assertEqual(key.count("|"), 3)
                self.assertIn(b["evidence"], ("sufficient", "insufficient"))
                self.assertGreaterEqual(b["n_markets"], 1)
            for e in events["events"]:
                self.assertTrue(e["source_urls"], "event rollup needs at least one API url")
            for note in swings["meta"]["caveats"]:
                self.assertTrue(len(note) > 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
