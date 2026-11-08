"""Reconstruct held-out measurements from archived SUMO output, then replay rules."""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "measurement_sources"))
from audit_metrics import audit_run
from analyze_independent_intervention_v1 import local_metrics
from stopline_instrumentation import lane_inventory


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained(root, name):
    if "\\" in name or ":" in name or ".." in Path(name).parts:
        raise ValueError(f"Unsafe archive member: {name}")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Archive member leaves its root: {name}")
    return path


def observation(directory, groups, inventory):
    a = audit_run(directory)
    lanes = local_metrics(directory, inventory)
    if a["unaccounted_inserted_end"] != 0:
        raise ValueError(f"Unreconciled vehicle population: {directory.name}")
    return dict(seed=a["seed"], begin_s=0, end_s=3600,
        planned=a["end_loaded"], inserted=a["end_inserted"], arrived=a["end_arrived"],
        running=a["end_running"], waiting=a["end_waiting"],
        entry_vh=a["entry_vehicle_hours_discrete"], network_vh=a["network_vehicle_hours_discrete"],
        total_vh=a["total_vehicle_hours_discrete"], completed_delay_s=a["trip_completed_timeLoss_mean_s"],
        teleports=a["teleport_events"], collisions=int(a["stat_safety_collisions"]),
        timing_warning=bool(a["tau_step_warning"] or a["tau_action_warning"] or a["integration_action_warning"]),
        local={group: {"front_crossings": sum(lanes[lane]["crossings"] for lane in selected),
                       "queue_m": sum(lanes[lane]["queue_m"] for lane in selected)}
               for group, selected in groups.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw, output = args.raw_root.resolve(), args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT) or output.is_relative_to(raw):
        raise ValueError("Choose a fresh output directory outside code and raw inputs")
    output.mkdir(parents=True)
    spec = importlib.util.spec_from_file_location("processed_replay", ROOT / "reproduce.py")
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    replay.verify()
    records = read(ROOT / "raw_package_manifest.json")["files_sha256"]
    for name, expected in records.items():
        path = contained(raw, name)
        if not path.is_file() or sha(path) != expected:
            raise ValueError(f"Missing or changed raw file: {name}")
    protocol = read(ROOT / "data/protocol.json")["protocol"]
    groups = read(ROOT / "data/monitored_groups.json")
    inventory = lane_inventory(ROOT / "inputs/holdout/B00_seed211/network.net.xml")
    runs = read(ROOT / "input_inventory.json")["runs"]
    observed, bridge = {}, []
    for index, run in enumerate(runs, 1):
        name = run["case"]
        folder = contained(raw, name)
        if name.startswith("holdout/"):
            observed[name] = observation(folder, groups, inventory)
        else:
            a = audit_run(folder)
            if a["unaccounted_inserted_end"] != 0:
                raise ValueError(f"Unreconciled bridge population: {name}")
            state = Path(name).name.rsplit("_seed", 1)[0]
            bridge.append(dict(state=state, seed=a["seed"],
                setting="explicit_sigma_step_1.0" if run["new_in_revision"] else "implicit_sigma_step_0.1",
                Q=a["end_arrived"], B=a["total_vehicle_hours_discrete"],
                D=a["trip_completed_timeLoss_mean_s"],
                burden_per_planned_s=3600*a["total_vehicle_hours_discrete"]/a["end_loaded"],
                teleports=a["teleport_events"], collisions=a["stat_safety_collisions"]))
        print(f"Measurements reconstructed: {index}/{len(runs)} {name}", flush=True)
    baseline = [observed[f"holdout/B00_seed{seed}"] for seed in protocol["holdout"]["seeds"]]
    cases = []
    for template in read(ROOT / "data/observable_cases.json")["cases"]:
        case = dict(template)
        case["reference"] = baseline
        case["treatment"] = [observed[f"holdout/{case['case_id']}_seed{seed}"] for seed in protocol["holdout"]["seeds"]]
        if case != template:
            raise AssertionError(f"Reconstructed measurements differ: {case['case_id']}")
        cases.append(case)
    with (ROOT / "data/bridge_run_metrics.csv").open(encoding="utf-8-sig", newline="") as stream:
        expected = {(r["state"], int(r["seed"]), r["setting"]): r for r in csv.DictReader(stream)}
    for row in bridge:
        target = expected[row["state"], row["seed"], row["setting"]]
        for key in ("Q", "B", "D", "burden_per_planned_s", "teleports", "collisions"):
            if not math.isclose(row[key], float(target[key]), rel_tol=1e-12, abs_tol=1e-9):
                raise AssertionError(f"Bridge measurement differs: {row['state']} {row['seed']} {key}")
    assert len(observed) == 65 and len(bridge) == 30
    # Exact measurement agreement connects raw reconstruction to the locked predictions.
    original, alternative = replay.verify_holdout(True), replay.verify_holdout(False)
    intervals = replay.verify_bridge()
    report = dict(raw_files_verified=len(records), raw_run_records=95, distinct_added_executions=80,
        reused_reference_executions=15, holdout_measurements_reconstructed=65,
        bridge_measurements_reconstructed=30, holdout_original=original,
        holdout_alternative=alternative, bridge=intervals, new_simulations=0,
        vehicle_balance_errors=0, independent_correctness_validated=False,
        independent_sensor_validation_complete=False, public_deposition_complete=False)
    for name, value in (("observations_reconstructed.json", {"cases": cases}),
                        ("bridge_reconstructed.json", bridge), ("verification.json", report)):
        (output / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("holdout_original", "holdout_alternative", "bridge")}, indent=2))


if __name__ == "__main__":
    main()
