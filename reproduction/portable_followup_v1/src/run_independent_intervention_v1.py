"""Fixed, adverse-condition-preserving signal intervention with a baseline control."""
import argparse
import copy
import json
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from audit_metrics import audit_run, write_csv
from freeze_submission import sha256
from run_timepilot import ROOT, SUMO
from stopline_instrumentation import lane_inventory

OUT = ROOT / "independent_intervention_v1"
SEEDS = [11, 29, 47, 71, 101]
STATES = ["baseline", "heavyveh_very_high", "weather_heavy_rain"]
PLANS = ["reference", "reallocation"]
SOURCE_BASE = ROOT / "connector_audit_v1/runs"
NETWORK = ROOT / "frozen/inputs/network.net.xml"
# Phase indices are zero-based. Clearances, cycles and offsets are preserved.
PHASE_DELTAS = {"n1": {0: 4.0, 2: -2.0, 6: -2.0}, "n2": {0: 4.0, 2: -2.0, 4: -2.0}}
TARGET_LANES = ["ED1.177_1", "ED1.177_2", "ED1.177_3", "ED2.378_1", "ED2.378_2"]


def route_source(state):
    if state == "baseline":
        return SOURCE_BASE / "fine_joint_seed11/routes.rou.xml"
    return ROOT / "core_detector_batch/inputs" / f"{state}.rou.xml"


def build_network():
    tree = ET.parse(NETWORK)
    rows = []
    for signal in tree.getroot().findall("tlLogic"):
        old_cycle = sum(float(p.attrib["duration"]) for p in signal.findall("phase"))
        for index, phase in enumerate(signal.findall("phase")):
            original = float(phase.attrib["duration"])
            delta = PHASE_DELTAS.get(signal.attrib["id"], {}).get(index, 0.0)
            if delta:
                if "y" in phase.attrib["state"].lower() or original + delta < 15:
                    raise RuntimeError("Clearance or minimum-green violation")
                phase.set("duration", f"{original + delta:g}")
            rows.append({"signal": signal.attrib["id"], "phase_index": index,
                         "state": phase.attrib["state"], "reference_s": original,
                         "intervention_s": original + delta, "delta_s": delta,
                         "offset_s": float(signal.attrib["offset"]), "cycle_s": old_cycle})
        new_cycle = sum(float(p.attrib["duration"]) for p in signal.findall("phase"))
        if new_cycle != old_cycle:
            raise RuntimeError("Cycle changed")
    original = ET.parse(NETWORK).getroot()
    changed = copy.deepcopy(tree.getroot())
    for before, after in zip(original.iter(), changed.iter()):
        if before.tag != after.tag:
            raise RuntimeError("Network structure changed")
        a, b = dict(before.attrib), dict(after.attrib)
        if before.tag == "phase":
            a.pop("duration")
            b.pop("duration")
        if a != b:
            raise RuntimeError("Unexpected network modification")
    if sum(1 for _ in original.iter()) != sum(1 for _ in changed.iter()):
        raise RuntimeError("Network element count changed")
    return tree, rows


