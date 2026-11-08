"""Paired intervention effects, baseline controls and local trade-offs; no post-hoc tuning."""
import csv
import json
import math
import statistics
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from audit_metrics import audit_run, write_csv
from freeze_submission import sha256
from run_independent_intervention_v1 import OUT, SOURCE_BASE, ROOT, NETWORK, STATES, PLANS, SEEDS, TARGET_LANES, route_source
from stopline_instrumentation import lane_inventory


def ci(values):
    if len(values) != 5 or not all(math.isfinite(x) for x in values):
        raise ValueError("Expected five finite paired seed values")
    center = statistics.mean(values)
    half = 2.7764451051977987 * statistics.stdev(values) / math.sqrt(len(values))
    return {"mean": center, "low": center - half, "high": center + half, "n": len(values)}


def percentage(reference, intervention):
    if reference <= 0:
        raise ValueError("Nonpositive response denominator")
    return 100 * (intervention / reference - 1)


def directory_for(state, plan, seed):
    if state == "baseline" and plan == "reference":
        return SOURCE_BASE / f"fine_joint_seed{seed}"
    return OUT / "runs" / f"{state}_{plan}_seed{seed}"


def local_metrics(directory, inventory):
    loops = {row["loop_id"]: row["lane"] for row in inventory}
    queue_lanes = {row["queue_id"]: row["lane"] for row in inventory}
    counts, queue, periods = Counter(), Counter(), Counter()
    seen = set()
    for _, element in ET.iterparse(directory / "stopline_events.xml", events=("end",)):
        if element.tag != "instantOut":
            continue
        a = element.attrib
        if a["state"] == "enter" and 0 <= float(a["time"]) < 3600:
            key = (a["id"], a["vehID"], a["time"])
            if key in seen:
                raise RuntimeError("Duplicate front entry requires audit, not silent deduplication")
            seen.add(key)
            counts[loops[a["id"]]] += 1
        element.clear()
    for _, element in ET.iterparse(directory / "lane_queues.xml", events=("end",)):
        if element.tag != "interval":
            continue
        a = element.attrib
        duration = float(a["end"]) - float(a["begin"])
        if not (0 <= float(a["begin"]) < float(a["end"]) <= 3600):
            raise RuntimeError("Unexpected detector interval")
        lane = queue_lanes[a["id"]]
        periods[lane] += duration
        queue[lane] += float(a["meanMaxJamLengthInMeters"]) * duration / 3600
        element.clear()
    if set(periods) != set(queue_lanes.values()) or any(t != 3600 for t in periods.values()):
        raise RuntimeError("Incomplete queue period")
    return {lane: {"crossings": counts[lane], "queue_m": queue[lane]} for lane in queue_lanes.values()}


def compare(rows, prefix):
    return {metric: ci([row[metric] for row in rows]) for metric in rows[0] if metric.startswith(prefix)}


