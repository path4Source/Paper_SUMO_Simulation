"""Join preserved collision, lane-change and trajectory records without causal relabelling."""
import gzip
import json
import math
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

from audit_metrics import audit_run, write_csv
from freeze_submission import sha256
from run_connector_audit_v1 import OUT, SOURCE, SEEDS, JOBS, ROOT, CONTROL_FIELDS, collisions


def interval(values):
    mean = statistics.mean(values)
    half = 2.7764451051977987 * statistics.stdev(values) / math.sqrt(len(values))
    return {"mean": mean, "ci95_low": mean - half, "ci95_high": mean + half, "n": len(values)}


def evidence(directory):
    events = [dict(e.attrib) for e in ET.parse(directory / "collisions.xml").getroot().findall("collision")]
    changes = [dict(e.attrib) for e in ET.parse(directory / "lanechanges.xml").getroot().findall("change")]
    nearby = []
    for index, event in enumerate(events):
        event["event_index"] = index
        related = [row for row in changes if row["id"] in (event["collider"], event["victim"])
                   and abs(float(row["time"]) - float(event["time"])) <= 2]
        event["related_lanechanges_within_2s"] = len(related)
        for row in related:
            nearby.append({"collision_index": index, "collision_time": event["time"], **row})
    tracks = []
    with gzip.open(directory / "connector_fcd.xml.gz", "rb") as stream:
        context = ET.iterparse(stream, events=("start", "end"))
        _, root = next(context)
        for action, element in context:
            if action != "end" or element.tag != "timestep":
                continue
            current = float(element.attrib["time"])
            relevant = [e for e in events if abs(float(e["time"]) - current) <= 3.0]
            if relevant:
                for vehicle in element.findall("vehicle"):
                    for collision in relevant:
                        if vehicle.attrib["id"] in (collision["collider"], collision["victim"]):
                            tracks.append({"collision_index": collision["event_index"], "time": current,
                                           "role": "collider" if vehicle.attrib["id"] == collision["collider"] else "victim",
                                           **vehicle.attrib})
            root.clear()
    return events, nearby, tracks


def main():
    events, changes, tracks, rows, checks = [], [], [], [], []
    for kind, step, seed in JOBS:
        directory = OUT / "runs" / f"{kind}_seed{seed}"
        record = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
        for name, expected in record["files_sha256"].items():
            if sha256(directory / name) != expected:
                raise RuntimeError(f"Changed evidence: {directory / name}")
        if record["protocol_sha256"] != sha256(OUT / "protocol.json"):
            raise RuntimeError("Protocol hash mismatch")
        checks.append({"run": directory.name, "files_verified": len(record["files_sha256"]), "passed": True})
        local_events, local_changes, local_tracks = evidence(directory)
        context = {"kind": kind, "seed": seed, "run": directory.name}
        events.extend([{**context, **row} for row in local_events])
        changes.extend([{**context, **row} for row in local_changes])
        tracks.extend([{**context, **row} for row in local_tracks])
        current, previous = audit_run(directory), audit_run(SOURCE / f"B00_seed{seed}")
        if kind == "passive":
            if any(current[key] != previous[key] for key in CONTROL_FIELDS):
                raise RuntimeError("Passive control mismatch")
            if collisions(directory / "collisions.xml") != collisions(SOURCE / f"B00_seed{seed}/collisions.xml"):
                raise RuntimeError("Passive collision mismatch")
        for key in ["end_arrived", "trip_completed_timeLoss_mean_s", "total_vehicle_hours_discrete",
                    "end_waiting", "end_running", "teleport_events", "stat_safety_collisions"]:
            rows.append({**context, "metric": key, "reference_dt05": previous[key], "observed": current[key],
                         "difference": current[key] - previous[key],
                         "relative_pct": 100 * (current[key] / previous[key] - 1) if previous[key] else None})
    for name, values in [("collisions", events), ("nearby_lanechanges", changes), ("event_trajectories", tracks),
                         ("paired_setting_comparison", rows), ("integrity_checks", checks)]:
        if values:
            write_csv(OUT / f"{name}.csv", values)
    metrics = sorted(set(row["metric"] for row in rows))
    summary = {"new_runs": 7, "unchanged_network": True,
               "passive_controls_exact": True,
               "warning_free_is_not_validation": True,
               "joint_step_action_not_pure_convergence": True,
               "collision_events": events,
               "paired_setting_changes": {}}
    for metric in metrics:
        selected = [row for row in rows if row["kind"] == "fine_joint" and row["metric"] == metric]
        summary["paired_setting_changes"][metric] = {
            "difference": interval([row["difference"] for row in selected]),
            "reference_mean": statistics.mean(row["reference_dt05"] for row in selected),
            "observed_mean": statistics.mean(row["observed"] for row in selected),
        }
        if all(row["relative_pct"] is not None for row in selected):
            summary["paired_setting_changes"][metric]["relative_pct"] = interval([row["relative_pct"] for row in selected])
    net = ET.parse(ROOT / "frozen/inputs/network.net.xml").getroot()
    geometry = {
        "junction": net.find("junction[@id='J3']").attrib,
        "lanes": [dict(e.attrib) for edge in ["ED1.91", ":J3_0", "ED1.177"]
                  for e in net.find(f"edge[@id='{edge}']").findall("lane")],
        "connections": [e.attrib for e in net.findall("connection") if e.attrib["from"] in ("ED1.91", ":J3_0")],
        "interpretation": "Recorded geometry and events support localization only. No network-repair counterfactual has been performed.",
    }
    (OUT / "connector_geometry.json").write_text(json.dumps(geometry, indent=2), encoding="utf-8")
    (OUT / "analysis_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
