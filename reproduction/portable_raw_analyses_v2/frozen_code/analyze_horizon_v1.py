"""Population-aware horizon audit, with exact pre-extension prefix checks."""
import csv
import json
import math
from pathlib import Path
import re
import statistics
import xml.etree.ElementTree as ET
from audit_metrics import write_csv
from run_horizon_v1 import ROOT, OUT, sha

DT = 0.1
HORIZONS = [3600, 5400, 7200]
WINDOWS = [(0, 600), (600, 1800), (1800, 3600), (3600, 5400), (5400, 7200), (600, 3600)]


def steps(path):
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag == "step":
            yield dict(node.attrib)
            node.clear()


def prefix_check(extended, reference):
    old = iter(steps(reference))
    checked = 0
    for row in steps(extended):
        if float(row["time"]) >= 3600:
            break
        prior = next(old, None)
        if prior is None or row != prior:
            raise ValueError("Summary prefix differs: %s time %s" % (extended, row["time"]))
        checked += 1
    assert checked == 36000 and next(old, None) is None
    return checked


def summarize(path):
    ranges = [(0, h) for h in HORIZONS] + WINDOWS
    accum = {r: dict(network=0.0, entry=0.0, halting=0.0, transit=0.0, n=0,
                     start_arrived=0, end=None) for r in ranges}
    previous = None
    drain = None
    timeline = []
    count = 0
    for row in steps(path):
        t = float(row["time"])
        assert abs(t - count * DT) < 1e-6, (t, count)
        count += 1
        running, waiting = int(row["running"]), int(row["waiting"])
        remainder = int(row["inserted"]) - int(row["ended"]) - running
        assert remainder >= 0
        if drain is None and t >= 3600 and int(row["arrived"]) == 7900 and running == 0 and waiting == 0:
            drain = round(t + DT, 1)
        for (a, b), v in accum.items():
            if a <= t < b:
                if v["n"] == 0:
                    v["start_arrived"] = int(previous["arrived"]) if previous else 0
                v["n"] += 1
                v["network"] += running * DT
                v["entry"] += waiting * DT
                v["halting"] += int(row["halting"]) * DT
                v["transit"] += remainder * DT
                v["end"] = row
        if count % 3000 == 0:
            timeline.append(dict(boundary_s=round(t + DT, 1), arrived=int(row["arrived"]),
                                 running=running, waiting=waiting, active_remainder=remainder))
        previous = row
    assert count == 72000, count
    result = {}
    for (a, b), v in accum.items():
        assert v["n"] == round((b-a)/DT)
        end = v["end"]
        arrivals = int(end["arrived"]) - v["start_arrived"]
        result[(a, b)] = dict(
            begin_s=a, end_s=b, scheduled_cohort=7900,
            loaded_end=int(end["loaded"]), inserted_end=int(end["inserted"]),
            arrived_end=int(end["arrived"]), ended_end=int(end["ended"]),
            running_end=int(end["running"]), waiting_end=int(end["waiting"]),
            active_remainder_end=int(end["inserted"])-int(end["ended"])-int(end["running"]),
            completions_in_window=arrivals, completion_rate_veh_h=arrivals*3600/(b-a),
            completion_fraction_end_pct=int(end["arrived"])/79,
            network_vehicle_hours=v["network"]/3600,
            entry_vehicle_hours=v["entry"]/3600,
            burden_vehicle_hours=(v["network"]+v["entry"])/3600,
            active_remainder_vehicle_hours=v["transit"]/3600,
            mean_halting=v["halting"]/(b-a), summary_rows=v["n"])
    return result, drain, timeline


def trip_rows(path):
    rows = []
    ids = set()
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag == "tripinfo":
            a = dict(node.attrib)
            assert a["id"] not in ids
            ids.add(a["id"])
            rows.append(a)
            node.clear()
    assert len(rows) == 7900
    return rows


