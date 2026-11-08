"""Full-design-only sensitivity analysis; never compiles manuscript artifacts."""
import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from SALib.analyze.morris import analyze

from audit_metrics import write_csv
from freeze_submission import sha256
from run_morris_v1 import OUT, PROBLEM, SEEDS, SPECS, LEVELS, TRAJECTORIES, validate_design, verify_complete

RESPONSES = ["arrived_veh_per_h", "total_vehicle_hours_discrete",
             "mean_halted_vehicles", "trip_completed_timeLoss_mean_s",
             "end_waiting", "end_running", "teleported_unique_pct_inserted",
             "stat_safety_collisions"]


def elementary_effects(x, y):
    """Independent audit of SALib: y has point x seed axes."""
    k = len(SPECS)
    bounds = np.asarray(PROBLEM["bounds"])
    unit = (x - bounds[:, 0]) / (bounds[:, 1] - bounds[:, 0])
    result = np.empty((TRAJECTORIES, k, y.shape[1]))
    pairs = []
    for t in range(TRAJECTORIES):
        first = t * (k + 1)
        for pos in range(k):
            i, j = first + pos, first + pos + 1
            delta = unit[j] - unit[i]
            ids = np.flatnonzero(np.abs(delta) > 1e-8)
            if len(ids) != 1:
                raise ValueError("Invalid trajectory")
            d = int(ids[0])
            result[t, d] = (y[j] - y[i]) / delta[d]
            pairs.append((t, d, i, j))
    return result, pairs


def indices(x, y):
    return analyze(copy.deepcopy(PROBLEM), x, np.asarray(y, dtype=float),
                   num_levels=LEVELS, num_resamples=2000, conf_level=0.95,
                   seed=20261021, print_to_console=False)


def warning_free(row):
    return (row["teleport_events"] == 0 and row["stat_safety_collisions"] == 0
            and not row["tau_step_warning"] and not row["tau_action_warning"]
            and not row["integration_action_warning"])


