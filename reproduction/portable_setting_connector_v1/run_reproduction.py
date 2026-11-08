"""Replay frozen setting and connector analyses without launching a simulator."""
import argparse
import ast
import importlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

import portable_io as io


def extract_calculation(source, function, through_output=None):
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function]
    if len(nodes) != 1:
        raise ValueError("Expected a unique archived function")
    node = nodes[0]
    if through_output is not None:
        positions = [i for i, statement in enumerate(node.body)
                     if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                     and isinstance(statement.value.func, ast.Name) and statement.value.func.id == "write_csv"
                     and any(isinstance(c, ast.Constant) and c.value == through_output
                             for c in ast.walk(statement.value.args[0]))]
        if len(positions) != 1:
            raise ValueError("Calculation boundary is absent or ambiguous")
        node.body = node.body[:positions[0] + 1]
    text = ast.unparse(node) + "\n"
    if any(name in text for name in ("manuscript_working", "revision_status", "reviewer_tracker")):
        raise ValueError("Historical document/status writes entered the calculation adapter")
    if ast.dump(ast.parse(text).body[0], include_attributes=False) != ast.dump(node, include_attributes=False):
        raise ValueError("Calculation adapter changed the archived AST")
    return text


def check_population(audit):
    if audit["end_loaded"] != audit["end_inserted"] + audit["end_waiting"]:
        raise ValueError("Scheduled-population identity failed")
    if audit["end_inserted"] != audit["end_arrived"] + audit["end_running"]:
        raise ValueError("Inserted-population identity failed")
    if audit["trip_records"] != audit["end_loaded"]:
        raise ValueError("Trip-record coverage failed")


def check_ledger(ledger, workspace, old_root, metrics):
    checked = 0
    for row in ledger:
        directory = io.relocate(row["source_dir"], old_root, workspace)
        audit = metrics.audit_run(directory)
        check_population(audit)
        for key, value in audit.items():
            if key == "source_dir":
                continue
            if key not in row:
                raise ValueError(f"Missing metric in archived ledger: {key}")
            checked += io.compare_value(row[key], "" if value is None else str(value), f"{directory.name}.{key}")
    return checked


def check_settings(ledger, workspace, old_root, protocol):
    expected = {(float(c["tau"]), float(c["step"]), float(c["action"]), int(c["seed"]), bool(c["junctions"]))
                for c in protocol["cases"]}
    actual = set()
    for row in ledger:
        directory = io.relocate(row["source_dir"], old_root, workspace)
        cfg = ET.parse(directory / "run.sumocfg").getroot()
        value = lambda path: cfg.find(path).attrib["value"]
        taus = {float(v.attrib["tau"]) for v in ET.parse(directory / "routes.rou.xml").getroot().findall("vType")}
        if len(taus) != 1:
            raise ValueError("Unexpected heterogeneous headway in the setting check")
        key = (taus.pop(), float(value("time/step-length")), float(value("processing/default.action-step-length")),
               int(value("random_number/seed")), value("processing/collision.check-junctions") == "true")
        recorded = (float(row["tau_s"]), float(row["step_s"]), float(row["action_step_s"]),
                    int(row["seed"]), row["junction_check"] == "True")
        if key != recorded or key in actual:
            raise ValueError("Setting metadata differs from saved XML or duplicates a design cell")
        if value("processing/step-method.ballistic") != "true":
            raise ValueError("Integration method changed")
        actual.add(key)
    if actual != expected or len(ledger) != protocol["expected_total_cases"]:
        raise ValueError("Frozen setting design not fully covered")
    return len(actual)


def check_markers(workspace, manifest):
    count = 0
    for item in manifest["run_records"]:
        directory = workspace / item["directory"]
        record = io.load(directory / "complete.json")
        if io.sha(directory / "complete.json") != item["marker_sha256"]:
            raise ValueError("Completion marker changed")
        for name, digest in record["files_sha256"].items():
            target = (directory / name).resolve()
            if not target.is_relative_to(directory.resolve()) or io.sha(target) != digest:
                raise ValueError("Changed or escaping run file")
            count += 1
        if item.get("protocol") and record["protocol_sha256"] != io.sha(workspace / item["protocol"]):
            raise ValueError("Run protocol changed")
    return count


