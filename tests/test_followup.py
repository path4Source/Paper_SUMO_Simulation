"""Check release routing, frozen bands, counting units and safe destinations."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "reproduction/portable_followup_v1"
spec = importlib.util.spec_from_file_location("followup_replay_test", PKG / "run_raw_reproduction.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)
spec2 = importlib.util.spec_from_file_location("root_followup_entry", ROOT / "reproduce.py")
entry = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(entry)


class FollowupTests(unittest.TestCase):
    def test_counting_units(self):
        ledger = replay.read(PKG / "execution_lineage.json")
        self.assertEqual(ledger["previous"] + ledger["passive_measurement"] + ledger["step_refinements"] + ledger["technical_control"], 1344)
        self.assertEqual(ledger["reused_step_references_not_added"], 30)
        jobs = replay.read(PKG / "data/portable_jobs.json")
        self.assertEqual(len(jobs["measurement"]), 110)
        self.assertEqual(sum(j["reused"] for j in jobs["numerical"]), 30)
        self.assertEqual(len(jobs["numerical"]), 90)

    def test_frozen_band_boundaries(self):
        self.assertEqual(replay.band_status({"lo": -2, "hi": 2}, 2), "within_band")
        self.assertEqual(replay.band_status({"lo": 2.01, "hi": 5}, 2), "outside_band")
        self.assertEqual(replay.band_status({"lo": -1, "hi": 5}, 2), "inconclusive")
        self.assertEqual(replay.band_status({"lo": -5, "hi": -2.01}, 2), "outside_band")

    def test_unsafe_paths(self):
        for value in ("../outside", "C:/outside", "a\\b", "/outside"):
            with self.assertRaises(ValueError):
                replay.safe(ROOT, value)

    def test_csv_comparison_detects_changed_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "values.csv"
            path.write_text("n,status,flag,band\n2,inconclusive,True,\n", encoding="utf-8")
            self.assertEqual(replay.compare_csv([dict(n=2, status="inconclusive", flag=True, band=None)], path), 4)
            with self.assertRaises(AssertionError):
                replay.compare_csv([dict(n=3, status="inconclusive", flag=True, band=None)], path)

    def test_analysis_route_and_no_sumo_dispatch(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(entry, "execute") as execute, patch.object(Path, "is_dir", return_value=True):
            output = Path(folder) / "results"
            entry.main(["analyze", "followup", "--output", str(output)])
            self.assertEqual(execute.call_args.args[0], PKG / "run_raw_reproduction.py")
            self.assertIn("--raw-root", execute.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
