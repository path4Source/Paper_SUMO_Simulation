"""Lane-resolved crossings, actual signal windows and detector-limited queues."""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict, Counter
import json
import math
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

from audit_metrics import audit_run, write_csv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "stopline_pilot"


def read_tls(path, step, end=3600.0):
    result = defaultdict(list)
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag == "tlsState":
            a = node.attrib
            result[a["id"]].append((float(a["time"]), int(a["phase"]), a["state"], a["programID"]))
            node.clear()
    for signal, records in result.items():
        records.sort()
        if len(records) != round(end / step):
            raise ValueError(f"Incomplete signal trace {signal}: {len(records)}")
        for i, record in enumerate(records):
            if abs(record[0] - i * step) > 1e-6:
                raise ValueError(f"Missing/duplicate TLS time {signal}: {record[0]}")
        if len({r[3] for r in records}) != 1:
            raise ValueError("Unexpected program switch")
    return dict(result)


def lane_state(state, indices):
    values = {state[i] for i in indices}
    return next(iter(values)) if len(values) == 1 else "mixed"


def compress_windows(records, indices, step, end):
    windows = []
    for t, _, state, _ in records:
        value = lane_state(state, indices)
        if windows and windows[-1]["state"] == value:
            windows[-1]["end_s"] = min(t + step, end)
        else:
            windows.append({"begin_s": t, "end_s": min(t + step, end), "state": value})
    for w in windows:
        w["complete_window"] = w["begin_s"] > 0 and w["end_s"] < end
    return windows


def cycle_intervals(records):
    starts = [r[0] for i, r in enumerate(records)
              if r[1] == 0 and (i == 0 or records[i - 1][1] != 0)]
    return list(zip(starts, starts[1:]))


def read_events(path, detector_map):
    raw = defaultdict(list)
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag == "instantOut":
            a = node.attrib
            if a["id"] not in detector_map:
                raise ValueError(f"Unknown detector {a['id']}")
            if a["state"] in ("enter", "leave"):
                raw[(detector_map[a["id"]], a["vehID"])].append(
                    (float(a["time"]), a["state"], "occupancy" in a))
            node.clear()
    crossings = defaultdict(list)
    issues = Counter()
    for (lane, veh), events in raw.items():
        # File order can differ from interpolated event-time order.
        events.sort(key=lambda e: (e[0], e[1] != "enter"))
        active = None
        for time, state, longitudinal in events:
            if state == "enter":
                if active is not None:
                    if abs(time - active["front_time_s"]) < 1e-8:
                        # At the exact lane end, repeated notifications can report
                        # the same vehicle at the same interpolated entry time.
                        active["identical_time_entry_duplicates"] += 1
                        issues["identical_time_entry_duplicates"] += 1
                        continue
                    raise ValueError(f"Repeated unmatched E1 entry: {lane}, {veh}")
                active = {"lane": lane, "vehicle": veh, "front_time_s": time,
                          "identical_time_entry_duplicates": 0}
            elif active is not None:
                active.update(exit_time_s=time, exit_kind="longitudinal" if longitudinal else "nonlongitudinal")
                crossings[lane].append(active)
                active = None
            else:
                issues["leave_without_observed_entry"] += 1
        if active is not None:
            active.update(exit_time_s=None, exit_kind="end_censored")
            crossings[lane].append(active)
    for rows in crossings.values():
        rows.sort(key=lambda r: r["front_time_s"])
    return crossings, dict(issues)


def read_queues(path, detector_map, end=3600):
    data = defaultdict(dict)
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag == "interval":
            a = node.attrib
            lane = detector_map[a["id"]]
            begin, finish = float(a["begin"]), float(a["end"])
            if abs(finish - begin - 1) > 1e-6 or abs(begin - round(begin)) > 1e-6:
                raise ValueError("Expected complete 1s queue intervals")
            key = int(round(begin))
            if key in data[lane]:
                raise ValueError(f"Duplicate queue interval {lane}, {key}")
            data[lane][key] = {
                "mean_jam_veh": float(a["meanMaxJamLengthInVehicles"]),
                "max_jam_veh": float(a["maxJamLengthInVehicles"]),
                "max_jam_m": float(a["maxJamLengthInMeters"]),
                "mean_speed_m_s": float(a["meanSpeed"]),
                "mean_vehicles": float(a["meanVehicleNumber"])
            }
            node.clear()
    for lane in detector_map.values():
        if len(data[lane]) != end or set(data[lane]) != set(range(end)):
            raise ValueError(f"Incomplete queue trace {lane}")
    return data


def queue_summary(queue, begin, end, detector_length):
    total = 0.0
    maximum = maximum_m = occupied = clipped = 0.0
    for second in range(math.floor(begin), math.ceil(end)):
        dt = max(0.0, min(end, second + 1) - max(begin, second))
        r = queue[second]
        total += r["mean_jam_veh"] * dt
        occupied += (r["max_jam_veh"] > 0) * dt
        clipped += (r["max_jam_m"] >= detector_length - 7.5) * dt
        maximum = max(maximum, r["max_jam_veh"])
        maximum_m = max(maximum_m, r["max_jam_m"])
    return {"mean_max_jam_veh": total / (end - begin), "max_jam_veh": maximum,
            "max_jam_m": maximum_m, "queue_present_fraction": occupied / (end - begin),
            "near_detector_limit_fraction": clipped / (end - begin)}


