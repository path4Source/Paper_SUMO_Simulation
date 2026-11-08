def main():
    data = ROOT / 'frozen/data/sumo_multiseed_results.csv'
    effects_path = ROOT / 'frozen/data/sumo_multiseed_effects.csv'
    audit_path = ROOT / 'audit/historical_run_audit.csv'
    raw = read(data)
    previous_effects = read(effects_path)
    audit = {r['run']: r for r in read(audit_path)}
    if len(raw) != 81 or len(previous_effects) != 78:
        raise ValueError('Expected original 27 x 3 design')
    original = {}
    for r in raw:
        key = (r['scenario'], int(r['seed']))
        if key in original:
            raise ValueError('Repeated scenario-seed')
        name = r['scenario'] if key[1] == 42 else r['scenario_run']
        a = audit[name]
        if int(a['seed']) != key[1]:
            raise ValueError('Mismatched seed')
        for local, source in METRICS.values():
            if source is not None:
                if abs(float(a[local]) - float(r[source])) > 1e-07:
                    raise ValueError(f'Processed/raw disagreement: {name}/{source}')
        if int(a['unaccounted_inserted_end']) or int(a['ended_not_arrived']):
            raise ValueError('Unresolved population accounting')
        original[key] = (r, a)
    observed = {r['scenario'] for r in raw}
    if len(observed) != 27:
        raise ValueError('Missing scenario')
    for s in observed:
        if {seed for name, seed in original if name == s} != SEEDS:
            raise ValueError(f'Incomplete seed set: {s}')
    expected = {(r['scenario'], int(r['seed'])): r for r in previous_effects}
    groups = defaultdict(list)
    pairs = []
    for (scenario, seed), (r, a) in sorted(original.items()):
        if scenario == 'baseline':
            continue
        _, b = original['baseline', seed]
        qualified = warning(a) or warning(b)
        point = {'scenario': scenario, 'factor': r['factor'], 'seed': seed, 'warning_qualified_pair': qualified, 'scenario_teleport_events': int(a['teleport_events']), 'baseline_teleport_events': int(b['teleport_events'])}
        for response, (local, _) in METRICS.items():
            point[response + '_change_pct'] = percent(float(a[local]), float(b[local]))
        for response, old_name in [('throughput', 'throughput_change_pct'), ('completed_trip_time_loss', 'time_loss_change_pct'), ('mean_halted', 'halting_change_pct')]:
            if abs(point[response + '_change_pct'] - float(expected[scenario, seed][old_name])) > 1e-07:
                raise ValueError('Matched normalization disagrees with legacy effect')
        pairs.append(point)
        groups[scenario].append(point)
    estimates = []
    for scenario, points in sorted(groups.items()):
        for response in METRICS:
            result = summary((p[response + '_change_pct'] for p in points))
            estimates.append({'scenario': scenario, 'factor': points[0]['factor'], 'response': response, 'response_unit': 'percent relative to same-seed original baseline', **result, 'warning_qualified': any((p['warning_qualified_pair'] for p in points)), 'warning_qualified_pairs': sum((p['warning_qualified_pair'] for p in points)), 'ci_crosses_zero': result['ci95_low'] <= 0 <= result['ci95_high'], 'interval_scope': 'three-seed pointwise t interval, df=2; exploratory; not multiplicity adjusted'})
    OUT.mkdir(exist_ok=True)
    write_csv(OUT / 'paired_seed_responses.csv', pairs)
    write_csv(OUT / 'pointwise_intervals.csv', estimates)
