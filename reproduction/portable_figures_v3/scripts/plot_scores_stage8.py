"""Publication figures regenerated from the emission-free audit outputs."""
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'score_revision_v1'
FIG = ROOT / 'manuscript_working/figures'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.labelsize': 10, 'xtick.labelsize': 9, 'ytick.labelsize': 10, 'pdf.fonttype': 42, 'svg.fonttype': 'none', 'axes.spines.top': False, 'axes.spines.right': False, 'axes.linewidth': 0.6, 'axes.edgecolor': '#687277', 'savefig.facecolor': 'white'})
TEAL, BLUE, GRAY, AMBER = ('#247C78', '#38628B', '#81898C', '#AD722B')

def read(name):
    with (DATA / name).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))

def save(fig, name):
    for ext in ['png', 'pdf', 'svg']:
        fig.savefig(FIG / (name + '.' + ext), dpi=600)
    plt.close(fig)

def clean(ax):
    ax.grid(False)
    ax.spines['left'].set_visible(False)
    ax.tick_params(axis='y', length=0)

def scores():
    rows = read('factor_scores.csv')
    fig, ax = plt.subplots(figsize=(8, 4.7))
    fig.subplots_adjust(left=0.29, right=0.94, bottom=0.16, top=0.97)
    values = [float(r['score']) for r in rows]
    ax.barh(range(len(rows)), values, color=[TEAL if i < 2 else BLUE if i < 5 else GRAY for i in range(len(rows))], height=0.6)
    for i, v in enumerate(values):
        ax.text(v + 0.016, i, f'{v:.3f}', va='center', fontsize=9)
    ax.set_yticks(range(len(rows)), [r['label'] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel('Service-loss score (Q, D, H)')
    clean(ax)
    save(fig, 'Fig_revision_scores')

def robustness():
    rows = read('range_summary.csv')[:8]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    fig.subplots_adjust(left=0.29, right=0.96, bottom=0.18, top=0.96)
    for i, r in enumerate(rows):
        mean, lo, hi = (float(r['mean']), float(r['best']), float(r['worst']))
        ax.errorbar(mean, i, xerr=[[mean - lo], [hi - mean]], fmt='o', color=TEAL if i < 2 else BLUE, markersize=5, capsize=4, lw=1.2)
    ax.set_yticks(range(len(rows)), [r['label'] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0.5, 13.5)
    ax.set_xticks(range(1, 14))
    ax.set_xlabel('Rank across six variants (lower = larger loss score)')
    clean(ax)
    save(fig, 'Fig_revision_score_robustness')

def multiseed():
    rows = read('multiseed_factor_scores.csv')
    fig, ax = plt.subplots(figsize=(8, 4.7))
    fig.subplots_adjust(left=0.29, right=0.95, bottom=0.16, top=0.97)
    for i, r in enumerate(rows):
        ax.errorbar(float(r['mean']), i, xerr=float(r['std']), fmt='o', color=TEAL if i < 2 else BLUE, markersize=5, capsize=3, lw=1)
    ax.set_yticks(range(len(rows)), [r['label'] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(-0.02, 1)
    ax.set_xlabel('Three-seed loss score: mean and sample SD')
    clean(ax)
    save(fig, 'Fig_revision_multiseed_scores')

def responses():
    rows = read('scenario_scores.csv')
    fig, ax = plt.subplots(figsize=(8, 4.7))
    fig.subplots_adjust(left=0.12, right=0.97, bottom=0.16, top=0.96)
    ax.axhline(0, color='#B2B7B8', lw=0.7, zorder=0)
    ax.axvline(0, color='#B2B7B8', lw=0.7, zorder=0)
    for demand, color, marker, label in [(False, BLUE, 'o', 'Non-demand perturbations'), (True, AMBER, 'D', 'Demand scaling')]:
        subset = [r for r in rows if (r['factor'] == 'demand_scale') == demand and r['scenario'] != 'reaction_fast']
        ax.scatter([float(r['dQ']) for r in subset], [float(r['dD']) for r in subset], c=color, marker=marker, s=35, edgecolors='white', linewidths=0.6, label=label)
    names = {'heavyveh_very_high': ('24% heavy vehicles', (-14, -22)), 'weather_heavy_rain': ('Heavy rain', (9, 10)), 'sigma_high': ('High stochasticity', (9, 6)), 'demand_peak': ('High demand', (-55, 7)), 'demand_low': ('Low demand', (-42, -16))}
    for r in rows:
        if r['scenario'] in names:
            label, offset = names[r['scenario']]
            ax.annotate(label, (float(r['dQ']), float(r['dD'])), xytext=offset, textcoords='offset points', fontsize=9)
    ax.set_xlim(-21, 7)
    ax.set_ylim(-24, 103)
    ax.set_xlabel('Route-completion throughput change (%)')
    ax.set_ylabel('Completed-trip time-loss change (%)')
    ax.legend(loc='upper left', frameon=False, fontsize=9)
    save(fig, 'Fig_revision_QD_response')

def framework():
    fig, ax = plt.subplots(figsize=(10, 5.4))
    fig.subplots_adjust(left=0.015, right=0.985, bottom=0.02, top=0.98)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 54)
    ax.axis('off')
    starts = [0, 34, 68]
    for x, title, color in zip(starts, ['1  Characterize', '2  Corroborate', '3  Test a response'], [BLUE, TEAL, BLUE]):
        ax.plot([x, x + 31], [49, 49], color=color, lw=2)
        ax.text(x, 51.5, title, weight='bold', color=color, fontsize=12, va='center')

    def box(x, y, w, h, txt, color=BLUE, fill='#FFFFFF', size=10):
        ax.add_patch(Rectangle((x, y), w, h, facecolor=fill, edgecolor=color, linewidth=0.8))
        ax.text(x + w / 2, y + h / 2, txt, ha='center', va='center', fontsize=size, linespacing=1.35, color='#202629')

    def arrow(x0, y0, x1, y1, color='#52656D'):
        ax.annotate('', (x1, y1), (x0, y0), arrowprops={'arrowstyle': '-|>', 'lw': 1, 'color': color, 'shrinkA': 2, 'shrinkB': 2})
    box(1, 36, 29, 10, 'Matched SUMO responses\nThroughput, time loss, halting')
    arrow(15.5, 36, 15.5, 32)
    ax.text(15.5, 30, 'What changed, and why?', ha='center', fontsize=10, weight='bold')
    for y, txt in [(22, 'Service deterioration'), (15, 'Demand variation'), (8, 'Simulator handling')]:
        box(2, y, 27, 5, txt, fill='#F3F6F7')
    ax.text(15.5, 3, 'Explanations may coexist', ha='center', fontsize=9, color='#52656D')
    arrow(30, 26, 34, 26)
    for y, txt in [(40, 'Paired seeds and uncertainty'), (31, 'Demand and vehicle accounting'), (22, 'Warnings in both comparison arms'), (13, 'Lane-end counts and local queues')]:
        box(35, y, 29, 6, txt, color=TEAL, fill='#F3F8F7', size=9.5)
    ax.text(49.5, 5, 'Supported, qualified, or unresolved\nNo unique cause inferred from a score', ha='center', va='center', fontsize=9, linespacing=1.4)
    arrow(64, 26, 68, 26)
    box(69, 36, 29, 10, 'Retain the adverse condition\nChange a different control lever')
    arrow(83.5, 36, 83.5, 32)
    box(69, 22, 29, 10, 'Matched-seed intervention\nNetwork burden + target/donor lanes', size=9.5)
    arrow(83.5, 22, 83.5, 18)
    box(69, 8, 29, 10, 'Joint recovery supported?\nCheck intervals, demand, warnings', color=TEAL, fill='#F3F8F7', size=9.5)
    ax.text(83.5, 3, 'Failure does not refute the diagnosis', ha='center', fontsize=9, color='#52656D')
    save(fig, 'Fig_revision_framework')
if __name__ == '__main__':
    scores()
    robustness()
    multiseed()
    responses()
    framework()
