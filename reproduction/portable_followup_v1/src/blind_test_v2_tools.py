"""Anonymous observation contract and lock/score tools for a future blinded test.

No scenarios or results are generated here. Human role confirmation, the primary
configuration decision, and protocol approval are prerequisites for prediction.
"""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import t

import diagnostic_rules_v2_draft as rules

ROOT = Path(__file__).resolve().parent
STATES = {"service_deterioration", "network_improvement", "demand_conditioned",
          "output_burden_tradeoff", "burden_increase_only", "burden_decrease_only",
          "insufficient_evidence"}
TAGS = {"demand", "warning", "local_recovery", "local_deterioration", "redistribution"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(value, out, indent=2, ensure_ascii=False, allow_nan=False)
        out.write("\n")


def utc():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name, integer=False):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0, f"Invalid {name}")
    if integer:
        require(int(value) == value, f"Non-integer {name}")
    return value


def interval(values):
    if any(v is None for v in values):
        return None
    values = np.asarray(values, dtype=float)
    require(len(values) >= 2 and np.isfinite(values).all(), "Invalid paired sample")
    mean = float(values.mean())
    half = float(t.ppf(.975, len(values)-1) * values.std(ddof=1) / math.sqrt(len(values)))
    return {"mean": mean, "lo": mean-half, "hi": mean+half, "n": len(values)}


def percent(a, b):
    return None if a is None or b is None or b <= 0 else 100*(a-b)/b


def validate_run(row, groups):
    allowed = {"seed", "begin_s", "end_s", "planned", "inserted", "arrived",
               "running", "waiting", "entry_vh", "network_vh", "total_vh",
               "completed_delay_s", "teleports", "collisions", "timing_warning", "local"}
    require(set(row) == allowed, "Run fields must match the anonymous observation contract")
    for name in ("seed", "planned", "inserted", "arrived", "running", "waiting",
                 "teleports", "collisions"):
        number(row[name], name, integer=True)
    for name in ("begin_s", "end_s", "entry_vh", "network_vh", "total_vh"):
        number(row[name], name)
    require(row["begin_s"] == 0 and row["end_s"] > 0,
            "Contract covers a full fixed-cohort window starting at zero")
    require(row["planned"] > 0, "Planned cohort must be positive")
    require(row["planned"] == row["inserted"] + row["waiting"], "Planned identity failed")
    require(row["inserted"] == row["arrived"] + row["running"], "Inserted identity failed")
    require(math.isclose(row["total_vh"], row["entry_vh"] + row["network_vh"],
                         rel_tol=1e-8, abs_tol=1e-6), "Burden identity failed")
    require(type(row["timing_warning"]) is bool, "Timing warning must be explicit")
    if row["completed_delay_s"] is not None:
        number(row["completed_delay_s"], "completed_delay_s")
    require(set(row["local"]).issubset(groups), "Undeclared monitored group")
    for item in row["local"].values():
        require(set(item) == {"front_crossings", "queue_m"}, "Invalid local fields")
        for key, value in item.items():
            if value is not None:
                number(value, key, integer=key == "front_crossings")


