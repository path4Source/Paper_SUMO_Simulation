"""Holdout routing, provenance, and counting checks for the merged release."""
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("holdout_release_entry", ROOT / "reproduce.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class HoldoutReleaseTests(unittest.TestCase):
    def setUp(self):
        self.catalog = entry.load(ROOT / "catalog.json")
        self.package = ROOT / self.catalog["analyses"]["holdout"]["directory"]

    def test_unique_execution_count(self):
        counts = self.catalog["run_counts"]
        self.assertEqual(sum(counts[k] for k in ("original", "revision_diagnostics_before_holdout",
            "exploratory", "morris_design", "morris_equivalence_controls", "added_holdout_and_bridge")), 1173)
        self.assertEqual(counts["reused_bridge_references"], 15)

    def test_input_count_is_not_new_run_count(self):
        records = entry.load(self.package / "input_inventory.json")["runs"]
        self.assertEqual(len(records), 95)
        self.assertEqual(sum(r["new_in_revision"] for r in records), 80)
        self.assertEqual(len([r for r in records if r["case"].startswith("holdout/")]), 65)

    def test_raw_archive_matches_package_index(self):
        records = entry.load(self.package / "raw_package_manifest.json")["files_sha256"]
        archive = next(a for a in entry.load(ROOT / "data_manifest.json")["archives"] if a["id"] == "holdout-raw")
        self.assertEqual({"data/holdout_raw/"+k:v for k,v in records.items()}, archive["files_sha256"])
        self.assertEqual(len({str(Path(name).parent) for name in records}), 95)
        self.assertIsNone(archive["public_url"])

    def test_frozen_predictions_cover_12_by_7(self):
        locked = entry.load(self.package / "data/predictions_LOCKED.json")
        self.assertEqual(len(locked["rows"]), 12)
        self.assertTrue(all(len(r["predictions"]) == 7 for r in locked["rows"]))

    def test_open_gates_are_preserved(self):
        manifest = entry.load(self.package / "manifest.json")
        for key in ("public_deposition_complete", "independent_correctness_complete",
                    "raw_to_measurement_validation_complete"):
            self.assertIs(manifest[key], False)

    def test_processed_route_does_not_require_raw_restore(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(entry, "execute") as execute:
            destination = Path(tmp) / "out"
            entry.main(["analyze", "holdout_processed", "--output", str(destination)])
            self.assertEqual(execute.call_args.args[0].name, "run_processed_reproduction.py")
            self.assertNotIn("--raw-root", execute.call_args.args[1])

    def test_current_figures_exactly_match_index(self):
        index = entry.load(ROOT / "figures/index.json")
        self.assertEqual({x["file"] for x in index}, {p.name for p in (ROOT / "figures").glob("*.pdf")})
        self.assertEqual(sum("main.tex" in x["source_documents"] for x in index), 11)
        self.assertEqual(sum("supplementary_appendix.tex" in x["source_documents"] for x in index), 4)


if __name__ == "__main__":
    unittest.main()
