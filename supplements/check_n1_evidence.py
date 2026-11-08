"""Recalculate the five-seed panel directly from its unchanged ZIP archive."""
import argparse
from collections import Counter
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path, PureWindowsPath
import re
import xml.etree.ElementTree as ET
import zipfile


def digest(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(block)
    return h.hexdigest()


def close(a, b):
    assert abs(float(a) - float(b)) < 1e-7, (a, b)


def run(archive, output):
    output.mkdir(parents=True, exist_ok=True)
    with archive.open('rb') as f:
        archive_hash = digest(f)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read('MANIFEST_SHA256.json'))
        assert len(set(z.namelist())) == len(z.namelist())
        for name, entry in manifest.items():
            assert z.getinfo(name).file_size == entry['bytes'], name
            with z.open(name) as f:
                assert digest(f) == entry['sha256'], name
        print(f'Archive integrity: {len(manifest)} members checked', flush=True)
        protocol = json.loads(z.read('report/protocol.json'))
        records = list(csv.DictReader(io.StringIO(z.read('report/all_45_population_records.csv').decode('utf-8-sig'))))
        pairs = list(csv.DictReader(io.StringIO(z.read('report/all_30_model_switch_pairs.csv').decode('utf-8-sig'))))
        index = {(r['case'], int(r['seed']), r['arm']): r for r in records}
        assert len(index) == len(records) == len(protocol['run_inventory']) == 45
        assert Counter(r['new'] for r in protocol['run_inventory']) == {True: 18, False: 27}
        measured, times = {}, []
        for r in protocol['run_inventory']:
            key = r['case'], r['seed'], r['arm']
            prefix = 'runs/' + r['arm'] + '/' + PureWindowsPath(r['path']).name + '/'
            with z.open(prefix + 'summary.xml') as f:
                head = f.read(30000).decode('utf-8')
            header = re.search(r'<sumoConfiguration\b.*?</sumoConfiguration>', head, re.S)
            assert header is not None
            config = {n.tag: n.get('value') for n in ET.fromstring(header.group()).iter() if 'value' in n.attrib}
            assert Decimal(config.get('begin', '0')) == 0
            assert Decimal(config['end']) == 3600
            assert Decimal(config['step-length']) == Decimal('0.1')
            assert Decimal(config['default.action-step-length']) == Decimal('0.1')
            assert int(config['seed']) == r['seed']
            network, entry, samples = 0, 0, 0
            last = None
            with z.open(prefix + 'summary.xml') as f:
                for _, node in ET.iterparse(f, events=('end',)):
                    if node.tag != 'step':
                        continue
                    # Integer decisecond indices avoid floating-point endpoint drift.
                    tick = Decimal(node.attrib['time']) * 10
                    assert tick == samples, (key, tick, samples)
                    assert 0 <= tick < 36000
                    network += int(node.attrib['running'])
                    entry += int(node.attrib['waiting'])
                    samples += 1
                    last = dict(node.attrib)
                    node.clear()
            assert samples == 36000
            saved = index[key]
            B = (network + entry) / 36000
            close(B, saved['total_vh'])
            close(network / 36000, saved['network_vh'])
            close(entry / 36000, saved['entry_vh'])
            for field, raw in [('planned', 'loaded'), ('inserted', 'inserted'), ('arrived', 'arrived'), ('running', 'running'), ('waiting', 'waiting')]:
                assert int(last[raw]) == int(saved[field])
            assert int(last['loaded']) == int(last['arrived']) + int(last['running']) + int(last['waiting']) == 7900
            collisions = ET.fromstring(z.read(prefix + 'collisions.xml')).findall('collision')
            teleports = [line for line in z.read(prefix + 'sumo_stderr.log').decode('utf-8').splitlines() if "Teleporting vehicle '" in line]
            wrong_lane = sum('(wrong lane)' in line for line in teleports)
            causes = Counter('wrongLane' if '(wrong lane)' in line else 'yield' if '(yield)' in line else 'jam' if '(jam)' in line else 'collision' if 'collision' in line else 'other' for line in teleports)
            assert len(collisions) == int(saved['collisions'])
            assert len(teleports) == int(saved['teleports'])
            junctions = dict(Counter(e.get('lane').split('_')[0].lstrip(':') for e in collisions))
            measured[key] = dict(B=B, Q=int(saved['arrived']), collisions=len(collisions), teleports=len(teleports), wrong_lane=wrong_lane, causes=dict(causes), junctions=junctions)
            times.append(dict(case=r['case'], seed=r['seed'], arm=r['arm'], samples=samples, first_s=0, last_s=3599.9,
                window='[0,3600)', interval_s=0.1, B_vehicle_hours=B, B_error_vs_saved=B-float(saved['total_vh']),
                network_count_sum=network, waiting_count_sum=entry, archive_prefix=prefix))
            print('Recalculated', *key, flush=True)
        passes = Counter()
        for p in pairs:
            key = p['case'], int(p['seed'])
            a = measured[*key, p['comparison'].removeprefix('combined_vs_')]
            b = measured[*key, 'combined']
            close((b['Q'] / a['Q'] - 1) * 100, p['Q_change_pct'])
            close((b['B'] / a['B'] - 1) * 100, p['count_burden_change_pct'])
            assert b['collisions'] == int(p['candidate_collisions']) and a['collisions'] == int(p['reference_collisions'])
            assert b['teleports'] == int(p['candidate_teleports']) and a['teleports'] == int(p['reference_teleports'])
            assert a['junctions'] == json.loads(p['reference_junctions'])
            assert b['junctions'] == json.loads(p['candidate_junctions'])
            guards = dict(no_added_collisions=b['collisions'] <= a['collisions'],
                no_added_n1=b['junctions'].get('n1', 0) <= a['junctions'].get('n1', 0),
                no_new_junction=not (set(b['junctions']) - set(a['junctions'])),
                no_added_teleports=b['teleports'] <= a['teleports'],
                no_added_wrong_lane=b['wrong_lane'] <= a['wrong_lane'],
                throughput_guard=(b['Q'] / a['Q'] - 1) * 100 >= -2,
                count_burden_guard=(b['B'] / a['B'] - 1) * 100 <= 5)
            for name, value in guards.items():
                assert value == (p[name] == 'True'), (key, name)
            assert all(guards.values()) == (p['meets_development_guards'] == 'True')
            passes[p['comparison']] += all(guards.values())
        assert len(pairs) == 30 and dict(passes) == {'combined_vs_original': 14, 'combined_vs_wait_only': 13}
        failure = [p for p in pairs if p['seed'] == '1103' and p['meets_development_guards'] == 'False']
        assert len(failure) == 1 and failure[0]['case'] == 'P04'
        assert failure[0]['comparison'] == 'combined_vs_wait_only'
        assert measured['P04', 1103, 'wait_only']['teleports'] == 0
        assert measured['P04', 1103, 'combined']['teleports'] == 2
        assert measured['P04', 1103, 'combined']['causes'] == {'yield': 1, 'wrongLane': 1}
        totals = {arm: {metric: sum(r[metric] for key,r in measured.items() if key[2] == arm) for metric in ('Q', 'collisions', 'teleports')} for arm in ('original', 'wait_only', 'combined')}
        assert totals == json.loads(z.read('report/verification.json'))['totals']
        result = dict(date='2026-11-08', archive_name=archive.name, archive_sha256=archive_hash,
            verified_manifest_members=len(manifest), runs_checked=45, summary_samples_checked=45*36000,
            sample_scope='36,000 samples per run: 0.0 through 3599.9 s; [0,3600), dt=0.1 s',
            formula='B = 0.1/3600 * sum(running + waiting)', units='vehicle-hours',
            max_absolute_B_error=max(abs(r['B_error_vs_saved']) for r in times),
            B_definition_matches_manuscript_eq8=True, paired_comparisons_recalculated=30,
            development_guard_boolean_checks=210,
            totals=totals, development_safeguard_passes=dict(passes), seed1103_exception=failure[0],
            new_simulations=0, original_archive_modified=False, new_human_reference_assessments=0,
            type='Author-side archive and arithmetic verification; not independent human classification validation')
        (output / 'verification.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        (output / 'all_45_sampling_checks.json').write_text(json.dumps(times, indent=2)+'\n', encoding='utf-8')
        return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('archive', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(run(args.archive, args.output), indent=2))