def features_for_case(case, seeds, monitored_groups, recovery_targets):
    require(set(case) == {"case_id", "same_demand_structure", "demand_structure_evidence",
                          "reference", "treatment"}, "Case contains missing or hidden fields")
    require(type(case["same_demand_structure"]) is bool or case["same_demand_structure"] is None,
            "Demand structure must be true, false or null")
    require(case["same_demand_structure"] is None or bool(case["demand_structure_evidence"]),
            "Demand-structure comparability requires an evidence identifier")
    arms = []
    for name in ("reference", "treatment"):
        rows = case[name]
        for row in rows:
            validate_run(row, set(monitored_groups))
        arm = {r["seed"]: r for r in rows}
        require(len(arm) == len(rows) and set(arm) == set(seeds), "Seed coverage mismatch")
        arms.append(arm)
    ref, trt = arms
    values = {k: [] for k in ("q", "d", "burden", "burden_per_planned", "demand",
                              "completion", "entry_backlog", "network_residual")}
    local = {g: {"front_crossings": [], "queue_m": []} for g in monitored_groups}
    same_window = True
    for seed in seeds:
        a, b = trt[seed], ref[seed]
        same_window &= (a["begin_s"], a["end_s"]) == (b["begin_s"], b["end_s"])
        values["q"].append(percent(a["arrived"]*3600/a["end_s"], b["arrived"]*3600/b["end_s"]))
        values["d"].append(percent(a["completed_delay_s"], b["completed_delay_s"]))
        values["burden"].append(percent(a["total_vh"], b["total_vh"]))
        values["burden_per_planned"].append(percent(a["total_vh"]/a["planned"],
                                                     b["total_vh"]/b["planned"]))
        values["demand"].append(percent(a["planned"], b["planned"]))
        for target, source in (("completion", "arrived"), ("entry_backlog", "waiting"),
                               ("network_residual", "running")):
            values[target].append(100*(a[source]/a["planned"] - b[source]/b["planned"]))
        for group in monitored_groups:
            for metric in local[group]:
                local[group][metric].append(percent(a["local"].get(group, {}).get(metric),
                                                     b["local"].get(group, {}).get(metric)))
    features = {k: interval(v) for k, v in values.items()}
    features.update(population_identity_valid=True,
                    teleports=sum(r["teleports"] for r in trt.values()),
                    collisions=sum(r["collisions"] for r in trt.values()),
                    config_warning_seeds=sum(r["timing_warning"] for r in trt.values()),
                    baseline_warning_seeds=sum(bool(r["teleports"] or r["collisions"] or
                                                    r["timing_warning"]) for r in ref.values()),
                    local={g: {k: interval(v) for k, v in m.items()} for g, m in local.items()})
    return features, rules.Scope(tuple(monitored_groups), tuple(recovery_targets),
                                 same_window, case["same_demand_structure"])


def code_hashes():
    return {name: file_digest(ROOT/name) for name in
            ("blind_test_v2_tools.py", "diagnostic_rules_v2_draft.py")}


def validate_protocol(p):
    require(p.get("schema") == "independent-test-v2", "Wrong protocol schema")
    for name in ("primary_configuration_approved", "measurement_contract_approved",
                 "rules_approved", "reference_protocol_approved", "sample_size_approved"):
        require(p.get(name) is True, f"Not ready: {name}")
    roles = p["roles"]
    require(roles["preparer"] and roles["predictor"] and roles["preparer"] != roles["predictor"],
            "Separate preparer and predictor required")
    for name in ("preparer_has_not_designed_rules", "preparer_accepted_custody",
                 "predictor_has_no_key_access"):
        require(roles.get(name) is True, f"Human confirmation pending: {name}")
    require(bool(roles.get("confirmation_record")), "Record actual role confirmation")
    seeds = p["seeds"]
    require(len(seeds) >= 2 and len(set(seeds)) == len(seeds), "Specify unique seed replications")
    for seed in seeds:
        number(seed, "seed", True)
    cases = p["case_ids"]
    require(bool(cases) and len(set(cases)) == len(cases), "Specify anonymous cases")
    require(p["variants"] == list(rules.VARIANTS), "Comparator set must include the abstention control")
    require(p["thresholds"] == rules.THRESHOLDS, "Threshold mismatch")
    require(len(p.get("sealed_construction_key_sha256", "")) == 64, "Missing sealed key commitment")
    config = p["configuration"]
    for name in ("sumo_version", "network_sha256", "step_s", "action_s", "sigma_step_s",
                 "integration", "junction_collision_checks", "collision_action",
                 "time_to_teleport_s", "window_s", "decision_record"):
        require(name in config and config[name] is not None, f"Missing fixed configuration: {name}")
    for name in ("step_s", "action_s", "sigma_step_s", "window_s"):
        require(number(config[name], name) > 0, f"Nonpositive {name}")
    rules.Scope(tuple(p["monitored_groups"]), tuple(p["recovery_targets"]), True, True)
    require(bool(p.get("reference_evidence_plan")), "Describe separate reference adjudication")


def freeze_protocol(p):
    validate_protocol(p)
    body = {"protocol": p, "code_sha256": code_hashes(), "created_utc": utc(),
            "scope": "A local commitment; hashes do not attest human independence."}
    return {**body, "freeze_sha256": digest(body)}


def validate_freeze(f):
    require(f["freeze_sha256"] == digest({k: v for k, v in f.items() if k != "freeze_sha256"}),
            "Freeze changed")
    validate_protocol(f["protocol"])
    require(f["code_sha256"] == code_hashes(), "Code changed after freeze")


