"""Reproduce original-study evidence using archived computations and raw outputs."""
import argparse
import ast
import copy
import importlib
import json
from pathlib import Path, PureWindowsPath
import shutil
import statistics
import sys

import numpy as np
import numpy.ma
import numpy.random
from portable_io import compare_value, install_read_isolation, load, make_stub, rows, sha, verify_package

PREFIXES = {
    "audit_historical": ("audit/historical_run_audit.csv", None),
    "audit_setup_stage13": ("original_departure_settings.csv", None),
    "audit_oat_precision_stage13": ("pointwise_intervals.csv", None),
    "audit_warning_exposure_stage14": (None, "table"),
}


def calculation_prefix(source, output=None, before=None):
    tree = ast.parse(source)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    if (output is None) == (before is None):
        raise ValueError("Specify exactly one calculation boundary")
    boundaries = []
    for i, node in enumerate(main.body):
        if output and isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == "write_csv" and call.args:
                arg = call.args[0]
                if isinstance(arg, ast.BinOp) and isinstance(arg.right, ast.Constant) and arg.right.value == output:
                    boundaries.append(i + 1)
        if before and isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == before for t in node.targets):
            boundaries.append(i)
    if len(boundaries) != 1:
        raise ValueError("Ambiguous or absent calculation boundary")
    selected = copy.deepcopy(main)
    selected.body = selected.body[:boundaries[0]]
    forbidden = ("manuscript_working", "reviewer_tracker", "revision_status")
    if any(isinstance(n, ast.Constant) and isinstance(n.value, str) and any(s in n.value for s in forbidden)
           for node in selected.body for n in ast.walk(node)):
        raise ValueError("Calculation prefix contains document/status edits")
    text = ast.unparse(ast.Module(body=[selected], type_ignores=[])) + "\n"
    if ast.dump(selected, include_attributes=False) != ast.dump(ast.parse(text).body[0], include_attributes=False):
        raise ValueError("Calculation AST changed")
    return text, {"main_top_level_statements": boundaries[0], "main_prefix_ast_identical": True,
                  "output_boundary": output, "before_assignment": before}


def relocated_original(value, old_raw, local_raw):
    candidate = PureWindowsPath(str(value))
    try:
        relative = candidate.relative_to(PureWindowsPath(old_raw))
    except ValueError:
        raise ValueError(f"Unexpected original-record path: {value}") from None
    if ".." in relative.parts:
        raise ValueError("Original-record path escapes archive")
    return local_raw.joinpath(*relative.parts)


def raw_metrics_check(workspace, package, modules):
    old_rows = rows(workspace / "revision/audit/historical_run_audit.csv")
    fresh = rows(workspace / "reextracted/audit/historical_run_audit.csv")
    old = {r["run"]: r for r in old_rows}
    if len(fresh) != 240 or {r["run"] for r in fresh} != set(old) or len(old) != 240:
        raise ValueError("Incomplete or duplicate original run coverage")
    cells, corrections = 0, []
    for row in fresh:
        expected = load(package / "expected_metrics" / (row["run"] + ".json"))
        for name, value in expected.items():
            cells += compare_value("" if value is None else str(value), row[name], f"{row['run']}.{name}")
        original = old[row["run"]]
        for name, value in original.items():
            if name not in ("source_dir", "collision_teleport_events", "teleport_causes_json"):
                cells += compare_value(value, row[name], f"historical.{row['run']}.{name}")
        parsed = modules["audit_metrics"].warning_metrics(Path(row["source_dir"]) / "sumo_stderr.log")
        correction = modules["audit_warning_exposure_stage14"].reconcile_collision_subtypes(
            original, parsed, (Path(row["source_dir"]) / "sumo_stderr.log").read_text(encoding="utf-8"))
        if correction:
            corrections.append(correction)
        elif original["teleport_causes_json"] != row["teleport_causes_json"]:
            raise ValueError("Unexpected historical cause difference")
        if int(row["end_loaded"]) != int(row["end_inserted"]) + int(row["end_waiting"]):
            raise ValueError("Planned population mismatch")
        if int(row["end_inserted"]) != int(row["end_arrived"]) + int(row["end_running"]):
            raise ValueError("Inserted population mismatch")
    documented = rows(package / "expected/warning_exposure_v1/historical_cause_corrections.csv")
    compare_value(sorted(documented, key=lambda r: r["run"]),
                  sorted([{k: str(v) for k, v in r.items()} for r in corrections], key=lambda r: r["run"]),
                  "previously_documented_cause_corrections")
    return {"runs": len(fresh), "raw_metric_fields_checked": cells,
            "previously_documented_corrected_runs": len(corrections),
            "previously_documented_reclassified_events": sum(r["reclassified_events"] for r in corrections)}, {r["run"]: r for r in fresh}


