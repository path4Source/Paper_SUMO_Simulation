"""Recheck all historical summaries and expose the complete original OAT population."""
import csv
import json
from pathlib import Path
from audit_metrics import summary_metrics, write_csv
from run_horizon_v1 import ROOT, OUT, sha


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    audit = read(ROOT / "audit/historical_run_audit.csv")
    manifests = {r["path"]: r for r in read(ROOT / "audit/raw_output_manifest.csv")}
    scenarios = read(ROOT / "score_revision_v1/source_inputs/sumo_oat_results.csv")
    result = []
    for old in audit:
        path = Path(old["source_dir"]) / "summary.xml"
        assert sha(path) == manifests[str(path)]["sha256"]
        new = summary_metrics(path, 0, 3600, float(old["step_s"]))
        for k, v in new.items():
            if k in old and old[k] != "":
                assert abs(float(old[k])-float(v)) < 1e-6, (old["run"], k)
        assert new["end_loaded"] == int(old["planned_flow_vehicles"])
        assert new["end_loaded"] == new["end_inserted"] + new["end_waiting"]
        assert new["end_inserted"] == new["end_arrived"] + new["end_running"] + new["unaccounted_inserted_end"]
        result.append(dict(run=old["run"], seed=int(old["seed"]),
                           planned=new["end_loaded"], inserted=new["end_inserted"], arrived=new["end_arrived"],
                           entry_waiting=new["end_waiting"], in_network=new["end_running"],
                           active_remainder=new["unaccounted_inserted_end"],
                           entry_vehicle_hours=new["entry_vehicle_hours_discrete"],
                           network_vehicle_hours=new["network_vehicle_hours_discrete"],
                           burden_vehicle_hours=new["total_vehicle_hours_discrete"],
                           inserted_mean_depart_delay_s=new["entry_mean_delay_inserted_s"],
                           completed_mean_time_loss_s=float(old["trip_completed_timeLoss_mean_s"]),
                           teleport_events=int(old["teleport_events"]),
                           source_summary_sha256=sha(path)))
    lookup = {r["run"]: r for r in result}
    oat = []
    for scenario in scenarios:
        row = lookup[scenario["scenario"]]
        assert row["seed"] == 42
        assert row["arrived"] == int(float(scenario["arrived_vehicles"]))
        oat.append(dict(scenario=scenario["scenario"], factor=scenario["factor"], level=scenario["level"], **row))
    assert len(oat) == 27 and len(result) == 240
    write_csv(OUT / "legacy_all_population_audit.csv", result)
    write_csv(OUT / "legacy_oat_population_audit.csv", oat)
    (OUT / "legacy_recheck.json").write_text(json.dumps(dict(historical_summaries_rechecked=240,
        original_oat_rows=27, matches_original_counts=True, raw_hashes_unchanged=True,
        scope="Summary integrals cover 0-3600 s and include insertion waiting; completed-trip means remain population-limited; teleport travel is not restored"), indent=2))
    print("Verified 240 raw summary hashes/integrals; exported all 27 OAT populations")


if __name__ == "__main__":
    main()
