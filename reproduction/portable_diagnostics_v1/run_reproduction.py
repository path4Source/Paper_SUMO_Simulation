"""Reproduce raw warning/window/challenge evidence without accessing source archives."""
import argparse
import importlib
import json
from pathlib import Path
import shutil
import sys

from portable_io import (check_core_ledger, compare_value, install_read_isolation, load,
                         make_stub, mapped_path_class, relocate, rows, sha, verify_package)


def policy_ledger(workspace, old_root, metrics):
    path = workspace / "warning_policy_check/run_results.csv"
    ledger = rows(path)
    if len(ledger) != 12:
        raise ValueError("Expected all twelve policy/control runs")
    cells = 0
    for row in ledger:
        directory = relocate(row["source_dir"], old_root, workspace)
        audit = metrics.audit_run(directory)
        for name, value in audit.items():
            if name != "source_dir":
                cells += compare_value(row[name], "" if value is None else str(value), f"{directory.name}.{name}")
        if (audit["end_loaded"] != audit["end_inserted"] + audit["end_waiting"]
                or audit["unaccounted_inserted_end"] != 0):
            raise ValueError("Policy population mismatch")
        if row["measurement_control"] == "exact_match":
            baseline = metrics.audit_run(workspace / "core_detector_batch/runs" / f"{row['scenario']}_seed{row['seed']}")
            for name in ("end_arrived", "end_inserted", "end_running", "end_waiting", "teleport_events",
                         "stat_safety_collisions", "trip_completed_timeLoss_mean_s", "total_vehicle_hours_discrete"):
                cells += compare_value(baseline[name], audit[name], f"detector_removal.{name}")
        row["source_dir"] = str(directory)
    metrics.write_csv(path, ledger)
    return cells


def verify_prediction_before_key(workspace, prediction_digest):
    prediction = workspace / "hidden_challenge_v1/locked_predictions.json"
    if not prediction.is_file() or sha(prediction) != prediction_digest:
        raise RuntimeError("Construction key accessed before matching frozen predictions")
    return {"predictions_existed_before_key_read": True, "predictions_sha256": prediction_digest}


def install_key_order_guard(workspace, prediction_digest):
    key = (workspace / "hidden_challenge_v1/construction_key/key.json").resolve()
    reads = []

    def guard(event, args):
        if event == "open" and isinstance(args[0], (str, bytes)) and Path(args[0]).resolve() == key:
            reads.append(verify_prediction_before_key(workspace, prediction_digest))
    sys.addaudithook(guard)
    return reads


def run(package, destination):
    package, destination = package.resolve(), destination.resolve()
    manifest = load(package / "manifest.json")
    verify_package(package, manifest)
    if destination.exists() or destination.is_relative_to(package / "inputs"):
        raise FileExistsError("A fresh output directory is required")
    workspace = destination / "workspace"
    shutil.copytree(package / "inputs", workspace)
    old_root = manifest["original_root"]
    install_read_isolation(old_root, package, destination)
    sys.path.insert(0, str(workspace / "scripts"))
    sys.path.insert(0, str(package / "adapters"))
    make_stub("freeze_submission", sha256=sha)
    make_stub("run_timepilot", ROOT=workspace)
    recorded_path = mapped_path_class(old_root, workspace)
    metrics = importlib.import_module("audit_metrics")
    local = importlib.import_module("analyze_core_detector_batch")
    warnings = importlib.import_module("audit_core_warnings")
    windows = importlib.import_module("audit_signal_windows")
    policy = importlib.import_module("policy_statistics")
    hidden = importlib.import_module("analyze_hidden_challenge_v1")
    local.ROOT, local.OUT, local.Path = workspace, workspace / "core_detector_batch", recorded_path
    for module in (warnings, windows):
        module.ROOT, module.CORE, module.OUT, module.Path = workspace, workspace / "core_detector_batch", workspace / "stage4_warning_audit", recorded_path
    warnings.OUT.mkdir()
    policy.ROOT, policy.OUT, policy.POLICY, policy.Path = workspace, warnings.OUT, workspace / "warning_policy_check", recorded_path
    core_cells, prior_corrections = check_core_ledger(workspace, old_root, metrics, package)
    policy_cells = policy_ledger(workspace, old_root, metrics)
    prediction_digest = manifest["files_sha256"]["expected/hidden_challenge_v1/locked_predictions.json"]
    key_reads = install_key_order_guard(workspace, prediction_digest)
    for label, action in (("local_crossing_prerequisite", local.main), ("core_warning_reconciliation", warnings.main),
                          ("protected_green_windows", windows.main), ("warning_policy_statistics", policy.main),
                          ("hidden_challenge_raw_extraction_and_rules", hidden.main)):
        print(f"BEGIN {label}", flush=True)
        action()
        print(f"END {label}", flush=True)
    if len(key_reads) != 1:
        raise ValueError(f"Expected one post-prediction construction-key read, observed {len(key_reads)}")
    comparisons = []
    for name in manifest["expected_outputs"]:
        expected, actual = package / "expected" / name, workspace / name
        left, right = (load(expected), load(actual)) if expected.suffix == ".json" else (rows(expected), rows(actual))
        if name == "stage4_warning_audit/core_run_results_corrected.csv":
            for row in left:
                row["source_dir"] = str(relocate(row["source_dir"], old_root, workspace))
        count = compare_value(left, right, name)
        comparisons.append({"path": name, "cells_checked": count, "values_match": True,
                            "byte_identical": sha(expected) == sha(actual), "reproduced_sha256": sha(actual)})
    for name, digest in manifest["input_sha256"].items():
        if name in ("core_detector_batch/run_results.csv", "warning_policy_check/run_results.csv"):
            continue
        if sha(workspace / name) != digest:
            raise ValueError(f"Frozen input changed: {name}")
    verify_package(package, manifest)
    report = {"scope": "Same-platform raw-to-result warning, window and internal-rule replay",
              "unique_archived_runs": 106, "core_runs": 9, "policy_runs": 12, "internal_challenge_runs": 85,
              "outputs_verified": len(comparisons), "byte_identical_outputs": sum(r["byte_identical"] for r in comparisons),
              "cells_checked": sum(r["cells_checked"] for r in comparisons),
              "core_ledger_fields_checked": core_cells, "policy_ledger_and_control_fields_checked": policy_cells,
              "preexisting_warning_reclassifications": prior_corrections, "construction_key_read_audit": key_reads,
              "construction_key_analysis_reads": 1, "post_analysis_input_hash_key_reads": len(key_reads) - 1,
              "frozen_predictions_byte_identical": sha(workspace / "hidden_challenge_v1/locked_predictions.json") == prediction_digest,
              "frozen_rules_and_raw_inputs_unchanged": True, "source_archive_reads_blocked_during_analysis": True,
              "outputs": comparisons, "new_simulations": 0, "independent_human_blind_validation": False,
              "public_deposition_complete": False}
    (destination / "reproduction_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "outputs"}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(Path(__file__).resolve().parent, args.output)