def factorial_contrasts(records, measures):
    factors = ("HV", "WR", "RT", "LT")
    keys = [(int(r["seed"]), tuple(int(r[f]) for f in factors)) for r in records]
    if len(keys) != 48 or len(set(keys)) != 48 or {s for s, _ in keys} != {42, 2024, 2025}:
        raise ValueError("Expected complete three-seed, four-factor factorial design")
    contrasts = []
    for seed in (42, 2024, 2025):
        group = [r for r in records if int(r["seed"]) == seed]
        base = next(r for r in group if all(int(r[f]) == 0 for f in factors))
        b = measures[base["scenario_run"]]
        effects = []
        for row in group:
            a = measures[row["scenario_run"]]
            effects.append({**{f: int(row[f]) for f in factors},
                            "throughput_loss_interaction": -100 * (float(a["end_arrived"]) - float(b["end_arrived"])) / float(b["end_arrived"]),
                            "time_loss_interaction": 100 * (float(a["trip_completed_timeLoss_mean_s"]) - float(b["trip_completed_timeLoss_mean_s"])) / float(b["trip_completed_timeLoss_mean_s"])})
        for i, first in enumerate(factors):
            for second in factors[i + 1:]:
                result = {"seed": seed, "first": first, "second": second}
                for metric in ("throughput_loss_interaction", "time_loss_interaction"):
                    means = {(a, b): statistics.mean(r[metric] for r in effects if r[first] == a and r[second] == b)
                             for a in (0, 1) for b in (0, 1)}
                    result[metric] = means[1, 1] - means[1, 0] - means[0, 1] + means[0, 0]
                contrasts.append(result)
    return contrasts


def validate_processed_sources(root, measures):
    cells, counts = 0, {}
    for name in ("sumo_multiseed_results.csv", "sumo_keyseed_results.csv", "sumo_factorial_results.csv"):
        records = rows(root / "frozen/data" / name)
        counts[name] = len(records)
        if len(records) != {"sumo_multiseed_results.csv": 81, "sumo_keyseed_results.csv": 90, "sumo_factorial_results.csv": 48}[name]:
            raise ValueError("Processed series coverage changed")
        for row in records:
            run = row["scenario_run"] if name == "sumo_factorial_results.csv" or int(row["seed"]) != 42 else row["scenario"]
            actual = measures[run]
            cells += compare_value(row["seed"], actual["seed"], run + ".seed")
            for raw, processed in (("end_arrived", "arrived_vehicles"), ("trip_completed_timeLoss_mean_s", "mean_time_loss"), ("mean_halted_vehicles", "mean_halting")):
                cells += compare_value(row[processed], actual[raw], run + "." + raw)
    contrasts = factorial_contrasts(rows(root / "frozen/data/sumo_factorial_results.csv"), measures)
    archived = rows(root / "frozen/data/sumo_factorial_interactions_by_seed.csv")
    lookup = {(int(r["seed"]), r["first"], r["second"]): r for r in archived}
    if len(lookup) != 18:
        raise ValueError("Unexpected factorial contrast coverage")
    for row in contrasts:
        expected = lookup[row["seed"], row["first"], row["second"]]
        for metric in ("throughput_loss_interaction", "time_loss_interaction"):
            cells += compare_value(expected[metric], row[metric], "factorial." + str(row["seed"]) + metric)
    return {"source_records": counts, "matched_raw_fields": cells, "factorial_contrast_cells": 36,
            "scope": "Series overlap is retained; counts are not independent runs. All interaction contrasts average the other two factors."}


