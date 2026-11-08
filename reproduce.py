"""Inspect, restore, and reproduce the archived traffic-simulation study."""
import argparse
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
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def contained(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError(f"Unsafe relative path: {name}")
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"Path leaves the repository: {name}")
    return target


def verify_files(root, records):
    for name, expected in records.items():
        path = contained(root, name)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Missing or changed file: {name}")
    return len(records)


def verify(root, complete=False):
    manifest = load(root / "repository_manifest.json")
    count = verify_files(root, manifest["files_sha256"])
    raw = 0
    if complete:
        for archive in load(root / "data_manifest.json")["archives"]:
            raw += verify_files(root, archive["files_sha256"])
    return {"repository_files_verified": count, "raw_files_verified": raw,
            "raw_data_checked": complete}


def check_restore_paths(root, records, *, windows=None):
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return
    # Archived analysis tools may also use legacy Windows path APIs.
    for name in records:
        path = contained(root, name)
        if len(str(path)) + len(".restoring") > 259:
            raise ValueError(
                "The repository path is too long for portable Windows restoration. "
                "Extract the code into a short directory such as E:/bt, keep analysis "
                "outputs in a short external directory, and retry. No files from "
                "this archive have been restored.")


def restore_one(root, archive_dir, entry):
    check_restore_paths(root, entry["files_sha256"])
    archive = contained(archive_dir, entry["filename"])
    if digest(archive) != entry["sha256"]:
        raise ValueError(f"Archive checksum differs: {entry['filename']}")
    expected = entry["files_sha256"]
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("Archive members do not match the data manifest")
        # Validate every destination before writing any files.
        for info in bundle.infolist():
            path = contained(root, info.filename)
            if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Directory and symbolic-link members are not supported")
            if path.exists() and digest(path) != expected[info.filename]:
                raise FileExistsError(f"Existing data differ; preserve and inspect: {path}")
        restored = 0
        for name in names:
            path = contained(root, name)
            if path.exists():
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            pending = path.with_name(path.name + ".restoring")
            with bundle.open(name) as source, pending.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            if digest(pending) != expected[name]:
                raise ValueError(f"Restored checksum differs; partial file retained: {pending}")
            if path.exists():
                raise FileExistsError(f"Destination appeared during restore: {path}")
            pending.rename(path)
            restored += 1
    return restored


def fresh_output(root, value):
    output = Path(value).resolve()
    if output.exists() or output.is_relative_to(root.resolve()) or root.resolve().is_relative_to(output):
        raise ValueError("Choose a new output directory outside the repository")
    return output


def package_check(root, directory):
    package = contained(root, directory)
    manifest = load(package / "manifest.json")
    records = manifest.get("files_sha256", manifest.get("files"))
    verify_files(package, records)
    return package


def execute(script, arguments, cwd, interpreter=None):
    subprocess.run([interpreter or sys.executable, "-B", str(script), *arguments], cwd=cwd, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    check = sub.add_parser("verify")
    check.add_argument("--complete", action="store_true")
    restore = sub.add_parser("restore")
    restore.add_argument("--archive-dir", required=True, type=Path)
    restore.add_argument("--dataset", help="Restore one archive identifier; otherwise restore all")
    cases = sub.add_parser("cases")
    cases.add_argument("group")
    sim = sub.add_parser("simulate")
    sim.add_argument("group")
    sim.add_argument("--case", required=True)
    sim.add_argument("--sumo", default="sumo")
    sim.add_argument("--output", required=True)
    analysis = sub.add_parser("analyze")
    analysis.add_argument("group")
    analysis.add_argument("--output", required=True)
    figures = sub.add_parser("figures")
    figures.add_argument("--group", required=True, choices=[
        "current", "scores", "legacy", "cycle", "intervention", "horizon", "weather", "bottleneck"])
    figures.add_argument("--output", required=True)
    figures.add_argument("--python", help="Separate plotting-environment interpreter")
    figures.add_argument("--drawio", help="Re-export the current framework with an installed draw.io executable")
    args = parser.parse_args(argv)
    catalog = load(ROOT / "catalog.json")
    if args.command == "list":
        print(json.dumps({"simulations": catalog["simulations"], "analyses": catalog["analyses"]}, indent=2))
    elif args.command == "verify":
        print(json.dumps(verify(ROOT, args.complete), indent=2))
    elif args.command == "restore":
        verify(ROOT)
        archives = load(ROOT / "data_manifest.json")["archives"]
        selected = [a for a in archives if args.dataset is None or a["id"] == args.dataset]
        if not selected:
            raise ValueError("Unknown data archive identifier")
        for entry in selected:
            check_restore_paths(ROOT, entry["files_sha256"])
        for entry in selected:
            count = restore_one(ROOT, args.archive_dir.resolve(), entry)
            print(f"{entry['id']}: {count} data files restored", flush=True)
    elif args.command in ("cases", "simulate"):
        info = catalog["simulations"][args.group]
        package = package_check(ROOT, info["directory"])
        if args.command == "cases":
            execute(package / "run_simulation.py", ["--list"], package)
        else:
            output = fresh_output(ROOT, args.output)
            execute(package / "run_simulation.py", ["--case", args.case, "--sumo", args.sumo,
                    "--output", str(output)], package)
    elif args.command == "analyze":
        info = catalog["analyses"][args.group]
        package = package_check(ROOT, info["directory"])
        output = fresh_output(ROOT, args.output)
        options = ["--output", str(output)]
        if info.get("raw_root"):
            raw = contained(ROOT, info["raw_root"])
            if not raw.is_dir():
                raise FileNotFoundError("Restore the companion raw data first")
            options.extend(["--raw-root", str(raw)])
        execute(package / info["entry"], options, package)
    elif args.command == "figures":
        if args.drawio and args.group != "current":
            raise ValueError("--drawio is supported only for --group current")
        output = fresh_output(ROOT, args.output)
        if args.group == "current":
            package = package_check(ROOT, catalog["current_figure_package"])
            shutil.copytree(package, output)
            options = ["--drawio", args.drawio] if args.drawio else []
            execute(output / "reproduce_figures.py", options, output, args.python)
        elif args.group == "bottleneck":
            package = package_check(ROOT, catalog["figure_update"])
            execute(package / "scripts/plot_bottleneck_stage29.py", ["--output", str(output)], package, args.python)
        else:
            package = package_check(ROOT, catalog["figure_package"])
            shutil.copytree(package, output)
            execute(output / "reproduce_figures.py", ["--group", args.group], output, args.python)


if __name__ == "__main__":
    main()
