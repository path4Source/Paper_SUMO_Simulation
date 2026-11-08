def main():
    audit_path = ROOT / 'audit/historical_run_audit.csv'
    audit = {r['run']: r for r in read(audit_path)}
    paths = {name: ROOT / 'frozen/data' / filename for name, filename in [('original_OAT', 'sumo_multiseed_results.csv'), ('key_ten_seed', 'sumo_keyseed_results.csv')]}
    cache, records, source_hashes, corrections = ({}, [], [], [])
    for series, path in paths.items():
        for source in read(path):
            seed, scenario = (int(source['seed']), source['scenario'])
            name = scenario if seed == 42 else source['scenario_run']
            original = audit[name]
            if name not in cache:
                log = Path(original['source_dir']) / 'sumo_stderr.log'
                parsed = warning_metrics(log)
                if not parsed['warning_log_present']:
                    raise RuntimeError(f'Missing warning log is not a zero: {name}')
                for key in ['teleport_events', 'teleported_unique_vehicles']:
                    if parsed[key] != int(original[key]):
                        raise RuntimeError(f'Archived/log discrepancy: {name}/{key}')
                correction = reconcile_collision_subtypes(original, parsed, log.read_text(encoding='utf-8', errors='strict'))
                if correction:
                    corrections.append(correction)
                if sum(json.loads(parsed['teleport_causes_json']).values()) != parsed['teleport_events']:
                    raise RuntimeError('Unreconciled cause counts')
                cache[name] = parsed
                source_hashes.append({'run': name, 'warning_log_sha256': sha256(log)})
            record = {'series': series, 'scenario': scenario, 'seed': seed, 'run': name, 'end_inserted': int(original['end_inserted']), 'end_arrived': int(original['end_arrived']), **cache[name]}
            record['unique_rate_pct_inserted'] = exposure_stats([record])['unique_rate_mean_pct']
            if record['end_arrived'] != int(float(source['arrived_vehicles'])):
                raise RuntimeError('Run scope does not match original results')
            records.append(record)
    counts = {series: sum((r['series'] == series for r in records)) for series in paths}
    if counts != {'original_OAT': 81, 'key_ten_seed': 90} or len(cache) != 144:
        raise RuntimeError('Unexpected original/reused run accounting')
    groups = defaultdict(list)
    for record in records:
        groups[record['series'], record['scenario']].append(record)
    summaries = []
    for (series, scenario), group in sorted(groups.items()):
        expected_n = 3 if series == 'original_OAT' else 10
        if len(group) != expected_n or len({r['seed'] for r in group}) != expected_n:
            raise RuntimeError('Duplicate/missing seed')
        summaries.append({'series': series, 'scenario': scenario, **exposure_stats(group)})
    OUT.mkdir(exist_ok=True)
    write_csv(OUT / 'run_exposure.csv', records)
    write_csv(OUT / 'scenario_exposure.csv', summaries)
    if corrections:
        write_csv(OUT / 'historical_cause_corrections.csv', corrections)