def population_at(trips, horizon):
    completed = [a for a in trips if 0 <= float(a["arrival"]) < horizon]
    inserted = [a for a in trips if 0 <= float(a["depart"]) < horizon]
    return dict(trip_completed=len(completed), trip_inserted=len(inserted),
                trip_undeparted=7900-len(inserted), trip_not_arrived_inserted=len(inserted)-len(completed),
                completed_mean_time_loss_s=statistics.mean(float(a["timeLoss"]) for a in completed) if completed else None,
                completed_mean_duration_s=statistics.mean(float(a["duration"]) for a in completed) if completed else None,
                completed_mean_depart_delay_s=statistics.mean(float(a["departDelay"]) for a in completed) if completed else None,
                completed_mean_total_elapsed_s=statistics.mean(float(a["duration"])+float(a["departDelay"]) for a in completed) if completed else None)


def events(path):
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "Teleporting vehicle '" not in line:
            continue
        vehicle = re.search(r"Teleporting vehicle '([^']+)'", line)
        t = re.search(r"time=([0-9.]+)", line)
        assert vehicle and t, line
        found.append(dict(time=float(t[1].rstrip(".")), vehicle=vehicle[1], collision="collision" in line))
    return found


def warning_counts(found, a, b):
    selected = [v for v in found if a <= v["time"] < b]
    return dict(teleport_events=len(selected), teleport_unique=len({v["vehicle"] for v in selected}),
                collision_teleports=sum(v["collision"] for v in selected))


def mean_ci(values):
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0
    half = 2.776445105 * sd / math.sqrt(len(values))
    return dict(mean=mean, sd=sd, ci_low=mean-half, ci_high=mean+half, n=len(values))


