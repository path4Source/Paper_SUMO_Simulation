"""Unmodified calculation functions extracted from the archived analysis."""
import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict


def records(path, tag):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        context = ET.iterparse(stream, events=("start", "end"))
        _, root = next(context)
        for event, node in context:
            if event == "end" and node.tag == tag:
                yield dict(node.attrib)
                root.clear()


def reconcile(directory, inventory):
    loops = {r["loop_id"]:r["lane"] for r in inventory}
    fronts = Counter()
    for row in records(directory / "stopline_events.xml", "instantOut"):
        if row["state"] == "enter" and 0 <= float(row["time"]) < 3600:
            fronts[loops[row["id"]]] += 1
    totals = defaultdict(Counter)
    periods = list(records(directory / "lane_flow.xml", "interval"))
    assert len(periods) == 12
    assert all(float(row["begin"]) == i*300 and float(row["end"]) == (i+1)*300
               for i, row in enumerate(periods))
    observed = Counter()
    for row in records(directory / "lane_flow.xml", "lane"):
        observed[row["id"]] += 1
        for key in ("left", "teleported", "vaporized", "arrived", "laneChangedFrom"):
            totals[row["id"]][key] += int(row.get(key, 0))
    assert all(observed[r["lane"]] == 12 for r in inventory)
    return [dict(lane=r["lane"], front_entries=fronts[r["lane"]], **dict(totals[r["lane"]]),
                 corrected_left=totals[r["lane"]]["left"]-totals[r["lane"]]["teleported"],
                 residual=fronts[r["lane"]]-totals[r["lane"]]["left"]+totals[r["lane"]]["teleported"])
            for r in inventory]


def queue_duration(directory, inventory):
    detectors = {"audit_step_"+r["queue_id"]:r for r in inventory}
    tally = defaultdict(Counter)
    expected_begin = {key:0 for key in detectors}
    for row in records(directory / "queue_step.xml.gz", "interval"):
        key = row["id"]
        info = detectors[key]
        begin, end = float(row["begin"]), float(row["end"])
        assert abs(begin-expected_begin[key]) < 1e-7 and abs(end-begin-.1)<1e-7
        expected_begin[key] = end
        length = info["queue_detector_length_m"]
        extent = float(row["maxJamLengthInMeters"])
        c = tally[key]
        c["steps"] += 1
        c["at_length_steps"] += int(extent >= length)
        c["at_length_minus_001_steps"] += int(extent >= length-.01)
        c["at_length_plus_001_steps"] += int(extent >= length+.01)
        c["mean_max_extent_sum"] += float(row["meanMaxJamLengthInMeters"])
    assert all(abs(t-3600)<1e-7 for t in expected_begin.values())
    rows = []
    for key, info in detectors.items():
        c = tally[key]
        assert c["steps"] == 36000
        rows.append(dict(lane=info["lane"], detector_length_m=info["queue_detector_length_m"], steps=c["steps"],
            extent_at_length_s=.1*c["at_length_steps"], extent_at_length_minus_001_s=.1*c["at_length_minus_001_steps"],
            extent_at_length_plus_001_s=.1*c["at_length_plus_001_steps"], mean_max_extent_m=c["mean_max_extent_sum"]/c["steps"]))
    return rows


def xml_digest(path, tags):
    h = hashlib.sha256()
    count = 0
    context = ET.iterparse(path, events=("start", "end"))
    _, root = next(context)
    for event, node in context:
        if event == "end" and node.tag in tags:
            payload = (node.tag, sorted(node.attrib.items()))
            h.update(json.dumps(payload, separators=(",", ":")).encode())
            h.update(b"\n")
            count += 1
            root.clear()
    return dict(records=count, sha256=h.hexdigest())


def band_status(stats, band):
    if stats["lo"] >= -band and stats["hi"] <= band:
        return "within_band"
    if stats["lo"] > band or stats["hi"] < -band:
        return "outside_band"
    return "inconclusive"


def validate_population(metrics):
    assert metrics["unaccounted_inserted_end"] == 0 and metrics["ended_not_arrived"] == 0
    assert metrics["trip_records"] == metrics["end_loaded"]
    assert metrics["trip_completed_count"] == metrics["end_arrived"]
    assert metrics["trip_unfinished_inserted_count"] == metrics["end_running"]
    assert metrics["trip_undeparted_count"] == metrics["end_waiting"]
    assert metrics["end_loaded"] == metrics["end_inserted"] + metrics["end_waiting"]
    assert not metrics["integration_action_warning"]
