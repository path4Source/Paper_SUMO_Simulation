"""Reproduce the current data figures without simulations or manuscript compilation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or digest(path) != expected:
            raise ValueError(f'Missing or changed figure input: {name}')
    return len(manifest['files'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Check packaged inputs only')
    parser.add_argument('--drawio', type=Path, help='Optionally re-export the editable framework using draw.io')
    args = parser.parse_args()
    count = verify()
    if args.verify:
        print(json.dumps({'verified_files': count, 'new_simulation_runs': 0}))
        return
    output = ROOT / 'manuscript_working/figures'
    audit = ROOT / 'audit/figure_redesign_20261022'
    if output.exists() or audit.exists():
        raise FileExistsError('Use a fresh copy of this package; previous outputs are retained.')
    output.mkdir(parents=True)
    audit.mkdir(parents=True)
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('current_style', ROOT / 'scripts/current_style.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()
    actual = json.loads((audit / 'figure_data_preservation.json').read_text(encoding='utf-8'))
    expected = json.loads((ROOT / 'expected/numerical_traces.json').read_text(encoding='utf-8'))
    observed = {r['figure']: r['numerical_trace_sha256'] for r in actual['figures']}
    if observed != expected:
        raise AssertionError('Numerical figure traces differ from the current manuscript references.')
    if actual['text_outside_canvas']:
        raise AssertionError('Text extends outside a figure canvas; inspect the retained previews.')
    framework = 'Fig_revision_framework'
    if args.drawio:
        if not args.drawio.is_file():
            raise FileNotFoundError(args.drawio)
        for ext in ('pdf', 'svg'):
            subprocess.run([str(args.drawio.resolve()), '--export', '--format', ext,
                            '--crop', '--border', '2', '--output', str(output / f'{framework}.{ext}'),
                            str(ROOT / f'sources/{framework}.drawio')], check=True)
            if not (output / f'{framework}.{ext}').is_file():
                raise RuntimeError(f'draw.io did not create the {ext} export')
        framework_action = 'exported_from_editable_drawio_source'
    else:
        shutil.copy2(ROOT / f'expected/{framework}.pdf', output / f'{framework}.pdf')
        framework_action = 'copied_verified_reference_pdf; editable_drawio_source_supplied'
    verify()
    result = {'numerical_figures_verified': len(observed), 'framework': framework_action,
              'new_simulation_runs': 0, 'compiled_manuscript': False}
    (ROOT / 'reproduction_result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
