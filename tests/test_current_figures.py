"""Current figure routing and package integrity without plotting or simulation."""
import importlib.util
import json
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
        self.assertEqual(len(entries), 15)
        for item in entries:
            asset = ROOT / 'figures' / item['file']
            self.assertEqual(asset.suffix, '.pdf')
            self.assertEqual(entry.digest(asset), item['sha256'])
            self.assertEqual(entry.digest(package / 'expected' / item['file']), item['sha256'])

    def test_route_to_current_renderer(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry, 'execute') as execute:
            destination = Path(temp) / 'output'
            entry.main(['figures', '--group', 'current', '--output', str(destination)])
            execute.assert_called_once_with(destination / 'reproduce_figures.py', [], destination, None)
            self.assertTrue((destination / 'sources/Fig_revision_framework.drawio').is_file())

    def test_drawio_option_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry, 'execute') as execute:
            destination = Path(temp) / 'output'
            entry.main(['figures', '--group', 'current', '--output', str(destination), '--drawio', 'drawio.exe'])
            self.assertEqual(execute.call_args.args[1], ['--drawio', 'drawio.exe'])

    def test_no_drawio_for_historical_groups(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(entry, 'execute') as execute:
            destination = Path(temp) / 'output'
            with self.assertRaises(ValueError):
                entry.main(['figures', '--group', 'scores', '--output', str(destination), '--drawio', 'drawio.exe'])
            execute.assert_not_called()
            self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
