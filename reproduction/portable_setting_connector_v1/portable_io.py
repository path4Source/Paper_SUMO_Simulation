"""Replay three frozen raw-output analyses with explicit location-only adapters."""
import argparse
import csv
import hashlib
import importlib
import json
import math
from pathlib import Path, PureWindowsPath
import shutil
import sys
import types


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def compare_value(expected, actual, location="root"):
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or expected.keys() != actual.keys():
            raise ValueError(f"Key mismatch at {location}")
        return sum(compare_value(v, actual[k], f"{location}.{k}") for k, v in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise ValueError(f"Length mismatch at {location}")
        return sum(compare_value(a, b, f"{location}[{i}]") for i, (a, b) in enumerate(zip(expected, actual)))
    if isinstance(expected, bool) or expected is None:
        if type(expected) is not type(actual) or expected != actual:
            raise ValueError(f"Typed value mismatch at {location}: {expected!r} != {actual!r}")
        return 1
    if expected == actual:
        return 1
    try:
        a, b = float(expected), float(actual)
    except (TypeError, ValueError):
        raise ValueError(f"Value mismatch at {location}: {expected!r} != {actual!r}") from None
    if not (math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)):
        raise ValueError(f"Numeric mismatch at {location}: {expected!r} != {actual!r}")
    return 1


def relocate(value, original_root, workspace):
    text = str(value)
    if Path(value).is_relative_to(workspace):
        return Path(value)
    old = PureWindowsPath(original_root)
    candidate = PureWindowsPath(text)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(old)
        except ValueError:
            return Path(value)
        if ".." in relative.parts:
            raise ValueError("Recorded path escapes the archived root")
        return workspace.joinpath(*relative.parts)
    return Path(value)


def mapped_path_class(original_root, workspace):
    class RecordedPath(type(Path())):
        def __init__(self, *args):
            super().__init__(relocate(Path(*args), original_root, workspace))
    return RecordedPath


def verify_package(package, manifest):
    for name, digest in manifest["files_sha256"].items():
        target = (package / name).resolve()
        if not target.is_relative_to(package.resolve()) or sha(target) != digest:
            raise ValueError(f"Package file changed or escapes root: {name}")


def make_stub(name, **bindings):
    module = types.ModuleType(name)
    module.__dict__.update(bindings)
    sys.modules[name] = module
    return module


def install_read_isolation(original_root, package, destination):
    source = Path(original_root).resolve()
    allowed = (package.resolve(), destination.resolve())

    def guard(event, args):
        if event in ("subprocess.Popen", "os.system", "socket.connect"):
            raise RuntimeError(f"Analysis-only reproduction forbids {event}")
        if event == "open" and isinstance(args[0], (str, bytes)):
            target = Path(args[0]).resolve()
            if target.is_relative_to(source) and not any(target.is_relative_to(p) for p in allowed):
                raise RuntimeError(f"Attempted access to original source archive: {target}")
    sys.addaudithook(guard)


def reconcile_historical_warning(row, audit, documented):
    old, new = int(row["collision_teleport_events"]), audit["collision_teleport_events"]
    if (old, new) != (int(documented["old_collision_teleport_events"]),
                      int(documented["corrected_collision_teleport_events"])) or new <= old:
        raise ValueError("Collision reclassification does not match the pre-existing audit")
    before, after = json.loads(row["teleport_causes_json"]), json.loads(audit["teleport_causes_json"])
    delta = new - old
    corrected = dict(before)
    corrected["collision"] = corrected.get("collision", 0) + delta
    corrected["other"] = corrected.get("other", 0) - delta
    if corrected["other"] < 0 or {k: v for k, v in corrected.items() if v} != {k: v for k, v in after.items() if v}:
        raise ValueError("Historical difference is not solely the documented cause reclassification")
    if new != audit["stat_safety_collisions"]:
        raise ValueError("Reclassified collision count disagrees with simulator statistics")
    if int(row["teleport_events"]) != audit["teleport_events"]:
        raise ValueError("Cause reclassification must not change total teleport events")
    return {"run": row["run"], "old_collision_teleports": old, "corrected_collision_teleports": new,
            "total_teleports_unchanged": int(row["teleport_events"]) == audit["teleport_events"],
            "scope": "Pre-existing stage4 side-collision correction; historical table retained, corrected audit replayed separately"}


def check_core_ledger(workspace, original_root, metrics, package):
    path = workspace / "core_detector_batch/run_results.csv"
    ledger = rows(path)
    checked = 0
    corrections = {r["run"]: r for r in rows(package / "expected/stage4_warning_audit/warning_category_corrections.csv")}
    reconciled = []
    for row in ledger:
        directory = relocate(row["source_dir"], original_root, workspace)
        audit = metrics.audit_run(directory)
        legacy = row["run"] in corrections
        if legacy:
            reconciled.append(reconcile_historical_warning(row, audit, corrections[row["run"]]))
        for name, value in audit.items():
            if name == "source_dir":
                continue
            if legacy and name in ("collision_teleport_events", "teleport_causes_json"):
                continue
            if name not in row:
                raise ValueError(f"Raw metric missing from original ledger: {name}")
            checked += compare_value(row[name], "" if value is None else str(value), f"{directory.name}.{name}")
        if audit["end_loaded"] != audit["end_inserted"] + audit["end_waiting"]:
            raise ValueError("Core scheduled-population identity failed")
        if audit["end_inserted"] != audit["end_arrived"] + audit["end_running"] + audit["unaccounted_inserted_end"]:
            raise ValueError("Core inserted-population identity failed")
        row["source_dir"] = str(directory)
    metrics.write_csv(path, ledger)
    if set(corrections) != {r["run"] for r in reconciled}:
        raise ValueError("Incomplete historical warning reconciliation")
    return checked, reconciled