def analyze(directory, inventory):
    metrics = audit_run(directory)
    step, end = metrics["step_s"], metrics["observation_end_s"]
    tls = read_tls(directory / "tls_states.xml", step, end)
    crossings, issues = read_events(directory / "stopline_events.xml", {r["loop_id"]: r["lane"] for r in inventory})
    queues = read_queues(directory / "lane_queues.xml", {r["queue_id"]: r["lane"] for r in inventory}, int(end))
    summaries, cycles, windows_out, events_out = [], [], [], []
    for lane in inventory:
        lid = lane["lane"]
        records = tls[lane["signal"]]
        times = [r[0] for r in records]
        windows = compress_windows(records, lane["link_indices"], step, end)
        boundaries = [w["begin_s"] for w in windows[1:]]
        usable = []
        states = Counter()
        for crossing in crossings[lid]:
            t = crossing["front_time_s"]
            if not 0 <= t < end:
                raise ValueError(f"Crossing outside observation {crossing}")
            state = lane_state(records[bisect_right(times, t) - 1][2], lane["link_indices"])
            near_boundary = any(abs(t - b) <= step for b in boundaries)
            row = {"run": directory.name, **crossing, "signal": lane["signal"],
                   "signal_state_at_front_time": state,
                   "within_one_step_of_state_change": near_boundary,
                   "phase_assignment_status": "boundary_uncertain" if near_boundary else "interior"}
            events_out.append(row)
            # A later lane-change/arrival departure from the loop does not undo
            # an already observed front crossing. Keep exit kind for the audit.
            usable.append(row)
            states[state] += 1
        durations = Counter()
        for w in windows:
            duration = w["end_s"] - w["begin_s"]
            durations[w["state"]] += duration
            selected = [r for r in usable if w["begin_s"] <= r["front_time_s"] < w["end_s"]]
            # No saturation estimator: describe headways away from phase boundaries only.
            interior = [r["front_time_s"] for r in selected
                        if not r["within_one_step_of_state_change"]]
            headways = [b - a for a, b in zip(interior, interior[1:])]
            before = queues[lid].get(int(w["begin_s"]) - 1)
            windows_out.append({"run": directory.name, "lane": lid, "edge": lane["edge"],
                "signal": lane["signal"], **w, "duration_s": duration,
                "front_crossings": len(selected), "pre_window_max_jam_veh": before["max_jam_veh"] if before else None,
                "operational_headway_pairs": len(headways) if w["state"] in "Gg" else 0,
                "mean_operational_headway_s": statistics.mean(headways) if headways and w["state"] in "Gg" else None,
                "headway_scope": "within same lane/state window; not saturation headway",
                **queue_summary(queues[lid], w["begin_s"], w["end_s"], lane["queue_detector_length_m"])})
        complete_cycles = cycle_intervals(records)
        for index, (begin, finish) in enumerate(complete_cycles):
            subset = [r for r in usable if begin <= r["front_time_s"] < finish]
            cstates = Counter(r["signal_state_at_front_time"] for r in subset)
            g_seconds = sum(max(0, min(finish, w["end_s"]) - max(begin, w["begin_s"]))
                            for w in windows if w["state"] == "G")
            cycles.append({"run": directory.name, "lane": lid, "edge": lane["edge"],
                "signal": lane["signal"], "cycle_index": index, "begin_s": begin, "end_s": finish,
                "front_crossings": len(subset), "protected_crossings": cstates["G"],
                "permissive_crossings": cstates["g"], "protected_green_s": g_seconds,
                "observed_protected_service_veh_per_green_h": 3600 * cstates["G"] / g_seconds if g_seconds else None,
                **queue_summary(queues[lid], begin, finish, lane["queue_detector_length_m"])})
        summaries.append({"run": directory.name, "lane": lid, "edge": lane["edge"], "signal": lane["signal"],
            "homogeneous_signal_states": lane["homogeneous_signal_states"],
            "deduplicated_front_entries": len(crossings[lid]), "accepted_front_crossings": len(usable),
            "repeated_entry_records": sum(r["identical_time_entry_duplicates"] for r in crossings[lid]),
            "nonlongitudinal_loop_leaves": sum(r["exit_kind"] == "nonlongitudinal" for r in crossings[lid]),
            "end_censored_front_crossings": sum(r["exit_kind"] == "end_censored" for r in usable),
            "protected_green_s": durations["G"], "permissive_green_s": durations["g"],
            "protected_crossings": states["G"], "permissive_crossings": states["g"],
            "other_state_crossings": sum(v for k, v in states.items() if k not in ("G", "g")),
            "near_boundary_crossings": sum(r["within_one_step_of_state_change"] for r in usable),
            "complete_cycles": len(complete_cycles),
            "observed_protected_service_veh_per_green_h": 3600 * states["G"] / durations["G"] if durations["G"] else None,
            **queue_summary(queues[lid], 0, end, lane["queue_detector_length_m"])})
    return summaries, cycles, windows_out, events_out, issues


def main():
    inventory = json.loads((OUT / "detector_inventory.json").read_text())
    all_summary, all_cycles, all_windows = [], [], []
    checks = []
    for directory in sorted((OUT / "runs").iterdir()):
        if not (directory / "complete.json").is_file():
            raise RuntimeError(f"Unfinished detector pilot {directory}")
        summary, cycles, windows, events, issues = analyze(directory, inventory)
        destination = OUT / "processed" / directory.name
        write_csv(destination / "front_crossings.csv", events)
        all_summary.extend(summary)
        all_cycles.extend(cycles)
        all_windows.extend(windows)
        checks.append({"run": directory.name, "lanes": len(summary), "crossings": len(events),
                       "complete_lane_cycles": len(cycles), "parser_issues": issues})
    write_csv(OUT / "lane_summary.csv", all_summary)
    write_csv(OUT / "complete_cycle_diagnostics.csv", all_cycles)
    write_csv(OUT / "signal_window_diagnostics.csv", all_windows)
    (OUT / "parser_checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