def predict(observations, frozen):
    validate_freeze(frozen)
    p = frozen["protocol"]
    require(set(observations) == {"schema", "cases", "configuration_sha256"}, "Unexpected public fields")
    require(observations["schema"] == "anonymous-observations-v2", "Wrong observations schema")
    require(observations["configuration_sha256"] == digest(p["configuration"]), "Configuration mismatch")
    cases = observations["cases"]
    require(len(cases) == len(p["case_ids"]) and {c["case_id"] for c in cases} == set(p["case_ids"]),
            "Incomplete or duplicate cases")
    rows = []
    for case in sorted(cases, key=lambda c: c["case_id"]):
        features, scope = features_for_case(case, p["seeds"], p["monitored_groups"], p["recovery_targets"])
        for run in case["reference"] + case["treatment"]:
            require(run["end_s"] == p["configuration"]["window_s"], "Window differs from freeze")
        rows.append({"case_id": case["case_id"], "features": features,
                     "predictions": {v: rules.classify(features, scope, v) for v in p["variants"]}})
    unique_refs = {digest(r) for c in cases for r in c["reference"]}
    body = {"schema": "locked-predictions-v2", "created_utc": utc(), "freeze": frozen,
            "observations_sha256": digest(observations), "scenario_count": len(cases),
            "treatment_run_count": sum(len(c["treatment"]) for c in cases),
            "distinct_reference_records": len(unique_refs), "rows": rows}
    return {**body, "prediction_sha256": digest(body)}


def state_of(prediction):
    return {"QD_gain": "network_improvement", "QD_loss": "service_deterioration",
            "not_evaluated": "insufficient_evidence"}.get(prediction["operating_state"],
                                                            prediction["operating_state"])


def tags_of(prediction):
    flags = set(prediction["flags"])
    tags = set()
    if state_of(prediction) == "demand_conditioned" and flags & {"demand_volume_changed", "demand_structure_changed"}:
        tags.add("demand")
    if "warning_audit_required" in flags or prediction["adoption"] == "qualified_warning":
        tags.add("warning")
    for flag, tag in (("local_recovery_evidence", "local_recovery"),
                      ("local_deterioration_evidence", "local_deterioration"),
                      ("spatial_redistribution", "redistribution")):
        if flag in flags:
            tags.add(tag)
    return tags


def fraction(n, d):
    if not d:
        return {"numerator": n, "denominator": d, "estimate": None, "wilson95": None}
    z = 1.959963984540054
    phat = n/d
    center = (phat + z*z/(2*d))/(1+z*z/d)
    half = z*math.sqrt(phat*(1-phat)/d + z*z/(4*d*d))/(1+z*z/d)
    return {"numerator": n, "denominator": d, "estimate": phat,
            "wilson95": [max(0, center-half), min(1, center+half)]}