def run(package, destination):
    package, destination = package.resolve(), destination.resolve()
    manifest = load(package / "manifest.json")
    verify_package(package, manifest)
    if destination.exists() or destination.is_relative_to(package):
        raise FileExistsError("Use a fresh output outside the package")
    workspace = destination / "workspace"
    shutil.copytree(package / "inputs", workspace)
    root, raw = workspace / "revision", workspace / "road_capacity_sci/outputs/sumo_runs"
    (workspace / "reextracted/audit").mkdir(parents=True)
    sys.path.insert(0, str(package / "frozen_code"))
    make_stub("freeze_submission", sha256=sha)
    make_stub("run_timepilot", ROOT=root, SUMO=Path("not_executed"))
    make_stub("run_horizon_v1", ROOT=root, OUT=root / "horizon_audit_v1", sha=sha)
    modules = {n: importlib.import_module(n) for n in manifest["module_names"]}
    for module in modules.values():
        module.ROOT = root
    modules["audit_historical"].ROOT = workspace / "reextracted"
    modules["audit_historical"].RAW = raw
    for name, folder in (("audit_setup_stage13", "configuration_lineage_v1"), ("audit_oat_precision_stage13", "oat_precision_v1"),
                         ("audit_warning_exposure_stage14", "warning_exposure_v1"), ("analyze_precision_stage11", "statistical_precision_v1")):
        modules[name].OUT = root / folder
        (root / folder).mkdir(exist_ok=True)
    modules["analyze_precision_stage11"].DATA = root / "frozen/data"
    (root / "horizon_audit_v1").mkdir()
    for name in PREFIXES:
        code = (package / "adapters" / (name + ".py")).read_text(encoding="utf-8")
        exec(compile(code, "calculation_prefix_" + name, "exec"), modules[name].__dict__)
    install_read_isolation(manifest["original_root"], package, destination)
    install_read_isolation(manifest["original_raw"], package, destination)
    # Only recorded paths change in these workspace copies; raw XML/logs remain byte-identical.
    for name, field in (("historical_run_audit.csv", "source_dir"), ("raw_output_manifest.csv", "path")):
        path = root / "audit" / name
        records = rows(path)
        for row in records:
            row[field] = str(relocated_original(row[field], manifest["original_raw"], raw))
        modules["audit_metrics"].write_csv(path, records)
    print("BEGIN raw_metric_reextraction_240", flush=True)
    modules["audit_historical"].main()
    raw_check, measures = raw_metrics_check(workspace, package, modules)
    source_check = validate_processed_sources(root, measures)
    print("END raw_metric_reextraction_240", flush=True)
    for name in ("legacy_population_stage9", "audit_setup_stage13", "audit_oat_precision_stage13", "audit_warning_exposure_stage14", "analyze_precision_stage11"):
        print("BEGIN " + name, flush=True)
        modules[name].main()
        print("END " + name, flush=True)
    comparisons = []
    for name in manifest["expected_outputs"]:
        expected, actual = package / "expected" / name, root / name
        left, right = (load(expected), load(actual)) if expected.suffix == ".json" else (rows(expected), rows(actual))
        count = compare_value(left, right, name)
        comparisons.append({"path": name, "values_match": True, "cells_checked": count,
                            "byte_identical": sha(expected) == sha(actual), "reproduced_sha256": sha(actual)})
    for name, digest in manifest["input_sha256"].items():
        if name in ("revision/audit/historical_run_audit.csv", "revision/audit/raw_output_manifest.csv"):
            continue
        if sha(workspace / name) != digest:
            raise ValueError(f"Input changed during reanalysis: {name}")
    verify_package(package, manifest)
    report = {"scope": "Five original-study analysis chains reproduced from 240 archived executions",
              "existing_original_runs": 240, "raw_metric_check": raw_check, "processed_source_check": source_check,
              "outputs_verified": len(comparisons), "byte_identical_outputs": sum(r["byte_identical"] for r in comparisons),
              "cells_checked": sum(r["cells_checked"] for r in comparisons), "outputs": comparisons,
              "numpy_version": np.__version__, "source_archive_reads_blocked_during_analysis": True,
              "archived_source_modules_unchanged": True, "calculation_prefixes_ast_identical": True,
              "new_simulations": 0, "public_deposition_complete": False, "independent_validation_complete": False}
    (destination / "reproduction_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "outputs"}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(Path(__file__).resolve().parent, args.output)
