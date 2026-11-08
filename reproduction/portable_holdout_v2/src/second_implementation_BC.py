"""A separate implementation for author-internal software verification.

Uses standard-library statistics, explicit decision tables and archived paired
measurements. It does not import the original feature extractor or classifier.
This is neither a clean-room implementation nor independent human adjudication.
"""
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ("target", "donor", "other")
VARIANTS = ("full", "without_population", "without_warning", "without_local",
            "conventional_QD", "QD_timing_warning", "always_abstain")
METRICS = ("q", "d", "burden", "burden_per_planned", "demand", "completion", "entry_backlog", "network_residual")
T95_DF4 = 2.7764451051977987


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def interval(values):
    if any(value is None for value in values):
        return None
    if len(values) != 5 or not all(math.isfinite(v) for v in values):
        raise ValueError("This audit is restricted to the frozen five-seed design")
    center = mean(values)
    half = T95_DF4 * stdev(values) / math.sqrt(5)
    return {"mean": center, "lo": center - half, "hi": center + half, "n": 5}


def pct(comparison, reference):
    if comparison is None or reference is None or reference <= 0:
        return None
    return 100 * (comparison - reference) / reference


def validate_measurement(row):
    for key in ("planned", "inserted", "arrived", "running", "waiting", "teleports", "collisions"):
        value = row[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or int(value) != value:
            raise ValueError("Invalid vehicle/event count: " + key)
    if row["planned"] <= 0 or row["planned"] != row["inserted"] + row["waiting"]:
        raise ValueError("Planned-population identity failed")
    if row["inserted"] != row["arrived"] + row["running"]:
        raise ValueError("Inserted-population identity failed")
    for key in ("entry_vh", "network_vh", "total_vh"):
        if not math.isfinite(row[key]) or row[key] < 0:
            raise ValueError("Invalid burden")
    if not math.isclose(row["total_vh"], row["entry_vh"] + row["network_vh"], rel_tol=1e-8, abs_tol=1e-6):
        raise ValueError("Burden identity failed")
    if row["begin_s"] != 0 or row["end_s"] <= row["begin_s"]:
        raise ValueError("Invalid observation window")
    if type(row["timing_warning"]) is not bool:
        raise ValueError("Explicit timing-warning status required")


def extract_features(case, seeds):
    arms = {}
    for arm in ("reference", "treatment"):
        for row in case[arm]:
            validate_measurement(row)
        byseed = {r["seed"]: r for r in case[arm]}
        if len(byseed) != len(case[arm]) or set(byseed) != set(seeds):
            raise ValueError("Duplicate or missing paired seed")
        arms[arm] = byseed
    series = {key: [] for key in METRICS}
    local = {g: {"front_crossings": [], "queue_m": []} for g in GROUPS}
    same_window = True
    for seed in sorted(seeds):
        r, c = arms["reference"][seed], arms["treatment"][seed]
        same_window &= (r["begin_s"], r["end_s"]) == (c["begin_s"], c["end_s"])
        duration_r, duration_c = r["end_s"] - r["begin_s"], c["end_s"] - c["begin_s"]
        series["q"].append(pct(c["arrived"] / duration_c * 3600, r["arrived"] / duration_r * 3600))
        for key, field in (("d", "completed_delay_s"), ("burden", "total_vh"), ("demand", "planned")):
            series[key].append(pct(c[field], r[field]))
        series["burden_per_planned"].append(pct(c["total_vh"] / c["planned"], r["total_vh"] / r["planned"]))
        for key, field in (("completion", "arrived"), ("entry_backlog", "waiting"), ("network_residual", "running")):
            series[key].append(100 * (c[field] / c["planned"] - r[field] / r["planned"]))
        for g in GROUPS:
            for metric in local[g]:
                local[g][metric].append(pct(c["local"].get(g, {}).get(metric), r["local"].get(g, {}).get(metric)))
    f = {key: interval(values) for key, values in series.items()}
    f.update(population_identity_valid=True,
             teleports=sum(r["teleports"] for r in arms["treatment"].values()),
             collisions=sum(r["collisions"] for r in arms["treatment"].values()),
             config_warning_seeds=sum(r["timing_warning"] for r in arms["treatment"].values()),
             baseline_warning_seeds=sum(bool(r["teleports"] or r["collisions"] or r["timing_warning"]) for r in arms["reference"].values()),
             local={g: {m: interval(v) for m, v in values.items()} for g, values in local.items()})
    scope = {"same_window": same_window, "same_demand_structure": case["same_demand_structure"],
             "groups": GROUPS, "targets": ("target",)}
    return f, scope


def direction(v, threshold):
    if v is None:
        return 0
    if v["lo"] > threshold:
        return 1
    if v["hi"] < -threshold:
        return -1
    return 0


def classify(f, scope, variant="full"):
    if variant not in VARIANTS:
        raise ValueError("Unknown comparator")
    warned = bool(f["teleports"] or f["collisions"] or f["config_warning_seeds"] or f["baseline_warning_seeds"])
    warning_used = warned and variant not in ("conventional_QD", "without_warning", "always_abstain")
    q, d = direction(f["q"], 2), direction(f["d"], 5)
    qd_gain, qd_loss = (q == 1 and d == -1), (q == -1 and d == 1)
    out = {"variant": variant, "operating_state": "insufficient_evidence", "adoption": "unresolved",
           "retained_improvement": False, "warning_observed": warned, "raw_QD_loss": qd_loss, "raw_QD_gain": qd_gain,
           "flags": [], "conflicts": [], "local_gain_groups": [], "local_loss_groups": []}
    if variant == "always_abstain":
        out["operating_state"] = "not_evaluated"
        return out
    if not scope["same_window"] or not f["population_identity_valid"]:
        out["flags"] = ["measurement_contract_failed"]
        return out
    if variant in ("conventional_QD", "QD_timing_warning"):
        out["operating_state"] = "QD_gain" if qd_gain else "QD_loss" if qd_loss else "insufficient_evidence"
        out["adoption"] = "qualified_warning" if warning_used else "supported" if qd_gain or qd_loss else "unresolved"
        out["retained_improvement"] = qd_gain and not warning_used
        return out

    flags, conflicts = set(), set()
    stable = f["demand"] is not None and f["demand"]["lo"] >= -1 and f["demand"]["hi"] <= 1
    changed = direction(f["demand"], 1) != 0
    comparable = stable and scope["same_demand_structure"] is True
    if changed:
        flags.add("demand_volume_changed")
    if scope["same_demand_structure"] is False:
        flags.add("demand_structure_changed")
    if scope["same_demand_structure"] is None:
        flags.add("demand_structure_not_established")
    if not stable and not changed:
        flags.add("demand_volume_uncertain")
    b = direction(f["burden"] if comparable else f["burden_per_planned"], 5)
    backlog_or_residual_up = any(direction(f[k], 2) == 1 for k in ("entry_backlog", "network_residual"))
    population_cost_clear = all(f[k] is not None and f[k]["hi"] <= 2 for k in ("entry_backlog", "network_residual"))
    if variant == "without_population":
        state = "network_improvement" if qd_gain else "service_deterioration" if qd_loss else "insufficient_evidence"
        flags.add("population_module_omitted")
    else:
        # First matching row encodes the specified precedence independently of the original function.
        branches = [
            (not comparable, "demand_conditioned"),
            (comparable and q != 0 and q == b, "output_burden_tradeoff"),
            (b == 1 and (q == -1 or backlog_or_residual_up), "service_deterioration"),
            (b == -1 and q == 1 and population_cost_clear, "network_improvement"),
            (b == 1, "burden_increase_only"),
            (b == -1, "burden_decrease_only"),
            (True, "insufficient_evidence"),
        ]
        state = next(label for condition, label in branches if condition)
        if not comparable and b:
            flags.add("per_planned_vehicle_burden_" + ("increased" if b == 1 else "decreased"))
        if state == "output_burden_tradeoff":
            conflicts.add("completion_output_and_full_population_burden")
        if b * d == -1:
            flags.add("completed_sample_differs_from_population")

    gains, losses, costs, measured = set(), set(), set(), set()
    if variant == "without_local":
        flags.add("local_module_omitted")
        target_gate = True
    else:
        for group in scope["groups"]:
            local = f["local"].get(group, {})
            if local.get("front_crossings") is None or local.get("queue_m") is None:
                continue
            measured.add(group)
            flow, queue = direction(local["front_crossings"], 2), direction(local["queue_m"], 5)
            if flow == 1 and queue == -1:
                gains.add(group)
            if flow == -1 and queue == 1:
                losses.add(group)
            if flow == -1 or queue == 1:
                costs.add(group)
        if gains:
            flags.add("local_recovery_evidence")
        if losses:
            flags.add("local_deterioration_evidence")
        if gains and costs:
            flags.add("spatial_redistribution")
        if state == "network_improvement" and costs:
            conflicts.add("network_improvement_with_local_cost")
        if state == "service_deterioration" and gains and not losses:
            conflicts.add("network_deterioration_with_only_local_recovery")
        if measured != set(scope["groups"]):
            flags.add("incomplete_local_coverage")
        target_gate = bool(scope["targets"]) and set(scope["targets"]).issubset(gains) and measured == set(scope["groups"]) and not costs
    support = state == "service_deterioration" or (state == "network_improvement" and target_gate)
    eligibility = "supported" if support else "unresolved"
    if conflicts:
        eligibility = "conflicting"
    if warning_used:
        flags.add("warning_audit_required")
        if eligibility != "conflicting":
            eligibility = "qualified_warning"
    out.update(operating_state=state, adoption=eligibility,
               retained_improvement=state == "network_improvement" and eligibility == "supported",
               flags=sorted(flags), conflicts=sorted(conflicts), local_gain_groups=sorted(gains), local_loss_groups=sorted(losses))
    return out


def normalized_prediction(pred):
    p = {k: v for k, v in pred.items() if k != "version"}
    for key in ("flags", "conflicts", "local_gain_groups", "local_loss_groups"):
        p[key] = sorted(p[key])
    return p


def feature_difference(a, b, path=""):
    if isinstance(a, dict):
        if set(a) != set(b):
            raise AssertionError("Feature keys differ: " + path)
        return max((feature_difference(a[k], b[k], path + "." + k) for k in a), default=0.)
    if a is None or isinstance(a, bool):
        if a != b:
            raise AssertionError("Non-numeric feature differs: " + path)
        return 0.
    error = abs(a - b)
    if not math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-9):
        raise AssertionError(f"Feature differs {path}: {a} / {b}")
    return error