def load_complete():
    protocol_path = OUT / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    digest = sha256(protocol_path)
    x = np.asarray([[p[n] for n in PROBLEM["names"]] for p in protocol["design_rows"]])
    validate_design(x)
    if protocol["simulation_seeds"] != SEEDS or protocol["problem"] != PROBLEM:
        raise RuntimeError("Analysis specification differs from frozen protocol")
    points = []
    manifests = []
    missing = []
    for p in protocol["design_rows"]:
        row = []
        for seed in SEEDS:
            directory = OUT / "runs" / f"t{p['trajectory']:02d}_p{p['position']:02d}_seed{seed}"
            if not (directory / "complete.json").exists():
                missing.append(directory.name)
                continue
            record = verify_complete(directory, digest)
            audit = record["audit"]
            if audit["point"] != p["point"] or audit["seed"] != seed:
                raise RuntimeError("Point/seed mismatch")
            row.append(audit)
            manifests.append({"run": directory.name, "complete_sha256": sha256(directory / "complete.json")})
        points.append(row)
    if missing:
        raise RuntimeError(f"Incomplete frozen design: {len(missing)} missing runs; no Morris indices generated. First missing: {missing[0]}")
    for seed in SEEDS:
        control = verify_complete(OUT / "runs" / f"control_seed{seed}", digest)
        if not control["audit"].get("output_equivalence_verified"):
            raise RuntimeError("Output equivalence gate not passed")
    return x, points, protocol, digest, manifests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    freeze_path = OUT / "analysis_code_freeze.json"
    code_hash = sha256(Path(__file__))
    if freeze_path.exists():
        frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
        if frozen["sha256"] != code_hash:
            raise RuntimeError("Analysis code changed after freeze; document amendment")
    else:
        if list((OUT / "runs").glob("t*/complete.json")):
            raise RuntimeError("Cannot claim pre-outcome analysis freeze after design runs")
        freeze_path.write_text(json.dumps({
            "frozen_utc": datetime.now(timezone.utc).isoformat(), "sha256": code_hash,
            "protocol_sha256": sha256(OUT / "protocol.json"),
            "scope": "Frozen analyzer before formal design outcomes; control runs only may exist.",
        }, indent=2), encoding="utf-8")
    if args.freeze_only:
        print(f"Analysis code frozen: {code_hash}")
        return
    x, points, protocol, digest, manifests = load_complete()
    summary, detail, seed_rows, omission_rows, eligible_rows, pair_rows = [], [], [], [], [], []
    valid = np.asarray([[warning_free(r) for r in p] for p in points])
    for response in RESPONSES:
        y = np.asarray([[r[response] for r in p] for p in points], dtype=float)
        if not np.all(np.isfinite(y)):
            raise RuntimeError(f"Nonfinite response: {response}; no imputation")
        effects, pairs = elementary_effects(x, y)
        result = indices(x, y.mean(axis=1))
        expected_mu = effects.mean(axis=2).mean(axis=0)
        expected_abs = np.abs(effects.mean(axis=2)).mean(axis=0)
        np.testing.assert_allclose(result["mu"], expected_mu, atol=1e-7, rtol=1e-10)
        np.testing.assert_allclose(result["mu_star"], expected_abs, atol=1e-7, rtol=1e-10)
        ranks = np.empty(len(SPECS), dtype=int)
        ranks[np.argsort(-result["mu_star"], kind="stable")] = np.arange(1, len(SPECS) + 1)
        per_seed = []
        for s, seed in enumerate(SEEDS):
            r = indices(x, y[:, s])
            np.testing.assert_allclose(r["mu"], effects[:, :, s].mean(axis=0), atol=1e-7, rtol=1e-10)
            per_seed.append(r["mu_star"])
            for d, name in enumerate(PROBLEM["names"]):
                seed_rows.append({"response": response, "seed": seed, "parameter": name,
                                  "mu": r["mu"][d], "mu_star": r["mu_star"][d], "sigma": r["sigma"][d]})
        omitted_ranks = []
        for s, seed in enumerate(SEEDS):
            r = indices(x, np.delete(y, s, axis=1).mean(axis=1))
            rr = np.empty(len(SPECS), dtype=int)
            rr[np.argsort(-r["mu_star"], kind="stable")] = np.arange(1, len(SPECS) + 1)
            omitted_ranks.append(rr)
            for d, name in enumerate(PROBLEM["names"]):
                omission_rows.append({"response": response, "omitted_seed": seed, "parameter": name,
                                      "mu_star": r["mu_star"][d], "raw_response_rank": int(rr[d])})
        per_seed = np.asarray(per_seed)
        omitted_ranks = np.asarray(omitted_ranks)
        for d, name in enumerate(PROBLEM["names"]):
            summary.append({
                "response": response, "parameter": name,
                "role": "demand-stress input" if name == "demand_scale" else "service-setting input",
                "mu": result["mu"][d], "mu_star": result["mu_star"][d], "sigma": result["sigma"][d],
                "mu_star_trajectory_bootstrap_95_halfwidth": result["mu_star_conf"][d],
                "raw_response_rank": int(ranks[d]),
                "seed_specific_mu_star_min": per_seed[:, d].min(),
                "seed_specific_mu_star_max": per_seed[:, d].max(),
                "seed_specific_mu_star_sd": per_seed[:, d].std(ddof=1),
                "leave_one_seed_out_best_rank": int(omitted_ranks[:, d].min()),
                "leave_one_seed_out_worst_rank": int(omitted_ranks[:, d].max()),
            })
        clean_effects = {d: [] for d in range(len(SPECS))}
        clean_seed_pair_counts = {d: 0 for d in range(len(SPECS))}
        for t, d, i, j in pairs:
            clean = valid[i] & valid[j]
            clean_seed_pair_counts[d] += int(clean.sum())
            if np.all(clean):
                clean_effects[d].append(float(effects[t, d].mean()))
            pair_rows.append({"response": response, "trajectory": t, "parameter": PROBLEM["names"][d],
                              "first_point": i, "second_point": j,
                              "mean_elementary_effect": float(effects[t, d].mean()),
                              "seed_effect_sd": float(effects[t, d].std(ddof=1)),
                              "warning_free_seed_pairs": int(clean.sum()), "seed_pairs": len(SEEDS)})
            for s, seed in enumerate(SEEDS):
                detail.append({"response": response, "trajectory": t, "parameter": PROBLEM["names"][d],
                               "seed": seed, "elementary_effect": effects[t, d, s],
                               "warning_free_pair": bool(clean[s])})
        for d, name in enumerate(PROBLEM["names"]):
            values = clean_effects[d]
            eligible_rows.append({
                "response": response, "parameter": name,
                "all_five_seeds_warning_free_pairs": len(values), "total_trajectory_pairs": TRAJECTORIES,
                "warning_free_seed_pairs": clean_seed_pair_counts[d], "total_seed_pairs": TRAJECTORIES * len(SEEDS),
                "selected_pair_mean_abs_effect": float(np.mean(np.abs(values))) if values else None,
                "interpretation": "Selected descriptive subset; not full-domain Morris sensitivity or unbiased ranking.",
            })
    for name, rows in [("indices.csv", summary), ("elementary_effects.csv", detail),
                       ("seed_specific_indices.csv", seed_rows), ("leave_one_seed_out.csv", omission_rows),
                       ("warning_free_pair_audit.csv", eligible_rows), ("paired_seed_precision.csv", pair_rows)]:
        write_csv(OUT / name, rows)
    manifest = {
        "finished_utc": datetime.now(timezone.utc).isoformat(), "protocol_sha256": digest,
        "analyzer_sha256": code_hash, "design_runs": len(points) * len(SEEDS),
        "warning_free_runs": int(valid.sum()), "warning_exposed_runs": int((~valid).sum()),
        "raw_response_only": True, "physical_or_causal_validation": False,
        "manifests": manifests,
        "ci_scope": protocol["uncertainty"], "range_scope": protocol["input_scope"],
    }
    (OUT / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Analyzed {manifest['design_runs']} runs; warning-exposed={manifest['warning_exposed_runs']}")


if __name__ == "__main__":
    main()
