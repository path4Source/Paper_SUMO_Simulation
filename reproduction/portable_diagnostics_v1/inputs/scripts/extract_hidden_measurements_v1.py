"""Export only permitted measurements; no routes, construction key or cause labels."""
import json
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from audit_metrics import audit_run


def measurements(directory, inventory):
    audit = audit_run(directory)
    loops = {r["loop_id"]: r["signal"] for r in inventory}
    queues = {r["queue_id"]: r["signal"] for r in inventory}
    count, queue, periods = Counter(), Counter(), Counter()
    for _, node in ET.iterparse(directory / "stopline_events.xml", events=("end",)):
        if node.tag == "instantOut":
            a = node.attrib
            if a["state"] == "enter" and 0 <= float(a["time"]) < 3600:
                count[loops[a["id"]]] += 1
            node.clear()
    for _, node in ET.iterparse(directory / "lane_queues.xml", events=("end",)):
        if node.tag == "interval":
            a = node.attrib
            duration = float(a["end"]) - float(a["begin"])
            queue[queues[a["id"]]] += float(a["meanMaxJamLengthInMeters"]) * duration / 3600
            periods[a["id"]] += duration
            node.clear()
    if set(periods) != set(queues) or any(t != 3600 for t in periods.values()):
        raise ValueError("Incomplete local measurement period")
    return {"seed": audit["seed"], "arrived": audit["end_arrived"],
            "delay": audit["trip_completed_timeLoss_mean_s"], "planned": audit["end_loaded"],
            "inserted": audit["end_inserted"], "running": audit["end_running"], "waiting": audit["end_waiting"],
            "vehicle_hours": audit["total_vehicle_hours_discrete"], "halting": audit["mean_halted_vehicles"],
            "teleports": audit["teleport_events"], "unique_teleported": audit["teleported_unique_vehicles"],
            "collisions": audit["stat_safety_collisions"],
            "config_warning": bool(audit["tau_step_warning"] or audit["tau_action_warning"] or audit["integration_action_warning"]),
            "local": {s: {"front_crossings": count[s], "queue_m": queue[s]} for s in ("n1", "n2", "n4")}}
