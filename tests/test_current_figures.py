"""Current figure routing and package integrity without plotting or simulation."""
import importlib.util
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('current_figure_entry', ROOT / 'reproduce.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class CurrentFigureTests(unittest.TestCase):
    def test_current_manifest_and_reference_assets(self):
        catalog = entry.load(ROOT / 'catalog.json')
        package = entry.package_check(ROOT, catalog['current_figure_package'])
        entries = entry.load(ROOT / 'figures/index.json')
        self.assertEqual([r['number'] for r in entries], [str(i) for i in range(1,11)]+['S1','S2'])
        for item in entries:
            asset = ROOT / 'figures' / item['file']
            self.assertEqual(asset.suffix, '.pdf')
            self.assertEqual(entry.digest(asset), item['sha256'])
            self.assertTrue((ROOT / item['reference']).is_file())
            if item['number'] not in ('1','3'):
                self.assertEqual(entry.digest(package / 'expected' / item['file']), item['sha256'])
        with (ROOT / entries[2]['reference']).open(encoding='utf-8-sig', newline='') as src:
            rows = [r for r in csv.DictReader(src) if r['response'] == 'throughput']
        self.assertEqual(len({r['scenario'] for r in rows}), 26)
        self.assertEqual({r['n'] for r in rows}, {'3'})
        self.assertEqual(sum(r['warning_qualified'].lower() == 'true' for r in rows), 9)

    def test_route_to_current_renderer(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry, 'execute') as execute:
            destination = Path(temp) / 'output'
            entry.main(['figures', '--group', 'current', '--output', str(destination)])
            core = destination / 'core-work'
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(execute.call_args_list[0].args,(core / 'reproduce_figures.py', [], core, None))
            execute.assert_called_with(ROOT / 'reproduction/manuscript_figures/assemble.py', [str(destination)], ROOT, None)

    def test_core_renderer_remains_available(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry, 'execute') as execute:
            destination = Path(temp) / 'output'
            entry.main(['figures', '--group', 'core-20261109', '--output', str(destination)])
            execute.assert_called_once_with(destination / 'reproduce_figures.py', [], destination, None)

    def test_drawio_option_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry, 'execute') as execute:
            destination = Path(temp) / 'output'
            entry.main(['figures', '--group', 'current', '--output', str(destination), '--drawio', 'drawio.exe'])
            self.assertEqual(execute.call_args.args[1], [str(destination), '--drawio', 'drawio.exe'])

    def test_no_drawio_for_historical_groups(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry, 'execute') as execute:
            destination = Path(temp) / 'output'
            with self.assertRaises(ValueError):
                entry.main(['figures', '--group', 'scores', '--output', str(destination), '--drawio', 'drawio.exe'])
            execute.assert_not_called()
            self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
