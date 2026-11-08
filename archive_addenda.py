"""Inspect and restore the supplementary research archives without running SUMO."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def destination(root, name):
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError(f"Unsafe archive path: {name}")
    result = (root / name).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"Archive path leaves destination: {name}")
    return result


def inspect(archive, entry):
    if archive.stat().st_size != entry["bytes"] or digest(archive) != entry["sha256"]:
        raise ValueError(f"Archive checksum differs: {entry['filename']}")
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != set(entry["files_sha256"]):
            raise ValueError(f"Archive membership differs: {entry['id']}")
        for item in bundle.infolist():
            destination(Path.cwd(), item.filename)
            if item.is_dir() or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Directory/symlink member: {item.filename}")
            with bundle.open(item) as handle:
                actual = hashlib.file_digest(handle, "sha256").hexdigest()
            if actual != entry["files_sha256"][item.filename]:
                raise ValueError(f"Member checksum differs: {item.filename}")
    return len(names)


def fresh_output(path):
    result = Path(path).resolve()
    if result.exists() or result.is_relative_to(ROOT) or ROOT.is_relative_to(result):
        raise ValueError("Choose a new directory outside the code checkout")
    return result


def restored_name(entry, name):
    if entry["group"] == "six" and name == "DELIVERY_MANIFEST_SHA256.json":
        return "archive_manifests/" + entry["id"] + ".json"
    return name


def restore(archive_dir, entries, output):
    output = fresh_output(output)
    planned = {}
    # Check every member and collision before creating the destination.
    for entry in entries:
        archive = destination(archive_dir, entry["filename"])
        inspect(archive, entry)
        for name in entry["files_sha256"]:
            target = destination(output, restored_name(entry, name))
            if str(target).casefold() in planned:
                raise ValueError(f"Duplicate destination across archives: {name}")
            if os.name == "nt" and len(str(target)) > 250:
                raise ValueError("Use a shorter destination path for Windows")
            planned[str(target).casefold()] = name
    output.mkdir(parents=True)
    for entry in entries:
        with zipfile.ZipFile(archive_dir / entry["filename"]) as bundle:
            for item in bundle.infolist():
                target = destination(output, restored_name(entry, item.filename))
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, target.open("xb") as dest:
                    shutil.copyfileobj(source, dest, 1024 * 1024)
                if digest(target) != entry["files_sha256"][item.filename]:
                    raise ValueError(f"Restored checksum differs: {item.filename}")
                timestamp = datetime(*item.date_time).timestamp()
                os.utime(target, (timestamp, timestamp))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    check = sub.add_parser("verify")
    check.add_argument("--archive-dir", required=True, type=Path)
    check.add_argument("--group", choices=("reference", "n1-event", "n1-five"))
    unpack = sub.add_parser("restore")
    unpack.add_argument("group", choices=("reference", "n1-event"))
    unpack.add_argument("--archive-dir", required=True, type=Path)
    unpack.add_argument("--output", required=True, type=Path)
    n1 = sub.add_parser("check-n1")
    n1.add_argument("--archive-dir", required=True, type=Path)
    n1.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    index = load(ROOT / "addenda_manifest.json")
    if args.command == "list":
        print(json.dumps({"baseline": index["manuscript_baseline"], "groups": index["groups"],
                          "publication_state": index["publication_state"]}, indent=2))
        return
    entries = [r for r in index["archives"] if not getattr(args, "group", None)
               or r["group"] == args.group]
    if args.command == "verify":
        count = sum(inspect(destination(args.archive_dir, r["filename"]), r) for r in entries)
        print(json.dumps({"archives_checked": len(entries), "members_checked": count,
                          "new_simulations": 0}))
    elif args.command == "restore":
        if args.group == "six":
            entries = [r for r in entries if r["id"] != "six-locked-analysis"]
        output = restore(args.archive_dir.resolve(), entries, args.output)
        print(json.dumps({"restored": str(output), "archives": len(entries),
                          "new_simulations": 0}))
    else:
        entry = next(r for r in index["archives"] if r["id"] == "n1-five-seed")
        archive = destination(args.archive_dir, entry["filename"])
        inspect(archive, entry)
        output = fresh_output(args.output)
        subprocess.run([sys.executable, "-B", str(ROOT / "supplements/check_n1_evidence.py"),
                        str(archive), "--output", str(output)], check=True)


if __name__ == "__main__":
    main()
