"""Audit historical raw evidence; missing evidence is reported, never imputed as zero."""
from __future__ import annotations

import csv
import json
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

from audit_metrics import audit_run, write_csv

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(r"E:\4\road_capacity_sci\outputs\sumo_runs")


def signal_inventory() -> None:
    net = ET.parse(ROOT / "frozen/inputs/network.net.xml").getroot()
    tls = {node.attrib["id"]: node for node in net.findall("tlLogic")}
    rows = []
    for connection in net.findall("connection"):
        if "tl" not in connection.attrib:
            continue
        a = connection.attrib
        phases = tls[a["tl"]].findall("phase")
        index = int(a["linkIndex"])
        cycle = sum(float(phase.attrib["duration"]) for phase in phases)
        g = sum(float(phase.attrib["duration"]) for phase in phases if phase.attrib["state"][index] in "gG")
        G = sum(float(phase.attrib["duration"]) for phase in phases if phase.attrib["state"][index] == "G")
        rows.append({"signal": a["tl"], "incoming_edge": a["from"], "incoming_lane": a["from"] + "_" + a["fromLane"],
                     "outgoing_edge": a["to"], "link_index": index, "direction": a.get("dir"),
                     "cycle_s": cycle, "green_G_or_g_s": g, "priority_green_G_s": G,
                     "movement_green_ratio": g / cycle, "baseline_program": tls[a["tl"]].attrib.get("programID")})
    write_csv(ROOT / "audit/baseline_movement_green_inventory.csv", rows)


def reviewer_tracker() -> None:
    text = (ROOT / "frozen/reviewer_comments.txt").read_text(encoding="utf-8-sig")
    maps = {1: ["P3/P4", "P2/P8", "P1", "P5", "P1/P2/P9"],
            2: ["P5/P9", "P1", "P2", "P3/P9", "P6", "P7", "P4"],
            3: ["P3/P4", "P6", "P1", "P2", "P5/P7", "P8", "P7", "P0/P9"]}
    rows = []
    sections = re.split(r"Reviewer ([123])\s*", text)
    for i in range(1, len(sections), 2):
        reviewer = int(sections[i])
        pieces = re.split(r"(?m)^(\d+)\.\s+", sections[i + 1])
        for j in range(1, len(pieces), 2):
            number = int(pieces[j])
            rows.append({"id": f"R{reviewer}.{number}", "comment_verbatim": pieces[j + 1].strip(),
                         "tasks": maps[reviewer][number - 1], "status": "open", "completed_evidence": "",
                         "remaining_work": "See revision plan; final reply must cite completed evidence only."})
    assert len(rows) == 20
    target = ROOT / "reviewer_tracker.csv"
    if not target.exists():
        write_csv(target, rows)
    response = ROOT / "response_to_reviewers_working.txt"
    if not response.exists():
        response.write_text("WORKING RECORD, NOT A SUBMISSION-READY RESPONSE\nNo response below claims that pending experiments are complete.\n\n" +
                            "\n\n".join(f"{row['id']}\nReviewer comment: {row['comment_verbatim']}\nStatus: Open ({row['tasks']}).\nResponse: Pending completed evidence.\nManuscript location: Pending." for row in rows), encoding="utf-8")


def main() -> None:
    rows, failures = [], []
    for directory in sorted(RAW.iterdir()):
        if not directory.is_dir():
            continue
        try:
            row = audit_run(directory)
            route = ET.parse(directory / "routes.rou.xml").getroot()
            car = next(vt for vt in route.findall("vType") if vt.get("id") == "car")
            row["car_tau_explicit"] = car.get("tau", "")
            row["car_action_step_explicit"] = car.get("actionStepLength", "")
            row["car_emission_class_explicit"] = car.get("emissionClass", "")
            truck = route.find("vType[@id='truck']")
            row["truck_present"] = truck is not None
            row["truck_emission_class_explicit"] = truck.get("emissionClass", "") if truck is not None else "not applicable"
            row["planned_flow_vehicles"] = sum(int(flow.attrib["number"]) for flow in route.findall("flow"))
            rows.append(row)
        except Exception as exc:
            failures.append({"run": directory.name, "error": str(exc)})
    write_csv(ROOT / "audit/historical_run_audit.csv", rows)
    (ROOT / "audit/historical_audit_failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    by_run = {row["run"]: row for row in rows}
    matches = []
    with (ROOT / "frozen/data/sumo_keyseed_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        for old in csv.DictReader(handle):
            seed = int(old["seed"])
            name = old.get("scenario_run") or (old["scenario"] if seed == 42 else f"{old['scenario']}_seed{seed}")
            recorded_name = name
            raw = by_run.get(name)
            if raw is None and seed == 42:
                fallback = by_run.get(old["scenario"])
                if fallback is not None and fallback["seed"] == seed:
                    name, raw = old["scenario"], fallback
            if raw is None or raw["seed"] != seed:
                raise ValueError(f"Missing or mismatched seed: {old['scenario']}, {seed}, {name}")
            matches.append({"scenario": old["scenario"], "seed": seed, "run": name,
                            "csv_recorded_run": recorded_name, "mapping": "exact" if name == recorded_name else "seed42 alias, validated raw header",
                            "arrived_csv_minus_raw": float(old["arrived_vehicles"]) - raw["end_arrived"],
                            "timeLoss_csv_minus_raw_s": float(old["mean_time_loss"]) - raw["trip_completed_timeLoss_mean_s"],
                            "teleports_csv_minus_raw": float(old["teleport_warnings"]) - raw["teleport_events"]})
    write_csv(ROOT / "audit/keyseed_provenance_check.csv", matches)
    baseline = [by_run[m["run"]] for m in matches if m["scenario"] == "baseline"]
    summary = []
    for metric in ("end_loaded", "end_inserted", "end_arrived", "end_waiting", "end_running",
                   "trip_completed_timeLoss_mean_s", "entry_mean_delay_inserted_s",
                   "network_vehicle_hours_discrete", "entry_vehicle_hours_discrete", "total_vehicle_hours_discrete",
                   "teleport_events", "teleported_unique_vehicles"):
        values = [row[metric] for row in baseline]
        summary.append({"metric": metric, "n": len(values), "mean": statistics.mean(values),
                        "sample_sd": statistics.stdev(values), "scope": "matched baseline keyseed runs; 0-3600 s"})
    write_csv(ROOT / "audit/baseline_tenseed_reaudit.csv", summary)
    signal_inventory()
    reviewer_tracker()
    print(json.dumps({"runs_audited": len(rows), "failures": failures, "keyseed_rows_checked": len(matches),
                      "max_abs_Q_discrepancy": max(abs(row["arrived_csv_minus_raw"]) for row in matches),
                      "max_abs_teleport_discrepancy": max(abs(row["teleports_csv_minus_raw"]) for row in matches)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
