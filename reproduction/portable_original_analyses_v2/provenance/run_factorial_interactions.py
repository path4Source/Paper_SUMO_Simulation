from __future__ import annotations

import argparse
from dataclasses import replace
from itertools import combinations, product
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sumolib import checkBinary

from plot_style import apply_paper_style
from run_capacity_factor_study import (
    DATA_DIR,
    FIG_DIR,
    SumoScenario,
    ensure_dirs,
    run_sumo_scenario,
)


FACTORS = {
    "HV": {
        "label": "Heavy vehicles",
        "updates": {"heavy_vehicle_share": 0.16},
    },
    "WR": {
        "label": "Heavy rain",
        "updates": {
            "max_speed_factor": 0.80,
            "accel_factor": 0.70,
            "decel_factor": 0.85,
            "sigma": 0.80,
        },
    },
    "RT": {
        "label": "Slow reaction",
        "updates": {"tau": 1.40},
    },
    "LT": {
        "label": "Long lost time",
        "updates": {"signal_yellow_factor": 1.80},
    },
}


def scenario_from_bits(bits: tuple[int, ...]) -> SumoScenario:
    names = list(FACTORS)
    kwargs = {}
    active = []
    for bit, name in zip(bits, names):
        if bit:
            active.append(name)
            kwargs.update(FACTORS[name]["updates"])
    code = "".join(str(bit) for bit in bits)
    label = "+".join(active) if active else "base"
    return SumoScenario(
        name=f"factorial_{code}",
        factor="factorial",
        level=label,
        **kwargs,
    )


def parse_seeds(seed_text: str) -> list[int]:
    return [int(item.strip()) for item in seed_text.split(",") if item.strip()]


def existing_rows(path: Path) -> dict[tuple[str, int], dict]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if "seed" not in df.columns:
        df["seed"] = 42
    return {(str(row["scenario"]), int(row["seed"])): row.to_dict() for _, row in df.iterrows()}


def run_factorial(seeds: list[int], reuse_existing: bool) -> pd.DataFrame:
    ensure_dirs()
    path = DATA_DIR / "sumo_factorial_results.csv"
    old = existing_rows(path) if reuse_existing else {}
    sumo_binary = checkBinary("sumo")
    rows = []
    for seed in seeds:
        for bits in product([0, 1], repeat=len(FACTORS)):
            scenario = scenario_from_bits(bits)
            key = (scenario.name, seed)
            if key in old:
                print(f"Reusing factorial scenario: {scenario.name}, seed {seed}", flush=True)
                row = dict(old[key])
            else:
                print(f"Running factorial scenario: {scenario.name}, seed {seed}", flush=True)
                run_name = f"{scenario.name}_seed{seed}"
                row = run_sumo_scenario(replace(scenario, name=run_name), sumo_binary=sumo_binary, seed=seed)
                row["scenario_run"] = row["scenario"]
                row["scenario"] = scenario.name
                row["factor"] = scenario.factor
                row["level"] = scenario.level
            for bit, name in zip(bits, FACTORS):
                row[name] = int(bit)
            row["seed"] = seed
            rows.append(row)
            pd.DataFrame(rows).to_csv(path, index=False)
    df = pd.DataFrame(rows).sort_values(["seed", *list(FACTORS)]).reset_index(drop=True)
    df.to_csv(path, index=False)
    return df


def build_effects(df: pd.DataFrame) -> pd.DataFrame:
    base = df[(df[list(FACTORS)] == 0).all(axis=1)][
        ["seed", "throughput_veh_per_h", "mean_time_loss", "mean_halting", "co2_per_vehicle_kg"]
    ].rename(
        columns={
            "throughput_veh_per_h": "base_throughput",
            "mean_time_loss": "base_time_loss",
            "mean_halting": "base_halting",
            "co2_per_vehicle_kg": "base_co2_per_vehicle",
        }
    )
    effects = df.merge(base, on="seed", how="left")
    effects["throughput_change_pct"] = (
        effects["throughput_veh_per_h"] - effects["base_throughput"]
    ) / effects["base_throughput"] * 100.0
    effects["time_loss_change_pct"] = (
        effects["mean_time_loss"] - effects["base_time_loss"]
    ) / effects["base_time_loss"] * 100.0
    effects["halting_change_pct"] = (
        effects["mean_halting"] - effects["base_halting"]
    ) / effects["base_halting"] * 100.0
    effects["co2_vehicle_change_pct"] = (
        effects["co2_per_vehicle_kg"] - effects["base_co2_per_vehicle"]
    ) / effects["base_co2_per_vehicle"] * 100.0
    effects["throughput_loss_pct"] = -effects["throughput_change_pct"]
    effects.to_csv(DATA_DIR / "sumo_factorial_effects.csv", index=False)
    return effects


