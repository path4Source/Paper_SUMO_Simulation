"""Trace warnings to events and reconcile detector counts without erasing discrepancies."""
import csv
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from audit_metrics import audit_run, write_csv

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core_detector_batch"
OUT = ROOT / "stage4_warning_audit"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_teleports(path):
    events, active = [], {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "Teleporting vehicle '" in line:
            match = re.search(r"Teleporting vehicle '([^']+)'; (.*?), lane='([^']+)'.*?time=([\d.]+)", line)
            if not match:
                raise ValueError(f"Unparsed teleport at {path}:{number}")
            vehicle, detail, lane, time = match.groups()
            if "collision" in detail:
                kind = "collision"
                subtype = detail.split(" with ")[0]
            else:
                reason = re.fullmatch(r"waited too long \(([^)]+)\)", detail)
                if not reason:
                    raise ValueError(f"Unknown reason: {detail}")
                kind, subtype = "gridlock", reason[1]
            if vehicle in active:
                raise ValueError(f"Repeated teleport without observed end: {vehicle}")
            row = {"vehicle": vehicle, "time_s": float(time.rstrip(".")), "origin_lane": lane,
                   "kind": kind, "subtype": subtype, "log_line": number,
                   "reinsertion_edge": "", "reinsertion_time_s": None}
            events.append(row)
            active[vehicle] = row
        elif "ends teleporting on edge" in line:
            match = re.search(r"Vehicle '([^']+)' ends teleporting on edge '([^']+)', time=([\d.]+)", line)
            if not match or match[1] not in active:
                raise ValueError(f"Unmatched teleport end: {line}")
            row = active.pop(match[1])
            row.update(reinsertion_edge=match[2], reinsertion_time_s=float(match[3].rstrip(".")))
    return events


def lane_count_totals(path):
    result = defaultdict(Counter)
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag == "lane":
            for key in ("left", "teleported", "vaporized", "arrived", "laneChangedFrom"):
                result[node.attrib["id"]][key] += int(node.attrib.get(key, 0))
            node.clear()
    return result


def main():
    inventory = json.loads((CORE / "detector_inventory.json").read_text())
    lane_to_signal = {r["lane"]: r["signal"] for r in inventory}
    for junction in ET.parse(ROOT / "frozen/inputs/network.net.xml").getroot().findall("junction"):
        for lane in junction.attrib.get("intLanes", "").split():
            lane_to_signal[lane] = junction.attrib["id"]
    originals = read_csv(CORE / "run_results.csv")
    event_rows, collision_rows, summaries, reconciliation, changes, associations = [], [], [], [], [], []
    for original in originals:
        directory = Path(original["source_dir"])
        row = audit_run(directory)
        row.update(scenario=original["scenario"], wall_s=original["wall_s"])
        teleports = parse_teleports(directory / "sumo_stderr.log")
        collisions = [dict(node.attrib) for node in ET.parse(directory / "collisions.xml").getroot().findall("collision")]
        assert len(collisions) == row["stat_safety_collisions"]
        assert len(teleports) == row["teleport_events"]
        assert sum(e["kind"] == "collision" for e in teleports) == len(collisions)
        if int(original["collision_teleport_events"]) != row["collision_teleport_events"]:
            changes.append({"run": directory.name, "old_collision_teleport_events": original["collision_teleport_events"],
                            "corrected_collision_teleport_events": row["collision_teleport_events"],
                            "reason": "Side-collision message was previously assigned to other; totals and raw simulation unchanged."})
        tp_by_vehicle = defaultdict(list)
        for event in teleports:
            event["signal"] = lane_to_signal.get(event["origin_lane"], "unmapped")
            tp_by_vehicle[event["vehicle"]].append(event)
            event_rows.append({"run": directory.name, "scenario": row["scenario"], "seed": row["seed"], **event})
        for event in collisions:
            collision_rows.append({"run": directory.name, **event})
        events = read_csv(CORE / "processed" / directory.name / "aligned_front_crossings.csv")
        by_lane = defaultdict(list)
        for event in events:
            by_lane[event["lane"]].append(event)
            earlier = [t for t in tp_by_vehicle[event["vehicle"]] if t["time_s"] <= float(event["front_time_s"])]
            if earlier:
                associations.append({"run": directory.name, "lane": event["lane"], "vehicle": event["vehicle"],
                                     "front_time_s": event["front_time_s"], "prior_teleports": len(earlier),
                                     "last_teleport_time_s": earlier[-1]["time_s"],
                                     "last_reinsertion_edge": earlier[-1]["reinsertion_edge"]})
        lane_totals = lane_count_totals(directory / "lane_flow.xml")
        for lane in inventory:
            lid = lane["lane"]
            counts = lane_totals[lid]
            front = len(by_lane[lid])
            # SUMO 1.24 increments nVehLeft and nVehTeleported on a teleport.
            corrected_left = counts["left"] - counts["teleported"]
            prior_tp = [e for e in by_lane[lid] if any(t["time_s"] <= float(e["front_time_s"])
                       for t in tp_by_vehicle[e["vehicle"]])]
            reconciliation.append({"run": directory.name, "lane": lid, "e1_front_entries": front,
                "lane_data_left_raw": counts["left"], "lane_data_teleported": counts["teleported"],
                "lane_data_left_minus_teleported": corrected_left,
                "raw_difference": front - counts["left"], "remaining_difference": front - corrected_left,
                "logged_teleport_origins": sum(t["origin_lane"] == lid for t in teleports),
                "front_entries_after_prior_teleport": len(prior_tp),
                "prior_teleport_vehicle_ids_json": json.dumps([e["vehicle"] for e in prior_tp]),
                "interpretation": "matched after removing teleport departures from laneData" if front == corrected_left else
                                  "residual cross-channel mismatch; preserve E1 and laneData separately"})
        row.update(first_teleport_s=min((t["time_s"] for t in teleports), default=None),
                   gridlock_teleports=sum(t["kind"] == "gridlock" for t in teleports),
                   collision_xml_count=len(collisions))
        summaries.append(row)
    write_csv(OUT / "core_run_results_corrected.csv", summaries)
    write_csv(OUT / "teleport_event_audit.csv", event_rows)
    write_csv(OUT / "collision_event_audit.csv", collision_rows)
    write_csv(OUT / "lane_count_reconciliation.csv", reconciliation)
    write_csv(OUT / "front_entries_after_teleport.csv", associations)
    if changes:
        write_csv(OUT / "warning_category_corrections.csv", changes)
    summary = {
        "runs": len(summaries), "teleport_events": len(event_rows), "collision_events": len(collision_rows),
        "event_counts_match_collision_xml_and_statistics": True,
        "side_collision_category_corrections": changes,
        "lane_run_pairs": len(reconciliation),
        "raw_exact_matches": sum(r["raw_difference"] == 0 for r in reconciliation),
        "matches_after_subtracting_teleport_departures": sum(r["remaining_difference"] == 0 for r in reconciliation),
        "residuals": [r for r in reconciliation if r["remaining_difference"]],
        "source_version": "SUMO v1_24_0 MSMeanData_Net.cpp notifyLeave increments both left and teleported",
        "source_url": "https://raw.githubusercontent.com/eclipse-sumo/sumo/v1_24_0/src/microsim/output/MSMeanData_Net.cpp",
        "interpretation": "Arithmetic reconciliation does not remove network effects of teleporting or establish saturation flow."
    }
    (OUT / "audit_checks.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
