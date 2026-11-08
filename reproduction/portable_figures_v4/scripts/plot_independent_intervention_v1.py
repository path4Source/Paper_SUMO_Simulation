"""Measured paired intervention responses, with unsmoothed seed points and t intervals."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'independent_intervention_v1'

def main():
    summary = json.loads((OUT / 'analysis_summary.json').read_text(encoding='utf-8'))
    paired = list(csv.DictReader((OUT / 'paired_intervention_effects.csv').open(encoding='utf-8-sig', newline='')))
    rows = summary['conditions']
    labels = {'baseline': 'Baseline traffic', 'heavyveh_very_high': 'Heavy vehicles (24%)', 'weather_heavy_rain': 'Heavy rain'}
    palette = {'baseline': '#5C656B', 'heavyveh_very_high': '#28678A', 'weather_heavy_rain': '#A65732'}
    metrics = [('Q_pct', 'Throughput change (%)'), ('B_pct', 'Total vehicle-hour change (%)'), ('target_crossings_pct', 'Target-lane crossing change (%)'), ('target_queue_m_pct', 'Target-lane queue-extent change (%)')]
    plt.rcParams.update({'font.family': 'Arial', 'font.size': 9, 'axes.labelsize': 9, 'xtick.labelsize': 8, 'ytick.labelsize': 9, 'axes.linewidth': 0.7, 'svg.fonttype': 'none', 'savefig.facecolor': 'white'})
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.9), sharey=True)
    for index, (ax, (metric, label)) in enumerate(zip(axes.flat, metrics)):
        ax.axvline(0, linewidth=0.8, linestyle=(0, (3, 3)), color='#92989B', zorder=0)
        extents = [0]
        for y, row in enumerate(rows):
            estimate = row['response'][metric]
            color = palette[row['state']]
            seed_values = [float(r[metric]) for r in paired if r['state'] == row['state']]
            offsets = np.linspace(-0.13, 0.13, 5)
            ax.scatter(seed_values, y + offsets, s=12, color=color, alpha=0.55, linewidths=0, zorder=2)
            ax.errorbar(estimate['mean'], y, xerr=[[estimate['mean'] - estimate['low']], [estimate['high'] - estimate['mean']]], fmt='D', color=color, ecolor=color, markersize=5, markerfacecolor='white' if row['warning_qualified'] else color, markeredgewidth=1.0, elinewidth=1.1, capsize=3, zorder=3)
            extents.extend([estimate['low'], estimate['high'], *seed_values])
        ax.set_yticks(range(3))
        ax.set_yticklabels([labels[r['state']] for r in rows])
        ax.set_ylim(2.55, -0.55)
        low, high = (min(extents), max(extents))
        pad = max(0.5, (high - low) * 0.16)
        ax.set_xlim(low - pad, high + pad)
        ax.set_xlabel(label, labelpad=6)
        ax.spines[['top', 'right', 'left']].set_visible(False)
        ax.tick_params(axis='y', length=0, pad=6)
        ax.text(0.0, 1.06, 'abcd'[index], transform=ax.transAxes, fontweight='bold', fontsize=11)
        ax.set_axisbelow(True)
    handles = [Line2D([0], [0], marker='o', color='none', markerfacecolor='#747B80', markeredgewidth=0, markersize=4, label='Matched seed'), Line2D([0], [0], marker='D', color='#4A5054', markerfacecolor='white', markersize=5, linewidth=1, label='Mean and 95% t interval; open = warning-qualified')]
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, 0.015), frameon=False, ncol=2, fontsize=8, handletextpad=0.5, columnspacing=1.7)
    fig.subplots_adjust(left=0.21, right=0.98, top=0.94, bottom=0.18, wspace=0.25, hspace=0.58)
    plotdir = OUT / 'figures'
    plotdir.mkdir(exist_ok=True)
    fig.savefig(plotdir / 'paired_intervention.png', dpi=600)
    fig.savefig(plotdir / 'paired_intervention.svg')
    fig.savefig(ROOT / 'manuscript_working/figures/Fig_revision_intervention.png', dpi=600)
    plt.close(fig)
    print('Exported measured 4-panel intervention figure at 600 dpi and editable SVG.')
if __name__ == '__main__':
    main()