def cell_mean(effects: pd.DataFrame, first: str, first_level: int, second: str, second_level: int, metric: str, seed: int) -> float:
    rows = effects[(effects[first] == first_level) & (effects[second] == second_level) & (effects["seed"] == seed)]
    return float(rows[metric].mean())


def build_interactions(effects: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for seed in sorted(effects["seed"].unique()):
        for first, second in combinations(FACTORS, 2):
            q00 = cell_mean(effects, first, 0, second, 0, "throughput_loss_pct", seed)
            q10 = cell_mean(effects, first, 1, second, 0, "throughput_loss_pct", seed)
            q01 = cell_mean(effects, first, 0, second, 1, "throughput_loss_pct", seed)
            q11 = cell_mean(effects, first, 1, second, 1, "throughput_loss_pct", seed)
            d00 = cell_mean(effects, first, 0, second, 0, "time_loss_change_pct", seed)
            d10 = cell_mean(effects, first, 1, second, 0, "time_loss_change_pct", seed)
            d01 = cell_mean(effects, first, 0, second, 1, "time_loss_change_pct", seed)
            d11 = cell_mean(effects, first, 1, second, 1, "time_loss_change_pct", seed)
            rows.append(
                {
                    "seed": seed,
                    "first": first,
                    "second": second,
                    "first_label": FACTORS[first]["label"],
                    "second_label": FACTORS[second]["label"],
                    "throughput_loss_interaction": q11 - q10 - q01 + q00,
                    "time_loss_interaction": d11 - d10 - d01 + d00,
                }
            )
    by_seed = pd.DataFrame(rows)
    by_seed.to_csv(DATA_DIR / "sumo_factorial_interactions_by_seed.csv", index=False)
    result = (
        by_seed.groupby(["first", "second", "first_label", "second_label"], as_index=False)
        .agg(
            throughput_loss_interaction_mean=("throughput_loss_interaction", "mean"),
            throughput_loss_interaction_std=("throughput_loss_interaction", "std"),
            time_loss_interaction_mean=("time_loss_interaction", "mean"),
            time_loss_interaction_std=("time_loss_interaction", "std"),
            n_seeds=("seed", "nunique"),
        )
        .sort_values("throughput_loss_interaction_mean", key=lambda s: s.abs(), ascending=False)
    )
    result.to_csv(DATA_DIR / "sumo_factorial_interactions.csv", index=False)
    return result


def plot_interactions(interactions: pd.DataFrame) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    labels = [FACTORS[name]["label"] for name in FACTORS]
    matrix = pd.DataFrame(np.nan, index=labels, columns=labels)
    for _, row in interactions.iterrows():
        matrix.loc[row["first_label"], row["second_label"]] = row["throughput_loss_interaction_mean"]
        matrix.loc[row["second_label"], row["first_label"]] = row["throughput_loss_interaction_mean"]

    fig, ax = plt.subplots(figsize=(6.8, 5.7))
    max_abs = float(np.nanmax(np.abs(matrix.values)))
    im = ax.imshow(matrix.values, cmap="RdBu_r", vmin=-max_abs, vmax=max_abs)
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_yticklabels(labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            value = matrix.iloc[i, j]
            if np.isfinite(value):
                ax.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=8, color="#111827")
    ax.set_title("Interaction effect on throughput-loss response")
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Difference-in-differences, pp; negative = sub-additive")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "Fig16_factorial_interactions.png", dpi=320)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seeds", default="")
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args()

    apply_paper_style()
    seeds = parse_seeds(args.seeds) if args.seeds else [args.seed]
    df = run_factorial(seeds=seeds, reuse_existing=args.reuse_existing)
    effects = build_effects(df)
    interactions = build_interactions(effects)
    plot_interactions(interactions)
    print(
        {
            "rows": int(len(df)),
            "interactions": int(len(interactions)),
            "top_interaction": interactions.iloc[0].to_dict() if len(interactions) else {},
        }
    )


if __name__ == "__main__":
    main()
