"""Run a selected archived configuration from a portable preparation tree."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from audit_metrics import audit_run
from portable_reanalysis_entry import compare_values

ROOT = Path(__file__).resolve().parent
LOCATION_FIELDS = {"run", "source_dir", "network_path_recorded"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def comparable_metrics(metrics):
    return {key: value for key, value in metrics.items() if key not in LOCATION_FIELDS}


def within(root, relative):
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes preparation tree: {relative}")
    return candidate


def verify(root):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["files_sha256"].items():
        path = within(root, relative)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Missing or changed dependency: {relative}")
    return manifest


def output_directory(root, requested):
    target = Path(requested)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    if target.exists():
        raise ValueError("Replay output exists; select a new directory")
    for name in ["cases", "expected"]:
        protected = root / name
        if target.is_relative_to(protected.resolve()):
            raise ValueError("Replay output cannot be placed in protected inputs")
    return target


def resolve_sumo(value):
    located = shutil.which(value)
    if located:
        executable = Path(located).resolve()
    else:
        executable = Path(value).resolve()
    if not executable.is_file():
        raise ValueError("SUMO executable not found")
    version = subprocess.run([str(executable), "--version"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", check=True,
                             timeout=30).stdout
    if not re.search(r"\bVersion\s+1\.24\.0\b", version):
        raise ValueError("This replay requires the recorded SUMO 1.24.0 version")
    return executable, version


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--case", help="Exact family/run identifier shown by --list")
    parser.add_argument("--sumo", default="sumo", help="Executable path or command on PATH")
    parser.add_argument("--output", help="New output directory; defaults to replays/family/run")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    manifest = verify(ROOT)
    if args.list:
        print("\n".join(manifest["cases"]))
        return
    if args.case not in manifest["cases"]:
        raise ValueError("Select an exact recorded case with --case")
    if args.timeout <= 0:
        raise ValueError("Timeout must be positive")
    executable, version = resolve_sumo(args.sumo)
    source = within(ROOT, "cases/" + args.case)
    out = output_directory(ROOT, args.output or "replays/" + args.case)
    expected = json.loads(within(ROOT, manifest["cases"][args.case]["expected_metrics"]).read_text(
        encoding="utf-8"))
    shutil.copytree(source, out)
    started = time.perf_counter()
    report = {
        "case": args.case, "started_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Same-configuration reproducibility check, not a new independent experiment.",
        "sumo_version": version, "sumo_executable_sha256": digest(executable),
        "same_executable_as_archived": digest(executable) == manifest["recorded_sumo_sha256"],
        "input_manifest_sha256": digest(ROOT / "manifest.json"),
        "command": ["sumo", "-c", "run.sumocfg"], "status": "running",
        "public_deposition_complete": False,
    }
    record = out / "replay_report.json"
    record.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Replaying {args.case}; original settings and seed preserved", flush=True)
    try:
        with (out / "sumo_stdout.log").open("w", encoding="utf-8") as stdout, (
                out / "sumo_stderr.log").open("w", encoding="utf-8") as stderr:
            completed = subprocess.run([str(executable), "-c", "run.sumocfg"], cwd=out,
                                       stdout=stdout, stderr=stderr, timeout=args.timeout)
        if completed.returncode:
            raise RuntimeError(f"SUMO exited with code {completed.returncode}")
        actual = comparable_metrics(audit_run(out))
        compare_values(expected, actual)
        verify(ROOT)
        report.update({
            "status": "reproduced", "metrics_compared": len(actual),
            "metrics_match_tolerance": {"absolute": 1e-12, "relative": 1e-12},
            "metrics": actual, "source_preparation_tree_preserved": True,
        })
    except Exception as exc:
        report.update({"status": "failed_preserved", "error": repr(exc)})
        raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        report["wall_s"] = time.perf_counter() - started
        record.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "case": args.case, "status": report["status"], "metrics_compared": len(actual),
        "same_executable_as_archived": report["same_executable_as_archived"],
        "wall_s": report["wall_s"], "independent_validation": False,
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
