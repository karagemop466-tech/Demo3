#!/usr/bin/env python3
"""Determinism and consistency checks for data/latest/roi_model.json (session 7b47094a).

Why this exists: the dashboard's high-ROI chat and model.html read this file, so the
committed artefact must be exactly what the committed generator produces from the
committed snapshot, and no published rate may be a hand-typed number.

Run:  python3 scripts/tests/test_roi_model.py   (also run from CI)
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GEN = ROOT / "model" / "build_roi_model.py"
OUT = ROOT / "data" / "latest" / "roi_model.json"


def load_gen():
    spec = importlib.util.spec_from_file_location("build_roi_model", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRoiModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(OUT.read_text())
        cls.gen = load_gen()

    def test_committed_file_matches_a_fresh_build(self):
        r = subprocess.run([sys.executable, str(GEN), "--check"], capture_output=True, text=True,
                           cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_rebuild_is_deterministic(self):
        a = json.dumps(self.gen.build(), sort_keys=True)
        b = json.dumps(self.gen.build(), sort_keys=True)
        self.assertEqual(a, b, "two rebuilds must be byte-identical")

    def test_counts_are_consistent_with_the_snapshot(self):
        m = self.doc["measured"]
        snap = json.loads((ROOT / "data" / "latest" / "markets_settled.json").read_text())
        self.assertEqual(m["universe"]["n_records_in_file"], len(snap["markets"]))
        self.assertEqual(m["universe"]["n_usable"],
                         m["universe"]["n_records_in_file"] - sum(m["universe"]["skipped"].values()))
        self.assertEqual(m["swing_market_counts"]["n_swing"],
                         m["up_swing"]["n"] + m["down_swing"]["n"])
        self.assertLessEqual(m["swing_market_counts"]["n_swing"], m["universe"]["n_usable"])
        for t in m["by_topic"]:
            self.assertLessEqual(t["n_swing"], t["n_settled"])

    def test_rates_recompute_from_the_snapshot(self):
        """Recompute base P(yes) and the swing counts independently of the generator."""
        snap = json.loads((ROOT / "data" / "latest" / "markets_settled.json").read_text())

        def dollars(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None

        rows, yes, swings = 0, 0, 0
        for m in snap["markets"]:
            res = (m.get("result") or "").strip().lower()
            last, prev = dollars(m.get("last_price_dollars")), dollars(m.get("previous_price_dollars"))
            if res not in ("yes", "no") or last is None or prev is None:
                continue
            rows += 1
            yes += 1 if res == "yes" else 0
            if abs(last - prev) >= 0.10 - 1e-9:
                swings += 1
        self.assertEqual(self.doc["measured"]["universe"]["n_usable"], rows)
        self.assertEqual(round(yes / rows, 4), self.doc["measured"]["base_rate_all_settled"]["p_yes"])
        self.assertEqual(swings, self.doc["measured"]["swing_market_counts"]["n_swing"])

    def test_small_bands_are_not_published_as_rates(self):
        for b in self.doc["measured"]["up_swing_by_prior_band"]:
            if not b["reported"]:
                self.assertLess(b["n"], 25)
                self.assertIsNone(b["p_yes"], "an unreported band must carry no rate")

    def test_every_example_row_links_the_official_demo_api(self):
        for r in self.doc["examples"]:
            self.assertTrue(r["source_url"].startswith(
                "https://external-api.demo.kalshi.co/trade-api/v2/"), r["source_url"])

    def test_screen_is_labelled_uncalibrated(self):
        self.assertEqual(self.doc["screen"]["status"], "uncalibrated-thresholds")
        self.assertEqual(self.doc["screen"]["params"]["min_abs_swing_dollars"], 0.10)
        self.assertIn("insufficient", self.doc["calibration_feasibility"]["conclusion"].lower())
        self.assertTrue(self.doc["caveats"], "caveats must ship with the numbers")

    def test_citation_urls_are_official(self):
        allowed = ("https://docs.kalshi.com/", "https://external-api.demo.kalshi.co/",
                   "https://demo-api.kalshi.co/")
        for key, url in self.doc["docs"].items():
            self.assertTrue(url.startswith(allowed), (key, url))


if __name__ == "__main__":
    unittest.main(verbosity=2)
