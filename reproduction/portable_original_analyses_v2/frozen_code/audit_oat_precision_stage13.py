"""Pair original OAT seeds and expose precision; no new simulations or power claims."""
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from analyze_precision_stage11 import summary
from audit_metrics import write_csv
from freeze_submission import sha256
from run_timepilot import ROOT

OUT = ROOT / "oat_precision_v1"
SEEDS = {42, 2024, 2025}
METRICS = {
    "throughput": ("end_arrived", "arrived_vehicles"),
    "completed_trip_time_loss": ("trip_completed_timeLoss_mean_s", "mean_time_loss"),
    "mean_halted": ("mean_halted_vehicles", "mean_halting"),
    "total_vehicle_hours": ("total_vehicle_hours_discrete", None),
}
LABELS = {
    "accel_high": "High acceleration",
    "accel_low": "Low acceleration",
    "bottleneck_speed_drop": "Local speed restriction",
    "decel_high": "High deceleration",
    "decel_low": "Low deceleration",
    "demand_high": "High demand",
    "demand_low": "Low demand",
    "demand_peak": "Peak demand",
    "heavyveh_high": "Heavy vehicles 16\\%",
    "heavyveh_mid": "Heavy vehicles 8\\%",
    "heavyveh_very_high": "Heavy vehicles 24\\%",
    "lane_control_ed2": "Lane-control variant",
    "mingap_high": "Large minimum gap",
    "mingap_low": "Small minimum gap",
    "reaction_fast": "Short desired headway",
    "reaction_slow": "Long desired headway",
    "sigma_high": "High stochasticity",
    "sigma_low": "Low stochasticity",
    "signal_green_long": "Long-phase variant",
    "signal_green_short": "Short-phase variant",
    "signal_losttime_high": "Yellow extension",
    "signal_offset_mismatch": "Offset variant",
    "speed_high": "High maximum speed",
    "speed_low": "Low maximum speed",
    "weather_heavy_rain": "Heavy rain",
    "weather_rain": "Rain",
}


def table_tex(estimates):
    by_key = {(r["scenario"], r["response"]): r for r in estimates}
    if set(LABELS) != {r["scenario"] for r in estimates}:
        raise ValueError("Scenario table labels incomplete")
    lines = [
        "% Generated from the archived three-seed OAT results; no new runs.",
        r"\begin{table}[!htbp]",
        r"\caption{Pointwise uncertainty for all 26 original non-baseline scenarios. Entries are matched-seed mean percentage changes [95\% Student $t$ interval, two degrees of freedom]. $Q$ is route-completion throughput, $D$ is completed-trip time loss, and $B$ is total vehicle-hours including entry waiting. Negative $Q$ denotes lower output; negative $D$ or $B$ denotes a lower measured burden. Demand responses are not capacity effects. The intervals are exploratory and not multiplicity-adjusted. A dagger marks a collision/teleport or timing-warning-qualified comparison; no recorded warning does not establish physical validity.}",
        r"\label{tab:oat_precision}",
        r"\centering",
        r"\begin{tabularx}{\textwidth}{P{0.28\textwidth}*{3}{>{\centering\arraybackslash}X}}",
        r"\toprule",
        r"Scenario & $\Delta Q$ (\%) & $\Delta D$ (\%) & $\Delta B$ (\%) \\",
        r"\midrule",
    ]
    for scenario, label in LABELS.items():
        if by_key[(scenario, "throughput")]["warning_qualified"]:
            label += r"$^\dagger$"
        cells = [label]
        for response in ("throughput", "completed_trip_time_loss", "total_vehicle_hours"):
            r = by_key[(scenario, response)]
            cells.append(f"{r['mean']:.2f} [{r['ci95_low']:.2f}, {r['ci95_high']:.2f}]")
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabularx}", r"\end{table}", ""])
    return "\n".join(lines)


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def percent(value, base):
    if base <= 0:
        raise ValueError("Nonpositive baseline denominator")
    return 100 * (value / base - 1)


def warning(a):
    if a["warning_log_present"] != "True":
        raise ValueError("Missing warning evidence is not a zero")
    return (int(a["teleport_events"]) > 0 or a["tau_step_warning"] == "True"
            or a["tau_action_warning"] == "True")


