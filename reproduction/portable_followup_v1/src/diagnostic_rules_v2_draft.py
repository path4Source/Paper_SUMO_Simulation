"""Population-first rules under development, NOT frozen blind-test rules.

v1 predictions and their archived 85-run development experiment are unchanged.
These rules have software tests, not independent diagnostic validation.
"""
import math
from dataclasses import dataclass

THRESHOLDS = {"flow_pct": 2.0, "delay_pct": 5.0, "burden_pct": 5.0,
              "demand_pct": 1.0, "share_pp": 2.0, "local_queue_pct": 5.0}
VERSION = "v2-draft-not-frozen"
VARIANTS = ("full", "without_population", "without_warning", "without_local",
            "conventional_QD", "QD_timing_warning", "always_abstain")


@dataclass(frozen=True)
class Scope:
    # Sets must be specified before outcomes, not selected for favorable signals.
    monitored_groups: tuple[str, ...]
    recovery_targets: tuple[str, ...]
    same_window: bool
    same_demand_structure: bool | None

    def __post_init__(self):
        if not self.monitored_groups or len(set(self.monitored_groups)) != len(self.monitored_groups):
            raise ValueError("Specify unique monitored groups")
        if len(set(self.recovery_targets)) != len(self.recovery_targets):
            raise ValueError("Duplicate recovery target")
        if not set(self.recovery_targets).issubset(self.monitored_groups):
            raise ValueError("Recovery targets must belong to monitored groups")


def checked_interval(value):
    if value is None:
        return None
    if not all(math.isfinite(value[k]) for k in ("mean", "lo", "hi")):
        raise ValueError("Non-finite interval")
    if not value["lo"] <= value["mean"] <= value["hi"] or value.get("n", 0) < 2:
        raise ValueError("Invalid interval")
    return value


def above(value, tolerance):
    return value is not None and value["lo"] > tolerance


def below(value, tolerance):
    return value is not None and value["hi"] < -tolerance


def bounded(value, tolerance):
    return value is not None and value["lo"] >= -tolerance and value["hi"] <= tolerance


