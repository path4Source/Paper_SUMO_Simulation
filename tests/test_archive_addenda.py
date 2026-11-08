import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile


SPEC = importlib.util.spec_from_file_location("archive_addenda", Path(__file__).parents[1] / "archive_addenda.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, name, files, group="six"):
        path = self.root / (name + ".zip")
        with zipfile.ZipFile(path, "x") as bundle:
            for filename, data in files.items():
                bundle.writestr(filename, data)
        return dict(id=name, group=group, filename=path.name, bytes=path.stat().st_size,
                    sha256=module.digest(path),
                    files_sha256={n: hashlib.sha256(v).hexdigest() for n, v in files.items()})

    def test_unsafe_paths(self):
        for name in ("../x", "/x", "C:/x", "x\\y", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                module.destination(self.root, name)

    def test_valid_archive(self):
        entry = self.archive("one", {"a/result.json": b"{}"})
        self.assertEqual(module.inspect(self.root / entry["filename"], entry), 1)

    def test_corrupt_archive(self):
        entry = self.archive("one", {"a.txt": b"one"})
        with (self.root / entry["filename"]).open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaises(ValueError):
            module.inspect(self.root / entry["filename"], entry)

    def test_member_hash_mismatch(self):
        entry = self.archive("one", {"a.txt": b"one"})
        entry["files_sha256"]["a.txt"] = "0" * 64
        with self.assertRaises(ValueError):
            module.inspect(self.root / entry["filename"], entry)

    def test_duplicate_destinations_before_creation(self):
        entries = [self.archive(n, {"runs/a.txt": n.encode()}) for n in ("one", "two")]
        output = self.root / "out"
        with self.assertRaises(ValueError):
            module.restore(self.root, entries, output)
        self.assertFalse(output.exists())

    def test_delivery_manifest_collision_is_preserved(self):
        entries = [self.archive(n, {f"runs/{n}/a.txt": n.encode(),
                                   "DELIVERY_MANIFEST_SHA256.json": n.encode()}) for n in ("one", "two")]
        output = module.restore(self.root, entries, self.root / "out")
        for name in ("one", "two"):
            self.assertEqual((output / f"archive_manifests/{name}.json").read_bytes(), name.encode())
            self.assertEqual((output / f"runs/{name}/a.txt").read_bytes(), name.encode())

    def test_existing_output_preserved(self):
        output = self.root / "existing"
        output.mkdir()
        (output / "keep.txt").write_bytes(b"keep")
        with self.assertRaises(ValueError):
            module.restore(self.root, [], output)
        self.assertEqual((output / "keep.txt").read_bytes(), b"keep")

    def test_traversal_archive_is_rejected(self):
        entry = self.archive("one", {"../bad.txt": b"bad"})
        with self.assertRaises(ValueError):
            module.inspect(self.root / entry["filename"], entry)


if __name__ == "__main__":
    unittest.main()
