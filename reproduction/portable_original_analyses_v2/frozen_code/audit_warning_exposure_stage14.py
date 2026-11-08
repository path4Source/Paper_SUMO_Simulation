"""Reconcile original warning logs and expose event versus vehicle denominators."""
import csv
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from audit_metrics import warning_metrics, write_csv
from freeze_submission import sha256
from run_timepilot import ROOT

OUT = ROOT / "warning_exposure_v1"
LABELS = {
    "baseline": "Baseline",
    "heavyveh_high": "Heavy vehicles 16\\%",
    "heavyveh_very_high": "Heavy vehicles 24\\%",
    "weather_heavy_rain": "Heavy rain",
    "sigma_high": "High stochasticity",
    "reaction_slow": "Long desired headway",
    "signal_losttime_high": "Yellow extension",
    "demand_peak": "High demand",
    "reaction_fast": "Short desired headway",
}


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def exposure_stats(records):
    rates = []
    for r in records:
        events, unique, collisions, inserted = (
            r[k] for k in ["teleport_events", "teleported_unique_vehicles",
                          "collision_teleport_events", "end_inserted"])
        if inserted <= 0 or not (0 <= unique <= events and unique <= inserted and 0 <= collisions <= events):
            raise ValueError("Inconsistent event/vehicle exposure accounting")
        rates.append(100 * unique / inserted)
    return {
        "seeds": len(records),
        "teleport_events_mean": statistics.mean(r["teleport_events"] for r in records),
        "teleport_events_max": max(r["teleport_events"] for r in records),
        "unique_vehicles_mean": statistics.mean(r["teleported_unique_vehicles"] for r in records),
        "unique_vehicles_max": max(r["teleported_unique_vehicles"] for r in records),
        "unique_rate_mean_pct": statistics.mean(rates),
        "unique_rate_max_pct": max(rates),
        "collision_teleports_mean": statistics.mean(r["collision_teleport_events"] for r in records),
        "collision_teleports_max": max(r["collision_teleport_events"] for r in records),
        "teleport_exposed_runs": sum(r["teleport_events"] > 0 for r in records),
        "warning_qualified_runs": sum(r["teleport_events"] > 0 or r["tau_step_warning"]
                                      or r["tau_action_warning"] for r in records),
    }


def make_table(rows):
    by_name = {r["scenario"]: r for r in rows}
    if set(by_name) != set(LABELS):
        raise ValueError(f"Unexpected key-scenario set: {set(by_name)}")
    lines = [
        "% Generated from original logs, counting each affected vehicle once per run.",
        r"\begin{table}[!htbp]",
        r"\caption{Teleport events and distinct affected vehicles across the ten original seeds. Event and vehicle cells report mean/max; the percentage is the mean of the ten per-run ratios of distinct teleported vehicles to inserted vehicles. Collision-related teleport events are a subset of teleport events, not an additional vehicle population. The final column counts runs with at least one teleport. No positive warning rate is designated harmless, and absence of recorded warnings does not establish physical validity.}",
        r"\label{tab:teleport_audit}",
        r"\centering",
        r"\begin{tabularx}{\textwidth}{Zrrrrr}",
        r"\toprule",
        r"Scenario & \shortstack{Teleport\\events} & \shortstack{Distinct\\vehicles} & \shortstack{Mean rate\\(\% inserted)} & \shortstack{Collision-related\\teleports} & \shortstack{Exposed\\runs} \\",
        r"\midrule",
    ]
    for name, label in LABELS.items():
        r = by_name[name]
        pair = lambda mean, max_: f"{r[mean]:.1f}/{r[max_]:.0f}"
        cells = [
            label, pair("teleport_events_mean", "teleport_events_max"),
            pair("unique_vehicles_mean", "unique_vehicles_max"),
            f"{r['unique_rate_mean_pct']:.2f}",
            pair("collision_teleports_mean", "collision_teleports_max"),
            f"{r['teleport_exposed_runs']}/{r['seeds']}",
        ]
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabularx}", r"\end{table}", ""])
    return "\n".join(lines)


def reconcile_collision_subtypes(original, parsed, text):
    old = int(original["collision_teleport_events"])
    new = parsed["collision_teleport_events"]
    if old == new:
        return None
    subtypes = {
        kind: sum(bool(re.search(r"; " + kind + r" collision\b", line))
                  for line in text.splitlines() if "Teleporting vehicle '" in line)
        for kind in ["junction", "frontal", "side"]
    }
    old_causes = json.loads(original["teleport_causes_json"])
    if (new - old != sum(subtypes.values()) or
            old_causes.get("other", 0) - sum(subtypes.values()) !=
            json.loads(parsed["teleport_causes_json"]).get("other", 0)):
        raise RuntimeError("Unexplained collision cause discrepancy")
    return {
        "run": original["run"], "historical_collision_teleports": old,
        "resolved_collision_teleports": new, "reclassified_events": new - old,
        **{k + "_collision_events": v for k, v in subtypes.items()},
        "reason": "Historical cause category omitted prefixed collision descriptions; raw events and distinct vehicle counts unchanged.",
    }


