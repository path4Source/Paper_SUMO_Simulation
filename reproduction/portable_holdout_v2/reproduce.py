"""Verify and reproduce the prospective holdout and stochastic-update comparison."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import second_implementation_BC as alternate


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(name):
    with (ROOT / "data" / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def verify():
    manifest = read(ROOT / "manifest.json")
    for name, expected in manifest["files_sha256"].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT.resolve()), name
        assert sha(path) == expected, name
    inventory = read(ROOT / "input_inventory.json")
    assert len(inventory["runs"]) == 95
    assert sum(r["new_in_revision"] for r in inventory["runs"]) == 80
    for run in inventory["runs"]:
        folder = ROOT / "inputs" / run["case"]
        cfg = ET.parse(folder / "run.sumocfg").getroot()
        for tag in ("net-file", "route-files", "additional-files"):
            for value in cfg.find("input/" + tag).get("value").split(","):
                path = (folder / value).resolve()
                assert path.is_relative_to(folder.resolve()) and path.is_file(), (run["case"], tag)
        assert cfg.find("time/step-length").get("value") == "0.1"
        assert cfg.find("processing/default.action-step-length").get("value") == "0.1"
        assert cfg.find("processing/collision.check-junctions").get("value") == "true"
        assert cfg.find("processing/step-method.ballistic").get("value") == "true"
        assert int(cfg.find("random_number/seed").get("value")) == run["seed"]
        sigma_steps = {v.get("sigmaStep") for v in ET.parse(folder / "routes.rou.xml").getroot().findall("vType")}
        assert sigma_steps == ({"1"} if run["new_in_revision"] else {None})
        additional = ET.parse(folder / "additional.xml").getroot()
        assert len(additional.findall("instantInductionLoop")) == 53
        assert len(additional.findall("laneAreaDetector")) == 53
    return {"verified_files": len(manifest["files_sha256"]), "input_runs": 95,
            "new_runs_in_archive": 80, "reused_references": 15,
            "simulations_executed": 0, "public_upload_performed": False}


def verify_holdout(use_original=False):
    public = read(ROOT / "data/protocol.json")
    protocol = public["protocol"]
    observations = read(ROOT / "data/observable_cases.json")
    locked = read(ROOT / "data/predictions_LOCKED.json")
    assert locked["protocol_sha256"] == public["original_protocol_sha256"]
    assert locked["observations_sha256"] == alternate.canonical_hash(observations)
    assert locked["prediction_sha256"] == alternate.canonical_hash({k:v for k,v in locked.items() if k != "prediction_sha256"})
    assert len({alternate.canonical_hash(c["reference"]) for c in observations["cases"]}) == 1
    expected = {r["case_id"]: r for r in locked["rows"]}
    decisions, error = [], 0.0
    if use_original:
        from blind_test_v2_tools import features_for_case
        from diagnostic_rules_v2_draft import classify
    for case in observations["cases"]:
        if use_original:
            features, scope = features_for_case(case, protocol["holdout"]["seeds"], ["target", "donor", "other"], ["target"])
        else:
            features, scope = alternate.extract_features(case, protocol["holdout"]["seeds"])
        error = max(error, alternate.feature_difference(features, expected[case["case_id"]]["features"]))
        for variant in alternate.VARIANTS:
            prediction = classify(features, scope, variant) if use_original else alternate.classify(features, scope, variant)
            prediction = alternate.normalized_prediction(prediction)
            target = alternate.normalized_prediction(expected[case["case_id"]]["predictions"][variant])
            assert prediction == target, (case["case_id"], variant)
            decisions.append({"case_id": case["case_id"], "comparator": variant, "prediction": prediction})
    assert len(decisions) == 84
    return {"cases": 12, "treatment_runs": 60, "shared_reference_runs": 5,
            "matched_predictions": 84, "paired_intervals": 168,
            "maximum_absolute_feature_difference": error, "decisions": decisions,
            "independent_correctness_validated": False}


def verify_bridge():
    observed = {(r["state"], int(r["seed"]), r["setting"]): r for r in rows("bridge_run_metrics.csv")}
    assert len(observed) == 30
    seeds = read(ROOT / "data/protocol.json")["protocol"]["bridge"]["seeds"]
    states = ["baseline", "heavyveh_very_high", "weather_heavy_rain"]
    old, new = "implicit_sigma_step_0.1", "explicit_sigma_step_1.0"
    settings, effects = [], []
    for state in states:
        for metric in ("Q", "B", "D", "burden_per_planned_s"):
            values = [alternate.pct(float(observed[state,s,new][metric]), float(observed[state,s,old][metric])) for s in seeds]
            settings.append({"state": state, "metric": metric, "contrast": "new setting versus old setting, percent", **alternate.interval(values)})
    for state in states[1:]:
        for metric in ("Q", "B", "D"):
            paired = {}
            for setting in (old, new):
                values = [alternate.pct(float(observed[state,s,setting][metric]), float(observed["baseline",s,setting][metric])) for s in seeds]
                paired[setting] = values
                effects.append({"state": state, "metric": metric, "contrast": setting, **alternate.interval(values)})
            effects.append({"state": state, "metric": metric, "contrast": "new minus old paired response (pp)",
                            **alternate.interval([a-b for a,b in zip(paired[new], paired[old])])})
    maximum = 0.0
    for calculated, filename in ((settings, "bridge_setting_contrasts.csv"), (effects, "bridge_scenario_responses.csv")):
        saved = {(r["state"],r["metric"],r["contrast"]):r for r in rows(filename)}
        assert len(calculated) == len(saved)
        for row in calculated:
            reference = saved[row["state"],row["metric"],row["contrast"]]
            for field in ("mean", "lo", "hi", "n"):
                delta = abs(row[field] - float(reference[field]))
                assert math.isclose(row[field], float(reference[field]), rel_tol=1e-11, abs_tol=1e-9)
                maximum = max(maximum, delta)
    return {"run_records": 30, "setting_contrasts": 12, "scenario_response_intervals": 18,
            "maximum_absolute_difference": maximum, "setting_results": settings, "scenario_results": effects}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "reproduce"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--original", action="store_true", help="Also replay the original frozen implementation (NumPy/SciPy required)")
    args = parser.parse_args()
    report = verify()
    if args.command == "reproduce":
        if args.output is None:
            parser.error("reproduce requires a new --output directory")
        assert not args.output.exists(), "Output exists; choose a new directory"
        report["holdout_alternative"] = verify_holdout()
        report["bridge"] = verify_bridge()
        if args.original:
            report["holdout_original"] = verify_holdout(True)
        args.output.mkdir(parents=True)
        (args.output / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    compact = {k:v for k,v in report.items() if k not in ("bridge", "holdout_alternative", "holdout_original")}
    if args.command == "reproduce":
        compact.update(matched_holdout_predictions=84, bridge_intervals_verified=30, independent_correctness_validated=False)
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
