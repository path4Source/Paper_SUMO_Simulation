"""Rerun one archived configuration in a new output directory."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--case")
    parser.add_argument("--sumo", default="sumo")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = json.loads((ROOT / "input_cases.json").read_text(encoding="utf-8"))
    if args.list:
        print(json.dumps(cases, indent=2))
        return
    if args.case not in cases or args.output is None:
        parser.error("Choose an archived --case and a fresh --output directory")
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        parser.error("Existing output or output inside the source package is not allowed")
    source = ROOT / "inputs" / args.case
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))["files_sha256"]
    for file in source.iterdir():
        expected = manifest[file.relative_to(ROOT).as_posix()]
        assert hashlib.sha256(file.read_bytes()).hexdigest() == expected
    output.mkdir(parents=True)
    for file in source.iterdir():
        shutil.copy2(file, output / file.name)
    version = subprocess.check_output([args.sumo, "--version"], text=True)
    if "1.24.0" not in version.splitlines()[0]:
        raise RuntimeError("The archived study used SUMO 1.24.0; no simulation was started")
    with (output / "sumo_stdout.log").open("x") as stdout, (output / "sumo_stderr.log").open("x") as stderr:
        subprocess.run([args.sumo, "-c", "run.sumocfg"], cwd=output, stdout=stdout, stderr=stderr, check=True)
    print(f"New rerun completed in {output}; archived evidence was not changed.")


if __name__ == "__main__":
    main()
