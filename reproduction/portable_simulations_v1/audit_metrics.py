"""Explicit observation scopes for legacy and revision SUMO output."""
from __future__ import annotations

import csv
import json
import re
import statistics
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"No records for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def embedded_config(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as handle:
        header = handle.read(30000)
    match = re.search(r"<sumoConfiguration\b.*?</sumoConfiguration>", header, re.S)
    if not match:
        raise ValueError(f"No configuration header in {path}")
    root = ET.fromstring(match.group())
    return {node.tag: node.attrib["value"] for node in root.iter() if "value" in node.attrib}


def summary_metrics(path: Path, begin: float, end: float, step: float) -> dict:
    last = None
    totals = Counter()
    observed = 0
    previous_time = None
    max_gap = 0.0
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag != "step":
            continue
        t = float(node.attrib["time"])
        if previous_time is not None:
            max_gap = max(max_gap, t - previous_time)
        previous_time = t
        if begin <= t < end:
            dt = min(step, end - t)
            for key in ("running", "waiting", "halting"):
                totals[key] += float(node.attrib[key]) * dt
            last = dict(node.attrib)
            observed += 1
        node.clear()
    if last is None:
        raise ValueError(f"No observed summary steps: {path}")
    if abs(observed * step - (end - begin)) > 1e-5 or max_gap > step + 1e-5:
        raise ValueError(f"Incomplete or downsampled summary: {path}")
    result = {f"end_{key}": int(float(last[key])) for key in
              ("loaded", "inserted", "arrived", "ended", "running", "waiting")}
    result.update({"observation_begin_s": begin, "observation_end_s": end,
                   "step_s": step, "summary_steps": observed,
                   "arrived_veh_per_h": result["end_arrived"] * 3600 / (end - begin),
                   "network_vehicle_hours_discrete": totals["running"] / 3600,
                   "entry_vehicle_hours_discrete": totals["waiting"] / 3600,
                   "total_vehicle_hours_discrete": (totals["running"] + totals["waiting"]) / 3600,
                   "mean_halted_vehicles": totals["halting"] / (end - begin),
                   "entry_mean_delay_inserted_s": float(last["meanWaitingTime"]),
                   "unaccounted_inserted_end": result["end_inserted"] - result["end_ended"] - result["end_running"],
                   "ended_not_arrived": result["end_ended"] - result["end_arrived"]})
    return result


def trip_metrics(path: Path) -> dict:
    counts = Counter()
    totals = Counter()
    ids = set()
    for _, trip in ET.iterparse(path, events=("end",)):
        if trip.tag != "tripinfo":
            continue
        a = trip.attrib
        if a["id"] in ids:
            raise ValueError(f"Duplicate trip ID in {path}: {a['id']}")
        ids.add(a["id"])
        depart, arrival = float(a["depart"]), float(a["arrival"])
        group = "undeparted" if depart < 0 else "completed" if arrival >= 0 else "unfinished_inserted"
        counts[group] += 1
        for metric in ("timeLoss", "duration", "departDelay"):
            if metric in a:
                value = float(a[metric])
                if value >= 0:
                    totals[(group, metric)] += value
                    counts[(group, metric)] += 1
        trip.clear()
    out = {"trip_records": len(ids)}
    for group in ("completed", "unfinished_inserted", "undeparted"):
        out[f"trip_{group}_count"] = counts[group]
        for metric in ("timeLoss", "duration", "departDelay"):
            n = counts[(group, metric)]
            out[f"trip_{group}_{metric}_mean_s"] = totals[(group, metric)] / n if n else None
            out[f"trip_{group}_{metric}_sum_s"] = totals[(group, metric)] if n else None
    return out


def warning_metrics(path: Path) -> dict:
    if not path.is_file():
        return {"warning_log_present": False, "teleport_events": None, "teleported_unique_vehicles": None}
    text = path.read_text(encoding="utf-8", errors="replace")
    starts = [line for line in text.splitlines() if "Teleporting vehicle '" in line]
    ids, causes, lanes = set(), Counter(), Counter()
    for line in starts:
        vehicle = re.search(r"Teleporting vehicle '([^']+)'", line)
        if not vehicle:
            raise ValueError(f"Unparsed teleport event: {line}")
        ids.add(vehicle[1])
        cause = "collision" if re.search(r"; (?:junction |frontal |side )?collision\b", line) else "jam" if "; waited too long (jam)" in line else \
                "yield" if "(yield)" in line else "wrongLane" if "(wrong lane)" in line else "other"
        causes[cause] += 1
        lane = re.search(r"lane='([^']+)'", line)
        lanes[lane[1] if lane else "unresolved"] += 1
    return {"warning_log_present": True, "teleport_events": len(starts),
            "teleported_unique_vehicles": len(ids), "collision_teleport_events": causes["collision"],
            "teleport_causes_json": json.dumps(dict(causes), sort_keys=True),
            "teleport_lanes_json": json.dumps(dict(lanes), sort_keys=True),
            "tau_step_warning": "lower than simulation step size" in text,
            "integration_action_warning": "but step-method.ballistic was not set" in text,
            "tau_action_warning": "lower than the action step" in text or "lower than action step" in text}


def audit_run(directory: Path) -> dict:
    config = embedded_config(directory / "summary.xml")
    step = float(config.get("step-length", "1"))
    result = {"run": directory.name, "source_dir": str(directory),
              "seed": int(config.get("seed", "23423")),
              "step_declared": "step-length" in config,
              "action_step_s": float(config.get("default.action-step-length", "0")) or step,
              "action_step_source": "global option or step default; inspect vType overrides",
              "integration_explicit": config.get("step-method.ballistic", "not explicit"),
              "network_path_recorded": config.get("net-file", ""),
              "collision_action": config.get("collision.action", "teleport"),
              "collision_check_junctions": config.get("collision.check-junctions", "false"),
              "time_to_teleport_s": float(config.get("time-to-teleport", "300")),
              "unfinished_output_enabled": config.get("tripinfo-output.write-unfinished", "false"),
              "undeparted_output_enabled": config.get("tripinfo-output.write-undeparted", "false")}
    result.update(summary_metrics(directory / "summary.xml", float(config.get("begin", "0")),
                                  float(config["end"]), step))
    result.update(trip_metrics(directory / "tripinfo.xml"))
    result.update(warning_metrics(directory / "sumo_stderr.log"))
    tp = result.get("teleported_unique_vehicles")
    result["teleported_unique_pct_inserted"] = 100 * tp / result["end_inserted"] if tp is not None and result["end_inserted"] else None
    statistics_file = directory / "statistics.xml"
    if statistics_file.exists():
        root = ET.parse(statistics_file).getroot()
        for tag in ("vehicles", "teleports", "safety", "vehicleTripStatistics"):
            node = root.find(tag)
            if node is not None:
                for key, val in node.attrib.items():
                    result[f"stat_{tag}_{key}"] = float(val)
    return result


def mean_sample_sd(values: list[float]) -> tuple[float, float]:
    return statistics.mean(values), statistics.stdev(values) if len(values) > 1 else 0.0
