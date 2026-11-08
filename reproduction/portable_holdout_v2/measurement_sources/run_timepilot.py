"""Exploratory time-step audit; never reuses manuscript results as new runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from audit_metrics import audit_run, write_csv
from freeze_submission import sha256

ROOT = Path(__file__).resolve().parents[1]
SUMO = Path(r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe")
SETTINGS = [(1.0, 1.0), (0.5, 0.5), (0.5, 1.0), (0.1, 0.5)]
TAUS = [1.0, 0.8, 1.4]
SEEDS = [42, 2024, 2025]
PILOT = ROOT / "pilot_euler_v2"


def freeze_protocol() -> dict:
    protocol = {"kind": "exploratory time-setting pilot, not confirmatory or blinded",
                "seeds": SEEDS, "tau_s": TAUS, "step_action_pairs_s": SETTINGS,
                "horizon_s": [0, 3600], "warmup_excluded_s": 0,
                "integration": "explicit semi-implicit Euler, step-method.ballistic=false",
                "amendment": "The first v1 baseline auto-selected ballistic and did not reproduce the original. It is preserved under pilot/. Freeze explicit Euler before further outcomes. First execution tranche: tau 1.0 and 0.8, (step,action)=(1,1) and (0.5,0.5), seed 42 only.",
                "network_sha256": sha256(ROOT / "frozen/inputs/network.net.xml"),
                "route_source_sha256": sha256(ROOT / "frozen/inputs/baseline_rendered.rou.xml"),
                "sumo_sha256": sha256(SUMO),
                "analysis": "Within-setting matched-seed comparison against tau=1.0. Count collision and noncollision teleports separately. No significance claims from pilot. Smaller step changes numerical and possibly behavioral response; no cross-setting comparison called treatment benefit.",
                "caveat": "Preserve original junction collision checks=false for reproduction; zero logged collisions is not a universal safety proof.",
                "stop_conditions": "Fail on SUMO error or incomplete outputs. Preserve failed runs. No selective removal based on response sign."}
    path = ROOT / "audit/timepilot_euler_v2_protocol.json"
    canonical = json.dumps(protocol, indent=2)
    if path.exists() and json.loads(path.read_text()) != json.loads(canonical):
        raise RuntimeError("Existing pilot protocol differs")
    if not path.exists():
        path.write_text(canonical, encoding="utf-8")
    return protocol


def run_one(tau: float, step: float, action: float, seed: int) -> dict:
    name = f"tau{tau:g}_dt{step:g}_action{action:g}_seed{seed}"
    directory = PILOT / "runs" / name
    complete = directory / "complete.json"
    if complete.exists():
        record = json.loads(complete.read_text())
        if record["runner_sha256"] != sha256(Path(__file__)):
            raise RuntimeError("Runner changed after completed run; review before reuse")
        for relative, expected in record["files_sha256"].items():
            if sha256(directory / relative) != expected:
                raise RuntimeError(f"Changed pilot evidence: {name}/{relative}")
    else:
        if directory.exists():
            raise RuntimeError(f"Partial run exists, inspect before retry: {directory}")
        directory.mkdir(parents=True)
        route = ET.parse(ROOT / "frozen/inputs/baseline_rendered.rou.xml")
        for vt in route.getroot().findall("vType"):
            vt.set("tau", f"{tau:g}")
        route.write(directory / "routes.rou.xml", encoding="utf-8", xml_declaration=True)
        additional = ET.Element("additional")
        ET.SubElement(additional, "edgeData", id="traffic", period="300", excludeEmpty="true", file="traffic_edges.xml")
        ET.SubElement(additional, "edgeData", id="emissions", type="emissions", period="300", excludeEmpty="true", file="emission_edges.xml")
        ET.ElementTree(additional).write(directory / "additional.xml", encoding="utf-8", xml_declaration=True)
        config = ET.Element("configuration")
        groups = {
            "input": {"net-file": str(ROOT / "frozen/inputs/network.net.xml"), "route-files": "routes.rou.xml", "additional-files": "additional.xml"},
            "output": {"summary-output": "summary.xml", "tripinfo-output": "tripinfo.xml", "tripinfo-output.write-unfinished": "true", "tripinfo-output.write-undeparted": "true", "statistic-output": "statistics.xml", "collision-output": "collisions.xml"},
            "time": {"begin": "0", "end": "3600", "step-length": f"{step:g}"},
            "processing": {"step-method.ballistic": "false", "default.action-step-length": f"{action:g}", "default.carfollowmodel": "Krauss", "collision.action": "teleport", "collision.stoptime": "0", "collision.check-junctions": "false", "collision.mingap-factor": "-1", "time-to-teleport": "300", "time-to-teleport.remove": "false", "max-depart-delay": "-1", "insertion-checks": "all"},
            "report": {"xml-validation": "never", "no-step-log": "true", "duration-log.disable": "true"},
            "random_number": {"seed": str(seed)},
        }
        for group, values in groups.items():
            node = ET.SubElement(config, group)
            for key, value in values.items():
                ET.SubElement(node, key, value=value)
        ET.indent(config)
        ET.ElementTree(config).write(directory / "run.sumocfg", encoding="utf-8", xml_declaration=True)
        command = [str(SUMO), "-c", "run.sumocfg"]
        start = time.perf_counter()
        with (directory / "sumo_stdout.log").open("w", encoding="utf-8") as out, (directory / "sumo_stderr.log").open("w", encoding="utf-8") as err:
            result = subprocess.run(command, cwd=directory, stdout=out, stderr=err, timeout=900)
        elapsed = time.perf_counter() - start
        if result.returncode:
            raise RuntimeError(f"SUMO failed with {result.returncode}: {directory}")
        audit_run(directory)
        record = {"runner_sha256": sha256(Path(__file__)), "command": command, "cwd": str(directory),
                  "finished_utc": datetime.now(timezone.utc).isoformat(), "wall_s": elapsed,
                  "files_sha256": {p.name: sha256(p) for p in directory.iterdir() if p.is_file()}}
        complete.write_text(json.dumps(record, indent=2), encoding="utf-8")
    row = audit_run(directory)
    row.update({"tau_s": tau, "step_s": step, "action_step_s": action, "wall_s": record["wall_s"],
                "tau_at_least_both_intervals": tau >= max(step, action)})
    print(f"{name}: arrived={row['end_arrived']}, TP={row['teleport_events']}, wall={record['wall_s']:.1f}s", flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-runs", type=int, default=36)
    args = parser.parse_args()
    freeze_protocol()
    rows = []
    for seed in SEEDS:
        for tau_group in (TAUS[:2], TAUS[2:]):
            for step, action in SETTINGS:
                for tau in tau_group:
                    if len(rows) >= args.max_runs:
                        return
                    rows.append(run_one(tau, step, action, seed))
                    write_csv(PILOT / "timepilot_results.csv", rows)
                    if (tau, step, action, seed) == (1.0, 1.0, 1.0, 42):
                        if rows[-1]["end_arrived"] != 6629 or abs(rows[-1]["trip_completed_timeLoss_mean_s"] - 148.07666616382562) > 1e-7:
                            raise RuntimeError("Baseline reproduction failed; do not launch matrix")


if __name__ == "__main__":
    main()
