"""Matched-seed outputs and lane-level evidence; never infer saturation flow."""
import csv
import json
import math
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict, Counter
from pathlib import Path

from audit_metrics import write_csv
from audit_phase_alignment import analyze as align
from analyze_stopline_pilot import read_queues, read_tls, cycle_intervals, queue_summary

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "core_detector_batch"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    results = read_csv(OUT / "run_results.csv")
    if len(results) != 9:
        raise RuntimeError("The frozen nine-run batch is incomplete")
    inventory = json.loads((OUT / "detector_inventory.json").read_text())
    lane_rows, cycle_rows, clock_checks, count_checks = [], [], [], []
    for result in results:
        directory = Path(result["source_dir"])
        events, clock = align(directory, inventory)
        clock_checks.append(clock)
        write_csv(OUT / "processed" / directory.name / "aligned_front_crossings.csv", events)
        by_lane = defaultdict(list)
        for event in events:
            by_lane[event["lane"]].append(event)
        queues = read_queues(directory / "lane_queues.xml", {r["queue_id"]: r["lane"] for r in inventory})
        tls = read_tls(directory / "tls_states.xml", 0.5)
        exits = Counter()
        for _, node in ET.iterparse(directory / "lane_flow.xml", events=("end",)):
            if node.tag == "lane":
                exits[node.attrib["id"]] += int(node.attrib.get("left", 0))
                node.clear()
        for lane in inventory:
            lid = lane["lane"]
            local = by_lane[lid]
            certain = Counter(r["notification_step_state"] for r in local if not r["phase_timing_ambiguous"])
            common = {"run": directory.name, "scenario": result["scenario"], "seed": result["seed"],
                      "signal": lane["signal"], "edge": lane["edge"], "lane": lid,
                      "warning_events_in_run": result["teleport_events"]}
            lane_rows.append({**common, "front_crossings": len(local),
                "protected_crossings_confirmed": certain["G"], "permissive_crossings_confirmed": certain["g"],
                "phase_ambiguous_crossings": sum(r["phase_timing_ambiguous"] for r in local),
                "homogeneous_signal_states": lane["homogeneous_signal_states"],
                "queue_detector_length_m": lane["queue_detector_length_m"],
                **queue_summary(queues[lid], 0, 3600, lane["queue_detector_length_m"])})
            count_checks.append({"run": directory.name, "lane": lid, "front_crossings": len(local),
                                 "lane_data_left": exits[lid], "difference": len(local) - exits[lid]})
            for index, (begin, end) in enumerate(cycle_intervals(tls[lane["signal"]])):
                subset = [r for r in local if begin <= r["phase_evaluation_time_s"] < end]
                cycle_rows.append({**common, "cycle_index": index, "begin_s": begin, "end_s": end,
                    "front_crossings": len(subset), "timing_ambiguous_crossings": sum(r["notification_time_ambiguous"] for r in subset),
                    **queue_summary(queues[lid], begin, end, lane["queue_detector_length_m"])})
        print(f"Processed {directory.name}: {len(events)} front crossings", flush=True)
    write_csv(OUT / "lane_diagnostics.csv", lane_rows)
    write_csv(OUT / "cycle_diagnostics.csv", cycle_rows)
    write_csv(OUT / "clock_alignment_checks.csv", clock_checks)
    write_csv(OUT / "count_checks.csv", count_checks)
    lookup = {(r["scenario"], int(r["seed"])): r for r in results}
    paired = []
    for scenario in ("heavyveh_very_high", "weather_heavy_rain"):
        for seed in (42, 2024, 2025):
            baseline, target = lookup["baseline", seed], lookup[scenario, seed]
            row = {"scenario": scenario, "seed": seed, "baseline_Q": baseline["end_arrived"],
                   "scenario_Q": target["end_arrived"], "teleport_events": target["teleport_events"],
                   "collision_teleport_events": target["collision_teleport_events"],
                   "unique_teleported_vehicles": target["teleported_unique_vehicles"]}
            for label, key in (("throughput", "end_arrived"), ("completed_delay", "trip_completed_timeLoss_mean_s"),
                               ("total_vehicle_hours", "total_vehicle_hours_discrete"), ("entry_vehicle_hours", "entry_vehicle_hours_discrete")):
                b, t = float(baseline[key]), float(target[key])
                row[label + "_change_pct"] = 100 * (t - b) / b
            paired.append(row)
    write_csv(OUT / "paired_effects.csv", paired)
    aggregate = []
    for scenario in ("heavyveh_very_high", "weather_heavy_rain"):
        group = [r for r in paired if r["scenario"] == scenario]
        for metric in ("throughput_change_pct", "completed_delay_change_pct", "total_vehicle_hours_change_pct"):
            values = [r[metric] for r in group]
            mean, sd = statistics.mean(values), statistics.stdev(values)
            half = 4.302652729911275 * sd / math.sqrt(3)
            aggregate.append({"scenario": scenario, "metric": metric, "n_seeds": 3, "mean": mean,
                              "sample_sd": sd, "ci95_lower_exploratory": mean - half,
                              "ci95_upper_exploratory": mean + half,
                              "scope": "conditional paired-seed t interval; warning events retained; not field or global validation"})
    write_csv(OUT / "paired_summary.csv", aggregate)
    summary = {"runs": 9, "lane_run_pairs": len(count_checks),
               "exact_count_matches": sum(r["difference"] == 0 for r in count_checks),
               "max_abs_count_difference": max(abs(r["difference"]) for r in count_checks),
               "complete_lane_cycles": len(cycle_rows), "phase_ambiguous_events": sum(r["phase_ambiguous_records"] for r in clock_checks),
               "saturation_flow_claim": False}
    (OUT / "analysis_checks.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