def run_audit():
    base = ROOT / "author_holdout_v2"
    protocol = json.loads((base / "protocol.json").read_text(encoding="utf-8"))
    observations = json.loads((base / "analysis/observable_cases.json").read_text(encoding="utf-8"))
    locked = json.loads((base / "analysis/predictions_LOCKED.json").read_text(encoding="utf-8"))
    assert locked["protocol_sha256"] == file_hash(base / "protocol.json")
    assert locked["observations_sha256"] == canonical_hash(observations)
    assert locked["prediction_sha256"] == canonical_hash({k: v for k, v in locked.items() if k != "prediction_sha256"})
    for name, expected in protocol["code_hashes"].items():
        assert file_hash(ROOT / "scripts" / name) == expected, name
    assert protocol["holdout"]["thresholds"] == {"flow_pct": 2., "delay_pct": 5., "burden_pct": 5., "demand_pct": 1., "share_pp": 2., "local_queue_pct": 5.}
    original = {r["case_id"]: r for r in locked["rows"]}
    rows, max_error = [], 0.
    reference_signatures = {canonical_hash(case["reference"]) for case in observations["cases"]}
    assert len(reference_signatures) == 1
    for case in observations["cases"]:
        features, scope = extract_features(case, protocol["holdout"]["seeds"])
        max_error = max(max_error, feature_difference(features, original[case["case_id"]]["features"]))
        for variant in VARIANTS:
            calculated = classify(features, scope, variant)
            expected = normalized_prediction(original[case["case_id"]]["predictions"][variant])
            rows.append({"case_id": case["case_id"], "comparator": variant, "prediction": calculated,
                         "matches_frozen_semantics": calculated == expected})
    assert len(rows) == 84
    return {"audit_type": "Author-internal second-implementation software check", "new_simulations": 0,
            "cases": 12, "comparison_simulations": 60, "shared_reference_simulations": 5,
            "intervals_recomputed": 168, "maximum_absolute_feature_difference": max_error,
            "matched_predictions": sum(r["matches_frozen_semantics"] for r in rows), "total_predictions": len(rows),
            "comparison": "All semantic prediction fields; set-valued flags sorted, historical version text excluded",
            "prediction_lock_sha256": locked["prediction_sha256"], "alternative_implementation_sha256": file_hash(__file__),
            "independent_human_validation": False, "reference_judgments_generated": False,
            "scope": "Reimplementation and consistency, not classification accuracy or blind human assessment",
            "rows": rows}


if __name__ == "__main__":
    result = run_audit()
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    if result["matched_predictions"] != 84:
        raise SystemExit("Second-implementation disagreement; preserve results and investigate")
