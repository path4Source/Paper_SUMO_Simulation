"""Recompute count-channel and fixed-clock step checks from archived output."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from audit_metrics import audit_run, write_csv
from analyze_independent_intervention_v1 import local_metrics
from stopline_instrumentation import lane_inventory
from blind_test_v2_tools import features_for_case, interval, percent
from diagnostic_rules_v2_draft import classify, VARIANTS
from followup_core import reconcile, queue_duration, xml_digest, band_status, validate_population


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def safe(root, relative):
    if ":" in relative or "\\" in relative or ".." in Path(relative).parts:
        raise ValueError(f"Unsafe relative path: {relative}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path leaves data root: {relative}")
    return path


def compare_csv(rows, path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        expected = list(csv.DictReader(stream))
    assert len(rows) == len(expected), path.name
    checked = 0
    for index, (actual, target) in enumerate(zip(rows, expected)):
        assert set(actual) == set(target), (path.name, index, set(actual) ^ set(target))
        for key, value in actual.items():
            target_value = target[key]
            if isinstance(value, bool):
                equal = str(value) == target_value
            elif isinstance(value, (int, float)):
                equal = math.isfinite(value) and math.isclose(value, float(target_value), rel_tol=1e-12, abs_tol=1e-9)
            elif value is None:
                equal = target_value == ""
            else:
                equal = str(value) == target_value
            if not equal:
                raise AssertionError((path.name, index, key, value, target_value))
            checked += 1
    return checked


def replay_evidence(directory, reference=None):
    saved = read(directory / "equivalence.json")
    for name, tags in (("summary.xml", {"step"}), ("tripinfo.xml", {"tripinfo"}),
                       ("stopline_events.xml", {"instantOut"}), ("lane_queues.xml", {"interval"}),
                       ("collisions.xml", {"collision"})):
        actual = xml_digest(directory / name, tags)
        record = saved[name]
        expected = record.get("reference", record.get("original"))
        assert actual == expected, (directory.name, name)
        if reference is not None:
            assert actual == xml_digest(reference / name, tags), (directory.name, name, "reference")
    assert saved["warnings"]["equal"]
    if reference is not None:
        assert (directory / "sumo_stderr.log").read_bytes() == (reference / "sumo_stderr.log").read_bytes()


def measurement_job(task):
    job, raw_root = task
    directory = safe(Path(raw_root), job["raw_path"])
    inventory = lane_inventory(directory / "network.net.xml")
    reference = safe(Path(raw_root).parent, job["reference_raw_path"]) if job.get("reference_raw_path") else None
    replay_evidence(directory, reference)
    rows = reconcile(directory, inventory)
    if job["family"] == "BH":
        common = {k: job[k] for k in ("case", "state", "plan", "seed")}
        return {"family": "BH", "case": job["case"],
                "counts": [{**common, **r} for r in rows],
                "queues": [{**common, **r} for r in queue_duration(directory, inventory)]}
    return {"family": "BK", "case": job["case"], "counts": [dict(case=job["case"], **r) for r in rows]}


def refinement_job(task):
    job, raw_root, groups = task
    base = Path(raw_root) if not job["reused"] else Path(raw_root).parent
    directory = safe(base, job["raw_path"])
    a = audit_run(directory)
    validate_population(a)
    assert a["step_s"] == job["step_s"] and a["action_step_s"] == 0.1
    network = directory / "network.net.xml"
    if not network.exists():
        network = ROOT / "data/network.net.xml"
    assert sha(network) == job["network_sha256"]
    lanes = local_metrics(directory, lane_inventory(network))
    row = dict(case=job["case"], state=job["state"], seed=job["seed"], sigma_s=job["sigma_s"], step_s=job["step_s"],
               Q=a["end_arrived"], B=a["total_vehicle_hours_discrete"], D=a["trip_completed_timeLoss_mean_s"],
               entry_vh=a["entry_vehicle_hours_discrete"], running=a["end_running"], waiting=a["end_waiting"],
               teleports=a["teleport_events"], collisions=a["stat_safety_collisions"],
               tau_step_warning=a["tau_step_warning"], tau_action_warning=a["tau_action_warning"])
    for group, selected in groups.items():
        row[group + "_crossings"] = sum(lanes[l]["crossings"] for l in selected)
    return row


def count_channel(counts, groups, output):
    indexed = {}
    for row in counts:
        indexed.setdefault(row["case"], {})[row["lane"]] = row
    observed = read(ROOT / "data/observable_cases.json")
    corrected = copy.deepcopy(observed)
    seeds = [211, 307, 401, 503, 601]
    for case in corrected["cases"]:
        for arm in ("reference", "treatment"):
            identity = "B00" if arm == "reference" else case["case_id"]
            for row in case[arm]:
                lanes = indexed[f"holdout_{identity}_seed{row['seed']}"]
                for group, selected in groups.items():
                    row["local"][group]["front_crossings"] = sum(lanes[l]["corrected_left"] for l in selected)
    locked = {r["case_id"]: r for r in read(ROOT / "data/predictions_LOCKED.json")["rows"]}
    comparisons, details, changes = [], [], []
    for old, new in zip(observed["cases"], corrected["cases"]):
        f0, s0 = features_for_case(old, seeds, list(groups), ["target"])
        f1, s1 = features_for_case(new, seeds, list(groups), ["target"])
        for variant in VARIANTS:
            a, b = classify(f0, s0, variant), classify(f1, s1, variant)
            assert a == locked[old["case_id"]]["predictions"][variant]
            comparisons.append(dict(case_id=old["case_id"], variant=variant, identical=a == b,
                                     changed_fields=";".join(k for k in a if a[k] != b[k])))
            details.append(dict(case_id=old["case_id"], variant=variant, original=a, second_channel=b))
        for group in groups:
            values = []
            for i in range(5):
                a = percent(old["treatment"][i]["local"][group]["front_crossings"], old["reference"][i]["local"][group]["front_crossings"])
                b = percent(new["treatment"][i]["local"][group]["front_crossings"], new["reference"][i]["local"][group]["front_crossings"])
                values.append(b-a)
            changes.append(dict(case_id=old["case_id"], group=group, unit="percentage points", **interval(values)))
    checked = 0
    for name, rows in (("all_84_prediction_comparisons.csv", comparisons), ("paired_crossing_response_changes.csv", changes)):
        checked += compare_csv(rows, ROOT / "expected/BK" / name)
        write_csv(output / name, rows)
    assert details == read(ROOT / "expected/BK/prediction_details.json")
    assert corrected == read(ROOT / "expected/BK/observations_second_channel.json")
    save(output / "prediction_details.json", details)
    save(output / "observations_second_channel.json", corrected)
    return dict(predictions=len(comparisons), identical=sum(r["identical"] for r in comparisons),
                paired_group_intervals=len(changes), checked_csv_fields=checked)


def numerical_checks(rows, output):
    seeds, periods, steps = [11, 29, 47, 71, 101], [0.1, 1.0], [0.1, 0.05, 0.02]
    states = ["baseline", "heavyveh_very_high", "weather_heavy_rain"]
    bands = {"Q": 2.0, "B": 5.0}
    indexed = {(r["sigma_s"], r["state"], r["seed"], r["step_s"]): r for r in rows}
    assert len(indexed) == 90
    contrasts, effects, shifts = [], [], []
    for sigma in periods:
        for state in states:
            for metric in ["Q", "B", "D", "target_crossings", "donor_crossings", "other_crossings"]:
                for coarse, fine in zip(steps, steps[1:]):
                    values = [percent(indexed[sigma,state,s,fine][metric], indexed[sigma,state,s,coarse][metric]) for s in seeds]
                    stats, band = interval(values), bands.get(metric)
                    contrasts.append(dict(sigma_s=sigma, state=state, metric=metric, coarse_s=coarse, fine_s=fine,
                        unit="percent", **stats, band=band, status=band_status(stats, band) if band is not None else "descriptive"))
                if state == "baseline":
                    continue
                response = {}
                for step in steps:
                    response[step] = [percent(indexed[sigma,state,s,step][metric], indexed[sigma,"baseline",s,step][metric]) for s in seeds]
                    effects.append(dict(sigma_s=sigma, state=state, metric=metric, step_s=step, unit="percent", **interval(response[step])))
                for coarse, fine in zip(steps, steps[1:]):
                    stats, band = interval([b-a for a,b in zip(response[coarse], response[fine])]), bands.get(metric)
                    shifts.append(dict(sigma_s=sigma, state=state, metric=metric, coarse_s=coarse, fine_s=fine,
                        unit="percentage points", **stats, band=band, status=band_status(stats, band) if band is not None else "descriptive"))
    checked = 0
    for name, values in (("all_90_run_metrics.csv", rows), ("within_state_step_changes.csv", contrasts),
                         ("paired_scenario_responses.csv", effects), ("scenario_response_step_changes.csv", shifts)):
        checked += compare_csv(values, ROOT / "expected/BL" / name)
        write_csv(output / name, values)
    primary = [r for r in contrasts + shifts if r["metric"] in bands]
    finest = [r for r in primary if r["fine_s"] == 0.02]
    assert (len(primary), len(finest)) == (40, 20)
    counts = {s: sum(r["status"] == s for r in finest) for s in ("within_band", "outside_band", "inconclusive")}
    assert counts == {"within_band": 0, "outside_band": 1, "inconclusive": 19}
    return dict(run_records=90, primary_comparisons=40, finest_comparisons=20,
                finest_status=counts, checked_csv_fields=checked, convergence_established=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    raw, output = args.raw_root.resolve(), args.output.resolve()
    if not 1 <= args.workers <= 8 or output.exists() or output.is_relative_to(ROOT) or output.is_relative_to(raw.parent):
        raise ValueError("Use 1-8 workers and a fresh output directory outside the repository and raw data")
    manifest = read(ROOT / "manifest.json")
    for name, expected in manifest["files_sha256"].items():
        assert sha(safe(ROOT, name)) == expected, name
    raw_manifest = read(ROOT / "raw_manifest.json")
    for index, (name, expected) in enumerate(raw_manifest["files_sha256"].items(), 1):
        assert sha(safe(raw, name)) == expected, name
        if index % 500 == 0:
            print(f"Follow-up raw hashes: {index}", flush=True)
    for name, expected in raw_manifest["reference_files_sha256"].items():
        assert sha(safe(raw.parent, name)) == expected, name
    output.mkdir(parents=True)
    jobs = read(ROOT / "data/portable_jobs.json")
    groups = read(ROOT / "data/monitored_groups.json")
    all_counts = {"BH": [], "BK": []}
    queue_rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks = [(job, str(raw)) for job in jobs["measurement"]]
        for i, result in enumerate(pool.map(measurement_job, tasks), 1):
            all_counts[result["family"]].extend(result["counts"])
            queue_rows.extend(result.get("queues", []))
            print(f"Measurement reconstruction: {i}/110 {result['case']}", flush=True)
        rows = []
        tasks = [(job, str(raw), groups) for job in jobs["numerical"]]
        for i, row in enumerate(pool.map(refinement_job, tasks), 1):
            rows.append(row)
            print(f"Step-check reconstruction: {i}/90 {row['case']}", flush=True)
    checked = 0
    for family in ("BH", "BK"):
        checked += compare_csv(all_counts[family], ROOT / "expected" / family / "lane_count_reconciliation.csv")
        write_csv(output / (family + "_lane_count_reconciliation.csv"), all_counts[family])
    checked += compare_csv(queue_rows, ROOT / "expected/BH/detector_extent_attainment.csv")
    write_csv(output / "BH_detector_extent_attainment.csv", queue_rows)
    channel = count_channel(all_counts["BK"], groups, output)
    numerical = numerical_checks(rows, output)
    control = safe(raw, jobs["control"]["raw_path"])
    reference = safe(raw.parent, jobs["control"]["reference_raw_path"])
    # The separately recorded amendment allows only removal of passive FCD device metadata.
    control_audit = read(control / "metadata_resolution.json")
    assert control_audit["equal_all_non_device_trip_attributes"]
    assert control_audit["amendment_sha256"] == sha(ROOT / "records/BL/control_metadata_amendment.json")
    replay_evidence_control(control, reference)
    assert (len(all_counts["BH"]), len(all_counts["BK"]), sum(r["steps"] for r in queue_rows)) == (1590, 4240, 57240000)
    report = dict(raw_files_hash_checked=len(raw_manifest["files_sha256"]), reference_files_hash_checked=len(raw_manifest["reference_files_sha256"]),
        new_simulations=0, unique_added_executions=171, reused_numerical_references=30,
        BH_exact_lane_counts=sum(r["residual"] == 0 for r in all_counts["BH"]),
        BK_exact_lane_counts=sum(r["residual"] == 0 for r in all_counts["BK"]),
        BH_queue_samples=57240000, measurement_csv_fields_checked=checked,
        BH_replay_digest_scope="Archived original digests; original BH source runs are not reparsed by this entry point",
        BK_original_vs_replay_records_reparsed=80, technical_control_reparsed=True,
        count_channel=channel, numerical=numerical, independent_correctness_complete=False)
    save(output / "verification.json", report)
    print(json.dumps(report, indent=2), flush=True)


def replay_evidence_control(directory, reference):
    for name, tags in (("summary.xml", {"step"}), ("stopline_events.xml", {"instantOut"}),
                       ("lane_queues.xml", {"interval"}), ("collisions.xml", {"collision"})):
        assert xml_digest(directory / name, tags) == xml_digest(reference / name, tags)
    from followup_core import records
    original = list(records(reference / "tripinfo.xml", "tripinfo"))
    repeated = list(records(directory / "tripinfo.xml", "tripinfo"))
    assert len(original) == len(repeated)
    for a, b in zip(original, repeated):
        expected_devices = [item for item in a.pop("devices", "").split() if item != "fcd_" + a["id"]]
        assert expected_devices == b.pop("devices", "").split()
        assert a == b
    assert (directory / "sumo_stderr.log").read_bytes() == (reference / "sumo_stderr.log").read_bytes()


if __name__ == "__main__":
    main()