def evaluate(locked, references, observations):
    require(locked["prediction_sha256"] == digest({k: v for k, v in locked.items() if k != "prediction_sha256"}),
            "Predictions changed after lock")
    validate_freeze(locked["freeze"])
    require(locked["observations_sha256"] == digest(observations), "Observations changed after prediction")
    # Recompute with frozen code instead of trusting editable prediction fields.
    require(predict(observations, locked["freeze"])["rows"] == locked["rows"], "Prediction replay mismatch")
    p = locked["freeze"]["protocol"]
    require(references["construction_key_sha256"] == p["sealed_construction_key_sha256"], "Key mismatch")
    require(references["adjudicator"] == p["roles"]["preparer"], "Reference custodian mismatch")
    refs = {r["case_id"]: r for r in references["cases"]}
    require(len(refs) == len(references["cases"]) and set(refs) == set(p["case_ids"]), "Reference coverage mismatch")
    for ref in refs.values():
        require(ref["kind"] in ("single", "mixed", "sham", "uncertain"), "Unknown case kind")
        require(ref["state"] in STATES or ref["state"] is None, "Unknown reference state")
        require(set(ref["tags"]).issubset(TAGS), "Unknown reference tag")
        require(type(ref["valid_gain"]) is bool or ref["valid_gain"] is None, "Invalid gain reference")
        require(bool(ref["evidence_ids"]) and bool(ref["rationale"]), "Reference needs recorded evidence")
        require(ref["reference_not_derived_from_rule_output"] is True, "Circular reference")
    result = {"scenario_count": len(refs), "treatment_run_count": locked["treatment_run_count"],
              "prediction_sha256": locked["prediction_sha256"], "reference_sha256": digest(references),
              "unit": "scenario, not seed, vehicle or cycle", "variants": {}}
    for variant in p["variants"]:
        matrix, audit_rows = {}, []
        for row in locked["rows"]:
            ref, pred = refs[row["case_id"]], row["predictions"][variant]
            state, tags = state_of(pred), tags_of(pred)
            determined = state != "insufficient_evidence" and not pred["conflicts"]
            if state == "demand_conditioned" and "demand" not in tags:
                determined = False
            predicted = state if determined else "abstain"
            if ref["kind"] == "single" and ref["state"] is not None:
                bucket = matrix.setdefault(ref["state"], {})
                bucket[predicted] = bucket.get(predicted, 0) + 1
            audit_rows.append({"case_id": row["case_id"], "kind": ref["kind"], "reference_state": ref["state"],
                               "predicted_state": predicted, "raw_state": state, "determined": determined,
                               "adoption": pred["adoption"],
                               "reference_tags": sorted(ref["tags"]), "predicted_tags": sorted(tags),
                               "reference_valid_gain": ref["valid_gain"], "retained_gain": pred["retained_improvement"],
                               "correct_state": None if ref["state"] is None else predicted == ref["state"],
                               "tag_set_exact": tags == set(ref["tags"])})
        known = [r for r in audit_rows if r["reference_state"] is not None and r["kind"] == "single"]
        positive = [r for r in audit_rows if r["reference_valid_gain"] is True]
        negative = [r for r in audit_rows if r["reference_valid_gain"] is False]
        mixed = [r for r in audit_rows if r["kind"] == "mixed"]
        metrics = {"single_cause_confusion": matrix, "rows": audit_rows,
                   "coverage": fraction(sum(r["determined"] for r in audit_rows), len(audit_rows)),
                   "abstention": fraction(sum(not r["determined"] for r in audit_rows), len(audit_rows)),
                   "unqualified_adoption_coverage": fraction(sum(r["adoption"] == "supported" for r in audit_rows), len(audit_rows)),
                   "single_case_correct_including_abstentions": fraction(sum(r["correct_state"] for r in known), len(known)),
                   "valid_gain_recall": fraction(sum(r["retained_gain"] for r in positive), len(positive)),
                   "missed_valid_gains": fraction(sum(not r["retained_gain"] for r in positive), len(positive)),
                   "false_retained_gains": fraction(sum(r["retained_gain"] for r in negative), len(negative)),
                   "unknown_gain_references": sum(r["reference_valid_gain"] is None for r in audit_rows),
                   "mixed_exact_evidence_tags": fraction(sum(r["tag_set_exact"] for r in mixed), len(mixed)),
                   "per_class": {}}
        for state in sorted({r["reference_state"] for r in known}):
            pos = [r for r in known if r["reference_state"] == state]
            neg = [r for r in known if r["reference_state"] != state]
            metrics["per_class"][state] = {
                "recall": fraction(sum(r["predicted_state"] == state for r in pos), len(pos)),
                "false_positive_rate": fraction(sum(r["predicted_state"] == state for r in neg), len(neg))}
        result["variants"][variant] = metrics
    result["scope"] = ("Evidence-state and gain-adoption agreement with separately adjudicated references. "
                       "Observable warning/demand tags are audit checks, not latent-cause accuracy. "
                       "Wilson intervals are descriptive for the selected scenarios; shared baselines and "
                       "designed case families limit a binomial population interpretation.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("protocol")
    pred = sub.add_parser("predict")
    pred.add_argument("observations")
    pred.add_argument("freeze")
    score = sub.add_parser("evaluate")
    score.add_argument("predictions")
    score.add_argument("references")
    score.add_argument("observations")
    for item in (freeze, pred, score):
        item.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_protocol(read(args.protocol))
    elif args.command == "predict":
        result = predict(read(args.observations), read(args.freeze))
    else:
        result = evaluate(read(args.predictions), read(args.references), read(args.observations))
    write_new(args.output, result)
    print(f"Saved {args.output}; existing files are never overwritten.")


if __name__ == "__main__":
    main()
