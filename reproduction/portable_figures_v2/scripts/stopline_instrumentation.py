"""Place passive detectors using the frozen network's actual controlled lanes."""
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET


def lane_inventory(network: Path):
    root = ET.parse(network).getroot()
    lanes = {lane.attrib["id"]: (edge.attrib["id"], lane.attrib)
             for edge in root.findall("edge") if not edge.attrib["id"].startswith(":")
             for lane in edge.findall("lane")}
    programs = {}
    for tl in root.findall("tlLogic"):
        if tl.attrib.get("type") != "static":
            raise ValueError("Pilot requires static signals; inspect new programs first")
        if tl.attrib["id"] in programs:
            raise ValueError("Multiple programs require an explicit selection")
        programs[tl.attrib["id"]] = tl
    grouped = defaultdict(list)
    for connection in root.findall("connection"):
        a = connection.attrib
        if "tl" in a and not a["from"].startswith(":"):
            grouped[f"{a['from']}_{a['fromLane']}"].append(dict(a))
    result = []
    for lane_id, connections in sorted(grouped.items()):
        edge, lane = lanes[lane_id]
        signals = {c["tl"] for c in connections}
        if len(signals) != 1:
            raise ValueError(f"Multiple signals for {lane_id}")
        signal = signals.pop()
        indices = sorted({int(c["linkIndex"]) for c in connections})
        phases = programs[signal].findall("phase")
        homogeneous = all(len({p.attrib["state"][i] for i in indices}) == 1 for p in phases)
        length = float(lane["length"])
        cycle = sum(float(p.attrib["duration"]) for p in phases)
        green = sum(float(p.attrib["duration"]) for p in phases
                    if all(p.attrib["state"][i] in "Gg" for i in indices))
        protected = sum(float(p.attrib["duration"]) for p in phases
                        if all(p.attrib["state"][i] == "G" for i in indices))
        result.append({
            "lane": lane_id, "edge": edge, "signal": signal, "length_m": length,
            "link_indices": indices, "connections": connections,
            "directions": sorted({c["dir"] for c in connections}),
            "homogeneous_signal_states": homogeneous,
            "cycle_s": cycle, "program": programs[signal].attrib["programID"],
            "offset_s": float(programs[signal].attrib.get("offset", "0")),
            "all_connections_green_s": green, "all_connections_protected_s": protected,
            "loop_id": "stop_" + lane_id, "loop_pos_m": length,
            "queue_id": "queue_" + lane_id, "queue_pos_m": max(0.0, length - 100.0),
            "queue_end_m": length, "queue_detector_length_m": min(100.0, length),
            "scope": "lane-level crossing; shared-lane movements not separately identified"
        })
    if not result:
        raise ValueError("No controlled external lanes")
    return result


def append_detectors(additional, inventory):
    for row in inventory:
        ET.SubElement(additional, "instantInductionLoop", id=row["loop_id"],
                      lane=row["lane"], pos=f"{row['loop_pos_m']:.6f}",
                      file="stopline_events.xml", friendlyPos="false")
        ET.SubElement(additional, "laneAreaDetector", id=row["queue_id"],
                      lane=row["lane"], pos=f"{row['queue_pos_m']:.6f}",
                      endPos=f"{row['queue_end_m']:.6f}", period="1",
                      file="lane_queues.xml", friendlyPos="false",
                      timeThreshold="1", speedThreshold="1.388888889", jamThreshold="10")
    ET.SubElement(additional, "timedEvent", type="SaveTLSStates", dest="tls_states.xml")
    ET.SubElement(additional, "laneData", id="audit_lane_flow", period="300",
                  excludeEmpty="false", file="lane_flow.xml")