def main():
    digest = sha256(OUT / "protocol.json")
    inventory = lane_inventory(NETWORK)
    new_inventory = {row["lane"]: row for row in lane_inventory(OUT / "inputs/reallocation.net.xml")}
    donors = [row["lane"] for row in inventory if new_inventory[row["lane"]]["all_connections_green_s"] < row["all_connections_green_s"]]
    groups = {"target": TARGET_LANES, "donor": donors,
              **{signal: [row["lane"] for row in inventory if row["signal"] == signal] for signal in ["n1", "n2", "n4"]}}
    if set(TARGET_LANES) & set(donors):
        raise RuntimeError("Target/donor lane overlap")
    populations, local_rows, integrity = [], [], []
    measured = {}
    for state in STATES:
        for plan in PLANS:
            for seed in SEEDS:
                directory = directory_for(state, plan, seed)
                record = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
                reused = state == "baseline" and plan == "reference"
                if not reused and record["protocol_sha256"] != digest:
                    raise RuntimeError("Changed protocol")
                for name, expected in record["files_sha256"].items():
                    if sha256(directory / name) != expected:
                        raise RuntimeError(f"Changed run: {directory / name}")
                if sha256(directory / "routes.rou.xml") != sha256(route_source(state)):
                    raise RuntimeError("Adverse condition or demand was changed")
                network_expected = NETWORK if plan == "reference" else OUT / "inputs/reallocation.net.xml"
                cfg = ET.parse(directory / "run.sumocfg").getroot()
                if Path(cfg.find("input/net-file").attrib["value"]) != network_expected:
                    raise RuntimeError("Wrong plan network")
                if not reused and sha256(network_expected) != record["network_sha256"]:
                    raise RuntimeError("Network changed after run")
                integrity.append({"state": state, "plan": plan, "seed": seed,
                                  "files_verified": len(record["files_sha256"]), "reused": reused,
                                  "route_parameters_unchanged": True, "passed": True})
                audit = audit_run(directory)
                counts_match = (audit["trip_records"] == audit["end_loaded"] == 7900
                                and audit["trip_completed_count"] == audit["end_arrived"]
                                and audit["trip_unfinished_inserted_count"] == audit["end_running"]
                                and audit["trip_undeparted_count"] == audit["end_waiting"])
                if not counts_match:
                    raise RuntimeError("Population mismatch")
                context = {"state": state, "plan": plan, "seed": seed}
                population = {**context, **{key: audit[key] for key in [
                    "end_loaded", "end_inserted", "end_arrived", "end_running", "end_waiting",
                    "trip_completed_timeLoss_mean_s", "network_vehicle_hours_discrete",
                    "entry_vehicle_hours_discrete", "total_vehicle_hours_discrete", "teleport_events",
                    "teleported_unique_vehicles", "stat_safety_collisions", "stat_safety_emergencyBraking"]},
                    "timing_warning": bool(audit["tau_step_warning"] or audit["tau_action_warning"] or audit["integration_action_warning"])}
                populations.append(population)
                local = local_metrics(directory, inventory)
                for lane, values in local.items():
                    local_rows.append({**context, "lane": lane, **values})
                grouped = {name: {key: sum(local[lane][key] for lane in lanes) for key in ["crossings", "queue_m"]}
                           for name, lanes in groups.items()}
                measured[(state, plan, seed)] = {"population": population, "local": grouped}
    paired, loss_comparisons, contrasts = [], [], []
    for state in STATES:
        for seed in SEEDS:
            a = measured[(state, "reference", seed)]
            b = measured[(state, "reallocation", seed)]
            pa, pb = a["population"], b["population"]
            row = {"state": state, "seed": seed,
                   "Q_pct": percentage(pa["end_arrived"], pb["end_arrived"]),
                   "D_pct": percentage(pa["trip_completed_timeLoss_mean_s"], pb["trip_completed_timeLoss_mean_s"]),
                   "B_pct": percentage(pa["total_vehicle_hours_discrete"], pb["total_vehicle_hours_discrete"]),
                   "Q_vehicles": pb["end_arrived"] - pa["end_arrived"],
                   "B_vehicle_hours": pb["total_vehicle_hours_discrete"] - pa["total_vehicle_hours_discrete"],
                   "backlog_pp": 100 * (pb["end_waiting"] - pa["end_waiting"]) / 7900,
                   "collision_events_both_arms": pa["stat_safety_collisions"] + pb["stat_safety_collisions"],
                   "teleport_events_both_arms": pa["teleport_events"] + pb["teleport_events"],
                   "timing_warning": pa["timing_warning"] or pb["timing_warning"]}
            for group in groups:
                for key in ["crossings", "queue_m"]:
                    row[f"{group}_{key}_pct"] = percentage(a["local"][group][key], b["local"][group][key])
            paired.append(row)
            if state != "baseline":
                base = measured[("baseline", "reference", seed)]["population"]
                loss_comparisons.append({"state": state, "seed": seed,
                                         "Q_pct": percentage(base["end_arrived"], pa["end_arrived"]),
                                         "D_pct": percentage(base["trip_completed_timeLoss_mean_s"], pa["trip_completed_timeLoss_mean_s"]),
                                         "B_pct": percentage(base["total_vehicle_hours_discrete"], pa["total_vehicle_hours_discrete"])})
    for state in STATES[1:]:
        for seed in SEEDS:
            a = next(r for r in paired if r["state"] == "baseline" and r["seed"] == seed)
            b = next(r for r in paired if r["state"] == state and r["seed"] == seed)
            contrasts.append({"state": state, "seed": seed,
                              **{metric + "_contrast": b[metric] - a[metric] for metric in ["Q_pct", "D_pct", "B_pct", "Q_vehicles", "B_vehicle_hours"]}})
    summaries = []
    for state in STATES:
        selected = [r for r in paired if r["state"] == state]
        response = {key: ci([row[key] for row in selected]) for key in selected[0]
                    if key.endswith("_pct") or key in ["Q_vehicles", "B_vehicle_hours", "backlog_pp"]}
        warns = any(row["collision_events_both_arms"] or row["teleport_events_both_arms"] or row["timing_warning"] for row in selected)
        numeric_network_support = response["Q_pct"]["low"] > 2 and response["B_pct"]["high"] < -5 and response["backlog_pp"]["high"] <= 2
        local_support = response["target_crossings_pct"]["low"] > 2 and response["target_queue_m_pct"]["high"] < -5
        summaries.append({"state": state, "response": response, "warning_qualified": bool(warns),
                          "numeric_network_recovery": numeric_network_support,
                          "unqualified_network_recovery": numeric_network_support and not warns,
                          "target_local_corroboration": local_support,
                          "joint_supported_intervention": numeric_network_support and not warns and local_support,
                          "donor_queue_deterioration": response["donor_queue_m_pct"]["low"] > 5,
                          "collisions_both_arms": sum(r["collision_events_both_arms"] for r in selected),
                          "teleports_both_arms": sum(r["teleport_events_both_arms"] for r in selected)})
    summary = {"new_runs": 25, "reused_runs": 5, "n_seeds": 5, "scope": "exploratory independent-control intervention, not blind causal validation",
               "groups": groups, "conditions": summaries,
               "adverse_reference_vs_baseline": {state: {key: ci([r[key] for r in loss_comparisons if r["state"] == state])
                                                           for key in ["Q_pct", "D_pct", "B_pct"]} for state in STATES[1:]},
               "adverse_minus_baseline_intervention_response": {state: {key: ci([r[key] for r in contrasts if r["state"] == state])
                                                                       for key in contrasts[0] if key.endswith("_contrast")} for state in STATES[1:]}}
    for name, rows in [("population_accounting", populations), ("lane_measurements", local_rows), ("paired_intervention_effects", paired),
                       ("adverse_reference_responses", loss_comparisons), ("intervention_response_contrasts", contrasts), ("integrity_checks", integrity)]:
        write_csv(OUT / f"{name}.csv", rows)
    (OUT / "analysis_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
