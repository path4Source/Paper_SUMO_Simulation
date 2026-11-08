"""Rebuild score measurements from an explicit read-only original SUMO archive."""
import argparse
import contextlib
import csv
import importlib.metadata
import io
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from replay_checks import compare_file, compare_values, digest, verify_manifest
import frozen_metrics
import score_analysis

ROOT = Path(__file__).resolve().parent


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def local_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Dependency escapes root: {name}")
    return path


def output_path(package, raw, requested):
    output = Path(requested).resolve()
    if output.exists() or any(output.is_relative_to(p.resolve()) for p in (package, raw)):
        raise ValueError("Use a new output outside the package and raw archive")
    return output


def raw_hashes(raw, manifest):
    for name, expected in manifest["raw_sha256"].items():
        path = local_file(raw, name)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Missing or changed raw file: {name}")


def verify_run_config(summary, seed):
    text = summary.read_text(encoding="utf-8")
    config_text = re.search(r"<sumoConfiguration\b.*?</sumoConfiguration>", text, re.S)
    if config_text is None:
        raise ValueError("Missing recorded SUMO configuration")
    config = ET.fromstring(config_text.group())
    values = {name: config.find(f".//{name}").get("value") for name in ("seed", "begin", "end")}
    if int(values["seed"]) != seed or float(values["begin"]) != 0 or float(values["end"]) != 3600:
        raise ValueError(f"Unexpected seed or observation horizon: {values}")


def extract(raw, run):
    directory = local_file(raw, run["directory"])
    summary = directory / "summary.xml"
    tripinfo = directory / "tripinfo.xml"
    verify_run_config(summary, run["seed"])
    values = {**frozen_metrics.parse_summary(summary), **frozen_metrics.parse_tripinfo(tripinfo)}
    trips = ET.parse(tripinfo).getroot().findall("tripinfo")
    if len(trips) != values["arrived_vehicles"] or any(float(t.get("arrival", "-1")) < 0 for t in trips):
        raise ValueError(f"Completion count mismatch: {run['directory']}")
    values["throughput_veh_per_h"] = values["arrived_vehicles"] / 1.0
    if run["legacy_emission_check"]:
        values.update(frozen_metrics.parse_emissions(directory / "emission_edges.xml"))
        values["co2_per_vehicle_kg"] = values["total_co2_kg"] / max(values["arrived_vehicles"], 1.0)
    return values


def replace_measurements(rows, measurements):
    rebuilt, checks = [], []
    for row in rows:
        key = (row["scenario"], int(row.get("seed", 42)))
        values = measurements[key]
        new = row.copy()
        for field, value in values.items():
            expected = float(row[field])
            compare_values(expected, value, f"{key}.{field}")
            new[field] = value
            checks.append({"scenario": key[0], "seed": key[1], "field": field,
                           "archived": expected, "reextracted": value,
                           "absolute_difference": abs(expected - value)})
        rebuilt.append(new)
    return rebuilt, checks


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def compare_summary(expected_path, actual_path, inputs):
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = json.loads(actual_path.read_text(encoding="utf-8"))
    actual_hashes = actual.pop("source_sha256")
    expected_hashes = expected.pop("source_sha256")
    if actual_hashes != {name: digest(inputs / name) for name in actual_hashes}:
        raise ValueError("Rebuilt-input provenance does not match analysis manifest")
    compare_values(expected, actual, "analysis_summary scientific contents")
    return {"file": "analysis_summary.json", "scientific_contents_match": True,
            "source_hashes_verified_against_rebuilt_inputs": True,
            "archived_source_sha256": expected_hashes, "rebuilt_source_sha256": actual_hashes,
            "byte_identical": digest(expected_path) == digest(actual_path)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    manifest = verify_manifest(ROOT)
    versions = {name: importlib.metadata.version(name) for name in manifest["python_packages"]}
    if versions != manifest["python_packages"]:
        raise ValueError("Use the recorded environment for exact replay")
    raw = Path(args.raw_root).resolve()
    output = output_path(ROOT, raw, args.output)
    raw_hashes(raw, manifest)
    output.mkdir(parents=True)
    inputs = output / "rebuilt_inputs"
    inputs.mkdir()
    measurements = {}
    for run in manifest["runs"]:
        measurements[(run["scenario"], run["seed"])] = extract(raw, run)
    all_checks = []
    for name in ("sumo_oat_results.csv", "sumo_multiseed_results.csv"):
        rebuilt, checks = replace_measurements(read_rows(ROOT / "inputs" / name), measurements)
        write_rows(inputs / name, rebuilt)
        all_checks.extend({"input_table": name, **row} for row in checks)
    # This table is a historical comparison target, never a measurement source.
    shutil.copy2(ROOT / "inputs/sumo_scenario_effects.csv", inputs / "sumo_scenario_effects.csv")
    score_analysis.SOURCE = inputs
    score_analysis.OUT = output / "scores"
    with contextlib.redirect_stdout(io.StringIO()) as captured:
        score_analysis.main()
    (output / "estimator_log.txt").write_text(captured.getvalue(), encoding="utf-8")
    results = [compare_file(ROOT / "expected" / name, output / "scores" / name)
               for name in manifest["score_outputs"] if name.endswith(".csv")]
    summary_check = compare_summary(ROOT / "expected/analysis_summary.json",
                                    output / "scores/analysis_summary.json", inputs)
    raw_hashes(raw, manifest)
    verify_manifest(ROOT)
    write_rows(output / "measurement_checks.csv", all_checks)
    report = {
        "unique_existing_runs_reextracted": len(measurements),
        "primary_QDH_measurements_reextracted": 3 * len(measurements),
        "legacy_CO2_intensities_reextracted": sum(r["legacy_emission_check"] for r in manifest["runs"]),
        "unique_measurement_fields_reextracted": sum(len(v) for v in measurements.values()),
        "input_table_field_checks": len(all_checks),
        "max_input_absolute_difference": max(r["absolute_difference"] for r in all_checks),
        "raw_files_hash_verified_before_and_after": len(manifest["raw_sha256"]),
        "score_outputs_verified": len(results) + 1, "csv_outputs": results, "summary_check": summary_check,
        "estimator_computational_ast_unchanged": True,
        "metric_parser_function_asts_unchanged": True,
        "new_simulations": 0, "warning_cases_removed": 0,
        "independent_human_validation": False, "public_deposition": False,
        "metadata_scope": "Scenario labels and unused edge aggregates are copied unchanged; only documented measurement fields are re-extracted. CO2 is used only for the archived four-component comparison, not the primary score.",
        "tolerance": {"relative": 1e-12, "absolute": 1e-12},
        "package_manifest_sha256": digest(ROOT / "manifest.json"),
        "python_packages": versions,
    }
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
