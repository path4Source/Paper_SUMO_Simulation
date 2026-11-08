"""Locked-rule evaluation first; construction-key comparison is a separate join."""
import csv
import json
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone

from audit_metrics import write_csv
from audit_core_warnings import parse_teleports
from diagnostic_rules_v1 import VARIANTS, classify, response_features
from extract_hidden_measurements_v1 import measurements
from freeze_submission import sha256
from run_timepilot import ROOT

OUT = ROOT / "hidden_challenge_v1"


def stable_json(path, data):
    text = json.dumps(data, indent=2, sort_keys=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"Existing frozen analysis differs: {path}")
    else:
        path.write_text(text, encoding="utf-8")


def main():
    protocol = json.loads((OUT / "protocol.json").read_text(encoding="utf-8"))
    for name, digest in protocol["code_hashes"].items():
        if sha256(ROOT / "scripts" / name) != digest:
            raise RuntimeError("Classifier/runner/extractor changed after freeze")
    inventory = json.loads((OUT / "detector_inventory.json").read_text())
    grouped, integrity, audit_population = defaultdict(list), [], []
    markers = sorted((OUT / "runs").glob("*/complete.json"))
    if len(markers) != 85:
        raise RuntimeError(f"Expected all 85 completed runs, got {len(markers)}")
    for index, marker in enumerate(markers, 1):
        directory = marker.parent
        record = json.loads(marker.read_text())
        if record["protocol_sha256"] != sha256(OUT / "protocol.json"):
            raise RuntimeError("Protocol mismatch")
        for name, digest in record["files_sha256"].items():
            if sha256(directory / name) != digest:
                raise RuntimeError(f"Output hash mismatch: {directory / name}")
        row = measurements(directory, inventory)
        front_keys = set()
        duplicate_fronts = 0
        for _, node in ET.iterparse(directory / "stopline_events.xml", events=("end",)):
            if node.tag == "instantOut":
                a = node.attrib
                if a["state"] == "enter":
                    event_key = (a["id"], a["vehID"], a["time"])
                    duplicate_fronts += event_key in front_keys
                    front_keys.add(event_key)
                node.clear()
        if duplicate_fronts:
            raise RuntimeError("Duplicated front-entry records require a documented extraction correction; do not silently change frozen measurements")
        case = directory.name.split("_seed")[0]
        grouped[case].append(row)
        if row["planned"] != row["inserted"] + row["waiting"] or row["inserted"] != row["arrived"] + row["running"]:
            raise RuntimeError("Population accounting mismatch")
        integrity.append({"case_id": case, "seed": row["seed"], "hashes_verified": True,
                          "population_accounted": True, "duplicate_fronts": duplicate_fronts,
                          "wall_s": record["wall_s"]})
        audit_population.append({"case_id": case, **{k: v for k, v in row.items() if k != "local"}})
        print(f"Verified and extracted {index}/85", flush=True)
    baseline = {r["seed"]: r for r in grouped.pop("B00")}
    baseline_events = []
    for seed in baseline:
        baseline_events += [{"seed": seed, **r} for r in parse_teleports(OUT / "runs" / f"B00_seed{seed}" / "sumo_stderr.log")]
    if baseline_events:
        write_csv(OUT / "baseline_warning_events.csv", baseline_events)
    stable_json(OUT / "observable_baselines.json", baseline)
    stable_json(OUT / "observable_cases.json", grouped)
    predictions, feature_table, sensitivities = {}, [], []
    for case, rows in sorted(grouped.items()):
        f = response_features(rows, baseline)
        predictions[case] = {"features": f,
                             "predictions": {variant: classify(f, variant) for variant in VARIANTS}}
        feature_table.append({"case_id": case,
                              **{f"{name}_{stat}": f[name][stat] for name in
                                 ("q", "d", "burden", "demand", "completion", "entry_backlog", "burden_per_planned")
                                 for stat in ("mean", "lo", "hi")},
                              "teleports_total": f["teleports"], "collisions_total": f["collisions"],
                              "config_warning_seeds": f["config_warning_seeds"],
                              "baseline_warning_seeds": f["baseline_warning_seeds"]})
        for scale in (0.5, 1.0, 2.0):
            result = classify(f, "D_full", scale)
            sensitivities.append({"case_id": case, "threshold_scale": scale,
                                  "status": result["status"], "retained_improvement": result["retained_improvement"],
                                  "labels": ";".join(result["labels"])})
    stable_json(OUT / "locked_predictions.json", predictions)
    manifest_path = OUT / "prediction_freeze.json"
    manifest = {"protocol_sha256": sha256(OUT / "protocol.json"),
                "predictions_sha256": sha256(OUT / "locked_predictions.json"),
                "rules_sha256": sha256(ROOT / "scripts/diagnostic_rules_v1.py"),
                "scope": "Predictions saved before analysis joins construction key; author knew the construction. No independent human blinding."}
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps({**manifest, "predictions_saved_utc": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    else:
        previous = json.loads(manifest_path.read_text())
        previous.pop("predictions_saved_utc")
        assert previous == manifest

    # Join predictions to construction here; no construction fields enter classify().
    key = {r["case_id"]: r for r in json.loads((OUT / "construction_key/key.json").read_text())}
    comparison, transitions = [], []
    for case, result in predictions.items():
        construction = key[case]
        f, predictions_here = result["features"], result["predictions"]
        full = predictions_here["D_full"]
        demand_changed = construction.get("demand", 1) != 1
        incompatible = construction.get("tau", 1) < 0.5
        supply_modified = any(k in construction for k in ("truck", "sigma", "speed", "accel", "decel")) or construction.get("tau", 1) > 1
        comparison.append({"case_id": case, "construction": construction["name"],
                           "demand_source_present": demand_changed, "incompatible_headway_source": incompatible,
                           "supply_parameters_modified": supply_modified,
                           "demand_source_detected": "demand_change" in full["labels"],
                           "timing_warning_detected": f["config_warning_seeds"] > 0,
                           "actual_scenario_warning": bool(f["teleports"] or f["collisions"] or f["config_warning_seeds"]),
                           "raw_QD_status": predictions_here["A_QD"]["status"], "full_status": full["status"],
                           "full_labels": ";".join(full["labels"]),
                           "local_loss_signals": ";".join(full["local_loss_signals"]),
                           "local_gain_signals": ";".join(full["local_gain_signals"]),
                           "q_mean_pct": f["q"]["mean"], "d_mean_pct": f["d"]["mean"],
                           "burden_mean_pct": f["burden"]["mean"],
                           "scenario_teleports": f["teleports"], "baseline_warning_seeds": f["baseline_warning_seeds"]})
        for variant, predicted in predictions_here.items():
            transitions.append({"case_id": case, "variant": variant, "status": predicted["status"],
                                "retained_improvement": predicted["retained_improvement"],
                                "demand_flag": "demand_change" in predicted["labels"],
                                "warning_flag": "warning_audit_required" in predicted["labels"],
                                "local_loss": bool(predicted["local_loss_signals"]),
                                "local_gain": bool(predicted["local_gain_signals"]),
                                "labels": ";".join(predicted["labels"])})
        if construction["name"] == "sham":
            for row in grouped[case]:
                if row != baseline[row["seed"]]:
                    raise RuntimeError("Sham does not exactly reproduce matched baseline")
    ablations = []
    for variant in VARIANTS:
        group = [r for r in transitions if r["variant"] == variant]
        ablations.append({"variant": variant, "conditions": len(group),
                          **{field: sum(bool(r[field]) for r in group) for field in
                             ("retained_improvement", "demand_flag", "warning_flag", "local_loss", "local_gain")},
                          "status_counts_json": json.dumps(dict(Counter(r["status"] for r in group)), sort_keys=True)})
    source_checks = []
    for truth, pred, label in [("demand_source_present", "demand_source_detected", "demand_source"),
                               ("incompatible_headway_source", "timing_warning_detected", "timing_compatibility")]:
        counts = Counter((bool(r[truth]), bool(r[pred])) for r in comparison)
        source_checks.append({"check": label, "TP": counts[True, True], "FN": counts[True, False],
                              "FP": counts[False, True], "TN": counts[False, False],
                              "scope": "Exposed input/log consistency only; not hidden causal classification accuracy."})
    for name, rows in [("integrity_checks", integrity), ("population_audit", audit_population),
                       ("paired_response_summary", feature_table), ("threshold_sensitivity", sensitivities),
                       ("construction_vs_observations", comparison), ("ablation_by_case", transitions),
                       ("ablation_summary", ablations), ("exposed_source_checks", source_checks)]:
        write_csv(OUT / (name + ".csv"), rows)
    summary = {"complete_runs": 85, "conditions": 16, "paired_seeds": 5,
               "construction_scope": "Four reused-construction controls (sham, demand 0.85/1.15, moderate weather); twelve parameter values/combinations outside original OAT. New responses, not sixteen novel constructions.",
               "primary_protocol_frozen_utc": protocol["frozen_utc"],
               "protocol_sha256": sha256(OUT / "protocol.json"),
               "baseline_warning_seeds": [seed for seed, r in baseline.items()
                                           if r["teleports"] or r["collisions"] or r["config_warning"]],
               "baseline_teleports_total": sum(r["teleports"] for r in baseline.values()),
               "sham_exact_match": True, "construction_source_checks": source_checks,
               "ablation_summary": ablations,
               "interpretation": "Internal pilot tests evidence-qualified triage, not independently blinded causal accuracy. Five seeds are exploratory; no stop-line saturation-flow or external validity claim.",
               "threshold_status_changes_half": sum(r["status"] != predictions[r["case_id"]]["predictions"]["D_full"]["status"] for r in sensitivities if r["threshold_scale"] == 0.5),
               "threshold_status_changes_double": sum(r["status"] != predictions[r["case_id"]]["predictions"]["D_full"]["status"] for r in sensitivities if r["threshold_scale"] == 2.0)}
    (OUT / "analysis_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