def run(package, destination):
    package, destination = package.resolve(), destination.resolve()
    manifest = load(package / "manifest.json")
    verify_package(package, manifest)
    if destination.exists() or destination.is_relative_to(package / "inputs"):
        raise FileExistsError("Use a fresh reproduction directory outside the archived inputs")
    workspace = destination / "workspace"
    shutil.copytree(package / "inputs", workspace)
    old_root = manifest["original_root"]
    install_read_isolation(old_root, package, destination)
    recorded_path = mapped_path_class(old_root, workspace)
    sys.path.insert(0, str(package / "frozen_code"))

    # Runner modules are replaced only by data-location bindings, never executed.
    make_stub("freeze_submission", sha256=sha)
    protocol = load(workspace / "independent_intervention_v1/protocol.json")
    setting = make_stub("run_independent_intervention_v1", ROOT=workspace,
                        OUT=workspace / "independent_intervention_v1",
                        SOURCE_BASE=workspace / "connector_audit_v1/runs",
                        NETWORK=workspace / "frozen/inputs/network.net.xml",
                        STATES=protocol["states"], PLANS=protocol["plans"], SEEDS=protocol["seeds"],
                        TARGET_LANES=protocol["target_lanes"])
    route_source = (package / "adapters/route_source.py").read_text(encoding="utf-8")
    exec(compile(route_source, "route_source_location_adapter", "exec"), setting.__dict__)
    make_stub("run_horizon_v1", ROOT=workspace, OUT=workspace / "horizon_audit_v1", sha=sha)
    metrics = importlib.import_module("audit_metrics")
    local = importlib.import_module("analyze_core_detector_batch")
    intervention = importlib.import_module("analyze_independent_intervention_v1")
    horizon = importlib.import_module("analyze_horizon_v1")
    warnings = importlib.import_module("audit_core_warnings")
    local.ROOT, local.OUT, local.Path = workspace, workspace / "core_detector_batch", recorded_path
    intervention.Path, horizon.Path = recorded_path, recorded_path
    warnings.ROOT, warnings.CORE, warnings.OUT = workspace, workspace / "core_detector_batch", workspace / "stage4_warning_audit"
    warnings.Path = recorded_path
    warnings.OUT.mkdir()

    ledger_cells, reclassifications = check_core_ledger(workspace, old_root, metrics, package)
    for label, action in (("local_service", local.main),
                          ("local_warning_reconciliation", warnings.main),
                          ("different_lever_intervention", intervention.main),
                          ("fixed_cohort_horizon", horizon.analyze)):
        print(f"BEGIN {label}", flush=True)
        action()
        print(f"END {label}", flush=True)
    comparisons = []
    for name in manifest["expected_outputs"]:
        expected, actual = package / "expected" / name, workspace / name
        left, right = (load(expected), load(actual)) if expected.suffix == ".json" else (rows(expected), rows(actual))
        if name == "stage4_warning_audit/core_run_results_corrected.csv":
            # Location-only normalization; every measurement and warning remains checked.
            for row in left:
                row["source_dir"] = str(relocate(row["source_dir"], old_root, workspace))
        checked = compare_value(left, right, name)
        comparisons.append({"path": name, "cells_checked": checked,
                            "byte_identical": sha(expected) == sha(actual), "values_match": True,
                            "reproduced_sha256": sha(actual)})
    # Only the workspace copy of the ledger has its source-directory field changed.
    for name, digest in manifest["input_sha256"].items():
        if name == "core_detector_batch/run_results.csv":
            continue
        if sha(workspace / name) != digest:
            raise ValueError(f"Analysis changed a raw input: {name}")
    verify_package(package, manifest)
    report = {"scope": "Three same-platform raw-to-result analysis chains; no new simulations",
              "chain_count": 3, "unique_archived_runs": len(manifest["run_records"]),
              "additional_local_warning_reconciliation_replayed": True,
              "local_runs": 9, "intervention_cells": 30, "intervention_reused_baselines": 5,
              "horizon_runs": 15, "core_ledger_cells_reextracted": ledger_cells,
              "outputs_verified": len(comparisons),
              "byte_identical_outputs": sum(r["byte_identical"] for r in comparisons),
              "cells_checked": sum(r["cells_checked"] for r in comparisons), "outputs": comparisons,
              "preexisting_warning_reclassifications": reclassifications,
              "frozen_analysis_code_unchanged": True, "raw_inputs_unchanged": True,
              "source_archive_reads_blocked_during_analysis": True,
              "new_simulations": 0, "public_deposition_complete": False,
              "independent_validation_complete": False}
    (destination / "reproduction_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "outputs"}, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(Path(__file__).resolve().parent, args.output)