def main():
    audit_path = ROOT / "audit/historical_run_audit.csv"
    audit = {r["run"]: r for r in read(audit_path)}
    paths = {name: ROOT / "frozen/data" / filename for name, filename in [
        ("original_OAT", "sumo_multiseed_results.csv"),
        ("key_ten_seed", "sumo_keyseed_results.csv"),
    ]}
    cache, records, source_hashes, corrections = {}, [], [], []
    for series, path in paths.items():
        for source in read(path):
            seed, scenario = int(source["seed"]), source["scenario"]
            name = scenario if seed == 42 else source["scenario_run"]
            original = audit[name]
            if name not in cache:
                log = Path(original["source_dir"]) / "sumo_stderr.log"
                parsed = warning_metrics(log)
                if not parsed["warning_log_present"]:
                    raise RuntimeError(f"Missing warning log is not a zero: {name}")
                for key in ["teleport_events", "teleported_unique_vehicles"]:
                    if parsed[key] != int(original[key]):
                        raise RuntimeError(f"Archived/log discrepancy: {name}/{key}")
                correction = reconcile_collision_subtypes(
                    original, parsed, log.read_text(encoding="utf-8", errors="strict"))
                if correction:
                    corrections.append(correction)
                if sum(json.loads(parsed["teleport_causes_json"]).values()) != parsed["teleport_events"]:
                    raise RuntimeError("Unreconciled cause counts")
                cache[name] = parsed
                source_hashes.append({"run": name, "warning_log_sha256": sha256(log)})
            record = {
                "series": series, "scenario": scenario, "seed": seed, "run": name,
                "end_inserted": int(original["end_inserted"]),
                "end_arrived": int(original["end_arrived"]),
                **cache[name],
            }
            record["unique_rate_pct_inserted"] = exposure_stats([record])["unique_rate_mean_pct"]
            if record["end_arrived"] != int(float(source["arrived_vehicles"])):
                raise RuntimeError("Run scope does not match original results")
            records.append(record)
    counts = {series: sum(r["series"] == series for r in records) for series in paths}
    if counts != {"original_OAT": 81, "key_ten_seed": 90} or len(cache) != 144:
        raise RuntimeError("Unexpected original/reused run accounting")
    groups = defaultdict(list)
    for record in records:
        groups[(record["series"], record["scenario"])].append(record)
    summaries = []
    for (series, scenario), group in sorted(groups.items()):
        expected_n = 3 if series == "original_OAT" else 10
        if len(group) != expected_n or len({r["seed"] for r in group}) != expected_n:
            raise RuntimeError("Duplicate/missing seed")
        summaries.append({"series": series, "scenario": scenario, **exposure_stats(group)})
    OUT.mkdir(exist_ok=True)
    write_csv(OUT / "run_exposure.csv", records)
    write_csv(OUT / "scenario_exposure.csv", summaries)
    if corrections:
        write_csv(OUT / "historical_cause_corrections.csv", corrections)
    table = ROOT / "manuscript_working/revision_warning_exposure_stage14.tex"
    table.write_text(make_table([r for r in summaries if r["series"] == "key_ten_seed"]), encoding="utf-8")
    manifest = {
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "new_sumo_runs": 0, "series_records": counts, "unique_original_runs": len(cache),
        "mean_rate_definition": "mean over seeds of 100 * unique teleported vehicle IDs / inserted vehicles in that run; not ratio of mean counts",
        "identity_scope": "Deduplicate IDs within each run, never across independent seeds; repeated teleport events retained.",
        "warning_rule": "Any relevant warning in either matched arm qualifies interpretation; rates are reported, not used as a fitted acceptance cutoff.",
        "caveats": "Original junction checks were disabled; no warning does not guarantee validity. Collision-related teleport events are not all possible collision events.",
        "input_hashes": {str(p.relative_to(ROOT)): sha256(p) for p in [audit_path, *paths.values()]},
        "sources": source_hashes,
        "historical_cause_classification_corrections": corrections,
        "reclassified_events_total": sum(r["reclassified_events"] for r in corrections),
        "frozen_historical_audit_modified": False,
        "script_sha256": sha256(Path(__file__)),
        "generated_table_sha256": sha256(table),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([r for r in summaries if r["series"] == "key_ten_seed"], indent=2))


if __name__ == "__main__":
    main()
