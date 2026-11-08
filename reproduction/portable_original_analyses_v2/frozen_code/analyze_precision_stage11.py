"""Recompute matched-seed precision without adding or changing SUMO runs."""
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import numpy as np

ROOT = Path(r"E:\4\scientific_reports_major_revision_20261019")
DATA = ROOT / "frozen/data"
OUT = ROOT / "statistical_precision_v1"
T975 = {2: 4.302652729696142, 4: 2.7764451051977987, 9: 2.2621571628540993}


def summary(values):
    values = [float(v) for v in values]
    n = len(values)
    mean, sd = statistics.mean(values), statistics.stdev(values)
    half = T975[n-1] * sd / math.sqrt(n)
    return {"n": n, "mean": mean, "sample_sd": sd, "ci95_halfwidth": half,
            "ci95_low": mean-half, "ci95_high": mean+half}


def read(name):
    with (DATA/name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write(name, rows):
    with (OUT/name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(exist_ok=True)
    effects = read("sumo_keyseed_effects.csv")
    rows = read("sumo_keyseed_results.csv")
    raw = {(r["scenario"], int(r["seed"])): r for r in rows}
    groups = {}
    for r in effects:
        s, seed = r["scenario"], int(r["seed"])
        assert seed not in groups.setdefault(s, {})
        b, v = raw[("baseline", seed)], raw[(s, seed)]
        dq = 100 * (float(v["arrived_vehicles"])/float(b["arrived_vehicles"])-1)
        dd = 100 * (float(v["mean_time_loss"])/float(b["mean_time_loss"])-1)
        assert abs(dq-float(r["throughput_change_pct"])) < 1e-9
        assert abs(dd-float(r["time_loss_change_pct"])) < 1e-9
        groups[s][seed] = {"dq": dq, "dd": dd, "tp": int(float(r["teleport_warnings"]))}
    marginal = []
    for scenario, values in sorted(groups.items()):
        assert len(values) == 10
        for key in ("dq", "dd"):
            marginal.append({"scenario": scenario, "response": key,
                             **summary(v[key] for v in values.values()),
                             "warning_qualified": any(v["tp"] > 0 for v in values.values())})
    write("ten_seed_paired_intervals.csv", marginal)

    hv, rain = groups["heavyveh_very_high"], groups["weather_heavy_rain"]
    assert set(hv) == set(rain)
    differences = [{"seed": seed, "hv_loss_pct": -hv[seed]["dq"],
                    "rain_loss_pct": -rain[seed]["dq"],
                    "hv_minus_rain_loss_pp": -hv[seed]["dq"]+rain[seed]["dq"]}
                   for seed in sorted(hv)]
    write("leading_pair_seed_differences.csv", differences)
    values = np.array([r["hv_minus_rain_loss_pp"] for r in differences])
    rng = np.random.default_rng(20261020)
    means = values[rng.integers(0, len(values), size=(50000, len(values)))].mean(axis=1)
    pair = summary(values)
    pair.update({"contrast": "HV24 throughput loss minus heavy-rain throughput loss",
                 "unit": "percentage points", "bootstrap_seed": 20261020,
                 "bootstrap_resamples": 50000,
                 "paired_percentile_bootstrap_ci95": np.quantile(means, [.025, .975]).tolist(),
                 "both_scenarios_warning_qualified": True,
                 "equivalence_claimed": False})
    (OUT/"leading_pair.json").write_text(json.dumps(pair, indent=2), encoding="utf-8")

    interactions = read("sumo_factorial_interactions_by_seed.csv")
    by_pair = {}
    for r in interactions:
        by_pair.setdefault((r["first"], r["second"]), []).append(r)
    int_rows = []
    for (first, second), cases in sorted(by_pair.items()):
        assert len({r["seed"] for r in cases}) == len(cases) == 3
        for response in ("throughput_loss_interaction", "time_loss_interaction"):
            int_rows.append({"first": first, "second": second, "response": response,
                             **summary(float(r[response]) for r in cases),
                             "interval_scope": "pointwise exploratory; not multiplicity-adjusted"})
    write("interaction_pointwise_intervals.csv", int_rows)
    inputs = ["sumo_keyseed_effects.csv", "sumo_keyseed_results.csv",
              "sumo_factorial_interactions_by_seed.csv"]
    manifest = {
        "new_sumo_runs": 0,
        "method": "seed-wise normalized effects; paired Student t mean CI, df=n-1",
        "assumptions": "independent seed replicates; t intervals approximate for non-normal differences",
        "bootstrap": "resample matched seed differences, not individual vehicles or time steps",
        "interaction_scope": "three seeds only; pointwise exploratory intervals, not confirmatory tests",
        "sources": [
            "https://www.itl.nist.gov/div898/handbook/eda/section3/eda353.htm",
            "https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm",
        ],
        "inputs_sha256": {n: hashlib.sha256((DATA/n).read_bytes()).hexdigest() for n in inputs},
        "limitations": ["No independent field evidence", "No Morris execution in this stage",
                        "No retrospective power or sufficiency claim",
                        "Non-significance does not establish equivalence",
                        "Intervals do not remove simulator warning qualification"],
    }
    (OUT/"manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"leading_pair": pair, "interval_rows": len(marginal),
                      "interaction_rows": len(int_rows)}, indent=2))


if __name__ == "__main__":
    main()
