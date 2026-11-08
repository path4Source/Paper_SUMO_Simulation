"""Freeze submitted sources and local evidence without modifying historical files."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path(r"E:\4\road_capacity_sci")
ARCHIVE = PROJECT / "scientific_reports/overleaf_submission_20260806_visual_final/supplementary_data/scripts"
ZIP = ROOT / "private_inputs/submitted.zip"
REVIEW = ROOT / "private_inputs/reviewer_comments.txt"
SUMO = Path(r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe")


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def copy_checked(source: Path, destination: Path) -> dict:
    digest = sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(destination) != digest:
            raise RuntimeError(f"Refusing to overwrite changed snapshot: {destination}")
    else:
        shutil.copy2(source, destination)
    return {"source": str(source), "snapshot": str(destination.relative_to(ROOT)),
            "bytes": source.stat().st_size, "sha256": digest}


def main() -> None:
    records = [copy_checked(ZIP, ROOT / "frozen/submitted.zip"),
               copy_checked(REVIEW, ROOT / "frozen/reviewer_comments.txt")]
    with zipfile.ZipFile(ZIP) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            for folder in ("frozen/manuscript", "manuscript_working"):
                base = (ROOT / folder).resolve()
                target = (base / member.filename).resolve()
                if not target.is_relative_to(base):
                    raise ValueError(f"Unsafe ZIP path: {member.filename}")
                data = archive.read(member)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(data)
                elif folder.startswith("frozen") and target.read_bytes() != data:
                    raise RuntimeError(f"Frozen source changed: {target}")
    for name, origin in (("historical_root", PROJECT / "scripts"), ("aug06_archive", ARCHIVE)):
        for path in sorted(origin.glob("*.py")):
            records.append(copy_checked(path, ROOT / "frozen/code" / name / path.name))
    for path in sorted((PROJECT / "outputs/data").glob("*.csv")):
        records.append(copy_checked(path, ROOT / "frozen/data" / path.name))
    for name in ("network.net.xml", "rou_A2B.rou.xml"):
        records.append(copy_checked(Path(r"E:\1") / name, ROOT / "frozen/inputs" / name))
    records.append(copy_checked(PROJECT / "outputs/sumo_runs/baseline/routes.rou.xml",
                                ROOT / "frozen/inputs/baseline_rendered.rou.xml"))
    raw_inventory = []
    for path in sorted((PROJECT / "outputs/sumo_runs").glob("*/*")):
        if path.is_file():
            raw_inventory.append({"path": str(path), "bytes": path.stat().st_size,
                                  "sha256": sha256(path)})
    evidence = ROOT / "audit"
    evidence.mkdir(exist_ok=True)
    for name, rows in (("frozen_manifest.csv", records), ("raw_output_manifest.csv", raw_inventory)):
        with (evidence / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    version = subprocess.run([str(SUMO), "--version"], capture_output=True, text=True, check=True).stdout
    (evidence / "sumo_version.txt").write_text(version, encoding="utf-8")
    subprocess.run([str(SUMO), "--save-template", str(evidence / "sumo_1_24_defaults.xml")], check=True)
    metadata = {"created_utc": datetime.now(timezone.utc).isoformat(), "submitted_zip_sha256": sha256(ZIP),
                "sumo_binary_sha256": sha256(SUMO), "frozen_files": len(records),
                "raw_files": len(raw_inventory), "manuscript_edited": False,
                "public_repository_created": False}
    (evidence / "freeze_record.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)


if __name__ == "__main__":
    main()