def run(package, destination):
    package, destination = package.resolve(), destination.resolve()
    manifest = io.load(package / "manifest.json")
    io.verify_package(package, manifest)
    if destination.exists() or destination.is_relative_to(package):
        raise FileExistsError("Use a fresh output directory outside the immutable package")
    workspace = destination / "workspace"
    shutil.copytree(package / "inputs", workspace)
    old_root = manifest["original_root"]
    io.install_read_isolation(old_root, package, destination)
    sys.path.insert(0, str(package / "frozen_code"))
    io.make_stub("freeze_submission", sha256=io.sha)
    protocol = io.load(workspace / "connector_audit_v1/protocol.json")
    runner = io.make_stub("run_connector_audit_v1", ROOT=workspace, OUT=workspace / "connector_audit_v1",
                          SOURCE=workspace / "hidden_challenge_v1/runs", JOBS=protocol["jobs"],
                          SEEDS=[s for kind, step, s in protocol["jobs"] if kind == "fine_joint"],
                          CONTROL_FIELDS=protocol["control_fields"], ET=ET)
    collision_source = (package / "provenance/run_connector_audit_v1.py").read_text(encoding="utf-8")
    collision_adapter = (package / "adapters/collisions.py").read_text(encoding="utf-8")
    if collision_adapter != extract_calculation(collision_source, "collisions"):
        raise ValueError("Collision reader differs from archived AST")
    exec(compile(collision_adapter, "unchanged_collision_reader", "exec"), runner.__dict__)
    metrics = importlib.import_module("audit_metrics")
    settings = importlib.import_module("report_stage3")
    settings.ROOT = workspace
    settings.Path = io.mapped_path_class(old_root, workspace)
    calculation = (package / "adapters/settings.py").read_text(encoding="utf-8")
    source = (package / "frozen_code/report_stage3.py").read_text(encoding="utf-8")
    if calculation != extract_calculation(source, "main", "stage3_settings/paired_summary.csv"):
        raise ValueError("Setting prefix differs from archived AST")
    exec(compile(calculation, "archived_setting_calculation_prefix", "exec"), settings.__dict__)
    connector = importlib.import_module("analyze_connector_audit_v1")
    files = check_markers(workspace, manifest)
    core_cells, corrections = io.check_core_ledger(workspace, old_root, metrics, package)
    ledger = io.rows(workspace / "stage3_settings/settings_results.csv")
    settings_cells = check_ledger(ledger, workspace, old_root, metrics)
    design_cells = check_settings(ledger, workspace, old_root, io.load(workspace / "audit/stage3_settings_protocol.json"))
    connector_cells = check_ledger(io.rows(workspace / "connector_audit_v1/run_audit.csv"), workspace, old_root, metrics)
    baseline_rows = [r for r in io.rows(workspace / "hidden_challenge_v1/run_audit.csv") if r["case_id"] == "B00"]
    if len(baseline_rows) != len(runner.SEEDS):
        raise ValueError("Missing or duplicate frozen baselines")
    baseline_cells = check_ledger(baseline_rows, workspace, old_root, metrics)
    for label, action in (("compatible_settings", settings.main), ("connector_audit", connector.main)):
        print(f"BEGIN {label}", flush=True)
        action()
        print(f"END {label}", flush=True)
    comparisons = []
    for name in manifest["expected_outputs"]:
        expected, actual = package / "expected" / name, workspace / name
        left, right = (io.load(expected), io.load(actual)) if expected.suffix == ".json" else (io.rows(expected), io.rows(actual))
        count = io.compare_value(left, right, name)
        comparisons.append({"path": name, "cells_checked": count, "values_match": True,
                            "byte_identical": io.sha(expected) == io.sha(actual), "reproduced_sha256": io.sha(actual)})
    for name, digest in manifest["input_sha256"].items():
        if name != "core_detector_batch/run_results.csv" and io.sha(workspace / name) != digest:
            raise ValueError(f"Analysis changed an input: {name}")
    io.verify_package(package, manifest)
    report = {"scope": "Two frozen same-platform raw-to-output reanalyses; no new simulations",
              "unique_existing_runs": len(manifest["run_records"]), "run_files_verified": files,
              "settings_design_cells": design_cells, "settings_cells_reextracted": settings_cells,
              "connector_cells_reextracted": connector_cells, "baseline_cells_reextracted": baseline_cells,
              "core_cells_reextracted": core_cells, "preexisting_warning_reclassifications": corrections,
              "outputs_verified": len(comparisons), "byte_identical_outputs": sum(r["byte_identical"] for r in comparisons),
              "cells_checked": sum(r["cells_checked"] for r in comparisons), "outputs": comparisons,
              "source_archive_read_blocked_during_analysis": True, "subprocess_and_network_blocked": True,
              "new_simulations": 0, "compile_invoked": False, "public_deposition_complete": False}
    (destination / "reproduction_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Verified both setting and connector chains", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(Path(__file__).resolve().parent, parser.parse_args().output)
