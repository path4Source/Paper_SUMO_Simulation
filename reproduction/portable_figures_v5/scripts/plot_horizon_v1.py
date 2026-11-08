"""Plot sampled summary trajectories; no curve smoothing or simulator screenshots."""
import csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'horizon_audit_v1'
FIG = ROOT / 'manuscript_working/figures'

def main():
    with (OUT / 'timeline.csv').open(encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10.5, 'axes.labelsize': 10.5, 'xtick.labelsize': 10, 'ytick.labelsize': 10, 'pdf.fonttype': 42, 'ps.fonttype': 42, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': False, 'svg.fonttype': 'none'})
    fig, axes = plt.subplots(1, 3, figsize=(8.4, 3.6), sharex=True)
    states = [('baseline', 'Baseline', '#50575F'), ('heavyveh_very_high', 'Heavy vehicles (24%)', '#B33B49'), ('weather_heavy_rain', 'Heavy rain', '#137C85')]
    for state, label, color in states:
        for ax, metric in zip(axes, ['arrived', 'waiting', 'running']):
            matrix = np.array([[float(r[metric]) for r in rows if r['state'] == state and int(r['seed']) == seed] for seed in [11, 29, 47, 71, 101]])
            assert matrix.shape == (5, 24)
            mean, sd = (matrix.mean(axis=0), matrix.std(axis=0, ddof=1))
            x = np.arange(5, 121, 5)
            ax.plot(x, mean, color=color, lw=1.7, label=label)
            ax.fill_between(x, np.maximum(0, mean - sd), mean + sd, color=color, alpha=0.13, linewidth=0)
    for i, (ax, ylabel) in enumerate(zip(axes, ['Completed vehicles', 'Awaiting insertion (veh)', 'Inside network (veh)'])):
        ax.axvline(60, color='#777777', ls=':', lw=0.9)
        ax.set_xlim(0, 120)
        ax.set_ylim(bottom=0)
        ax.set_xticks([0, 30, 60, 90, 120])
        ax.set_xlabel('Simulation time (min)')
        ax.set_ylabel(ylabel)
        ax.text(0, 1.03, '(%s)' % chr(97 + i), transform=ax.transAxes, fontweight='bold')
        ax.tick_params(length=3)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.02), fontsize=10.5)
    fig.subplots_adjust(left=0.08, right=0.985, bottom=0.18, top=0.81, wspace=0.43)
    for ext in ['pdf', 'svg', 'png']:
        fig.savefig(FIG / ('Fig_revision_horizon.' + ext), dpi=600, facecolor='white')
    plt.close(fig)
if __name__ == '__main__':
    main()
