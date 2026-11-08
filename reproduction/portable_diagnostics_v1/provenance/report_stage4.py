"""Summarize completed warning-policy experiments and measurement limits."""
import json
import math
import statistics
import difflib
import re
from datetime import datetime, timezone
from pathlib import Path

from audit_core_warnings import read_csv
from audit_metrics import write_csv, warning_metrics
from freeze_submission import sha256
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "stage4_warning_audit"
POLICY = ROOT / "warning_policy_check"


def change(value, baseline):
    return 100 * (float(value) / float(baseline) - 1)


def estimate(values):
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    half = 4.302652729911275 * sd / math.sqrt(3)
    return {"n_seeds": 3, "mean": mean, "sample_sd": sd,
            "ci95_lower_exploratory": mean - half, "ci95_upper_exploratory": mean + half}


def main():
    old_rows = read_csv(OUT / "core_run_results_corrected.csv")
    new_rows = read_csv(POLICY / "run_results.csv")
    assert len(old_rows) == 9 and len(new_rows) == 12
    old = {(r["scenario"], int(r["seed"])): r for r in old_rows}
    new = {(r["scenario"], int(r["seed"])): r for r in new_rows if r["policy_s"] == "-1"}
    checks = []
    for row in new_rows:
        directory = Path(row["source_dir"])
        record = json.loads((directory / "complete.json").read_text())
        for name, digest in record["files_sha256"].items():
            if sha256(directory / name) != digest:
                raise RuntimeError(f"Completed output changed: {directory / name}")
        checks.append({"run": row["run"], "sha256_verified": True,
                       "loaded_equals_inserted_plus_waiting": int(row["end_loaded"]) == int(row["end_inserted"]) + int(row["end_waiting"]),
                       "inserted_accounted": float(row["unaccounted_inserted_end"]) == 0,
                       "control_status": row["measurement_control"]})
    assert all(r["loaded_equals_inserted_plus_waiting"] and r["inserted_accounted"] for r in checks)
    for seed in (42, 2024, 2025):
        for key in ("end_arrived", "end_inserted", "end_waiting", "end_running", "total_vehicle_hours_discrete"):
            assert old["baseline", seed][key] == new["baseline", seed][key]
    paired, summaries = [], []
    metrics = {"throughput": "end_arrived", "completed_delay": "trip_completed_timeLoss_mean_s",
               "total_vehicle_hours": "total_vehicle_hours_discrete", "entry_vehicle_hours": "entry_vehicle_hours_discrete"}
    for scenario in ("heavyveh_very_high", "weather_heavy_rain"):
        for seed in (42, 2024, 2025):
            a, b = old[scenario, seed], new[scenario, seed]
            row = {"scenario": scenario, "seed": seed,
                   "Q_policy300": a["end_arrived"], "Q_no_gridlock_teleport": b["end_arrived"],
                   "TP_policy300": a["teleport_events"], "TP_no_gridlock_teleport": b["teleport_events"],
                   "collisions_policy300": a["stat_safety_collisions"], "collisions_no_gridlock_teleport": b["stat_safety_collisions"],
                   "affected_unique_policy300": a["teleported_unique_vehicles"], "affected_unique_no_gridlock_teleport": b["teleported_unique_vehicles"]}
            for metric, key in metrics.items():
                row[metric + "_effect_policy300_pct"] = change(a[key], old["baseline", seed][key])
                row[metric + "_effect_no_gridlock_pct"] = change(b[key], new["baseline", seed][key])
                row[metric + "_policy_shift_pp"] = row[metric + "_effect_no_gridlock_pct"] - row[metric + "_effect_policy300_pct"]
            for population in ("inserted", "waiting", "running"):
                row[population + "_policy300"] = a["end_" + population]
                row[population + "_no_gridlock"] = b["end_" + population]
            paired.append(row)
        group = [r for r in paired if r["scenario"] == scenario]
        for metric in metrics:
            for outcome in ("effect_policy300_pct", "effect_no_gridlock_pct", "policy_shift_pp"):
                key = metric + "_" + outcome
                summaries.append({"scenario": scenario, "metric": metric, "outcome": outcome,
                                  **estimate([r[key] for r in group]),
                                  "interval_scope": "paired-seed Student t with df=2; exploratory conditional interval, not equivalence or field validation"})
    write_csv(OUT / "policy_integrity_checks.csv", checks)
    write_csv(OUT / "policy_paired_effects.csv", paired)
    write_csv(OUT / "policy_summary.csv", summaries)
    lookup = {(r["scenario"], r["metric"], r["outcome"]): r for r in summaries}
    hv_old = lookup["heavyveh_very_high", "throughput", "effect_policy300_pct"]["mean"]
    hv_new = lookup["heavyveh_very_high", "throughput", "effect_no_gridlock_pct"]["mean"]
    rain_old = lookup["weather_heavy_rain", "throughput", "effect_policy300_pct"]["mean"]
    rain_new = lookup["weather_heavy_rain", "throughput", "effect_no_gridlock_pct"]["mean"]
    audit = json.loads((OUT / "audit_checks.json").read_text())
    green = json.loads((OUT / "green_window_checks.json").read_text())
    # Historical files are not rewritten; keep a new warning-only re-audit.
    historical = []
    for row in read_csv(ROOT / "audit/historical_run_audit.csv"):
        directory = Path(row["source_dir"])
        historical.append({"run": row["run"], "source_dir": str(directory),
                           **warning_metrics(directory / "sumo_stderr.log")})
    write_csv(OUT / "historical_warning_reaudit.csv", historical)
    report = f"""Scientific Reports 大修：第四阶段进展（2026-10-20）
本文件报告已完成的警告敏感性和测量核查，不是最终修回稿。

一、完成12次新增运行
3次原300秒策略的测量控制：移除被动检测器后，基线、重车、暴雨的种子42输出均复现，包括吞吐、车辆积压、延误、总车辆小时和警告。
9次策略敏感性：基线、24%重车、暴雨各3种子；关闭等待超时传送，但保留路口碰撞检查及碰撞传送处理。
所有运行的文件哈希与车辆守恒检查通过。未修改冻结的原始网络或投稿ZIP。

二、少量传送不能直接当作“无影响”
重车相对各自同种子基线的平均吞吐变化：原策略{hv_old:.2f}%，关闭等待超时传送后{hv_new:.2f}%；平均差{hv_new-hv_old:.2f}个百分点。
暴雨对应为{rain_old:.2f}%和{rain_new:.2f}%；平均差{rain_new-rain_old:.2f}个百分点。
新策略三个种子的基线输出不变。重车的碰撞次数变为4、2、2；暴雨为0、1、0。关闭等待超时传送不等于关闭碰撞传送，也不是得到“无伪影真值”。
恶化方向保留，但不能以少量警告为由给出完全有效或安全的结论。策略敏感性、碰撞事件、不同车辆群体均应随结果报告。
所有区间按3个配对种子计算Student t区间（自由度2），仅为条件性探索区间，不是等效性证明。

三、事件和车道计数核查
重点场景原9次运行共{audit['teleport_events']}次传送，其中{audit['collision_events']}次为碰撞触发；与碰撞XML及统计输出吻合。
修正了2条侧向碰撞的类别归属，未改传送总数或吞吐。
SUMO 1.24源码显示，车道出口left计数也包含传送离开。扣除该计数后，477组车道-运行对照中{audit['matches_after_subtracting_teleport_departures']}组与E1前缘过线计数一致。
仍保留暴雨种子42的ED2.378_0两辆残差，两车均有此前传送记录；没有删除或强行调平。

四、车道级证据的边界
已核查{green['complete_protected_windows']}个完整保护绿灯窗口，其中{green['queue_supported_windows']}个满足绿灯前检测到队列及无相位歧义的初步条件。
剔除窗口前4次过线并要求相邻过线期间持续检测到队列后，得到{green['operational_headway_pairs']}对运行车头时距。这些不是独立重复实验，也不是已验证的饱和车头时距。
下游接收空间尚无逐时验证，E2仅覆盖进口最后至多100米，因此不估计饱和流率。当前应使用“实测于仿真中的保护绿灯服务率/周期过线量”，不再借此验证解析容量。

五、修稿执行结论
R1.3：新增警告策略敏感性，不能再写“小量传送可以忽略”。
R1.4/R2.1：新增直接过线与周期队列证据，并保留计数差异和测量范围。
R2.5/R3.2：原有重车/天气撤销扰动只作一致性检查；干预失败不等于机制判断被否定。
下一阶段重点是同任务诊断规则与消融、隐藏或混合原因的保留测试，以及维持不利条件的独立干预。尚未完成独立人工盲测、全场景新配置重跑、最终主文合并和公共仓库发布。
"""
    (ROOT / "第四阶段修稿进展.txt").write_text(report, encoding="utf-8")
    english = f"""STAGE 4 RESPONSE DRAFT: COMPLETED EVIDENCE ONLY, NOT A FINAL RESPONSE LETTER

Reviewer 1, comment 3: warning screening
We agree that a small event count is not sufficient to establish that a simulation outcome is unaffected by warnings. We separated waiting-triggered teleports from collision-triggered teleports and cross-checked the latter against the collision event output and safety statistics. A matched-seed sensitivity check disabled the 300 s waiting-triggered teleport policy while preserving collision detection, collision handling, routes, timing and demand. Three detector-removal controls reproduced the original instrumented results exactly for the selected seed; nine additional runs tested the changed waiting-teleport policy over three matched seeds. The mean heavy-vehicle throughput response changed from {hv_old:.2f}% to {hv_new:.2f}%, and the heavy-rain response from {rain_old:.2f}% to {rain_new:.2f}%. The baseline was unchanged for all three seeds. Collision events remained, and the heavy-vehicle count increased in two seeds. Consequently, we report these outcomes as conditional warning-sensitive evidence, not as warning-free or safety-validated results. Full classification rules and integration across the revised scenario set remain outstanding.

Reviewers 1 and 2: direct service measurements
Lane-end front-entry events were compared with an independent lane-output channel. For SUMO 1.24, the latter increments its departure count for teleport departures as well as downstream movement. After explicitly separating these departures, 476 of 477 lane-run combinations agreed. A two-vehicle residual remained on ED2.378_0 in one heavy-rain run; both front-entry records involved vehicles with prior teleport events. The residual was retained rather than forced to agree. Complete protected-green windows and queue-supported operational headways were then tabulated, including an exploratory exclusion of the first four passages in each eligible window. Downstream receiving space has not been resolved at the same temporal scale. We therefore report observed service rates and cycle-level counts, not saturation flow or validation of the analytical capacity model.

Reviewer 2, comment 5 and reviewer 3, comment 2: counterfactual scope
Reducing heavy-vehicle share and reversing a weather component reuse the perturbation structure. They will be described as reversal consistency checks, not independent verification of a causal mechanism. The unsuccessful cycle-preserving timing probe shows that this particular response was ineffective under its retained yellow intervals and reduced green opportunity. It does not invalidate the diagnosis of lost service time. New interventions that retain the adverse condition are still required before this request can be marked complete.

Statistical scope
Each response is calculated relative to the baseline with the same seed and policy. Policy differences are paired differences in those percentage responses, expressed in percentage points. Exploratory 95% intervals use the sample standard deviation of the three paired observations and a Student t multiplier with two degrees of freedom. An interval overlapping zero is not taken as evidence of equivalence. Cycle windows and individual headways are descriptive repeated observations, not additional independent simulation replicates.

Evidence: stage4_warning_audit/policy_paired_effects.csv, policy_summary.csv, teleport_event_audit.csv, collision_event_audit.csv, lane_count_reconciliation.csv, protected_green_windows.csv, lane_green_service_summary.csv.
"""
    (ROOT / "revision_drafts/stage4_response_and_methods.txt").write_text(english, encoding="utf-8")
    manuscript = ROOT / "manuscript_working"
    pdf = manuscript / "main.pdf"
    log = (manuscript / "main.log").read_text(encoding="utf-8", errors="replace")
    if re.search(r"LaTeX Warning:.*(?:undefined|multiply defined)|Overfull \\hbox", log):
        raise RuntimeError("Resolve manuscript reference/overflow warnings before recording integration")
    pdf_pages = len(PdfReader(pdf).pages)
    snapshot = (ROOT / "audit/main_before_stage4.tex").read_text(encoding="utf-8")
    current = (manuscript / "main.tex").read_text(encoding="utf-8")
    (ROOT / "audit/stage4_manuscript.diff").write_text("".join(difflib.unified_diff(
        snapshot.splitlines(True), current.splitlines(True), fromfile="main_before_stage4.tex", tofile="main.tex")), encoding="utf-8")
    integration = {"working_pdf_pages": pdf_pages, "pdf_sha256": sha256(pdf),
                   "main_source_sha256": sha256(manuscript / "main.tex"),
                   "audit_section_sha256": sha256(manuscript / "revision_audit_stage4.tex"),
                   "status": "partial working manuscript only; not submission-ready",
                   "completed": ["time-setting and warning-policy section, paired intervals and cycle plot inserted",
                                 "main prose headway terminology corrected",
                                 "reversal checks and failed-intervention interpretation narrowed",
                                 "comparison table now uses a common diagnostic task"],
                   "remaining": ["legacy image lettering and embedded SI not yet regenerated",
                                 "full scenario numerical settings and primary score/model revision incomplete",
                                 "frozen-rule held-out/ablation tests and independent interventions outstanding"]}
    (ROOT / "audit/stage4_manuscript_integration.json").write_text(json.dumps(integration, indent=2), encoding="utf-8")
    with (ROOT / "第四阶段修稿进展.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"\n六、已写入工作稿\n工作稿已编译为{pdf_pages}页（包含附录）。新增设置/警告策略审计、配对区间和周期图，并修改摘要、贡献、反事实解释、方法比较与结论。主文文字已统一期望时间间距术语。旧图内部标签和嵌入式SI尚未同步，因此不是最终修回版。最终编译无未定义引用或横向溢出警告。\n")
    tracker = read_csv(ROOT / "reviewer_tracker.csv")
    updates = {
        "R1.3": ("12-run policy sensitivity and event-level collision/teleport audit completed; small counts not declared harmless.", "Freeze operational warning rules; integrate full scenario set and test sensitivity beyond three seeds."),
        "R1.4": ("53-lane direct front-entry and protected-green measurements; 476/477 count comparisons reconcile after separating teleport departures; residual retained.", "Demonstrate incremental diagnostic value; do not claim saturation flow without downstream receiving checks."),
        "R2.1": ("Cycle-level crossing/queue figure and protected-green window audit completed.", "Consolidate manuscript figures, remove duplicates and integrate uncertainty panels."),
        "R1.5": ("Main prose uses desired time headway; old and revised configuration results separated in the working manuscript.", "Regenerate legacy figure/SI terminology; finish units and scope audit across the full revision."),
        "R2.5": ("Working manuscript now treats perturbation reversals as consistency checks and failed retiming as intervention failure, not rejected diagnosis.", "Test independent interventions that retain adverse conditions; regenerate the response framework artwork."),
        "R2.7": ("Method comparison table changed to a shared multi-metric diagnostic task without inaccurate claims about OAT.", "Complete quantitative same-task ablations and held-out evaluation."),
        "R3.2": ("Circular verification claims narrowed in working abstract, contributions, results, captions and conclusion.", "Independent interventions retaining the adverse condition are not yet completed."),
    }
    for row in tracker:
        if row["id"] in updates:
            row["status"] = "partial"
            row["completed_evidence"], row["remaining_work"] = updates[row["id"]]
    write_csv(ROOT / "reviewer_tracker.csv", tracker)
    status_path = ROOT / "revision_status.json"
    status = json.loads(status_path.read_text())
    status.update(stage="D warning-policy sensitivity and lane-window audit complete; main revision pending",
                  updated_utc=datetime.now(timezone.utc).isoformat(),
                  complete_revision_runs_excluding_debug=56, stage4_new_policy_runs=12,
                  low_count_warning_sensitivity_complete=True,
                  saturation_flow_validated=False, main_revision_complete=False,
                  partial_main_integration=True, working_pdf_pages=pdf_pages,
                  next="Frozen same-task diagnostic rules, held-out mixed-case tests and ablations; independent adverse-condition interventions. No claim of independent human blinding.")
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps({"heavy_vehicle_effects": [hv_old, hv_new], "rain_effects": [rain_old, rain_new],
                      "completed_policy_runs": len(new_rows), "green_window_audit": green}, indent=2))


if __name__ == "__main__":
    main()
