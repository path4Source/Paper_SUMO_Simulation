"""Presentation-only restyling of existing figures; numerical artists are checked.

Plot construction is reused from the existing renderers. This script does not
run experiments, recalculate effects, change uncertainty intervals, or write
to the frozen data and analysis directories.
"""
import ast
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PathCollection
from matplotlib.patches import Rectangle
from matplotlib.text import Text
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / 'manuscript_working/figures'
AUDIT = ROOT / 'audit/figure_redesign_20261022'
sys.path.insert(0, str(ROOT / 'scripts'))
BLUE, TEAL, AMBER, INK = '#2D6FA4', '#277C78', '#BB7B2C', '#22313D'
reports = []
bounds = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name, relative=None):
    path = ROOT / (relative or f'scripts/{name}.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def figure_function(module, path, name, stop_assignment=None, stop_save=False, stop_loop=None):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    body = []
    for statement in function.body:
        if stop_loop and isinstance(statement, ast.For) and isinstance(statement.target, ast.Name) and statement.target.id == stop_loop:
            break
        if stop_assignment and isinstance(statement, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == stop_assignment for t in statement.targets):
            break
        if stop_save and isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            f = statement.value.func
            if isinstance(f, ast.Attribute) and f.attr == 'savefig':
                break
        body.append(statement)
    else:
        raise ValueError(f'No output boundary found in {name}')
    function.body = body + [ast.Return(value=ast.Name(id='fig', ctx=ast.Load()))]
    compiled = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = dict(vars(module))
    exec(compile(compiled, str(path), 'exec'), namespace)
    return namespace[name]()


def numerical_trace(fig):
    """Coordinates, bar extents and uncertainty-band paths, excluding layout."""
    trace = []
    for ax in fig.axes:
        lines = [{'x': np.asarray(a.get_xdata()).tolist(), 'y': np.asarray(a.get_ydata()).tolist()}
                 for a in ax.lines]
        patches = [[float(p.get_x()), float(p.get_y()), float(p.get_width()), float(p.get_height())]
                   for p in ax.patches if isinstance(p, Rectangle)]
        collections = []
        for c in ax.collections:
            row = {'offsets': np.asarray(c.get_offsets()).tolist()}
            if not isinstance(c, PathCollection):
                row['paths'] = [p.vertices.tolist() for p in c.get_paths()]
            collections.append(row)
        trace.append({'lines': lines, 'bars': patches, 'collections': collections})
    return json.dumps(trace, sort_keys=True, allow_nan=True)


def polish(fig, name):
    original = numerical_trace(fig)
    plt.rcParams.update({'font.family': 'Arial', 'font.size': 10.5,
                        'pdf.fonttype': 42, 'svg.fonttype': 'none'})
    for text in fig.findobj(Text):
        text.set_fontfamily('Arial')
        text.set_fontsize(10.5)
        if text.get_text() in ('a', 'b', 'c', 'd'):
            text.set_fontsize(12)
            text.set_fontweight('bold')
    for ax in fig.axes:
        ax.grid(False)
        ax.tick_params(axis='both', labelsize=10, width=.7)
        for side in ('top', 'right'):
            ax.spines[side].set_visible(False)
        for spine in ax.spines.values():
            spine.set_linewidth(.65)
            spine.set_color('#74838D')
        ax.xaxis.label.set_fontsize(10.5)
        ax.yaxis.label.set_fontsize(10.5)
        ax.xaxis.labelpad = 7
        for line in ax.lines:
            if name != 'Fig_revision_network_stage10':
                line.set_linewidth(max(1.05, line.get_linewidth()))

    horizontal = {'Fig_revision_scores': 4.2, 'Fig_revision_score_robustness': 3.8,
        'Fig_revision_multiseed_scores': 4.2, 'Fig_revision_oat_stage10': 6.6,
        'Fig_revision_three_seed_stage10': 6.6, 'Fig_revision_ten_seed_stage10': 3.8,
        'Fig23_weather_decomposition': 3.3, 'Fig_revision_interactions_stage10': 3.3}
    if name in horizontal:
        fig.set_size_inches(7.2, horizontal[name])
        fig.subplots_adjust(left=.37, right=.965, bottom=.19 if horizontal[name] < 4 else .14, top=.96)
        ax = fig.axes[0]
        ax.spines['left'].set_visible(False)
        ax.tick_params(axis='y', length=0)
        # add_axes in the legacy weather renderer is not affected by subplots_adjust.
        ax.set_position([.37, .19 if horizontal[name] < 4 else .14, .595,
                         .77 if horizontal[name] < 4 else .82])
        for label in ax.get_yticklabels():
            s = label.get_text()
            if len(s) > 32 and ', ' in s:
                label.set_text(s.replace(', ', ',\n', 1))
        ax.set_yticks(ax.get_yticks(), [a.get_text() for a in ax.get_yticklabels()])
        if name == 'Fig_revision_interactions_stage10':
            labels = [a.get_text().replace(' + ', ' +\n') for a in ax.get_yticklabels()]
            ax.set_yticks(ax.get_yticks(), labels)
            ax.set_xlabel('Throughput-loss interaction (percentage points)')
        if name == 'Fig23_weather_decomposition':
            ax.set_xlabel('Throughput change from matched baseline (%)')
            for i, p in enumerate(ax.patches):
                p.set_facecolor(TEAL if i == 4 else BLUE)
            for text in ax.texts:
                text.set_fontsize(10.5)
        if name == 'Fig_revision_score_robustness':
            ax.set_xlabel('Rank across six variants (lower = larger loss)')
        if name in ('Fig_revision_oat_stage10', 'Fig_revision_three_seed_stage10', 'Fig_revision_ten_seed_stage10'):
            ax.set_xlabel('Throughput change from matched baseline (%)')

    elif name == 'Fig_revision_network_stage10':
        fig.set_size_inches(7.2, 4.35)
        fig.subplots_adjust(left=.015, right=.985, top=.99, bottom=.19)
        for text in fig.axes[0].texts:
            if text.get_text() in ('n4', 'n1', 'n2'):
                text.set_text('Signal ' + text.get_text())
                text.set_fontweight('bold')
        for legend in fig.legends:
            for text in legend.get_texts():
                text.set_fontsize(9.5)

    elif name == 'Fig_revision_QD_response':
        fig.set_size_inches(7.2, 4.3)
        fig.subplots_adjust(left=.14, right=.97, top=.96, bottom=.17)
        ax = fig.axes[0]
        for text in ax.texts:
            text.set_fontsize(10)
        ax.legend(loc='upper left', frameon=False, fontsize=10)

    elif name == 'Fig_revision_cycle_audit':
        fig.set_size_inches(7.2, 5.1)
        fig.subplots_adjust(left=.15, right=.97, bottom=.13, top=.86, hspace=.25)
        for ax in fig.axes:
            ax.set_xticks(range(0, 61, 10))
        fig.axes[0].legend(loc='upper center', bbox_to_anchor=(.5, 1.29), ncol=3,
                           fontsize=10, frameon=False, handlelength=1.7, columnspacing=1.2)

    elif name == 'Fig_revision_intervention':
        fig.set_size_inches(7.2, 5.35)
        fig.subplots_adjust(left=.24, right=.97, top=.94, bottom=.25, wspace=.30, hspace=.68)
        names = ['Throughput change (%)', 'Total vehicle-hours change (%)',
                 'Target-lane crossings\nchange (%)', 'Target-lane queue extent\nchange (%)']
        for ax, label in zip(fig.axes, names):
            ax.set_xlabel(label, fontsize=10.5)
            ax.set_yticks(range(3), ['Baseline traffic', '24% heavy vehicles', 'Heavy rain'])
            from matplotlib.colors import to_rgba
            color_map = {'#28678A': AMBER, '#A65732': TEAL}
            for line in ax.lines:
                for old, new in color_map.items():
                    if np.allclose(to_rgba(line.get_color()), to_rgba(old)):
                        line.set_color(new)
                        line.set_markeredgecolor(new)
                        if line.get_markerfacecolor() != 'white':
                            line.set_markerfacecolor(new)
            for collection in ax.collections:
                for getter, setter in [(collection.get_facecolors, collection.set_facecolors),
                                       (collection.get_edgecolors, collection.set_edgecolors)]:
                    colors = getter().copy()
                    for index, rgba in enumerate(colors):
                        for old, new in color_map.items():
                            if np.allclose(rgba[:3], to_rgba(old)[:3]):
                                colors[index, :3] = to_rgba(new)[:3]
                    setter(colors)
        for legend in fig.legends:
            legend.remove()
        from matplotlib.lines import Line2D
        handles = [Line2D([0], [0], marker='o', color='none', markerfacecolor='#747B80',
                    markeredgewidth=0, markersize=4, label='Matched seed'),
                   Line2D([0], [0], marker='D', color='#4A5054', markerfacecolor='white',
                    markersize=5, linewidth=1, label='Mean and 95% t interval')]
        fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(.58, .055),
                   frameon=False, ncol=2, fontsize=9.5)
        fig.text(.58, .018, 'Open diamond: warning-qualified comparison', ha='center', fontsize=9.5)

    elif name == 'Fig08_baseline_edge_bottleneck':
        fig.set_size_inches(7.2, 4.3)
        fig.subplots_adjust(left=.12, right=.98, bottom=.25, top=.96)
        fig.axes[0].set_ylabel('Share of network cumulative waiting (%)')

    elif name == 'Fig_revision_horizon':
        fig.set_size_inches(7.2, 3.8)
        fig.subplots_adjust(left=.09, right=.985, bottom=.22, top=.80, wspace=.55)
        for ax in fig.axes:
            ax.set_xlabel('Simulation time\n(min)')
            ax.set_xticks([0, 60, 120])
        for legend in fig.legends:
            legend.set_bbox_to_anchor((.53, 1.0))
            for text in legend.get_texts():
                text.set_fontsize(9.5)

    updated = numerical_trace(fig)
    if updated != original:
        raise AssertionError(f'Numerical artists changed: {name}')
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for legend in fig.legends:
        legend_box = legend.get_window_extent(renderer)
        for ax in fig.axes:
            for label in (ax.xaxis.label, ax.yaxis.label):
                if label.get_visible() and label.get_text() and legend_box.overlaps(label.get_window_extent(renderer)):
                    raise AssertionError(f'Legend overlaps an axis label: {name}')
    for text in fig.findobj(Text):
        if not text.get_visible() or not text.get_text().strip():
            continue
        b = text.get_window_extent(renderer)
        # Tick labels outside the displayed range are clipped by the axes.
        if text in [t for ax in fig.axes for t in ax.get_xticklabels()+ax.get_yticklabels()]:
            continue
        if b.x0 < -2 or b.y0 < -2 or b.x1 > fig.bbox.width+2 or b.y1 > fig.bbox.height+2:
            bounds.append({'figure': name, 'text': text.get_text(), 'bbox': list(b.bounds)})
    for ext in ('pdf', 'svg', 'png'):
        fig.savefig(FIG / f'{name}.{ext}', dpi=450, facecolor='white')
    fig.savefig(AUDIT / f'{name}_preview.png', dpi=160, facecolor='white')
    trace_hash = hashlib.sha256(original.encode()).hexdigest()
    reports.append({'figure': name, 'data_artists_unchanged': True,
                    'numerical_trace_sha256': trace_hash, 'size_inches': list(fig.get_size_inches())})
    plt.close(fig)


