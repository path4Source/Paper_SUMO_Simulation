"""Verify the local input inventory; do not execute simulations or analyses."""
import csv
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes release root: {relative}")
    return path


def verify_inventory(catalog):
    catalog = Path(catalog).resolve()
    release_root = catalog.parent
    manifest = json.loads((catalog / "manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["files_sha256"].items():
        if digest(contained(catalog, relative)) != expected:
            raise ValueError(f"Catalog content changed: {relative}")
    expected_keys = set()
    for bundle, record in manifest["bundles"].items():
        root = contained(release_root, bundle)
        bundle_manifest = root / "manifest.json"
        if digest(bundle_manifest) != record["manifest_sha256"]:
            raise ValueError(f"Bundle manifest changed: {bundle}")
        contents = json.loads(bundle_manifest.read_text(encoding="utf-8"))
        for relative, expected in contents["files_sha256"].items():
            if digest(contained(root, relative)) != expected:
                raise ValueError(f"Bundle file missing/changed: {bundle}/{relative}")
        expected_keys.update((bundle, key) for key in contents["cases"])
    with (catalog / "run_inventory.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    keys = [(row["bundle"], row["case"]) for row in rows]
    identities = [row["execution_id"] for row in rows]
    if len(set(keys)) != len(keys) or len(set(identities)) != len(identities):
        raise ValueError("Duplicate counted execution")
    if set(keys) != expected_keys:
        raise ValueError("Catalog does not exactly cover the included input bundles")
    counts = {category: sum(row["category"] == category for row in rows)
              for category in {row["category"] for row in rows}}
    if counts != manifest["category_counts"]:
        raise ValueError("Execution category counts changed")
    return {"total_input_sets": len(rows), "category_counts": counts,
            "new_simulations": 0, "scope": "Input inventory integrity, not complete raw-to-result reproduction"}


if __name__ == "__main__":
    print(json.dumps(verify_inventory(Path(__file__).resolve().parent), indent=2))