def main():
    data = ROOT / "frozen/data/sumo_multiseed_results.csv"
    effects_path = ROOT / "frozen/data/sumo_multiseed_effects.csv"
    audit_path = ROOT / "audit/historical_run_audit.csv"
    raw = read(data)
    previous_effects = read(effects_path)
    audit = {r["run"]: r for r in read(audit_path)}
    if len(raw) != 81 or len(previous_effects) != 78:
        raise ValueError("Expected original 27 x 3 design")
    original = {}
    for r in raw:
        key = (r["scenario"], int(r["seed"]))
        if key in original:
            raise ValueError("Repeated scenario-seed")
        name = r["scenario"] if key[1] == 42 else r["scenario_run"]
        a = audit[name]
        if int(a["seed"]) != key[1]:
            raise ValueError("Mismatched seed")
        for local, source in METRICS.values():
            if source is not None:
                if abs(float(a[local]) - float(r[source])) > 1e-7:
                    raise ValueError(f"Processed/raw disagreement: {name}/{source}")
        if int(a["unaccounted_inserted_end"]) or int(a["ended_not_arrived"]):
            raise ValueError("Unresolved population accounting")
        original[key] = (r, a)
    observed = {r["scenario"] for r in raw}
    if len(observed) != 27:
        raise ValueError("Missing scenario")
    for s in observed:
        if {seed for name, seed in original if name == s} != SEEDS:
            raise ValueError(f"Incomplete seed set: {s}")
    expected = {(r["scenario"], int(r["seed"])): r for r in previous_effects}
    groups = defaultdict(list)
    pairs = []
    for (scenario, seed), (r, a) in sorted(original.items()):
        if scenario == "baseline":
            continue
        _, b = original[("baseline", seed)]
        qualified = warning(a) or warning(b)
        point = {"scenario": scenario, "factor": r["factor"], "seed": seed,
                 "warning_qualified_pair": qualified, "scenario_teleport_events": int(a["teleport_events"]),
                 "baseline_teleport_events": int(b["teleport_events"])}
        for response, (local, _) in METRICS.items():
            point[response + "_change_pct"] = percent(float(a[local]), float(b[local]))
        for response, old_name in [("throughput", "throughput_change_pct"),
                                   ("completed_trip_time_loss", "time_loss_change_pct"),
                                   ("mean_halted", "halting_change_pct")]:
            if abs(point[response + "_change_pct"] - float(expected[(scenario, seed)][old_name])) > 1e-7:
                raise ValueError("Matched normalization disagrees with legacy effect")
        pairs.append(point)
        groups[scenario].append(point)
    estimates = []
    for scenario, points in sorted(groups.items()):
        for response in METRICS:
            result = summary(p[response + "_change_pct"] for p in points)
            estimates.append({
                "scenario": scenario, "factor": points[0]["factor"], "response": response,
                "response_unit": "percent relative to same-seed original baseline",
                **result,
                "warning_qualified": any(p["warning_qualified_pair"] for p in points),
                "warning_qualified_pairs": sum(p["warning_qualified_pair"] for p in points),
                "ci_crosses_zero": result["ci95_low"] <= 0 <= result["ci95_high"],
                "interval_scope": "three-seed pointwise t interval, df=2; exploratory; not multiplicity adjusted",
            })
    OUT.mkdir(exist_ok=True)
    write_csv(OUT / "paired_seed_responses.csv", pairs)
    write_csv(OUT / "pointwise_intervals.csv", estimates)
    table = ROOT / "manuscript_working/revision_oat_precision_stage13.tex"
    table.write_text(table_tex(estimates), encoding="utf-8")
    counts = {}
    for response in METRICS:
        rows = [r for r in estimates if r["response"] == response]
        counts[response] = {
            "scenarios": len(rows),
            "ci_crosses_zero": sum(r["ci_crosses_zero"] for r in rows),
            "warning_qualified_scenarios": sum(r["warning_qualified"] for r in rows),
            "median_ci_halfwidth_pp": sorted(r["ci95_halfwidth"] for r in rows)[12:14],
        }
        counts[response]["median_ci_halfwidth_pp"] = sum(counts[response]["median_ci_halfwidth_pp"]) / 2
    manifest = {
        "finished_utc": datetime.now(timezone.utc).isoformat(), "new_sumo_runs": 0,
        "paired_rows": len(pairs), "interval_rows": len(estimates), "summary": counts,
        "input_hashes": {str(p.relative_to(ROOT)): sha256(p) for p in [data, effects_path, audit_path]},
        "script_sha256": sha256(Path(__file__)),
        "generated_table_sha256": sha256(table),
        "uncertainty": "Paired normalized response at each of the three fixed seeds; mean +/- t_0.975,2 * sample SD/sqrt(3). Seed is the replicate, not a vehicle or cycle. Small-n approximate intervals can be wide; zero crossing does not establish equivalence.",
        "population": "Throughput uses route arrivals, D uses completed-trip means, H uses mean halted vehicles, B integrates entry-waiting plus in-network running population over 0-3600 s. B is not excess delay and does not reconstruct teleport travel.",
        "scope": "Original configuration only. These 81 historical runs are not added to new-run totals or pooled with revised 0.1/0.1-s experiments.",
        "warnings": "Any warning in either paired arm qualifies interpretation. Historical junction collision checking was disabled, so no recorded warning is not a guarantee of physical validity.",
        "precision_sufficient_claimed": False,
        "retrospective_power_claimed": False,
        "rank_difference_test_claimed": False,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"paired_rows": len(pairs), "interval_rows": len(estimates), "summary": counts}, indent=2))


if __name__ == "__main__":
    main()