def analyze():
    protocol = json.loads((OUT / "protocol.json").read_text())
    horizons, windows, timelines, integrity, trip_audits = [], [], [], [], []
    for item in protocol["sources"]:
        state, seed = item["state"], item["seed"]
        directory = OUT / "runs" / ("%s_seed%d" % (state, seed))
        marker = json.loads((directory / "complete.json").read_text())
        assert marker["protocol_sha256"] == sha(OUT / "protocol.json")
        for name, digest in marker["files_sha256"].items():
            assert sha(directory / name) == digest, (directory, name)
        prefix = prefix_check(directory / "summary.xml", Path(item["source"]) / "summary.xml")
        ranges, drain, series = summarize(directory / "summary.xml")
        trips = trip_rows(directory / "tripinfo.xml")
        warnings = events(directory / "sumo_stderr.log")
        meta = dict(state=state, seed=seed)
        for horizon in HORIZONS:
            r = dict(meta, **ranges[(0, horizon)], **population_at(trips, horizon),
                     **warning_counts(warnings, 0, horizon), drain_boundary_s=drain,
                     right_censored_at_7200=drain is None)
            assert r["loaded_end"] == 7900
            assert r["inserted_end"] + r["waiting_end"] == 7900
            assert r["arrived_end"] == r["trip_completed"]
            assert r["inserted_end"] == r["trip_inserted"]
            assert r["ended_end"] == r["arrived_end"]
            horizons.append(r)
        for a, b in WINDOWS:
            windows.append(dict(meta, **ranges[(a, b)], **warning_counts(warnings, a, b)))
        timelines.extend(dict(meta, **row) for row in series)
        final = ranges[(0, 7200)]
        full = population_at(trips, 7200)
        # This comparison is diagnostic, not an equality assumption in teleport runs.
        sum_elapsed_h = sum(float(t["duration"])+float(t["departDelay"]) for t in trips
                            if 0 <= float(t["arrival"]) < 7200)/3600
        trip_audits.append(dict(meta, drain_boundary_s=drain, completed_at_cap=full["trip_completed"],
                               completed_elapsed_vehicle_hours=sum_elapsed_h,
                               summary_burden_vehicle_hours=final["burden_vehicle_hours"],
                               difference_vehicle_hours=sum_elapsed_h-final["burden_vehicle_hours"],
                               all_completed=full["trip_completed"] == 7900))
        integrity.append(dict(meta, prefix_rows_identical=prefix, hashes_verified=True,
                              horizon_accounting_verified=True, summary_rows=72000,
                              final_trip_records=len(trips)))
        print("audited", state, seed, "drain", drain, flush=True)
    paired = []
    for kind, rows in [("horizon", horizons), ("window", windows)]:
        metrics = ["completions_in_window", "burden_vehicle_hours", "network_vehicle_hours", "entry_vehicle_hours"]
        if kind == "horizon":
            metrics += ["completed_mean_time_loss_s", "completed_mean_total_elapsed_s"]
        lookup = {(r["state"], r["seed"], r["begin_s"], r["end_s"]): r for r in rows}
        for r in rows:
            if r["state"] == "baseline":
                continue
            base = lookup[("baseline", r["seed"], r["begin_s"], r["end_s"])]
            for m in metrics:
                delta = 100*(r[m]-base[m])/base[m] if base[m] else None
                paired.append(dict(kind=kind, state=r["state"], seed=r["seed"], begin_s=r["begin_s"],
                                   end_s=r["end_s"], metric=m, value=r[m], baseline=base[m],
                                   difference=r[m]-base[m], percent_response=delta))
    comparisons = []
    groups = sorted({(r["kind"], r["state"], r["begin_s"], r["end_s"], r["metric"]) for r in paired})
    for kind, state, a, b, m in groups:
        rows = [r for r in paired if (r["kind"], r["state"], r["begin_s"], r["end_s"], r["metric"]) == (kind, state, a, b, m)]
        available = [r["percent_response"] for r in rows if r["percent_response"] is not None]
        comparisons.append(dict(kind=kind, state=state, begin_s=a, end_s=b, metric=m,
                                percent_response_defined=len(available)==5,
                                **mean_ci(available if len(available)==5 else [r["difference"] for r in rows])))
    state_horizon = []
    for state in protocol["states"]:
        for h in HORIZONS:
            rows = [r for r in horizons if r["state"] == state and r["end_s"] == h]
            numeric = ["inserted_end", "arrived_end", "waiting_end", "running_end", "burden_vehicle_hours",
                       "network_vehicle_hours", "entry_vehicle_hours", "active_remainder_vehicle_hours",
                       "completed_mean_time_loss_s", "completed_mean_depart_delay_s", "completed_mean_duration_s",
                       "completed_mean_total_elapsed_s", "completion_fraction_end_pct"]
            result = dict(state=state, end_s=h, n=5)
            for m in numeric:
                result[m+"_mean"] = statistics.mean(r[m] for r in rows)
                result[m+"_sd"] = statistics.stdev(r[m] for r in rows)
            result.update(teleport_events_total=sum(r["teleport_events"] for r in rows),
                          collision_teleports_total=sum(r["collision_teleports"] for r in rows))
            state_horizon.append(result)
    for name, rows in [("horizon_populations", horizons), ("window_populations", windows),
                       ("timeline", timelines), ("integrity_checks", integrity), ("trip_burden_crosscheck", trip_audits),
                       ("paired_responses", paired), ("response_summary", comparisons), ("state_horizon_summary", state_horizon)]:
        write_csv(OUT / (name+".csv"), rows)
    summary = dict(protocol_sha256=sha(OUT / "protocol.json"), completed_new_runs=15,
                   all_prefixes_exact=True, checked_prefix_steps=540000, all_accounting_checks=True,
                   all_drained_by_cap=all(r["all_completed"] for r in trip_audits),
                   censored_runs=[dict(state=r["state"], seed=r["seed"], completed_at_cap=r["completed_at_cap"])
                                  for r in trip_audits if not r["all_completed"]],
                   drain_by_state={state: mean_ci([r["drain_boundary_s"] for r in trip_audits if r["state"]==state])
                                   for state in protocol["states"] if all(r["drain_boundary_s"] is not None for r in trip_audits if r["state"]==state)},
                   state_horizons=state_horizon, comparisons=comparisons)
    (OUT / "analysis_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    analyze()
