"""Reproduce archived score tables and frozen rule predictions locally.

This entry point is copied into a separate, incomplete release-preparation tree.
It never runs SUMO, compiles documents, downloads packages or uploads files.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WINDOWS_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(root):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files_sha256"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError(f"Missing or escaping dependency: {name}")
        if digest(path) != expected:
            raise ValueError(f"Dependency changed: {name}")
    return manifest


def compare_values(expected, actual, location="root"):
    if isinstance(expected, bool) or expected is None:
        if actual is not expected:
            raise ValueError(f"Mismatch at {location}")
    elif isinstance(expected, (float, int)):
        if not isinstance(actual, (float, int)) or isinstance(actual, bool):
            raise ValueError(f"Type mismatch at {location}")
        if not (math.isfinite(expected) and math.isfinite(actual)):
            raise ValueError(f"Non-finite value at {location}")
        if not math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"Numeric mismatch at {location}: {expected} != {actual}")
    elif isinstance(expected, dict):
        if not isinstance(actual, dict) or expected.keys() != actual.keys():
            raise ValueError(f"Keys differ at {location}")
        for key in expected:
            compare_values(expected[key], actual[key], f"{location}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise ValueError(f"Length differs at {location}")
        for i, (a, b) in enumerate(zip(expected, actual)):
            compare_values(a, b, f"{location}[{i}]")
    elif actual != expected:
        raise ValueError(f"Mismatch at {location}: {expected!r} != {actual!r}")


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        names = reader.fieldnames
        rows = list(reader)
    for row in rows:
        for key, value in row.items():
            try:
                row[key] = float(value)
            except (ValueError, TypeError):
                pass
    return {"fieldnames": names, "rows": rows}


def compare_file(expected, actual):
    if expected.suffix == ".csv":
        compare_values(csv_rows(expected), csv_rows(actual), expected.name)
    elif expected.suffix == ".json":
        compare_values(json.loads(expected.read_text(encoding="utf-8")),
                       json.loads(actual.read_text(encoding="utf-8")), expected.name)
    else:
        raise ValueError("Unsupported comparison")
    return {"file": expected.name, "numeric_and_text_match": True,
            "byte_identical": digest(expected) == digest(actual),
            "expected_sha256": digest(expected), "actual_sha256": digest(actual)}


def output_location(root, requested):
    path = (root / requested).resolve()
    if path.exists():
        raise ValueError("Output already exists; choose a new directory")
    protected = [root / "inputs", root / "expected", root / "model_inputs"]
    if path == root.resolve() or any(path.is_relative_to(p.resolve()) for p in protected):
        raise ValueError("Output must not be inside protected dependencies")
    return path


def replay_rules(root, out):
    from diagnostic_rules import VARIANTS, classify, response_features

    def load(name, base="inputs/rules"):
        return json.loads((root / base / name).read_text(encoding="utf-8"))

    baselines = {int(k): v for k, v in load("observable_baselines.json").items()}
    cases = load("observable_cases.json")
    expected = load("locked_predictions.json", "expected/rules")
    if len(cases) != 16 or len(baselines) != 5 or cases.keys() != expected.keys():
        raise ValueError("Unexpected frozen internal-challenge scope")
    result, counts = {}, Counter()
    for case, rows in cases.items():
        features = response_features(rows, baselines)
        predictions = {v: classify(features, v) for v in VARIANTS}
        result[case] = {"features": features, "predictions": predictions}
        # These values must reproduce exactly, not merely within a tolerance.
        if result[case] != expected[case]:
            raise ValueError(f"Frozen rule prediction differs: {case}")
        for variant, prediction in predictions.items():
            counts[variant] += prediction["retained_improvement"]
    with (root / "expected/rules/threshold_sensitivity.csv").open(
            encoding="utf-8-sig", newline="") as stream:
        sensitivity = list(csv.DictReader(stream))
    if len(sensitivity) != 48:
        raise ValueError("Unexpected threshold-check scope")
    for row in sensitivity:
        prediction = classify(result[row["case_id"]]["features"],
                              "D_full", float(row["threshold_scale"]))
        if (prediction["status"] != row["status"]
                or str(prediction["retained_improvement"]) != row["retained_improvement"]):
            raise ValueError("Frozen threshold prediction differs")
    (out / "rule_predictions.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return {"case_variant_predictions": len(result) * len(VARIANTS),
            "threshold_predictions": len(sensitivity), "retained_gains": dict(counts),
            "independent_validation": False}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="generated",
                        help="New output directory, relative to this entry point or absolute.")
    args = parser.parse_args(argv)
    manifest = verify_manifest(ROOT)
    versions = {name: importlib.metadata.version(name) for name in manifest["python_packages"]}
    if versions != manifest["python_packages"]:
        raise RuntimeError(f"Use the recorded environment for exact replay: {versions}")
    out = output_location(ROOT, args.output)
    out.mkdir(parents=True)
    import score_analysis

    score_analysis.OUT = out / "scores"
    score_analysis.main()
    comparisons = [compare_file(ROOT / "expected/scores" / name, out / "scores" / name)
                   for name in manifest["score_outputs"]]
    if len(comparisons) != 9:
        raise ValueError("Missing score comparison")
    rules = replay_rules(ROOT, out)
    verify_manifest(ROOT)
    report = {
        "scope": "Relocated deterministic reanalysis of archived values, not a fresh SUMO run or independent validation.",
        "score_outputs_verified": len(comparisons), "score_outputs": comparisons,
        "rules": rules, "input_hashes_preserved": True, "new_simulations": 0,
        "public_deposition_complete": False, "python_packages": versions,
    }
    (out / "reproduction_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
