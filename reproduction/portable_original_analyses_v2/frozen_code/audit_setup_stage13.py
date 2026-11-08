"""Extract original/revision settings and vehicle definitions from saved inputs."""
import csv
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from audit_metrics import embedded_config, write_csv
from freeze_submission import sha256
from run_timepilot import ROOT, SUMO

OUT = ROOT / "configuration_lineage_v1"
OPTIONS = [
    "step-length", "default.action-step-length", "step-method.ballistic", "default.carfollowmodel",
    "collision.action", "collision.stoptime", "collision.check-junctions", "collision.mingap-factor",
    "time-to-teleport", "time-to-teleport.remove", "max-depart-delay", "insertion-checks",
    "tripinfo-output.write-unfinished", "tripinfo-output.write-undeparted",
]
VEHICLE_KEYS = ["accel", "decel", "sigma", "length", "minGap", "maxSpeed", "tau",
                "actionStepLength", "vClass", "emissionClass", "guiShape"]
TAU_SOURCE_URL = "https://raw.githubusercontent.com/eclipse-sumo/sumo/v1_24_0/src/microsim/cfmodels/MSCFModel.cpp"


def values(path):
    return {e.tag: e.attrib["value"] for e in ET.parse(path).getroot().iter() if "value" in e.attrib}


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def resolve(cfg, defaults):
    row = {}
    for name in OPTIONS:
        row[name] = cfg.get(name, defaults[name])
        row[name + "_source"] = "explicit" if name in cfg else "SUMO 1.24.0 option default"
    action = float(row["default.action-step-length"])
    row["resolved_global_action_s"] = action if action > 0 else float(row["step-length"])
    return row


def resolved_vehicle(attrs):
    result = dict(attrs)
    result["tau"] = float(attrs.get("tau", "1.0"))
    return result


def check_vehicle_versions(scenario, versions):
    reference = {k: resolved_vehicle(v) for k, v in versions[0].items()}
    if any({k: resolved_vehicle(v) for k, v in version.items()} != reference
           for version in versions[1:]):
        raise RuntimeError(f"Resolved vehicle parameters differ across original seeds: {scenario}")
    return any(version != versions[0] for version in versions[1:])


