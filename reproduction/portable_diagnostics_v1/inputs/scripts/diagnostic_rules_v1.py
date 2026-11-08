"""Outcome-independent triage rules for the first parameter-hidden challenge.

This module consumes observable measurements only, never construction labels.
The output is qualified evidence, not identification of a unique physical cause.
"""
import statistics

THRESHOLDS = {"flow_pct": 2.0, "delay_pct": 5.0, "burden_pct": 5.0,
              "demand_pct": 1.0, "share_pp": 2.0, "local_queue_pct": 5.0}
VARIANTS = {
    "A_QD": (False, False, False),
    "B_accounting": (True, False, False),
    "C_warning": (True, True, False),
    "D_full": (True, True, True),
    "D_without_accounting": (False, True, True),
    "D_without_warning": (True, False, True),
}


def interval(values):
    if len(values) != 5:
        raise ValueError("This frozen pilot requires exactly five paired seeds")
    mean = statistics.mean(values)
    half = 2.7764451051977987 * statistics.stdev(values) / len(values) ** 0.5
    return {"mean": mean, "lo": mean - half, "hi": mean + half, "n": len(values)}


def response_features(rows, references):
    """Reference pairing uses seed, but no scenario/parameter/source identifiers."""
    if len({r["seed"] for r in rows}) != 5:
        raise ValueError("Duplicate or missing seed")
    pairs = [(r, references[r["seed"]]) for r in sorted(rows, key=lambda x: x["seed"])]
    features = {}
    for name, field in [("q", "arrived"), ("d", "delay"), ("burden", "vehicle_hours"),
                        ("demand", "planned"), ("halting", "halting")]:
        features[name] = interval([100 * (a[field] / b[field] - 1) for a, b in pairs])
    for name, field in [("completion", "arrived"), ("entry_backlog", "waiting")]:
        features[name] = interval([100 * (a[field] / a["planned"] - b[field] / b["planned"])
                                   for a, b in pairs])
    features["burden_per_planned"] = interval([
        100 * ((a["vehicle_hours"] / a["planned"]) / (b["vehicle_hours"] / b["planned"]) - 1)
        for a, b in pairs])
    features["teleports"] = sum(a["teleports"] for a, _ in pairs)
    features["collisions"] = sum(a["collisions"] for a, _ in pairs)
    features["config_warning_seeds"] = sum(bool(a["config_warning"]) for a, _ in pairs)
    features["baseline_warning_seeds"] = sum(bool(b["teleports"] or b["collisions"] or b["config_warning"])
                                                for _, b in pairs)
    features["local"] = {}
    for signal in ("n1", "n2", "n4"):
        local = {}
        for metric in ("front_crossings", "queue_m"):
            base = [b["local"][signal][metric] for _, b in pairs]
            if min(base) <= 0:
                local[metric] = None
            else:
                local[metric] = interval([100 * (a["local"][signal][metric] / b["local"][signal][metric] - 1)
                                          for a, b in pairs])
        features["local"][signal] = local
    return features


def classify(f, variant="D_full", threshold_scale=1.0):
    accounting, warning, local = VARIANTS[variant]
    t = {k: v * threshold_scale for k, v in THRESHOLDS.items()}
    q, d = f["q"], f["d"]
    raw_loss = q["hi"] < -t["flow_pct"] and d["lo"] > t["delay_pct"]
    raw_gain = q["lo"] > t["flow_pct"] and d["hi"] < -t["delay_pct"]
    labels, reasons = [], []
    status = "loss_candidate" if raw_loss else "gain_candidate" if raw_gain else "unresolved_or_small"
    warning_present = warning and bool(f["teleports"] or f["collisions"] or
                                      f["config_warning_seeds"] or f["baseline_warning_seeds"])
    if warning_present:
        labels.append("warning_audit_required")
        reasons.append("Any recorded teleport/collision or timing warning vetoes unqualified improvement; magnitude and cause require separate audit.")
    changed_demand = accounting and abs(f["demand"]["mean"]) > t["demand_pct"]
    if changed_demand:
        labels.append("demand_change")
        if f["demand"]["mean"] > 0 and (
                f["burden_per_planned"]["lo"] > t["burden_pct"] or
                f["entry_backlog"]["lo"] > t["share_pp"] or f["completion"]["hi"] < -t["share_pp"]):
            labels.append("demand_pressure_observed")
        status = "demand_conditioned_unresolved"
        reasons.append("Demand differs: Q and delay cannot alone isolate supply deterioration or capacity gain; mixed causes remain possible.")
    if accounting and not changed_demand and raw_loss:
        if f["burden"]["lo"] > t["burden_pct"] or f["completion"]["hi"] < -t["share_pp"]:
            status = "service_deterioration_supported"
        else:
            status = "conflicting_evidence"
    if accounting and not changed_demand and raw_gain:
        if f["burden"]["hi"] < -t["burden_pct"] and f["entry_backlog"]["hi"] <= t["share_pp"]:
            status = "improvement_candidate"
        else:
            status = "conflicting_evidence"
    local_loss, local_gain = [], []
    if local:
        for signal, metrics in f["local"].items():
            flow, queue = metrics["front_crossings"], metrics["queue_m"]
            if flow is None or queue is None:
                continue
            if flow["hi"] < -t["flow_pct"] and queue["lo"] > t["local_queue_pct"]:
                local_loss.append(signal)
            if flow["lo"] > t["flow_pct"] and queue["hi"] < -t["local_queue_pct"]:
                local_gain.append(signal)
        if local_loss:
            labels.append("local_deterioration_evidence")
        if local_gain:
            labels.append("local_recovery_evidence")
        if (raw_loss and local_gain and not local_loss) or (raw_gain and local_loss and not local_gain):
            reasons.append("Network and prespecified local signals disagree; spatial redistribution needs inspection.")
            if not changed_demand:
                status = "conflicting_evidence"
        if status in ("improvement_candidate", "gain_candidate") and not local_gain:
            status = "network_improvement_only"
    if warning_present:
        status = "warning_qualified_" + status
    return {"status": status, "raw_loss": raw_loss, "raw_gain": raw_gain,
            "labels": labels, "local_loss_signals": local_loss, "local_gain_signals": local_gain,
            "retained_improvement": status in ("improvement_candidate", "gain_candidate"),
            "reasons": reasons}
