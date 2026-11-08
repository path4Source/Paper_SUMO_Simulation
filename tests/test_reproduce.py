"""Safety and integrity checks for the public-facing repository entry point."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

MODULE = Path(__file__).resolve().parents[1] / "reproduce.py"
spec = importlib.util.spec_from_file_location("publication_entry", MODULE)
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class EntryTests(unittest.TestCase):
    def test_relative_path(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(entry.contained(Path(d), "a/b.txt"), Path(d).resolve() / "a/b.txt")

    def test_path_escape(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("../outside", "/outside", "C:/outside", "a\\b"):
                with self.assertRaises(ValueError):
                    entry.contained(Path(d), name)

    def make_archive(self, directory, records):
        path = directory / "data.zip"
        with zipfile.ZipFile(path, "w") as bundle:
            for name, content in records.items():
                bundle.writestr(name, content)
        return {"filename": path.name, "sha256": entry.digest(path),
                "files_sha256": {name: hashlib.sha256(content).hexdigest()
                                 for name, content in records.items()}}

    def test_restore_and_idempotent_skip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            record = self.make_archive(Path(d), {"data/result.txt": b"real record"})
            self.assertEqual(entry.restore_one(root, Path(d), record), 1)
            self.assertEqual(entry.restore_one(root, Path(d), record), 0)
            self.assertEqual((root / "data/result.txt").read_bytes(), b"real record")

    def test_do_not_replace_existing_data(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            (root / "result.txt").write_bytes(b"different")
            record = self.make_archive(Path(d), {"result.txt": b"record"})
            with self.assertRaises(FileExistsError):
                entry.restore_one(root, Path(d), record)
            self.assertEqual((root / "result.txt").read_bytes(), b"different")

    def test_corrupt_archive(self):
        with tempfile.TemporaryDirectory() as d:
            record = self.make_archive(Path(d), {"result.txt": b"record"})
            record["sha256"] = "wrong"
            with self.assertRaises(ValueError):
                entry.restore_one(Path(d) / "repo", Path(d), record)

    def test_unlisted_archive_member(self):
        with tempfile.TemporaryDirectory() as d:
            record = self.make_archive(Path(d), {"result.txt": b"record"})
            record["files_sha256"] = {}
            with self.assertRaises(ValueError):
                entry.restore_one(Path(d) / "repo", Path(d), record)

    def test_malicious_archive_member(self):
        with tempfile.TemporaryDirectory() as d:
            record = self.make_archive(Path(d), {"../result.txt": b"record"})
            with self.assertRaises(ValueError):
                entry.restore_one(Path(d) / "repo", Path(d), record)
            self.assertFalse((Path(d) / "result.txt").exists())

    def test_output_must_be_new_and_external(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            root.mkdir()
            for target in (root, root / "results", root.parent):
                with self.assertRaises(ValueError):
                    entry.fresh_output(root, str(target))
            self.assertEqual(entry.fresh_output(root, str(Path(d) / "output")), Path(d).resolve() / "output")

    def test_checksum_detects_changed_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.txt").write_bytes(b"text")
            expected = {"a.txt": entry.digest(root / "a.txt")}
            self.assertEqual(entry.verify_files(root, expected), 1)
            (root / "a.txt").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                entry.verify_files(root, expected)


if __name__ == "__main__":
    unittest.main()