def freeze():
    for seed in SEEDS:
        directory = SOURCE_BASE / f"fine_joint_seed{seed}"
        record = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
        for name, digest in record["files_sha256"].items():
            if sha256(directory / name) != digest:
                raise RuntimeError(f"Changed reused baseline: {directory / name}")
        if sha256(directory / "routes.rou.xml") != sha256(route_source("baseline")):
            raise RuntimeError("Baseline route files differ between seeds")
    _, phase_rows = build_network()
    parameters = {state: [v.attrib for v in ET.parse(route_source(state)).getroot().findall("vType")] for state in STATES}
    protocol = {
        "version": "1.0", "design": "Exploratory 3-condition x 2-plan paired intervention check; 5 fixed seeds per cell.",
        "purpose": "Respond to R2.5 and R3.2 with a new operational intervention that does not remove the heavy-vehicle/weather perturbation, and distinguish generic retiming benefit from adverse-condition-specific benefit.",
        "states": STATES, "plans": PLANS, "seeds": SEEDS,
        "new_runs": 25, "reused_reference_baselines": 5,
        "reused_scope": "Only unchanged 0.1/0.1-s baselines from connector audit are reused; all 25 intervention/adverse-condition runs are new. No earlier OAT or weather-component outcome is counted as a new intervention.",
        "selection": "Plan fixed before these outcomes, using the existing ED1.177 and ED2.378 bottleneck locations, not optimized on current outcomes. Seeds are the previously fixed five; no seed is removed because of warnings. This is not an independently blinded classifier test.",
        "intervention": "At n1 phase 0 gains 4 s, phases 2 and 6 each lose 2 s; at n2 phase 0 gains 4 s, phases 2 and 4 each lose 2 s. Phase indices are zero-based. All state strings, yellow durations, cycles, offsets, n4 timing and network geometry remain unchanged. Donor green intervals remain at least 18 s. This is a testable candidate, not an optimized or safety-calibrated signal plan.",
        "phase_rows": phase_rows,
        "adversity": "Retain exact archived 24% truck composition and heavy-rain vehicle parameters separately. Routes, demands, vehicle parameters and departure settings are identical within each condition's reference/intervention pair. Tau omitted in rain file retains simulator default 1 s. No emission outcomes or truck-lane restrictions are introduced.",
        "vehicle_types": parameters,
        "simulation": "SUMO 1.24.0; ballistic; step/action 0.1/0.1 s; horizon 0-3600 s; no warmup removal; junction collision checks on; collision teleport and 300-s gridlock teleport; complete trip-population output; all source settings otherwise retained.",
        "primary": "Within each condition, report paired percentage change in arrived throughput and total vehicle-hours (network running plus entry waiting). Report completed-trip time loss, final insertion backlog, in-network vehicles, unique teleported vehicles and collisions as supporting diagnostics.",
        "comparison": "Also report adverse-reference versus baseline-reference and the paired difference in intervention percentage responses (adverse minus baseline), in percentage points. The latter is a response-heterogeneity contrast, not an independent causal validation of the original source label.",
        "local": "Direct lane-end front crossings and summed time-mean lane queue extent over the last up-to-100m. Target lanes fixed as listed. Donor lanes are those whose all-connections-green duration decreases under the fixed plan. Also report each signal and every lane; n4 is unchanged by the plan, not an independent isolated control because traffic can redistribute.",
        "target_lanes": TARGET_LANES,
        "uncertainty": "Student t95 intervals of five paired seed responses, df4. Exploratory, unadjusted for multiple outcomes/conditions; no confirmatory efficacy or equivalence claim. Confidence intervals crossing zero remain unresolved.",
        "interpretation_rule": "Network recovery requires the whole throughput CI above +2% and the whole total vehicle-hour CI below -5%; no timing/collision/teleport warning in either arm; and the upper confidence bound of insertion-backlog change no greater than +2 percentage points of planned demand. Local corroboration separately requires target crossing CI above +2% and target queue CI below -5%; donor deterioration is reported separately. Failure or conflict is retained and does not falsify the original degradation diagnosis. These are conservative reporting rules, not a proof of mechanism.",
        "no_tuning": "Run all prespecified cells. Do not replace the plan, drop seeds, change tolerances or suppress failures after observing outcomes. Any later candidate requires a new protocol and is exploratory.",
        "source_hashes": {"network": sha256(NETWORK), "sumo": sha256(SUMO),
                          **{f"routes_{state}": sha256(route_source(state)) for state in STATES},
                          **{f"baseline_seed{seed}": sha256(SOURCE_BASE / f"fine_joint_seed{seed}/complete.json") for seed in SEEDS}},
        "code_hashes": {name: sha256(ROOT / "scripts" / name) for name in ["run_independent_intervention_v1.py", "audit_metrics.py", "stopline_instrumentation.py"]},
    }
    OUT.mkdir(exist_ok=True)
    path = OUT / "protocol.json"
    protocol = json.loads(json.dumps(protocol))
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        old.pop("frozen_utc")
        if old != protocol:
            raise RuntimeError("Frozen intervention protocol differs")
    else:
        if (OUT / "runs").exists():
            raise RuntimeError("Runs predate protocol")
        path.write_text(json.dumps({**protocol, "frozen_utc": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    inputs = OUT / "inputs"
    inputs.mkdir(exist_ok=True)
    tree, rows = build_network()
    candidate = inputs / "reallocation.net.xml"
    if not candidate.exists():
        tree.write(candidate, encoding="utf-8", xml_declaration=True)
    if ET.tostring(ET.parse(candidate).getroot()) != ET.tostring(tree.getroot()):
        raise RuntimeError("Generated plan differs")
    write_csv(OUT / "signal_plan.csv", rows)
    return sha256(path)


def run(state, plan, seed, digest):
    if state == "baseline" and plan == "reference":
        directory = SOURCE_BASE / f"fine_joint_seed{seed}"
        record = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
        reused = True
    else:
        directory = OUT / "runs" / f"{state}_{plan}_seed{seed}"
        marker = directory / "complete.json"
        reused = False
        if marker.exists():
            record = json.loads(marker.read_text(encoding="utf-8"))
            if record["protocol_sha256"] != digest:
                raise RuntimeError("Protocol hash mismatch")
            for name, expected in record["files_sha256"].items():
                if sha256(directory / name) != expected:
                    raise RuntimeError(f"Changed completed evidence: {directory / name}")
        else:
            if directory.exists():
                raise RuntimeError(f"Partial run must be audited: {directory}")
            directory.mkdir(parents=True)
            template = SOURCE_BASE / f"fine_joint_seed{seed}"
            for name in ["additional.xml", "fcd_edges.txt"]:
                shutil.copy2(template / name, directory / name)
            shutil.copy2(route_source(state), directory / "routes.rou.xml")
            cfg = ET.parse(template / "run.sumocfg")
            network = NETWORK if plan == "reference" else OUT / "inputs/reallocation.net.xml"
            cfg.getroot().find("input/net-file").set("value", str(network))
            cfg.write(directory / "run.sumocfg", encoding="utf-8", xml_declaration=True)
            start = time.perf_counter()
            with (directory / "sumo_stdout.log").open("w") as stdout, (directory / "sumo_stderr.log").open("w") as stderr:
                proc = subprocess.run([str(SUMO), "-c", "run.sumocfg"], cwd=directory, stdout=stdout, stderr=stderr, timeout=2400)
            if proc.returncode:
                raise RuntimeError(f"SUMO failed: {directory}")
            row = audit_run(directory)
            if row["end_loaded"] != 7900 or row["trip_records"] != 7900 or row["end_inserted"] + row["end_waiting"] != 7900:
                raise RuntimeError(f"Population mismatch: {directory}")
            if row["unaccounted_inserted_end"] or row["ended_not_arrived"] or row["integration_action_warning"]:
                raise RuntimeError(f"Accounting/integration mismatch: {directory}")
            record = {"protocol_sha256": digest, "finished_utc": datetime.now(timezone.utc).isoformat(),
                      "network_sha256": sha256(network), "wall_s": time.perf_counter() - start,
                      "files_sha256": {p.name: sha256(p) for p in directory.iterdir() if p.is_file()}}
            marker.write_text(json.dumps(record, indent=2), encoding="utf-8")
    row = audit_run(directory)
    cfg_values = {e.tag: e.attrib["value"] for e in ET.parse(directory / "run.sumocfg").getroot().iter() if "value" in e.attrib}
    row["unfinished_flag_in_output_header"] = row.pop("unfinished_output_enabled")
    row["unfinished_output_declared_in_config"] = cfg_values.get("tripinfo-output.write-unfinished", "not declared")
    row.update(state=state, plan=plan, reused=reused, wall_s=record["wall_s"])
    print(f"{state}/{plan}/seed{seed}: Q={row['end_arrived']} TP={row['teleport_events']} collisions={row['stat_safety_collisions']} reused={reused}", flush=True)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    digest = freeze()
    print("Protocol frozen: " + digest, flush=True)
    if args.freeze_only:
        return
    rows = []
    jobs = [(state, plan, seed) for seed in SEEDS for state in STATES for plan in PLANS]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run, *job, digest) for job in jobs]
        for future in as_completed(futures):
            rows.append(future.result())
            write_csv(OUT / "run_audit.csv", sorted(rows, key=lambda r: (r["state"], r["plan"], r["seed"])))
            print(f"Completed {len(rows)}/30 cells (25 new + 5 reused)", flush=True)


if __name__ == "__main__":
    main()
