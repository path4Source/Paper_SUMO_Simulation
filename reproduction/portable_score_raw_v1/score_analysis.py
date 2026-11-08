"""Reanalyse archived responses without emissions; never modify simulation outputs."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'generated' / 'scores'
SOURCE = ROOT / 'inputs' / 'scores'
WEIGHTS = np.array([9.0, 5.0, 3.0]) / 17.0
METRICS = ['throughput_veh_per_h', 'mean_time_loss', 'mean_halting']
LABELS = {'heavy_vehicle_share': 'Heavy vehicles', 'weather': 'Weather', 'driver_sigma': 'Behavioral stochasticity', 'reaction_time': 'Desired time headway', 'signal_lost_time': 'Signal lost time', 'signal_green': 'Green duration', 'acceleration': 'Acceleration', 'max_speed': 'Maximum speed', 'min_gap': 'Minimum gap', 'deceleration': 'Deceleration', 'signal_offset': 'Signal offset', 'lane_control': 'Lane control', 'bottleneck_speed': 'Bottleneck speed', 'demand_scale': 'Demand stress'}

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))

def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def components(raw, include_emission=False):
    metrics = METRICS + (['co2_per_vehicle_kg'] if include_emission else [])
    baselines = {int(r.get('seed', 42)): r for r in raw if r['scenario'] == 'baseline'}
    rows = [r for r in raw if r['scenario'] != 'baseline']
    response = np.array([[(float(r[m]) / float(baselines[int(r.get('seed', 42))][m]) - 1) * 100 for m in metrics] for r in rows])
    direction = np.array([-1] + [1] * (len(metrics) - 1))
    loss_raw, gain_raw = (np.maximum(response * direction, 0), np.maximum(-response * direction, 0))
    loss_max, gain_max = (loss_raw.max(axis=0), gain_raw.max(axis=0))
    loss = np.divide(loss_raw, loss_max, out=np.zeros_like(loss_raw), where=loss_max > 0)
    gain = np.divide(gain_raw, gain_max, out=np.zeros_like(gain_raw), where=gain_max > 0)
    return (rows, response, loss, gain, loss_max, gain_max)

def ranks(values):
    values = np.asarray(values)
    return np.array([1 + np.sum(values > v + 1e-12) + (np.sum(np.isclose(values, v, atol=1e-12, rtol=0)) - 1) / 2 for v in values])

def main():
    OUT.mkdir(exist_ok=True)
    inputs = {name: sha(SOURCE / name) for name in ['sumo_oat_results.csv', 'sumo_multiseed_results.csv', 'sumo_scenario_effects.csv']}
    raw = read_csv(SOURCE / 'sumo_oat_results.csv')
    multi = read_csv(SOURCE / 'sumo_multiseed_results.csv')
    assert len(raw) == 27 and len(multi) == 81
    rows, response, loss, gain, lm, gm = components(raw)
    score, ipi = (loss @ WEIGHTS, gain @ WEIGHTS)
    old_rows, _, old_l, old_g, _, _ = components(raw, True)
    old_score = old_l @ np.array([0.45, 0.25, 0.15, 0.15])
    archived = {r['scenario']: r for r in read_csv(SOURCE / 'sumo_scenario_effects.csv')}
    assert max((abs(old_score[i] - float(archived[r['scenario']]['cldi'])) for i, r in enumerate(rows))) < 1e-10
    assert max((abs((old_g @ [0.45, 0.25, 0.15, 0.15])[i] - float(archived[r['scenario']]['ipi'])) for i, r in enumerate(rows))) < 1e-10
    results = []
    for i, r in enumerate(rows):
        results.append({'scenario': r['scenario'], 'factor': r['factor'], 'level': r['level'], 'Q': float(r[METRICS[0]]), 'D': float(r[METRICS[1]]), 'H': float(r[METRICS[2]]), 'dQ': response[i, 0], 'dD': response[i, 1], 'dH': response[i, 2], 'score_QDH_raw': score[i], 'ipi_QDH_raw': ipi[i], 'score_QDHE_archived': old_score[i], 'score_role': 'not_used_demand_stress' if r['factor'] == 'demand_scale' else 'descriptive_loss', 'improvement_role': 'audit_only_not_operational_recommendation'})
    write_csv(OUT / 'scenario_scores.csv', results)
    factors = sorted(set((r['factor'] for r in rows)) - {'demand_scale'})
    idx = {f: np.array([i for i, r in enumerate(rows) if r['factor'] == f]) for f in factors}
    fscore = np.array([score[idx[f]].max() for f in factors])
    fold = np.array([old_score[idx[f]].max() for f in factors])
    factor_rows = [{'factor': f, 'label': LABELS[f], 'score': fscore[i], 'raw_ipi': ipi[idx[f]].max(), 'old_score': fold[i], 'rank': ranks(fscore)[i], 'old_rank': ranks(fold)[i]} for i, f in enumerate(factors)]
    factor_rows.sort(key=lambda r: (r['rank'], r['factor']))
    write_csv(OUT / 'factor_scores.csv', factor_rows)
    rng = np.random.default_rng(20261020)
    sampled = rng.dirichlet(np.ones(3), 5000)
    fsamples = np.column_stack([(loss[idx[f]] @ sampled.T).max(axis=0) for f in factors])
    sample_ranks = np.array([ranks(row) for row in fsamples])
    weight_rows = [{'factor': f, 'label': LABELS[f], 'first_frequency': float(np.mean(sample_ranks[:, i] == 1)), 'top3_frequency': float(np.mean(sample_ranks[:, i] <= 3)), 'top5_frequency': float(np.mean(sample_ranks[:, i] <= 5))} for i, f in enumerate(factors)]
    write_csv(OUT / 'weight_frequencies.csv', weight_rows)
    write_csv(OUT / 'weight_samples.csv', [{'sample': i + 1, 'wQ': x[0], 'wD': x[1], 'wH': x[2]} for i, x in enumerate(sampled)])
    variants = {'Max': fscore, 'Mean': np.array([score[idx[f]].mean() for f in factors]), 'Remove peak': np.array([np.sort(score[idx[f]])[-2] if len(idx[f]) > 1 else score[idx[f]][0] for f in factors])}
    for j, label in enumerate(['Without Q', 'Without D', 'Without H']):
        weights = WEIGHTS.copy()
        weights[j] = 0
        weights /= weights.sum()
        reduced = loss @ weights
        variants[label] = np.array([reduced[idx[f]].max() for f in factors])
    rr = []
    for name, values in variants.items():
        for f, value, rank in zip(factors, values, ranks(values)):
            rr.append({'variant': name, 'factor': f, 'score': value, 'rank': rank})
    write_csv(OUT / 'range_rankings.csv', rr)
    range_summary = []
    for f in factors:
        values = np.array([r['rank'] for r in rr if r['factor'] == f])
        range_summary.append({'factor': f, 'label': LABELS[f], 'best': values.min(), 'worst': values.max(), 'mean': values.mean(), 'top3_frequency': float(np.mean(values <= 3)), 'top5_frequency': float(np.mean(values <= 5))})
    range_summary.sort(key=lambda r: r['mean'])
    write_csv(OUT / 'range_summary.csv', range_summary)
    mr, _, ml, mg, mlm, mgm = components(multi)
    mscore, mipi = (ml @ WEIGHTS, mg @ WEIGHTS)
    mresults = [{'seed': int(r['seed']), 'scenario': r['scenario'], 'factor': r['factor'], 'score': mscore[i], 'raw_ipi': mipi[i]} for i, r in enumerate(mr)]
    write_csv(OUT / 'multiseed_scores.csv', mresults)
    ms = []
    for f in factors:
        maxima = [max((r['score'] for r in mresults if r['factor'] == f and r['seed'] == seed)) for seed in [42, 2024, 2025]]
        ms.append({'factor': f, 'label': LABELS[f], 'mean': float(np.mean(maxima)), 'std': float(np.std(maxima, ddof=1)), 'n': 3})
    ms.sort(key=lambda r: -r['mean'])
    write_csv(OUT / 'multiseed_factor_scores.csv', ms)
    manifest = {'source_sha256': inputs, 'new_sumo_runs': 0, 'weights_QDH': WEIGHTS.tolist(), 'normalization': 'All 26 non-baseline responses for seed 42; pooled 78 seed-matched responses for the three-seed check. Fixed within each analysis, including range variants.', 'loss_denominators_pct': lm.tolist(), 'gain_denominators_pct': gm.tolist(), 'multiseed_loss_denominators_pct': mlm.tolist(), 'multiseed_gain_denominators_pct': mgm.tolist(), 'demand': 'Retained in normalization for audit continuity, excluded from factor ranking and score interpretation.', 'screening': 'All IPI values are raw descriptive audit values; no composite score grants operational improvement status.', 'random_seed': 20261020, 'weight_samples': 5000, 'range_variants': list(variants), 'tie_policy': 'average rank; same fixed component denominators in all six variants', 'legacy_four_component_reproduction': 'passed at absolute tolerance 1e-10', 'leading_five': [r['factor'] for r in factor_rows[:5]], 'multiseed_leading_five': [r['factor'] for r in ms[:5]], 'changed_ranks': [r for r in factor_rows if r['rank'] != r['old_rank']]}
    (OUT / 'analysis_summary.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    assert all((sha(SOURCE / name) == digest for name, digest in inputs.items()))
    print(json.dumps({'factor_scores': factor_rows[:5], 'weight_frequencies': [r for r in weight_rows if r['top3_frequency'] > 0], 'range': range_summary[:5], 'multiseed': ms[:5], 'changed_ranks': manifest['changed_ranks']}, indent=2))
if __name__ == '__main__':
    main()
