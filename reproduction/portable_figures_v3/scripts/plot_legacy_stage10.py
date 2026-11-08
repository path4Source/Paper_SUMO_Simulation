"""Regenerate legacy figures from frozen numerical tables, without changing data."""
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from stopline_instrumentation import lane_inventory
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'frozen/data'
FIG = ROOT / 'manuscript_working/figures'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.labelsize': 10, 'xtick.labelsize': 9, 'ytick.labelsize': 10, 'pdf.fonttype': 42, 'svg.fonttype': 'none', 'axes.spines.top': False, 'axes.spines.right': False, 'savefig.facecolor': 'white'})

def read(name):
    with (DATA / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def label(row):
    s = row['scenario_label']
    for old, new in [('Reaction time', 'Desired headway'), ('reaction time', 'desired headway'), ('Driver randomness', 'Behavioral stochasticity'), ('Weather condition', 'Weather')]:
        s = s.replace(old, new)
    return s

def save(fig, name):
    for ext in ('pdf', 'png', 'svg'):
        fig.savefig(FIG / (name + '.' + ext), dpi=600)
    plt.close(fig)

def response(name, source, value, error=None):
    rows = [r for r in read(source) if r['scenario'] != 'reaction_fast']
    rows.sort(key=lambda r: float(r[value]))
    fig, ax = plt.subplots(figsize=(8, max(3.6, 0.235 * len(rows) + 0.9)))
    fig.subplots_adjust(left=0.43, right=0.97, bottom=0.16 if len(rows) < 10 else 0.1, top=0.97)
    for i, r in enumerate(rows):
        color = '#AD722B' if r['factor'] == 'demand_scale' else '#38628B'
        if error:
            ax.errorbar(float(r[value]), i, xerr=float(r[error]), fmt='o', color=color, capsize=3, ms=4.5)
        else:
            ax.barh(i, float(r[value]), color=color, height=0.65)
    ax.axvline(0, color='#788084', lw=0.7)
    ax.set_yticks(range(len(rows)), [label(r) for r in rows])
    ax.invert_yaxis()
    ax.set_xlabel('Throughput response relative to matched baseline (%)')
    ax.tick_params(axis='y', length=0)
    ax.spines['left'].set_visible(False)
    ax.grid(False)
    save(fig, name)
    return {'figure': name, 'source': source, 'rows': len(rows), 'value': value, 'sample_sd': error, 'excluded_from_plot_only': 'reaction_fast'}

def network():
    path = ROOT / 'frozen/inputs/network.net.xml'
    root = ET.parse(path).getroot()
    inventory = lane_inventory(path)
    assert len(inventory) == 53
    fig, ax = plt.subplots(figsize=(8, 4.7))
    fig.subplots_adjust(left=0.025, right=0.98, top=0.98, bottom=0.17)
    shapes = {}
    for edge in root.findall('edge'):
        if edge.get('id').startswith(':'):
            continue
        for lane in edge.findall('lane'):
            coords = [(float(v.split(',')[1]), 500 - float(v.split(',')[0])) for v in lane.get('shape').split()]
            shapes[lane.get('id')] = coords
            ax.plot([v[0] for v in coords], [v[1] for v in coords], color='#B5BDC1', lw=0.6, zorder=1)
    placements = {'ED2': (1480, -120), 'ED1.177': (835, 155), 'Eh3': (1400, 315), 'Ed1.209': (1020, -175), 'ED2.378': (1375, 140)}
    for row in read('baseline_edge_bottleneck.csv')[:5]:
        coords = shapes[row['edge'] + '_0']
        ax.plot([v[0] for v in coords], [v[1] for v in coords], color='#C38435', lw=3, zorder=2)
        anchor = ((coords[0][0] + coords[-1][0]) / 2, (coords[0][1] + coords[-1][1]) / 2)
        ax.annotate(row['edge'] + '  {:.1f}%'.format(100 * float(row['waiting_share'])), xy=anchor, xytext=placements[row['edge']], ha='center', va='center', fontsize=10, arrowprops={'arrowstyle': '-', 'color': '#687277', 'lw': 0.7}, bbox={'facecolor': 'white', 'edgecolor': 'none', 'pad': 1})
    for row in inventory:
        x, y = shapes[row['lane']][-1]
        ax.scatter([x], [y], marker='s', s=7, color='#247C78', zorder=4)
    for node in root.findall('junction'):
        if node.get('type') != 'traffic_light':
            continue
        x, y = (float(node.get('y')), 500 - float(node.get('x')))
        ax.scatter([x], [y], s=50, facecolor='white', edgecolor='#263A43', zorder=5)
        ax.annotate(node.get('id'), (x, y), xytext=(0, -20), textcoords='offset points', ha='center', fontsize=10)
    ax.plot([100, 300], [-360, -360], color='#263A43', lw=1.2)
    ax.plot([100, 100], [-368, -352], color='#263A43', lw=1.2)
    ax.plot([300, 300], [-368, -352], color='#263A43', lw=1.2)
    ax.text(200, -335, '200 m', ha='center', fontsize=10)
    ax.set_aspect('equal')
    ax.set_xlim(-30, 1730)
    ax.set_ylim(-420, 540)
    ax.axis('off')
    fig.legend(handles=[Line2D([0], [0], color='#B5BDC1', lw=1, label='SUMO lane geometry'), Line2D([0], [0], color='#C38435', lw=3, label='Top-five baseline waiting edges'), Line2D([0], [0], color='#247C78', marker='s', ls='', ms=4, label='Lane-end detectors (53 lanes)'), Line2D([0], [0], color='#263A43', marker='o', markerfacecolor='white', ls='', label='Traffic signal')], loc='lower center', bbox_to_anchor=(0.5, 0.01), frameon=False, ncol=2, fontsize=9)
    save(fig, 'Fig_revision_network_stage10')
    return {'figure': 'Fig_revision_network_stage10', 'source': 'frozen SUMO lane geometry and baseline waiting shares', 'detector_lane_count': 53, 'geometry_transform': 'x_display=y_model; y_display=500-x_model'}

def main():
    manifest = [response('Fig_revision_oat_stage10', 'sumo_scenario_effects.csv', 'throughput_change_pct'), response('Fig_revision_three_seed_stage10', 'sumo_multiseed_scenario_summary.csv', 'dq_mean', 'dq_std'), response('Fig_revision_ten_seed_stage10', 'sumo_keyseed_scenario_summary.csv', 'dq_mean', 'dq_std')]
    rows = read('sumo_factorial_interactions.csv')
    fig, ax = plt.subplots(figsize=(8, 3.6))
    fig.subplots_adjust(left=0.49, right=0.97, bottom=0.22, top=0.96)
    labels = []
    for i, r in enumerate(rows):
        labels.append((r['first_label'] + ' + ' + r['second_label']).replace('Slow reaction', 'Long desired headway'))
        ax.errorbar(float(r['throughput_loss_interaction_mean']), i, xerr=float(r['throughput_loss_interaction_std']), fmt='o', ms=5, capsize=3, color='#38628B')
    ax.set_yticks(range(len(rows)), labels)
    ax.invert_yaxis()
    ax.axvline(0, color='#788084', lw=0.7)
    ax.set_xlabel('Interaction in throughput loss (percentage points)')
    ax.tick_params(axis='y', length=0)
    ax.spines['left'].set_visible(False)
    ax.grid(False)
    save(fig, 'Fig_revision_interactions_stage10')
    manifest.append({'figure': 'Fig_revision_interactions_stage10', 'source': 'sumo_factorial_interactions.csv', 'rows': len(rows), 'error_bars': 'sample SD, n=3'})
    manifest.append(network())
    (ROOT / 'audit/stage10_figure_provenance.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))
if __name__ == '__main__':
    main()
