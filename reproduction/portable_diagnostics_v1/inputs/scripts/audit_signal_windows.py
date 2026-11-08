"""Describe queue-supported green windows; downstream eligibility remains unmeasured."""
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from audit_metrics import write_csv
from audit_core_warnings import read_csv
from analyze_stopline_pilot import read_queues, read_tls, compress_windows, queue_summary

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core_detector_batch"
OUT = ROOT / "stage4_warning_audit"


def queue_during_pair(queue, start, finish):
    if finish <= start:
        return False
    # Require an observed jam in every intersected one-second detector interval.
    return all(queue[t]["mean_jam_veh"] > 0
               for t in range(math.floor(start), math.ceil(finish)))


def select_operational_pairs(events, queue, discard=4):
    events = sorted(events, key=lambda e: float(e["front_time_s"]))
    result = []
    for first, second in zip(events[discard:], events[discard + 1:]):
        if first["notification_time_ambiguous"] == "True" or second["notification_time_ambiguous"] == "True":
            continue
        start, finish = float(first["front_time_s"]), float(second["front_time_s"])
        if queue_during_pair(queue, start, finish):
            result.append((first["vehicle"], second["vehicle"], finish - start))
    return result


def main():
    inventory = json.loads((CORE / "detector_inventory.json").read_text())
    runs = read_csv(OUT / "core_run_results_corrected.csv")
    windows_out, pairs_out, lane_out = [], [], []
    for run in runs:
        directory = Path(run["source_dir"])
        queues = read_queues(directory / "lane_queues.xml", {l["queue_id"]: l["lane"] for l in inventory})
        tls = read_tls(directory / "tls_states.xml", 0.5)
        by_lane = defaultdict(list)
        for event in read_csv(CORE / "processed" / directory.name / "aligned_front_crossings.csv"):
            by_lane[event["lane"]].append(event)
        for lane in inventory:
            lid = lane["lane"]
            local_rows, local_pairs = [], []
            for index, window in enumerate(compress_windows(tls[lane["signal"]], lane["link_indices"], 0.5, 3600)):
                if window["state"] != "G":
                    continue
                begin, end = window["begin_s"], window["end_s"]
                events = [e for e in by_lane[lid] if begin <= float(e["phase_evaluation_time_s"]) < end]
                certain = [e for e in events if e["phase_timing_ambiguous"] == "False"
                           and e["notification_step_state"] == "G"]
                before = queues[lid].get(int(begin) - 1)
                pre_queue = before is not None and before["mean_jam_veh"] > 0
                candidate = window["complete_window"] and pre_queue and len(certain) == len(events)
                pairs = select_operational_pairs(certain, queues[lid]) if candidate else []
                common = {"run": directory.name, "scenario": run["scenario"], "seed": run["seed"],
                          "lane": lid, "signal": lane["signal"], "window_index": index}
                row = {**common, **window, "protected_front_entries_certain": len(certain),
                       "phase_ambiguous_entries": len(events) - len(certain),
                       "queue_observed_before_green": pre_queue,
                       "pre_green_mean_max_jam_veh": before["mean_jam_veh"] if before else None,
                       "queue_supported_window": candidate,
                       "operational_headway_pairs_after_first4": len(pairs),
                       "mean_operational_headway_s": statistics.mean(p[2] for p in pairs) if pairs else None,
                       "median_operational_headway_s": statistics.median(p[2] for p in pairs) if pairs else None,
                       "teleport_events_in_run": run["teleport_events"],
                       "downstream_unblocked_verified": False, "saturation_estimate_eligible": False,
                       **queue_summary(queues[lid], begin, end, lane["queue_detector_length_m"])}
                local_rows.append(row)
                local_pairs.extend(p[2] for p in pairs)
                for first, second, headway in pairs:
                    pairs_out.append({**common, "first_vehicle": first, "second_vehicle": second,
                                      "headway_s": headway, "scope": "operational, not saturation headway"})
            windows_out.extend(local_rows)
            complete = [r for r in local_rows if r["complete_window"]]
            seconds = sum(r["end_s"] - r["begin_s"] for r in complete)
            count = sum(r["protected_front_entries_certain"] for r in complete)
            lane_out.append({"run": directory.name, "scenario": run["scenario"], "seed": run["seed"], "lane": lid,
                             "complete_protected_windows": len(complete),
                             "queue_supported_windows": sum(r["queue_supported_window"] for r in complete),
                             "complete_protected_green_s": seconds, "certain_front_entries": count,
                             "observed_service_veh_per_green_h": 3600 * count / seconds if seconds else None,
                             "operational_headway_pairs": len(local_pairs),
                             "median_operational_headway_s": statistics.median(local_pairs) if local_pairs else None,
                             "saturation_flow_veh_per_h": None,
                             "eligibility_limitation": "Downstream blockage not resolved; queues observed only over final up-to-100m; startup deletion alone does not establish saturation."})
        print(f"Green-window audit complete: {directory.name}", flush=True)
    write_csv(OUT / "protected_green_windows.csv", windows_out)
    write_csv(OUT / "queue_supported_headway_pairs.csv", pairs_out)
    write_csv(OUT / "lane_green_service_summary.csv", lane_out)
    checks = {"protected_windows_total": len(windows_out),
              "complete_protected_windows": sum(r["complete_window"] for r in windows_out),
              "queue_supported_windows": sum(r["queue_supported_window"] for r in windows_out),
              "operational_headway_pairs": len(pairs_out),
              "saturation_eligible_windows": 0,
              "interpretation": "Exploratory measurement audit, not a frozen diagnostic classifier or saturation-flow estimate. First four passages discarded within a complete protected-green window; pre-green and between-passage queues required. No threshold fitted to force any scenario ranking."}
    (OUT / "green_window_checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print(json.dumps(checks, indent=2), flush=True)


if __name__ == "__main__":
    main()
