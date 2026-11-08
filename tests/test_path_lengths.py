"""Check Windows restoration limits before any data are written."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("entry_paths", Path(__file__).resolve().parents[1] / "reproduce.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class RestorePathTests(unittest.TestCase):
    def test_short_paths_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            entry.check_restore_paths(Path(directory), {"data/result.xml": "hash"}, windows=True)

    def test_long_paths_fail_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "/".join(["nested" * 8] * 6) + "/result.xml"
            with self.assertRaisesRegex(ValueError, "short directory"):
                entry.check_restore_paths(root, {name: "hash"}, windows=True)
            self.assertEqual(list(root.iterdir()), [])

    def test_posix_not_subject_to_windows_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            name = "/".join(["nested" * 8] * 6) + "/result.xml"
            entry.check_restore_paths(Path(directory), {name: "hash"}, windows=False)


if __name__ == "__main__":
    unittest.main()
