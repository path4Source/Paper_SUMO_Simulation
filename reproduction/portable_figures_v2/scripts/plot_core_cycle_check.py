"""Descriptive cycle evidence for a previously selected bottleneck lane."""
import csv
from collections import defaultdict
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'core_detector_batch'

def main():
    with (OUT / 'cycle_diagnostics.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = [r for r in csv.DictReader(handle) if r['lane'] == 'ED2.378_1']
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.labelsize': 10, 'xtick.labelsize': 9, 'ytick.labelsize': 9, 'legend.fontsize': 9, 'axes.spines.top': False, 'axes.spines.right': False, 'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, axes = plt.subplots(2, 1, figsize=(7.0, 5.0), sharex=True)
    styles = [('baseline', 'Baseline', '#333333'), ('heavyveh_very_high', '24% heavy vehicles', '#B76421'), ('weather_heavy_rain', 'Heavy rain', '#147568')]
    for scenario, label, color in styles:
        groups = defaultdict(list)
        for r in rows:
            if r['scenario'] == scenario:
                groups[int(r['cycle_index'])].append(r)
        assert groups and all((len(v) == 3 for v in groups.values()))
        ordered = [groups[k] for k in sorted(groups)]
        x = [(float(g[0]['begin_s']) + float(g[0]['end_s'])) / 120 for g in ordered]
        for ax, metric in zip(axes, ('front_crossings', 'mean_max_jam_veh')):
            data = np.array([[float(r[metric]) for r in group] for group in ordered])
            ax.fill_between(x, data.min(axis=1), data.max(axis=1), color=color, alpha=0.12, linewidth=0)
            ax.plot(x, data.mean(axis=1), color=color, linewidth=1.4, marker='o', markersize=2.5, label=label)
    axes[0].set_ylabel('Front crossings\n(vehicles per cycle)')
    axes[1].set_ylabel('Mean detected jam\n(vehicles)')
    axes[1].set_xlabel('Simulation time (min)')
    for i, ax in enumerate(axes):
        ax.set_ylim(bottom=0)
        ax.set_xlim(0, 60)
        ax.text(0.012, 0.96, chr(97 + i), transform=ax.transAxes, fontweight='bold', fontsize=11, va='top')
    axes[0].legend(loc='upper center', bbox_to_anchor=(0.5, 1.26), ncol=3, frameon=False)
    fig.subplots_adjust(left=0.14, right=0.98, bottom=0.12, top=0.86, hspace=0.17)
    fig.align_ylabels(axes)
    figures = OUT / 'figures'
    figures.mkdir(exist_ok=True)
    fig.savefig(figures / 'ED2_378_lane1_cycle_check.png', dpi=400, facecolor='white')
    fig.savefig(figures / 'ED2_378_lane1_cycle_check.pdf', facecolor='white')
    plt.close(fig)
    caption = 'Internal revision evidence, not yet a final manuscript figure. Cycle-resolved observations on lane ED2.378_1, one of the previously identified bottleneck approaches. Panel a shows front crossings during complete observed signal cycles; panel b shows the cycle-average E2 mean-maximum jam in vehicles over the final up-to-100 m. Lines are means over seeds 42, 2024 and 2025; bands are the minimum-to-maximum seed range, not confidence intervals. The initial transient is retained and the terminal incomplete cycle is omitted. All curves use explicit ballistic integration, 0.5 s simulation/action intervals and junction collision checks. Low-count warnings in adverse runs are retained and must accompany interpretation. These are detector-limited operational observations, not saturation-flow or complete upstream back-of-queue estimates. The lane was selected from the existing bottleneck inventory, not by the size of the new effect.\n'
    (figures / 'caption.txt').write_text(caption, encoding='utf-8')
if __name__ == '__main__':
    main()
