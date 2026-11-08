"""Re-extract every Morris record and replay the unchanged frozen analyzer."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from frozen_helpers import check_accounting, sha256
from frozen_metrics import audit_run
from reproduction_compare import compare_values, verify_manifest
from run_reproduction import verify_records

ROOT = Path(__file__).resolve().parent
LOCATIONS = {"source_dir", "network_path_recorded"}
METADATA = {"kind", "point", "trajectory", "position", "planned", "planned_trucks",
            "realized_planned_share", "wall_s", "output_equivalence_verified"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def local_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or escaping evidence: {name}")
    return path


def output_path(root, raw, requested):
    out = (root / requested).resolve()
    if out.exists() or out == root.resolve() or out.is_relative_to(raw.resolve()):
        raise ValueError("Preserve existing outputs and raw archive")
    if root.resolve().is_relative_to(out) or raw.resolve().is_relative_to(out):
        raise ValueError("Output cannot be a source ancestor")
    for protected in ("inputs", "expected", "frozen_code"):
        if out.is_relative_to((root / protected).resolve()):
            raise ValueError("Output cannot be inside protected package inputs")
    return out


def raw_hashes(directory, record):
    for name, expected in record["files_sha256"].items():
        if sha256(local_file(directory, name)) != expected:
            raise ValueError(f"Raw evidence changed: {directory.name}/{name}")


def reextract(directory, exported, protocol, expected_complete):
    marker = directory / "complete.json"
    if sha256(marker) != expected_complete:
        raise ValueError(f"Completion marker changed: {directory.name}")
    original = load(marker)
    if original["protocol_sha256"] != exported["protocol_sha256"]:
        raise ValueError("Protocol mismatch")
    if original["files_sha256"] != exported["original_files_sha256"]:
        raise ValueError("Raw hash inventory mismatch")
    raw_hashes(directory, original)
    fresh = {k: v for k, v in audit_run(directory).items() if k not in LOCATIONS}
    metadata = METADATA | set(protocol["problem"]["names"])
    expected = {k: v for k, v in exported["audit"].items() if k not in metadata}
    compare_values(expected, fresh, directory.name)
    check_accounting(fresh, exported["audit"]["planned"])
    rebuilt = copy.deepcopy(exported)
    # Only immutable design/execution metadata are carried over; all measured
    # fields supplied to the estimator come from this fresh raw-output parse.
    rebuilt["audit"] = {k: fresh[k] if k in fresh else v
                        for k, v in exported["audit"].items()}
    if any(k not in fresh and k not in metadata for k in rebuilt["audit"]):
        raise ValueError("Unreconstructed measurement")
    raw_hashes(directory, original)
    if sha256(marker) != expected_complete:
        raise ValueError("Completion marker changed during extraction")
    return rebuilt, {"run": directory.name, "kind": exported["audit"]["kind"],
                     "metrics_reextracted": len(fresh), "raw_files_verified": len(original["files_sha256"]),
                     "teleport_events": fresh["teleport_events"],
                     "all_measured_fields_matched": True,
                     "raw_hashes_verified_before_and_after": True}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", required=True, type=Path,
                        help="Read-only Morris archive containing protocol.json and runs/")
    parser.add_argument("--output", default="raw_reproduction")
    args = parser.parse_args(argv)
    start = time.perf_counter()
    raw = args.raw_root.resolve()
    if (raw / "batch_scheduler.lock").exists():
        raise ValueError("Execution lock remains; do not inspect a changing archive")
    manifest = verify_manifest(ROOT)
    protocol = verify_records(ROOT, manifest)
    if sha256(raw / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("Raw archive uses another protocol")
    names = set(manifest["source_complete_sha256"])
    actual = {p.name for p in (raw / "runs").iterdir() if p.is_dir()}
    if names != actual or len(names) != 665:
        raise ValueError("Missing or extra raw run directories")
    if sha256(ROOT / "frozen_metrics.py") != protocol["code_sha256"]["audit_metrics.py"]:
        raise ValueError("Metric parser differs from the pre-outcome frozen code")
    out = output_path(ROOT, raw, args.output)
    out.mkdir(parents=True)
    derived = out / "reextracted_package"
    derived.mkdir()
    for name in manifest["files_sha256"]:
        if not name.startswith("inputs/runs/"):
            target = derived / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_file(ROOT, name), target)
    checked = []
    try:
        for index, name in enumerate(sorted(names), 1):
            rel = f"inputs/runs/{name}/complete.json"
            rebuilt, detail = reextract(raw / "runs" / name, load(ROOT / rel), protocol,
                                        manifest["source_complete_sha256"][name])
            write(derived / rel, rebuilt)
            if sha256(derived / rel) != manifest["files_sha256"][rel]:
                raise ValueError(f"Fresh measurements change processed record bytes: {name}")
            checked.append(detail)
            if index % 55 == 0 or index == len(names):
                write(out / "extraction_progress.json", {"verified": index, "planned": len(names),
                                                        "new_simulations": 0, "complete": False})
                print(f"Raw records re-extracted and verified: {index}/{len(names)}", flush=True)
        write(out / "raw_record_checks.json", checked)
        shutil.copy2(ROOT / "manifest.json", derived / "manifest.json")
        verify_manifest(derived)
        command = [sys.executable, "-I", "-B", "-c",
                   "import runpy,sys; from pathlib import Path; p=Path(sys.argv[1]).resolve(); "
                   "sys.path.insert(0,str(p.parent)); sys.argv=[str(p)]; runpy.run_path(str(p),run_name='__main__')",
                   str(derived / "run_reproduction.py")]
        proc = subprocess.run(command, cwd=out, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        (out / "analyzer_log.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        if proc.returncode:
            raise RuntimeError("Frozen analysis replay failed; inspect analyzer_log.txt")
        replay = load(derived / "generated/reproduction_report.json")
        verify_manifest(ROOT)
        report = {"scope": "Full raw-output extraction linked to relocated frozen Morris analysis",
                  "design_runs_reextracted": sum(r["kind"] == "design" for r in checked),
                  "control_runs_reextracted": sum(r["kind"] == "control" for r in checked),
                  "measured_fields_reextracted": sum(r["metrics_reextracted"] for r in checked),
                  "raw_files_verified_before_and_after": sum(r["raw_files_verified"] for r in checked),
                  "all_665_rebuilt_processed_records_byte_identical": True,
                  "csv_outputs_verified": replay["csv_outputs_verified"],
                  "csv_outputs": replay["csv_outputs"],
                  "protocol_sha256": manifest["protocol_sha256"],
                  "analyzer_sha256": manifest["analyzer_sha256"],
                  "metric_parser_sha256": sha256(ROOT / "frozen_metrics.py"),
                  "new_simulations": 0, "warning_cases_removed": 0,
                  "independent_human_validation": False, "public_deposition": False,
                  "manuscript_or_frozen_results_modified": False,
                  "raw_archive_storage": "External read-only path supplied explicitly; not bundled or uploaded",
                  "wall_s": time.perf_counter() - start}
        write(out / "verification.json", report)
        print(json.dumps({k: v for k, v in report.items() if k != "csv_outputs"}, indent=2), flush=True)
    except Exception as exc:
        write(out / "failure.json", {"verified_records_before_failure": len(checked),
                                     "type": type(exc).__name__, "error": str(exc),
                                     "raw_archive_modified": False})
        raise


if __name__ == "__main__":
    main()
