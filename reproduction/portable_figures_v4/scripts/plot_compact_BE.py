"""Replot existing paired evidence; no simulations or changed estimators."""
import csv
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
from scipy.stats import t

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "manuscript_working/figures"
AUDIT = ROOT / "audit/compression_BE_20261023"


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def save(fig, stem):
    fig.canvas.draw()
    for ext in ("pdf", "svg", "png"):
        fig.savefig(FIG / (stem + "." + ext), dpi=400, facecolor="white")
    plt.close(fig)


def main():
    plt.rcParams.update({"font.family": "Arial", "font.size": 9, "axes.labelsize": 9,
        "xtick.labelsize": 8, "ytick.labelsize": 9, "axes.linewidth": .7,
        "pdf.fonttype": 42, "svg.fonttype": "none"})
    source = ROOT / "frozen/data/sumo_keyseed_scenario_summary.csv"
    rows = [r for r in read(source) if r["scenario"] != "reaction_fast"]
    rows.sort(key=lambda r: float(r["dq_mean"]))
    names = {"heavyveh_very_high": "Heavy vehicles (24%)", "heavyveh_high": "Heavy vehicles (16%)",
             "weather_heavy_rain": "Heavy rain", "reaction_slow": "Long desired headway",
             "sigma_high": "High driver imperfection", "losttime_high": "Extended yellow",
             "demand_peak": "High demand stress"}
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.7), sharey=True)
    trace = []
    for j, (metric, xlabel) in enumerate((("dq", "Throughput change (%)"), ("dd", "Completed-trip time-loss change (%)"))):
        ax = axes[j]
        for y, row in enumerate(rows):
            mu = float(row[metric + "_mean"])
            half = float(row[metric + "_std"]) * t.ppf(.975, 9) / np.sqrt(10)
            col = "#B77724" if row["factor"] == "demand_scale" else "#28678A"
            ax.errorbar(mu, y, xerr=half, fmt="o", color=col, ms=4, capsize=2, lw=1)
            trace.append(dict(scenario=row["scenario"], metric=metric, mean=mu, ci_half=float(half)))
        ax.axvline(0, color="#989FA2", lw=.7, ls=(0, (3, 3)))
        ax.set_yticks(range(len(rows)), [names.get(r["scenario"], r["scenario_label"]) for r in rows])
        ax.set_ylim(len(rows) - .5, -.5)
        ax.set_xlabel(xlabel)
        ax.tick_params(axis="y", length=0)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.text(0, 1.05, "ab"[j], transform=ax.transAxes, weight="bold", size=10)
    fig.subplots_adjust(left=.29, right=.985, top=.90, bottom=.20, wspace=.28)
    save(fig, "Fig_key_effects_BE")
    base = ROOT / "independent_intervention_v1"
    conditions = json.loads((base / "analysis_summary.json").read_text())["conditions"]
    pairs = read(base / "paired_intervention_effects.csv")
    labels = {"baseline": "Baseline traffic", "heavyveh_very_high": "Heavy vehicles (24%)", "weather_heavy_rain": "Heavy rain"}
    colors = {"baseline": "#5C656B", "heavyveh_very_high": "#28678A", "weather_heavy_rain": "#A65732"}
    metrics = [("Q_pct", "Corridor throughput change (%)"), ("B_pct", "Total vehicle-hour change (%)"),
        ("target_crossings_pct", "Target crossings change (%)"), ("target_queue_m_pct", "Target queue-extent change (%)"),
        ("donor_crossings_pct", "Donor crossings change (%)"), ("donor_queue_m_pct", "Donor queue-extent change (%)")]
    fig, axes = plt.subplots(3, 2, figsize=(7.2, 5.7), sharey=True)
    for j, (ax, (metric, xlabel)) in enumerate(zip(axes.flat, metrics)):
        ext = [0]
        for y, condition in enumerate(conditions):
            values = np.array([float(r[metric]) for r in pairs if r["state"] == condition["state"]])
            mu = values.mean()
            half = values.std(ddof=1) * t.ppf(.975, 4) / np.sqrt(5)
            estimate = condition["response"][metric]
            assert np.allclose([mu, mu-half, mu+half], [estimate["mean"], estimate["low"], estimate["high"]])
            color = colors[condition["state"]]
            ax.scatter(values, y + np.linspace(-.13, .13, 5), s=10, color=color, alpha=.55, linewidths=0)
            ax.errorbar(mu, y, xerr=half, fmt="D", ms=4.5, markerfacecolor="white",
                        color=color, capsize=2.5, lw=1)
            ext += [mu-half, mu+half, *values]
        ax.axvline(0, color="#989FA2", lw=.7, ls=(0, (3, 3)), zorder=0)
        ax.set_yticks(range(3), [labels[r["state"]] for r in conditions])
        ax.set_ylim(2.5, -.5)
        pad = max(.5, (max(ext)-min(ext)) * .12)
        ax.set_xlim(min(ext)-pad, max(ext)+pad)
        ax.set_xlabel(xlabel)
        ax.tick_params(axis="y", length=0)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.text(0, 1.06, "abcdef"[j], transform=ax.transAxes, weight="bold", size=10)
    handles = [Line2D([0], [0], marker="o", color="none", markerfacecolor="#747B80", markeredgewidth=0, ms=4, label="Paired seed"),
               Line2D([0], [0], marker="D", color="#4A5054", markerfacecolor="white", ms=5, lw=1, label="Mean and 95% interval; warning-qualified")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.58,.012), frameon=False, ncol=2, fontsize=8)
    fig.subplots_adjust(left=.225, right=.985, top=.95, bottom=.13, wspace=.28, hspace=.72)
    save(fig, "Fig_intervention_complete_BE")
    record = {"key_effects": trace, "key_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "intervention_six_metrics_recomputed_from_five_seed_pairs": True,
              "new_runs": 0, "original_figures_unchanged": True}
    (AUDIT / "figure_provenance.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
