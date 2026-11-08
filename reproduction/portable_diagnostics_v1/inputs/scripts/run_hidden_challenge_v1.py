"""Prospectively frozen, parameter-hidden synthetic challenge; no human blinding."""
import argparse
import copy
import json
import random
import subprocess
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from audit_metrics import audit_run, write_csv
from freeze_submission import sha256
from run_timepilot import ROOT, SUMO
from stopline_instrumentation import lane_inventory
from diagnostic_rules_v1 import THRESHOLDS, VARIANTS

OUT = ROOT / "hidden_challenge_v1"
SEEDS = [11, 29, 47, 71, 101]
CONDITIONS = [
    {"name": "sham"},
    {"name": "demand_reduced", "demand": 0.85},
    {"name": "demand_increased", "demand": 1.15},
    {"name": "truck12", "truck": 0.12},
    {"name": "truck20", "truck": 0.20},
    {"name": "headway13", "tau": 1.3},
    {"name": "stochastic065", "sigma": 0.65},
    {"name": "composite_moderate", "speed": 0.90, "accel": 0.85, "decel": 0.90, "sigma": 0.65},
    {"name": "compatible_short_headway", "tau": 0.70},
    {"name": "incompatible_short_headway", "tau": 0.30},
    {"name": "truck12_reduced_demand", "truck": 0.12, "demand": 0.85},
    {"name": "truck12_high_demand", "truck": 0.12, "demand": 1.15},
    {"name": "stochastic_high_demand", "sigma": 0.65, "demand": 1.15},
    {"name": "composite_high_demand", "speed": 0.90, "accel": 0.85, "decel": 0.90, "sigma": 0.65, "demand": 1.15},
    {"name": "incompatible_high_demand", "tau": 0.30, "demand": 1.15},
    {"name": "truck12_incompatible", "truck": 0.12, "tau": 0.30},
]
CODE_FILES = ["run_hidden_challenge_v1.py", "diagnostic_rules_v1.py", "audit_metrics.py",
              "stopline_instrumentation.py", "extract_hidden_measurements_v1.py"]


def cases():
    result = copy.deepcopy(CONDITIONS)
    random.Random(20261020).shuffle(result)
    return [{"case_id": f"C{i:02d}", **row} for i, row in enumerate(result, 1)]