def main():
    protected = {}
    for folder in ('frozen', 'score_revision_v1', 'independent_intervention_v1', 'core_detector_batch', 'horizon_audit_v1'):
        for p in (ROOT / folder).glob('**/*'):
            if p.is_file() and (p.suffix in ('.csv', '.json', '.py') or p.name == 'network.net.xml'):
                protected[str(p.relative_to(ROOT))] = sha(p)
    scores = load('plot_scores_stage8')
    scores.save = polish
    for f in (scores.scores, scores.robustness, scores.multiseed, scores.responses):
        f()
    legacy = load('plot_legacy_stage10')
    legacy.save = polish
    legacy.response('Fig_revision_oat_stage10', 'sumo_scenario_effects.csv', 'throughput_change_pct')
    legacy.response('Fig_revision_three_seed_stage10', 'sumo_multiseed_scenario_summary.csv', 'dq_mean', 'dq_std')
    legacy.response('Fig_revision_ten_seed_stage10', 'sumo_keyseed_scenario_summary.csv', 'dq_mean', 'dq_std')
    legacy.network()
    rows = legacy.read('sumo_factorial_interactions.csv')
    fig, ax = plt.subplots(figsize=(8, 3.6))
    for i, r in enumerate(rows):
        ax.errorbar(float(r['throughput_loss_interaction_mean']), i,
                    xerr=float(r['throughput_loss_interaction_std']), fmt='o', ms=5, capsize=3, color=BLUE)
    ax.set_yticks(range(len(rows)), [(r['first_label']+' + '+r['second_label']).replace(
        'Slow reaction', 'Long desired headway') for r in rows])
    ax.invert_yaxis()
    ax.axvline(0, color='#788084', lw=.7)
    ax.tick_params(axis='y', length=0)
    ax.spines['left'].set_visible(False)
    polish(fig, 'Fig_revision_interactions_stage10')

    cycle = load('plot_core_cycle_check')
    fig = figure_function(cycle, ROOT/'scripts/plot_core_cycle_check.py', 'main', stop_assignment='figures')
    polish(fig, 'Fig_revision_cycle_audit')
    intervention = load('plot_independent_intervention_v1')
    fig = figure_function(intervention, ROOT/'scripts/plot_independent_intervention_v1.py', 'main', stop_assignment='plotdir')
    polish(fig, 'Fig_revision_intervention')
    weather_path = ROOT/'scripts/legacy_weather.py'
    weather = load('legacy_weather', str(weather_path.relative_to(ROOT)))
    weather.WEATHER_DECOMPOSITION = ROOT/'frozen/data/weather_decomposition_summary.csv'
    fig = figure_function(weather, weather_path, 'build_weather_decomposition', stop_save=True)
    polish(fig, 'Fig23_weather_decomposition')
    bottleneck = load('plot_bottleneck_stage29', 'scripts/plot_bottleneck_stage29.py')
    fig, _ = bottleneck.draw(bottleneck.data_rows(ROOT/'frozen/data/baseline_edge_bottleneck.csv'))
    polish(fig, 'Fig08_baseline_edge_bottleneck')
    horizon = load('plot_horizon_v1')
    fig = figure_function(horizon, ROOT/'scripts/plot_horizon_v1.py', 'main', stop_loop='ext')
    polish(fig, 'Fig_revision_horizon')
    for name, digest in protected.items():
        if sha(ROOT/name) != digest:
            raise AssertionError(f'Protected file changed: {name}')
    result = {'figures': reports, 'protected_input_count': len(protected),
              'protected_inputs_unchanged': True, 'text_outside_canvas': bounds,
              'new_simulation_runs': 0}
    (AUDIT/'figure_data_preservation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
