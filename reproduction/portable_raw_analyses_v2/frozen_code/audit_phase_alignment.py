"""Check E1 interpolation against actual notification-step TLS states."""
from bisect import bisect_right
from collections import Counter
import csv
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from audit_metrics import audit_run, write_csv
from analyze_stopline_pilot import read_tls, lane_state

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "stage3_phase_alignment"


def notification_records(path):
    active, complete = {}, []
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag != "instantOut":
            continue
        a = node.attrib
        key = a["id"], a["vehID"]
        t = float(a["time"])
        if a["state"] == "enter":
            if key in active:
                if active[key]["front_time_s"] != t:
                    raise ValueError(f"Nonidentical repeated entry: {key}")
                active[key]["duplicate_records"] += 1
            else:
                active[key] = {"detector": key[0], "vehicle": key[1], "front_time_s": t,
                               "first_stay_step_s": None, "duplicate_records": 0}
        elif a["state"] == "stay" and key in active:
            if active[key]["first_stay_step_s"] is None:
                active[key]["first_stay_step_s"] = t
        elif a["state"] == "leave" and key in active:
            complete.append(active.pop(key))
        node.clear()
    complete.extend(active.values())
    return complete


def interpolation_step(time, step):
    return round(math.ceil((time - 1e-9) / step) * step, 8)


def analyze(directory, inventory):
    step = audit_run(directory)["step_s"]
    tls = read_tls(directory / "tls_states.xml", step)
    times = {signal: [r[0] for r in records] for signal, records in tls.items()}
    detectors = {r["loop_id"]: r for r in inventory}
    records = notification_records(directory / "stopline_events.xml")
    counts = Counter()
    results = []
    for record in records:
        lane = detectors[record["detector"]]
        signal, indices = lane["signal"], lane["link_indices"]
        t, actual = record["front_time_s"], record["first_stay_step_s"]
        inferred = interpolation_step(t, step)
        near_rounding = abs(t / step - round(t / step)) * step <= 0.011
        direct = actual is not None
        if direct and not (-0.011 <= actual - t <= step + 0.011):
            raise ValueError(f"E1 interpolation outside a step: {record}")
        if direct and abs(actual - inferred) > 1e-6:
            counts["ceil_mismatch"] += 1
            if not near_rounding:
                raise ValueError(f"Unexplained non-boundary notification mismatch: {record}")
            counts["ceil_mismatch_near_rounded_step_boundary"] += 1
        # The output source emits enter at SIMTIME-step+interpolation, stay at
        # SIMTIME, and TLS at SIMTIME. Prefer the observed stay notification.
        evaluation_time = actual if direct else inferred
        old_index = bisect_right(times[signal], t) - 1
        index = bisect_right(times[signal], evaluation_time) - 1
        old = lane_state(tls[signal][old_index][2], indices)
        corrected = lane_state(tls[signal][index][2], indices)
        candidates = {corrected}
        if not direct and near_rounding:
            next_index = bisect_right(times[signal], evaluation_time + step) - 1
            candidates.add(lane_state(tls[signal][next_index][2], indices))
        phase_ambiguous = len(candidates) > 1
        counts["phase_ambiguous_records"] += phase_ambiguous
        if direct:
            counts["direct_notification_records"] += 1
            counts["direct_old_phase_disagreements"] += old != corrected
        else:
            counts["no_stay_records_inferred"] += 1
            counts["no_stay_rounding_ambiguous"] += near_rounding
        results.append({"run": directory.name, "lane": lane["lane"], "signal": signal, **record,
                        "phase_evaluation_time_s": evaluation_time,
                        "phase_clock_source": "observed_stay_notification" if direct else "inferred_from_interpolated_entry",
                        "notification_time_ambiguous": not direct and near_rounding,
                        "phase_timing_ambiguous": phase_ambiguous,
                        "possible_signal_states_json": json.dumps(sorted(candidates)),
                        "old_floor_lookup_state": old, "notification_step_state": corrected,
                        "phase_changed_by_alignment": old != corrected})
    counts["front_crossings"] = len(results)
    return results, {"run": directory.name, "step_s": step, **dict(counts)}


def main():
    source = ROOT / "stopline_pilot"
    inventory = json.loads((source / "detector_inventory.json").read_text())
    summaries = []
    for directory in sorted((source / "runs").iterdir()):
        events, summary = analyze(directory, inventory)
        write_csv(OUT / directory.name / "aligned_front_crossings.csv", events)
        summaries.append(summary)
    write_csv(OUT / "clock_alignment_checks.csv", summaries)
    note = {
        "scope": "Version-specific internal timing audit, not field validation or a saturation-flow estimate.",
        "evidence": "E1 enter timestamps are interpolated before the notification step; same-event stay output identifies the actual simulation processing step. TLS state is saved at that processing step.",
        "sources": [
            "https://raw.githubusercontent.com/eclipse-sumo/sumo/v1_24_0/src/microsim/output/MSInstantInductLoop.cpp",
            "https://raw.githubusercontent.com/eclipse-sumo/sumo/v1_24_0/src/microsim/actions/Command_SaveTLSState.cpp"],
        "rule": "Use observed first stay time where present; otherwise ceil the interpolated entry time to the simulation step. For entries rounded to a step boundary without a stay notification, retain ambiguity rather than force a phase label.",
        "consequence": "Earlier floor-time phase assignments are superseded for aligned analyses, but raw outputs and prior diagnostic tables are retained. Crossing totals are unchanged.",
        "remaining": "Queue conditioning, startup headways, blocking and movement ambiguity still prevent a saturation-flow claim."
    }
    (OUT / "timing_method.json").write_text(json.dumps(note, indent=2), encoding="utf-8")
    print(json.dumps(summaries, indent=2), flush=True)


if __name__ == "__main__":
    main()