def classify(features, scope, variant="full"):
    """Return state, evidence flags and adoption separately; never infer unique cause.

    Features are paired scenario-level intervals, not per-vehicle replications.
    Completion is retained for population interpretation, never a second vote for Q.
    """
    if variant not in VARIANTS:
        raise ValueError("Unknown variant")
    f = {key: checked_interval(features.get(key)) for key in
         ("q", "d", "burden", "burden_per_planned", "demand", "completion",
          "entry_backlog", "network_residual")}
    t = THRESHOLDS
    flags, conflicts = [], []
    warned = any(features.get(k, 0) for k in
                 ("teleports", "collisions", "config_warning_seeds", "baseline_warning_seeds"))
    warning_gate = warned and variant not in ("without_warning", "conventional_QD", "always_abstain")
    raw_loss = below(f["q"], t["flow_pct"]) and above(f["d"], t["delay_pct"])
    raw_gain = above(f["q"], t["flow_pct"]) and below(f["d"], t["delay_pct"])
    out = {"version": VERSION, "variant": variant, "operating_state": "insufficient_evidence",
           "adoption": "unresolved", "retained_improvement": False,
           "warning_observed": warned, "raw_QD_loss": raw_loss, "raw_QD_gain": raw_gain,
           "flags": flags, "conflicts": conflicts, "local_gain_groups": [], "local_loss_groups": []}
    if variant == "always_abstain":
        out["operating_state"] = "not_evaluated"
        return out
    if not scope.same_window or features.get("population_identity_valid") is not True:
        flags.append("measurement_contract_failed")
        return out
    if variant in ("conventional_QD", "QD_timing_warning"):
        out["operating_state"] = "QD_gain" if raw_gain else "QD_loss" if raw_loss else "insufficient_evidence"
        out["adoption"] = "qualified_warning" if warning_gate else "supported" if raw_gain or raw_loss else "unresolved"
        out["retained_improvement"] = raw_gain and not warning_gate
        return out

    population = variant != "without_population"
    local = variant != "without_local"
    changed = above(f["demand"], t["demand_pct"]) or below(f["demand"], t["demand_pct"])
    stable_volume = bounded(f["demand"], t["demand_pct"])
    comparable_demand = stable_volume and scope.same_demand_structure is True
    if changed:
        flags.append("demand_volume_changed")
    if scope.same_demand_structure is False:
        flags.append("demand_structure_changed")
    elif scope.same_demand_structure is None:
        flags.append("demand_structure_not_established")
    if not changed and not stable_volume:
        flags.append("demand_volume_uncertain")

    q_loss, q_gain = below(f["q"], t["flow_pct"]), above(f["q"], t["flow_pct"])
    burden = f["burden"] if comparable_demand else f["burden_per_planned"]
    burden_up, burden_down = above(burden, t["burden_pct"]), below(burden, t["burden_pct"])
    backlog_up = above(f["entry_backlog"], t["share_pp"])
    residual_up = above(f["network_residual"], t["share_pp"])
    no_population_cost = all(f[k] is not None and f[k]["hi"] <= t["share_pp"]
                             for k in ("entry_backlog", "network_residual"))
    state = "insufficient_evidence"
    if population:
        if not comparable_demand:
            state = "demand_conditioned"
            if burden_up:
                flags.append("per_planned_vehicle_burden_increased")
            if burden_down:
                flags.append("per_planned_vehicle_burden_decreased")
        elif (q_loss and burden_down) or (q_gain and burden_up):
            state = "output_burden_tradeoff"
            conflicts.append("completion_output_and_full_population_burden")
        elif burden_up and (q_loss or backlog_up or residual_up):
            state = "service_deterioration"
        elif burden_down and q_gain and no_population_cost:
            state = "network_improvement"
        elif burden_up:
            state = "burden_increase_only"
        elif burden_down:
            state = "burden_decrease_only"
        if burden_up and below(f["d"], t["delay_pct"]):
            flags.append("completed_sample_differs_from_population")
        if burden_down and above(f["d"], t["delay_pct"]):
            flags.append("completed_sample_differs_from_population")
    else:
        state = "network_improvement" if raw_gain else "service_deterioration" if raw_loss else state
        flags.append("population_module_omitted")

    available, gain, loss, costs = set(), set(), set(), set()
    if local:
        for group in scope.monitored_groups:
            metrics = features.get("local", {}).get(group, {})
            flow = checked_interval(metrics.get("front_crossings"))
            queue = checked_interval(metrics.get("queue_m"))
            if flow is None or queue is None:
                continue
            available.add(group)
            if above(flow, t["flow_pct"]) and below(queue, t["local_queue_pct"]):
                gain.add(group)
            if below(flow, t["flow_pct"]) and above(queue, t["local_queue_pct"]):
                loss.add(group)
            if below(flow, t["flow_pct"]) or above(queue, t["local_queue_pct"]):
                costs.add(group)
        out["local_gain_groups"], out["local_loss_groups"] = sorted(gain), sorted(loss)
        if gain:
            flags.append("local_recovery_evidence")
        if loss:
            flags.append("local_deterioration_evidence")
        if gain and costs:
            flags.append("spatial_redistribution")
        if state == "network_improvement" and costs:
            conflicts.append("network_improvement_with_local_cost")
        if state == "service_deterioration" and gain and not loss:
            conflicts.append("network_deterioration_with_only_local_recovery")
        if available != set(scope.monitored_groups):
            flags.append("incomplete_local_coverage")
    else:
        flags.append("local_module_omitted")

    # Full-method gain requires every predeclared target, never any favorable signal.
    recovery = (bool(scope.recovery_targets) and set(scope.recovery_targets).issubset(gain)
                and available == set(scope.monitored_groups) and not costs) if local else True
    supported = (state == "network_improvement" and recovery) or state == "service_deterioration"
    adoption = "supported" if supported else "unresolved"
    if conflicts:
        adoption = "conflicting"
    # Warnings qualify an existing state; they do not turn it into a proven artifact.
    if warning_gate:
        flags.append("warning_audit_required")
        if adoption != "conflicting":
            adoption = "qualified_warning"
    out.update(operating_state=state, adoption=adoption,
               retained_improvement=state == "network_improvement" and adoption == "supported")
    return out
