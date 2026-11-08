"""Replay the unchanged frozen estimator from audited processed run records.

Only data-loading and CSV/hash helper bindings are supplied locally. No SUMO
execution, raw-XML re-extraction, document compilation or network access occurs.
"""
import argparse
import importlib.metadata
import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path

import numpy as np

from frozen_helpers import sha256, validate_design, write_csv
from reproduction_compare import compare_file, verify_manifest
import frozen_helpers

ROOT = Path(__file__).resolve().parent
PRIMARY = ["arrived_veh_per_h", "total_vehicle_hours_discrete"]


def output_path(root, requested):
    target = (root / requested).resolve()
    if target.exists():
        raise ValueError("Output exists; preserve it and choose a new path")
    for name in ("inputs", "expected"):
        if target.is_relative_to((root / name).resolve()):
            raise ValueError("Output cannot be inside protected inputs or expected results")
    if target == root.resolve():
        raise ValueError("Output cannot be the release root")
    return target


def verify_records(root, manifest):
    protocol_path = root / "inputs/protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if sha256(protocol_path) != manifest["protocol_sha256"]:
        raise ValueError("Protocol differs")
    expected = {
        f"t{p['trajectory']:02d}_p{p['position']:02d}_seed{s}": (p, s)
        for p in protocol["design_rows"] for s in protocol["simulation_seeds"]
    }
    expected.update({f"control_seed{s}": (None, s) for s in protocol["simulation_seeds"]})
    records = {p.parent.name: p for p in (root / "inputs/runs").glob("*/complete.json")}
    if records.keys() != expected.keys() or len(records) != 665:
        raise ValueError("Missing or extra design/control records")
    for name, path in records.items():
        record = json.loads(path.read_text(encoding="utf-8"))
        row = record["audit"]
        p, seed = expected[name]
        if record["protocol_sha256"] != manifest["protocol_sha256"] or row["seed"] != seed:
            raise ValueError(f"Protocol/seed mismatch: {name}")
        if p is None:
            if row["kind"] != "control" or row.get("output_equivalence_verified") is not True:
                raise ValueError(f"Unverified equivalence control: {name}")
        else:
            if row["kind"] != "design":
                raise ValueError(f"Not a design record: {name}")
            for key in ("point", "trajectory", "position", *protocol["problem"]["names"]):
                if row[key] != p[key]:
                    raise ValueError(f"Point/input mismatch: {name}/{key}")
        frozen_helpers.check_accounting(row, row["planned"])
    return protocol


def bindings(root, out, manifest, protocol):
    frozen_helpers.PROBLEM = protocol["problem"]
    frozen_helpers.SPECS = protocol["problem"]["names"]
    frozen_helpers.LEVELS = protocol["levels"]
    frozen_helpers.TRAJECTORIES = protocol["retained_trajectories"]

    def verify_processed(directory, digest):
        name = f"inputs/runs/{directory.name}/complete.json"
        path = directory / "complete.json"
        if digest != manifest["protocol_sha256"] or sha256(path) != manifest["files_sha256"][name]:
            raise ValueError(f"Processed record changed: {directory.name}")
        return json.loads(path.read_text(encoding="utf-8"))

    modules = {}
    for name, members in {
        "audit_metrics": {"write_csv": write_csv},
        "freeze_submission": {"sha256": sha256},
        "run_morris_v1": {
            "OUT": out, "PROBLEM": protocol["problem"], "SEEDS": protocol["simulation_seeds"],
            "SPECS": protocol["problem"]["names"], "LEVELS": protocol["levels"],
            "TRAJECTORIES": protocol["retained_trajectories"], "validate_design": validate_design,
            "verify_complete": verify_processed,
        },
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(members)
        modules[name] = module
    return modules


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="generated")
    args = parser.parse_args(argv)
    manifest = verify_manifest(ROOT)
    versions = {name: importlib.metadata.version(name) for name in manifest["python_packages"]}
    if versions != manifest["python_packages"]:
        raise RuntimeError(f"Recorded versions required for exact replay: {versions}")
    protocol = verify_records(ROOT, manifest)
    out = output_path(ROOT, args.output)
    out.mkdir(parents=True)
    for name in ("protocol.json", "analysis_code_freeze.json"):
        shutil.copy2(ROOT / "inputs" / name, out / name)
    shutil.copytree(ROOT / "inputs/runs", out / "runs")
    supplied = bindings(ROOT, out, manifest, protocol)
    saved = {name: sys.modules.get(name) for name in supplied}
    old_argv = sys.argv
    try:
        sys.modules.update(supplied)
        spec = importlib.util.spec_from_file_location("frozen_morris_analyzer", ROOT / "frozen_analyzer.py")
        analyzer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(analyzer)
        sys.argv = [str(ROOT / "frozen_analyzer.py")]
        analyzer.main()
    finally:
        sys.argv = old_argv
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    comparisons = [compare_file(ROOT / "expected" / name, out / name)
                   for name in manifest["analysis_outputs"]]
    if len(comparisons) != 6 or not all(r["byte_identical"] for r in comparisons):
        raise RuntimeError("Expected six byte-identical analysis CSVs in the recorded environment")
    actual = json.loads((out / "analysis_manifest.json").read_text(encoding="utf-8"))
    expected = json.loads((ROOT / "expected/analysis_manifest.json").read_text(encoding="utf-8"))
    fields = ("protocol_sha256", "analyzer_sha256", "design_runs", "warning_free_runs",
              "warning_exposed_runs", "raw_response_only", "physical_or_causal_validation",
              "ci_scope", "range_scope")
    if any(actual[k] != expected[k] for k in fields):
        raise RuntimeError("Analysis manifest semantics differ")
    verify_manifest(ROOT)
    report = {
        "scope": "Relocated processed-data reanalysis; not raw-output extraction, SUMO replay or independent validation.",
        "design_records": 660, "equivalence_controls": 5,
        "csv_outputs_verified": len(comparisons), "csv_outputs": comparisons,
        "frozen_analyzer_byte_identical": sha256(ROOT / "frozen_analyzer.py") == manifest["analyzer_sha256"],
        "io_adapter": "Explicit local processed-record loader; estimator and helper bodies unchanged",
        "manifest_nonidentical_fields": "Timestamp and hashes of exported processed records",
        "new_simulations": 0, "input_hashes_preserved": True,
        "public_upload": False, "license_granted": False, "python_packages": versions,
    }
    (out / "reproduction_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
