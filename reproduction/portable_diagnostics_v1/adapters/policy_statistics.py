import json
import math
import statistics
from pathlib import Path
from audit_core_warnings import read_csv
from audit_metrics import write_csv
from freeze_submission import sha256

def change(value, baseline):
    return 100 * (float(value) / float(baseline) - 1)

def estimate(values):
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    half = 4.302652729911275 * sd / math.sqrt(3)
    return {'n_seeds': 3, 'mean': mean, 'sample_sd': sd, 'ci95_lower_exploratory': mean - half, 'ci95_upper_exploratory': mean + half}

def main():
    old_rows = read_csv(OUT / 'core_run_results_corrected.csv')
    new_rows = read_csv(POLICY / 'run_results.csv')
    assert len(old_rows) == 9 and len(new_rows) == 12
    old = {(r['scenario'], int(r['seed'])): r for r in old_rows}
    new = {(r['scenario'], int(r['seed'])): r for r in new_rows if r['policy_s'] == '-1'}
    checks = []
    for row in new_rows:
        directory = Path(row['source_dir'])
        record = json.loads((directory / 'complete.json').read_text())
        for name, digest in record['files_sha256'].items():
            if sha256(directory / name) != digest:
                raise RuntimeError(f'Completed output changed: {directory / name}')
        checks.append({'run': row['run'], 'sha256_verified': True, 'loaded_equals_inserted_plus_waiting': int(row['end_loaded']) == int(row['end_inserted']) + int(row['end_waiting']), 'inserted_accounted': float(row['unaccounted_inserted_end']) == 0, 'control_status': row['measurement_control']})
    assert all((r['loaded_equals_inserted_plus_waiting'] and r['inserted_accounted'] for r in checks))
    for seed in (42, 2024, 2025):
        for key in ('end_arrived', 'end_inserted', 'end_waiting', 'end_running', 'total_vehicle_hours_discrete'):
            assert old['baseline', seed][key] == new['baseline', seed][key]
    paired, summaries = ([], [])
    metrics = {'throughput': 'end_arrived', 'completed_delay': 'trip_completed_timeLoss_mean_s', 'total_vehicle_hours': 'total_vehicle_hours_discrete', 'entry_vehicle_hours': 'entry_vehicle_hours_discrete'}
    for scenario in ('heavyveh_very_high', 'weather_heavy_rain'):
        for seed in (42, 2024, 2025):
            a, b = (old[scenario, seed], new[scenario, seed])
            row = {'scenario': scenario, 'seed': seed, 'Q_policy300': a['end_arrived'], 'Q_no_gridlock_teleport': b['end_arrived'], 'TP_policy300': a['teleport_events'], 'TP_no_gridlock_teleport': b['teleport_events'], 'collisions_policy300': a['stat_safety_collisions'], 'collisions_no_gridlock_teleport': b['stat_safety_collisions'], 'affected_unique_policy300': a['teleported_unique_vehicles'], 'affected_unique_no_gridlock_teleport': b['teleported_unique_vehicles']}
            for metric, key in metrics.items():
                row[metric + '_effect_policy300_pct'] = change(a[key], old['baseline', seed][key])
                row[metric + '_effect_no_gridlock_pct'] = change(b[key], new['baseline', seed][key])
                row[metric + '_policy_shift_pp'] = row[metric + '_effect_no_gridlock_pct'] - row[metric + '_effect_policy300_pct']
            for population in ('inserted', 'waiting', 'running'):
                row[population + '_policy300'] = a['end_' + population]
                row[population + '_no_gridlock'] = b['end_' + population]
            paired.append(row)
        group = [r for r in paired if r['scenario'] == scenario]
        for metric in metrics:
            for outcome in ('effect_policy300_pct', 'effect_no_gridlock_pct', 'policy_shift_pp'):
                key = metric + '_' + outcome
                summaries.append({'scenario': scenario, 'metric': metric, 'outcome': outcome, **estimate([r[key] for r in group]), 'interval_scope': 'paired-seed Student t with df=2; exploratory conditional interval, not equivalence or field validation'})
    write_csv(OUT / 'policy_integrity_checks.csv', checks)
    write_csv(OUT / 'policy_paired_effects.csv', paired)
    write_csv(OUT / 'policy_summary.csv', summaries)
