def main():
    settings = read_csv(ROOT / 'stage3_settings/settings_results.csv')
    core = read_csv(ROOT / 'core_detector_batch/run_results.csv')
    assert len(settings) == 15 and len(core) == 9
    raw_manifest = {r['path']: r['sha256'] for r in read_csv(ROOT / 'audit/raw_output_manifest.csv')}
    core_protocol = json.loads((ROOT / 'audit/core_detector_batch_protocol.json').read_text())
    for scenario in ('heavyveh_very_high', 'weather_heavy_rain'):
        source = core_protocol['routes'][scenario]
        assert source['sha256'] == raw_manifest[source['source']], 'Adverse route changed since historical freeze'
    integrity = []
    for row in settings + core:
        directory = Path(row['source_dir'])
        record = json.loads((directory / 'complete.json').read_text())
        for name, digest in record['files_sha256'].items():
            assert sha256(directory / name) == digest, f'Changed evidence {directory / name}'
        assert int(row['end_loaded']) == int(row['end_inserted']) + int(row['end_waiting']) == 7900
        assert int(row['end_inserted']) == int(row['end_arrived']) + int(row['end_running'])
        assert int(row['trip_records']) == 7900
        integrity.append({'run': row['run'], 'output_hashes_passed': True, 'vehicle_accounting_passed': True})
    write_csv(ROOT / 'stage3_settings/integrity_checks.csv', integrity)
    matched, summary = ([], [])
    for step in (0.5, 0.1):
        chosen = [r for r in settings if float(r['step_s']) == step and float(r['action_step_s']) == step and (r['junction_check'] == 'False')]
        lookup = {(int(r['seed']), float(r['tau_s'])): r for r in chosen}
        for seed in (42, 2024, 2025):
            b, t = (lookup[seed, 1.0], lookup[seed, 0.8])
            pair = {'step_s': step, 'action_step_s': step, 'seed': seed, 'baseline_Q': b['end_arrived'], 'short_headway_Q': t['end_arrived'], 'baseline_TP': b['teleport_events'], 'short_headway_TP': t['teleport_events']}
            for name, key in (('Q', 'end_arrived'), ('completed_delay', 'trip_completed_timeLoss_mean_s'), ('total_vehicle_hours', 'total_vehicle_hours_discrete')):
                pair[name + '_change_pct'] = 100 * (float(t[key]) - float(b[key])) / float(b[key])
            matched.append(pair)
        for metric in ('Q_change_pct', 'completed_delay_change_pct', 'total_vehicle_hours_change_pct'):
            values = [r[metric] for r in matched if r['step_s'] == step]
            mean, lo, hi = interval(values)
            summary.append({'step_s': step, 'action_s': step, 'metric': metric, 'mean': mean, 'ci95_lower_exploratory': lo, 'ci95_upper_exploratory': hi, 'n_matched_seeds': 3, 'scope': 'conditional exploratory paired t interval, not numerical convergence'})
    write_csv(ROOT / 'stage3_settings/paired_effects.csv', matched)
    write_csv(ROOT / 'stage3_settings/paired_summary.csv', summary)
