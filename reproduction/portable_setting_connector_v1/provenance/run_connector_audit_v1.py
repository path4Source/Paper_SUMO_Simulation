"""Preserved-network connector audit; new settings are exploratory, not a repair."""
import argparse
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

OUT = ROOT / "connector_audit_v1"
SOURCE = ROOT / "hidden_challenge_v1/runs"
SEEDS = [11, 29, 47, 71, 101]
JOBS = [("passive", 0.5, seed) for seed in [11, 101]] + [
    ("fine_joint", 0.1, seed) for seed in SEEDS
]
CONTROL_FIELDS = [
    "end_loaded", "end_inserted", "end_arrived", "end_running", "end_waiting",
    "trip_records", "trip_completed_timeLoss_mean_s", "teleport_events",
    "stat_safety_collisions", "network_vehicle_hours_discrete",
    "entry_vehicle_hours_discrete", "total_vehicle_hours_discrete",
]


def source_record(seed):
    directory = SOURCE / f"B00_seed{seed}"
    record = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
    for name, expected in record["files_sha256"].items():
        if sha256(directory / name) != expected:
            raise RuntimeError(f"Changed source evidence: {directory / name}")
    return record


def freeze():
    records = {str(seed): source_record(seed) for seed in SEEDS}
    protocol = {
        "version": "1.0",
        "purpose": "Audit two observed baseline side collisions before independent intervention validation.",
        "selection": "Seeds 11 and 101 are selected retrospectively because their existing 0.5-s baseline runs have side collisions. The new 0.1-s comparison includes ALL five previously fixed seeds, not selected clean seeds.",
        "jobs": JOBS,
        "design": "Two passive-output controls at step/action 0.5/0.5 s, plus five exploratory joint step/action 0.1/0.1-s runs. Tau=1 s, ballistic integration, original network, original demand and signal plans, 3600 s, no warm-up removal, collision checks and collision/gridlock policies unchanged.",
        "outputs": "Add lane-change events with coordinates and FCD on ED1.91, :J3_0 and ED1.177. Retain whole-hour events, populations and warnings. FCD uses all vehicles on these edges, no stochastic device selection.",
        "hypothesis": "Side collisions may involve the short 3-to-6-lane fan-out connector and internal lane-changing geometry. Location alone is not causal proof; examine trajectories and lane-change records.",
        "analysis": "Require exact passive reproduction of predeclared population, burden, completed-delay and warning metrics, plus identical collision element attributes. Compare five paired baseline responses for the joint setting change with exploratory t95 intervals (df4); report every warning including new locations. This changes behavioral action frequency as well as numerical step and is NOT a pure numerical convergence test or field validation.",
        "decision": "No network edits, no disabling collision checks, no warning-based seed removal, no threshold tuning, no replacement of old results. A warning-free result is not proof of validity. Any unresolved collision keeps interpretation qualified.",
        "new_runs": 7,
        "control_fields": CONTROL_FIELDS,
        "sources": {str(seed): sha256(SOURCE / f"B00_seed{seed}/complete.json") for seed in SEEDS},
        "network_sha256": sha256(ROOT / "frozen/inputs/network.net.xml"),
        "sumo_sha256": sha256(SUMO),
        "code_sha256": {p: sha256(ROOT / "scripts" / p) for p in [
            "run_connector_audit_v1.py", "audit_metrics.py", "freeze_submission.py"
        ]},
    }
    OUT.mkdir(exist_ok=True)
    path = OUT / "protocol.json"
    canonical = json.loads(json.dumps(protocol))
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        old.pop("frozen_utc")
        if old != canonical:
            raise RuntimeError("Frozen protocol differs; use a new version")
    else:
        if (OUT / "runs").exists():
            raise RuntimeError("Outcomes predate protocol")
        path.write_text(json.dumps({**canonical, "frozen_utc": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    return sha256(path)


def collisions(path):
    return [e.attrib for e in ET.parse(path).getroot().findall("collision")]


def run(kind, step, seed, digest):
    directory = OUT / "runs" / f"{kind}_seed{seed}"
    marker = directory / "complete.json"
    source = SOURCE / f"B00_seed{seed}"
    if marker.exists():
        record = json.loads(marker.read_text(encoding="utf-8"))
        if record["protocol_sha256"] != digest:
            raise RuntimeError("Protocol changed")
        for name, expected in record["files_sha256"].items():
            if sha256(directory / name) != expected:
                raise RuntimeError(f"Changed output: {directory / name}")
    else:
        if directory.exists():
            raise RuntimeError(f"Partial run exists: {directory}")
        directory.mkdir(parents=True)
        for name in ["routes.rou.xml", "additional.xml"]:
            shutil.copy2(source / name, directory / name)
        (directory / "fcd_edges.txt").write_text("edge:ED1.91\nedge::J3_0\nedge:ED1.177\n", encoding="utf-8")
        cfg = ET.parse(source / "run.sumocfg")
        cfg.getroot().find("time/step-length").set("value", str(step))
        cfg.getroot().find("processing/default.action-step-length").set("value", str(step))
        output = cfg.getroot().find("output")
        for name, value in {
            "lanechange-output": "lanechanges.xml",
            "lanechange-output.xy": "true",
            "fcd-output": "connector_fcd.xml.gz",
            "fcd-output.filter-edges.input-file": "fcd_edges.txt",
        }.items():
            ET.SubElement(output, name, value=value)
        ET.indent(cfg)
        cfg.write(directory / "run.sumocfg", encoding="utf-8", xml_declaration=True)
        start = time.perf_counter()
        with (directory / "sumo_stdout.log").open("w") as out, (directory / "sumo_stderr.log").open("w") as err:
            proc = subprocess.run([str(SUMO), "-c", "run.sumocfg"], cwd=directory, stdout=out, stderr=err, timeout=1800)
        if proc.returncode:
            raise RuntimeError(f"SUMO failed: {directory}")
        row = audit_run(directory)
        if row["end_loaded"] != 7900 or row["end_inserted"] + row["end_waiting"] != 7900 or row["trip_records"] != 7900:
            raise RuntimeError(f"Population accounting failed: {directory}")
        if row["unaccounted_inserted_end"] or row["ended_not_arrived"] or row["integration_action_warning"]:
            raise RuntimeError(f"Accounting/integration failed: {directory}")
        if kind == "passive":
            old = audit_run(source)
            differences = {key: [old[key], row[key]] for key in CONTROL_FIELDS if old[key] != row[key]}
            if differences or collisions(source / "collisions.xml") != collisions(directory / "collisions.xml"):
                raise RuntimeError(f"Passive output changed trajectory: {differences}")
        record = {"protocol_sha256": digest, "finished_utc": datetime.now(timezone.utc).isoformat(),
                  "wall_s": time.perf_counter() - start,
                  "files_sha256": {p.name: sha256(p) for p in directory.iterdir() if p.is_file()}}
        marker.write_text(json.dumps(record, indent=2), encoding="utf-8")
    row = audit_run(directory)
    row.update(kind=kind, wall_s=record["wall_s"], passive_reproduction_passed=(kind == "passive"))
    print(f"{kind}/seed{seed}: Q={row['end_arrived']} TP={row['teleport_events']} collisions={row['stat_safety_collisions']}", flush=True)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    digest = freeze()
    print("Frozen protocol: " + digest, flush=True)
    if args.freeze_only:
        return
    rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run, *job, digest) for job in JOBS]
        for future in as_completed(futures):
            rows.append(future.result())
            write_csv(OUT / "run_audit.csv", sorted(rows, key=lambda r: (r["kind"], r["seed"])))
            print(f"Completed {len(rows)}/7", flush=True)


if __name__ == "__main__":
    main()