def freeze():
    protocol = {
        "version": "1.0", "kind": "prospective frozen-rule, parameter-hidden internal synthetic challenge",
        "not": "Not independently blinded, not field validation, not unique causal identification, not an external preregistration.",
        "n_conditions": 16, "n_seeds_each": 5, "seeds": SEEDS, "new_runs": 85,
        "baseline_runs": 5, "condition_runs": 80,
        "setting": "SUMO 1.24.0; explicit ballistic; step/action 0.5 s; 0-3600 s; no warmup exclusion; junction collision checks on; collision action teleport; gridlock teleport 300 s.",
        "construction": cases(),
        "scope": "New parameter values/combinations and new seeds in the existing corridor, not an independent network. Values are assumed challenge bounds, not empirical weather/behavior distributions.",
        "demand": "All 25 OD flows scaled uniformly; nearest integer per flow, and rounded truck allocation within each flow. Report realized planned counts and shares.",
        "truck": "Retain archived truck dimensions/behavior, without changing vClass/emissionClass. No emissions in classifier or outcomes.",
        "local": "53 incoming controlled lanes; exact-lane-end instantaneous E1 front entries; E2 final up-to-100m mean maximum jam length in metres, aggregated by three prespecified signal IDs n1/n2/n4. Entire-hour service counts, not green-conditioned saturation flow. Teleport-exposed local counts remain qualified.",
        "inputs_to_rules": "Anonymous case ID outside rule function; five matched seed measurements Q, completed-trip time loss, mean halted vehicles, planned/inserted/running/waiting populations, discrete total vehicle-hours including entry waiting, warning counts/timing warnings, three signal-level local counts/queue measures. No scenario names, vehicle parameters, original routes or construction key passed to classifier.",
        "thresholds": THRESHOLDS, "variants": VARIANTS,
        "uncertainty": "Five seed-wise paired responses; Student t 95% intervals df=4. A direction is supported only when the whole interval passes the predeclared practical threshold. These exploratory intervals are not equivalence tests or multiplicity-adjusted claims. Conditions, not vehicles/cycles, are diagnostic units.",
        "warning_rule": "Any observed collision/teleport or timing compatibility warning requires qualification and vetoes retained improvement. No warning count declared harmless. This does not establish that warnings caused the entire measured response.",
        "threshold_sensitivity": "After fixed primary analysis, report 0.5x and 2x tolerances without changing the primary rules or selecting the better version.",
        "benchmark_truth": "Construction key describes applied inputs, not realized degradation. Demand-source and incompatible-timing detection can be checked against the key, but these are exposed audit facts, not latent-cause accuracy. Supply-family retrieval is descriptive only; absent support or mixed-case abstention is retained, not relabelled. No total diagnostic accuracy or macro-F1 against self-generated performance labels.",
        "ablation": "Same cases/seeds/thresholds for QD, +accounting, +warnings, +local, and leave-one-module-out accounting/warnings. Report status transitions, qualified/unqualified gains, demand attribution safeguards, local corroboration and unresolved cases, not superiority over control algorithms.",
        "execution": "Four subprocesses maximum; retain all completed warning outcomes. Halt on process, missing-output or population-accounting error. Sham must exactly reproduce baseline; otherwise invalidate the challenge until explained. Do not tune after observing outcomes.",
        "source_hashes": {"network": sha256(ROOT / "frozen/inputs/network.net.xml"),
                          "baseline_routes": sha256(ROOT / "core_detector_batch/inputs/baseline.rou.xml"),
                          "truck_routes": sha256(ROOT / "core_detector_batch/inputs/heavyveh_very_high.rou.xml"),
                          "config_template": sha256(ROOT / "core_detector_batch/runs/baseline_seed42/run.sumocfg"),
                          "sumo_binary": sha256(SUMO)},
        "code_hashes": {name: sha256(ROOT / "scripts" / name) for name in CODE_FILES},
    }
    path = OUT / "protocol.json"
    OUT.mkdir(exist_ok=True)
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        old.pop("frozen_utc")
        # Tuples deserialize as lists.
        if old != json.loads(json.dumps(protocol)):
            raise RuntimeError("Frozen protocol/code changed; do not overwrite or reuse outcomes")
    else:
        if (OUT / "runs").exists():
            raise RuntimeError("Outcomes predate protocol")
        path.write_text(json.dumps({**protocol, "frozen_utc": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    private = OUT / "construction_key"
    private.mkdir(exist_ok=True)
    (private / "key.json").write_text(json.dumps(cases(), indent=2), encoding="utf-8")
    (OUT / "detector_inventory.json").write_text(json.dumps(lane_inventory(ROOT / "frozen/inputs/network.net.xml"), indent=2), encoding="utf-8")
    return sha256(path)


def build_routes(condition):
    root = ET.parse(ROOT / "core_detector_batch/inputs/baseline.rou.xml").getroot()
    truck = float(condition.get("truck", 0))
    if truck:
        vehicle = ET.parse(ROOT / "core_detector_batch/inputs/heavyveh_very_high.rou.xml").getroot().find("vType[@id='truck']")
        root.insert(1, copy.deepcopy(vehicle))
    for vehicle in root.findall("vType"):
        vehicle.set("tau", str(condition.get("tau", 1)))
        if "sigma" in condition:
            vehicle.set("sigma", str(condition["sigma"]))
        for key, attr in [("speed", "maxSpeed"), ("accel", "accel"), ("decel", "decel")]:
            if key in condition:
                vehicle.set(attr, f"{float(vehicle.attrib[attr]) * condition[key]:.8g}")
    flows = list(root.findall("flow"))
    for flow in flows:
        root.remove(flow)
        number = int(float(flow.attrib["number"]) * condition.get("demand", 1) + 0.5)
        trucks = int(number * truck + 0.5)
        flow.set("number", str(number - trucks))
        root.append(flow)
        if trucks:
            other = copy.deepcopy(flow)
            other.set("id", flow.attrib["id"].removesuffix("_car") + "_truck")
            other.set("number", str(trucks))
            other.set("type", "truck")
            root.append(other)
    ET.indent(root)
    return root


def build_detectors():
    add = ET.Element("additional")
    for row in lane_inventory(ROOT / "frozen/inputs/network.net.xml"):
        ET.SubElement(add, "instantInductionLoop", id=row["loop_id"], lane=row["lane"],
                      pos=str(row["loop_pos_m"]), file="stopline_events.xml", friendlyPos="false")
        ET.SubElement(add, "laneAreaDetector", id=row["queue_id"], lane=row["lane"],
                      pos=str(row["queue_pos_m"]), endPos=str(row["queue_end_m"]), period="300",
                      file="lane_queues.xml", friendlyPos="false", timeThreshold="1",
                      speedThreshold="1.388888889", jamThreshold="10")
    ET.indent(add)
    return add


def run(condition, seed, protocol_hash):
    case = condition["case_id"]
    directory = OUT / "runs" / f"{case}_seed{seed}"
    marker = directory / "complete.json"
    if marker.exists():
        record = json.loads(marker.read_text(encoding="utf-8"))
        if record["protocol_sha256"] != protocol_hash:
            raise RuntimeError("Protocol changed")
        for name, digest in record["files_sha256"].items():
            if sha256(directory / name) != digest:
                raise RuntimeError(f"Changed completed file: {directory / name}")
    else:
        if directory.exists():
            raise RuntimeError(f"Unfinished run must be audited: {directory}")
        directory.mkdir(parents=True)
        cfg = ET.parse(ROOT / "core_detector_batch/runs/baseline_seed42/run.sumocfg")
        cfg.getroot().find("random_number/seed").set("value", str(seed))
        cfg.write(directory / "run.sumocfg", encoding="utf-8", xml_declaration=True)
        route = build_routes(condition)
        ET.ElementTree(route).write(directory / "routes.rou.xml", encoding="utf-8", xml_declaration=True)
        ET.ElementTree(build_detectors()).write(directory / "additional.xml", encoding="utf-8", xml_declaration=True)
        start = time.perf_counter()
        with (directory / "sumo_stdout.log").open("w") as out, (directory / "sumo_stderr.log").open("w") as err:
            proc = subprocess.run([str(SUMO), "-c", "run.sumocfg"], cwd=directory, stdout=out, stderr=err, timeout=1800)
        if proc.returncode:
            raise RuntimeError(f"SUMO exit {proc.returncode}: {directory}")
        row = audit_run(directory)
        planned = sum(int(f.attrib["number"]) for f in route.findall("flow"))
        if not (row["end_loaded"] == row["end_inserted"] + row["end_waiting"] == row["trip_records"] == planned):
            raise RuntimeError(f"Demand population mismatch: {directory}")
        if row["unaccounted_inserted_end"] or row["ended_not_arrived"] or row["integration_action_warning"]:
            raise RuntimeError(f"Accounting or integration issue: {directory}")
        record = {"protocol_sha256": protocol_hash, "finished_utc": datetime.now(timezone.utc).isoformat(),
                  "wall_s": time.perf_counter() - start,
                  "files_sha256": {p.name: sha256(p) for p in directory.iterdir() if p.is_file()}}
        marker.write_text(json.dumps(record, indent=2), encoding="utf-8")
    row = audit_run(directory)
    row.update(case_id=case, wall_s=record["wall_s"])
    print(f"{case}/seed{seed}: Q={row['end_arrived']} TP={row['teleport_events']} collisions={row['stat_safety_collisions']}", flush=True)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    digest = freeze()
    print("Protocol frozen: " + digest, flush=True)
    if args.freeze_only:
        return
    jobs = [({"case_id": "B00", "name": "baseline"}, seed) for seed in SEEDS]
    jobs += [(condition, seed) for seed in SEEDS for condition in cases()]
    rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run, condition, seed, digest) for condition, seed in jobs]
        try:
            for future in as_completed(futures):
                rows.append(future.result())
                write_csv(OUT / "run_audit.csv", sorted(rows, key=lambda r: (r["case_id"], r["seed"])))
                print(f"Completed {len(rows)}/85", flush=True)
        except Exception:
            for future in futures:
                future.cancel()
            raise
    print("All 85 runs complete; classify before joining construction key.", flush=True)


if __name__ == "__main__":
    main()