def main():
    template = OUT / "sumo_124_option_template.xml"
    tau_source = OUT / "SUMO_v1_24_0_MSCFModel.cpp"
    if "getCFParam(SUMO_ATTR_TAU, 1.0)" not in tau_source.read_text(encoding="utf-8"):
        raise RuntimeError("Version-specific desired-headway default not verified")
    defaults = values(template)
    source_rows = read(ROOT / "frozen/data/sumo_multiseed_results.csv")
    if len(source_rows) != 81:
        raise RuntimeError("Unexpected original OAT scope")
    setting_rows, vehicle_rows, flow_rows, manifests = [], [], [], []
    per_scenario = defaultdict(list)
    for source in source_rows:
        scenario, seed = source["scenario"], int(source["seed"])
        name = scenario if seed == 42 else source["scenario_run"]
        directory = ROOT.parent / "road_capacity_sci/outputs/sumo_runs" / name
        cfg = embedded_config(directory / "summary.xml")
        root = ET.parse(directory / "routes.rou.xml").getroot()
        if any("actionStepLength" in v.attrib for v in root.findall("vType")):
            raise RuntimeError("Vehicle action override needs explicit reporting")
        setting_rows.append({"series": "original_OAT", "run": name, "seed": seed,
                             "begin_s": cfg["begin"], "end_s": cfg["end"], **resolve(cfg, defaults)})
        types = {v.attrib["id"]: dict(v.attrib) for v in root.findall("vType")}
        per_scenario[scenario].append(types)
        for type_id, attrs in types.items():
            vehicle_rows.append({"scenario": scenario, "seed": seed, "vehicle_type": type_id,
                                 "resolved_tau_s": resolved_vehicle(attrs)["tau"],
                                 "tau_source": "explicit" if "tau" in attrs else "SUMO 1.24.0 default",
                                 **{k: attrs.get(k, "not explicitly assigned") for k in VEHICLE_KEYS}})
        for flow in root.findall("flow"):
            a = flow.attrib
            flow_rows.append({"scenario": scenario, "seed": seed, "flow": a["id"], "type": a["type"],
                              "planned": int(a["number"]), "begin": a["begin"], "end": a["end"],
                              "departLane": a.get("departLane", "not explicitly assigned"),
                              "departSpeed": a.get("departSpeed", "not explicitly assigned")})
        manifests.append({"run": name, "routes_sha256": sha256(directory / "routes.rou.xml"),
                          "summary_sha256": sha256(directory / "summary.xml")})
    explicit_default_differences = [
        scenario for scenario, versions in per_scenario.items()
        if check_vehicle_versions(scenario, versions)
    ]
    signatures = {tuple(r[k] for k in OPTIONS) for r in setting_rows}
    if len(signatures) != 1:
        raise RuntimeError("Original OAT global settings not uniform")
    if {r["departLane"] for r in flow_rows} != {"free"} or {r["departSpeed"] for r in flow_rows} != {"max"}:
        raise RuntimeError("Departure settings not uniform")

    examples = {
        "compatible_headway_0.1": ROOT / "stage3_settings/runs/tau0.8_dt0.1_action0.1_seed42_junctions0/run.sumocfg",
        "intervention_reference_0.1": ROOT / "connector_audit_v1/runs/fine_joint_seed11/run.sumocfg",
        "morris_0.1": ROOT / "morris_screening_v1/runs/control_seed11/run.sumocfg",
    }
    for series, path in examples.items():
        cfg = values(path)
        setting_rows.append({"series": series, "run": path.parent.name,
                             "seed": int(cfg["seed"]), "begin_s": cfg["begin"],
                             "end_s": cfg["end"], **resolve(cfg, defaults)})
        manifests.append({"run": path.parent.name, "config_sha256": sha256(path)})
    write_csv(OUT / "global_settings.csv", setting_rows)
    write_csv(OUT / "original_vehicle_definitions.csv", vehicle_rows)
    write_csv(OUT / "original_departure_settings.csv", flow_rows)

    selected = [("Baseline passenger", "baseline", "car"),
                ("Heavy-vehicle archetype", "heavyveh_very_high", "truck"),
                ("Rain passenger", "weather_rain", "car"),
                ("Heavy-rain passenger", "weather_heavy_rain", "car")]
    lines = [
        "% Generated from actual original route definitions and saved option defaults.",
        r"\begin{table}[!htbp]",
        r"\caption{Original vehicle definitions, with effective values verified across the three OAT seeds. Values are parameters of assumed simulator archetypes, not calibrated fleet measurements. Maximum speed is a vehicle-type limit, not the desired-speed distribution. The desired-headway value is 1~s whether explicitly assigned or inherited from the SUMO 1.24.0 default; the shorter/longer-headway scenarios explicitly set 0.8/1.4~s.}",
        r"\label{tab:vehicle_definitions_audit}",
        r"\centering",
        r"\begin{tabularx}{\textwidth}{Zrrrrrrr}",
        r"\toprule",
        r"Type/condition & \shortstack{Max speed\\(m/s)} & \shortstack{Accel.\\(m/s$^2$)} & \shortstack{Decel.\\(m/s$^2$)} & $\sigma$ & \shortstack{Length\\(m)} & \shortstack{Gap\\(m)} & $\tau$ (s) \\",
        r"\midrule",
    ]
    selection = []
    for label, scenario, type_id in selected:
        attrs = per_scenario[scenario][0][type_id]
        selection.append({"label": label, **attrs,
                          "resolved_tau_s": resolved_vehicle(attrs)["tau"],
                          "tau_source": "explicit" if "tau" in attrs else "SUMO 1.24.0 default"})
        vals = [f"{float(attrs[k]):.3f}".rstrip("0").rstrip(".")
                for k in ["maxSpeed", "accel", "decel", "sigma", "length", "minGap"]]
        vals.append(f"{resolved_vehicle(attrs)['tau']:g}")
        lines.append(" & ".join([label] + vals) + r" \\")
    lines.extend([
        r"\bottomrule", r"\end{tabularx}", r"\end{table}", "",
        r"All original OD flows specify free departure-lane selection and maximum admissible departure speed. Planned counts are split deterministically into passenger and heavy-vehicle flows within each OD pair; no heavy vehicles occur in the baseline or weather-only scenarios. Neither vehicle class nor emission class is explicitly assigned to the heavy-vehicle archetype. Its dynamics, dimensions, and graphical shape therefore do not constitute a calibrated freight fleet or heavy-duty emissions specification.",
        "",
        r"The original OAT series uses the SUMO 1.24.0 defaults of a 1~s simulation step, action updates every step, semi-implicit Euler integration, Krauss car following, collision-triggered teleportation without a stopping interval, and a 300~s waiting-teleport threshold. Junction collision checks are disabled by default. Insertion checks remain enabled and delayed insertion is not discarded. These are resolved software defaults, not options explicitly specified in every archived run.",
        "",
        r"The compatible-headway comparisons change both simulation and action intervals to 0.5/0.5~s or 0.1/0.1~s with explicit ballistic integration, while retaining the original junction-check setting. The separate local-measurement and warning-policy audits enable junction collision checks; their primary step/action setting is 0.5/0.5~s. The five-seed intervention, finite-cohort horizon extension, and Morris experiment use explicit 0.1/0.1~s intervals and junction checks. Except in the separately labeled waiting-teleport-disabled audit, collision teleportation and the 300~s waiting threshold are retained. Every original one-hour comparison starts from an empty network without a discarded warm-up; the horizon extension retains the same finite demand cohort rather than continuing demand to 7200~s.",
        "",
    ])
    output = ROOT / "manuscript_working/revision_setup_details_stage13.tex"
    output.write_text("\n".join(lines), encoding="utf-8")
    manifest = {
        "finished_utc": datetime.now(timezone.utc).isoformat(), "original_runs": len(source_rows),
        "original_unique_global_settings": len(signatures), "vehicle_records": len(vehicle_rows),
        "departure_records": len(flow_rows), "selected_definitions": selection,
        "scenarios_with_explicit_vs_default_tau": explicit_default_differences,
        "tau_default_source_url": TAU_SOURCE_URL, "tau_default_source_sha256": sha256(tau_source),
        "sources": manifests, "sumo_sha256": sha256(SUMO), "defaults_sha256": sha256(template),
        "script_sha256": sha256(Path(__file__)), "generated_tex_sha256": sha256(output),
        "new_simulations": 0,
        "documentation": "https://sumo.dlr.de/docs/Simulation/Safety.html",
        "remaining": "Full final cross-reference/figure terminology checks deferred; no calibration or causal-validation claim.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ["original_runs", "original_unique_global_settings",
                                             "vehicle_records", "departure_records", "selected_definitions"]}, indent=2))


if __name__ == "__main__":
    main()
