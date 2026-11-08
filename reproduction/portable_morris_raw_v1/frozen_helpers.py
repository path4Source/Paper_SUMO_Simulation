import csv
import hashlib
from pathlib import Path
import numpy as np

def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"No records for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()

def validate_design(x):
    k = len(SPECS)
    if x.shape != (TRAJECTORIES * (k + 1), k):
        raise ValueError("Unexpected Morris matrix size")
    bounds = np.asarray(PROBLEM["bounds"])
    unit = (x - bounds[:, 0]) / (bounds[:, 1] - bounds[:, 0])
    if np.any(unit < -1e-9) or np.any(unit > 1 + 1e-9):
        raise ValueError("Out-of-bounds Morris point")
    if not np.allclose(unit * (LEVELS - 1), np.round(unit * (LEVELS - 1)), atol=1e-8):
        raise ValueError("Off-grid Morris point")
    delta = LEVELS / (2 * (LEVELS - 1))
    for block in unit.reshape(TRAJECTORIES, k + 1, k):
        differences = np.abs(np.diff(block, axis=0))
        changes = differences > 1e-8
        if not np.all(changes.sum(axis=0) == 1) or not np.all(changes.sum(axis=1) == 1):
            raise ValueError("Invalid one-at-a-time trajectory")
        if not np.allclose(differences[changes], delta, atol=1e-8):
            raise ValueError("Incorrect elementary step")

def check_accounting(row, planned):
    if row["end_loaded"] != planned or row["trip_records"] != planned:
        raise RuntimeError("Incomplete planned population")
    if row["end_inserted"] + row["end_waiting"] != planned:
        raise RuntimeError("Insertion population mismatch")
    if row["unaccounted_inserted_end"] or row["ended_not_arrived"]:
        raise RuntimeError("Running/arrived population mismatch")
    if row["trip_completed_count"] != row["end_arrived"] or row["trip_undeparted_count"] != row["end_waiting"]:
        raise RuntimeError("Trip-summary population mismatch")
    if row["trip_unfinished_inserted_count"] != row["end_running"]:
        raise RuntimeError("Unfinished population mismatch")
    if row["tau_step_warning"] or row["tau_action_warning"] or row["integration_action_warning"]:
        raise RuntimeError("Invalid timing/integration settings")
