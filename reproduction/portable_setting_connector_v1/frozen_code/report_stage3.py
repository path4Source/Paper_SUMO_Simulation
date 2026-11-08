"""Build an evidence-linked stage report and draft revision text."""
import csv
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from audit_metrics import write_csv
from freeze_submission import sha256

ROOT = Path(__file__).resolve().parents[1]


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def interval(values):
    mean, sd = statistics.mean(values), statistics.stdev(values)
    half = 4.302652729911275 * sd / math.sqrt(3)
    return mean, mean - half, mean + half


def main():
    settings = read_csv(ROOT / "stage3_settings/settings_results.csv")
    core = read_csv(ROOT / "core_detector_batch/run_results.csv")
    assert len(settings) == 15 and len(core) == 9
    raw_manifest = {r["path"]: r["sha256"] for r in read_csv(ROOT / "audit/raw_output_manifest.csv")}
    core_protocol = json.loads((ROOT / "audit/core_detector_batch_protocol.json").read_text())
    for scenario in ("heavyveh_very_high", "weather_heavy_rain"):
        source = core_protocol["routes"][scenario]
        assert source["sha256"] == raw_manifest[source["source"]], "Adverse route changed since historical freeze"
    integrity = []
    for row in settings + core:
        directory = Path(row["source_dir"])
        record = json.loads((directory / "complete.json").read_text())
        for name, digest in record["files_sha256"].items():
            assert sha256(directory / name) == digest, f"Changed evidence {directory / name}"
        assert int(row["end_loaded"]) == int(row["end_inserted"]) + int(row["end_waiting"]) == 7900
        assert int(row["end_inserted"]) == int(row["end_arrived"]) + int(row["end_running"])
        assert int(row["trip_records"]) == 7900
        integrity.append({"run": row["run"], "output_hashes_passed": True, "vehicle_accounting_passed": True})
    write_csv(ROOT / "stage3_settings/integrity_checks.csv", integrity)
    matched, summary = [], []
    for step in (0.5, 0.1):
        chosen = [r for r in settings if float(r["step_s"]) == step and float(r["action_step_s"]) == step and r["junction_check"] == "False"]
        lookup = {(int(r["seed"]), float(r["tau_s"])): r for r in chosen}
        for seed in (42, 2024, 2025):
            b, t = lookup[seed, 1.0], lookup[seed, 0.8]
            pair = {"step_s": step, "action_step_s": step, "seed": seed,
                    "baseline_Q": b["end_arrived"], "short_headway_Q": t["end_arrived"],
                    "baseline_TP": b["teleport_events"], "short_headway_TP": t["teleport_events"]}
            for name, key in (("Q", "end_arrived"), ("completed_delay", "trip_completed_timeLoss_mean_s"),
                              ("total_vehicle_hours", "total_vehicle_hours_discrete")):
                pair[name + "_change_pct"] = 100 * (float(t[key]) - float(b[key])) / float(b[key])
            matched.append(pair)
        for metric in ("Q_change_pct", "completed_delay_change_pct", "total_vehicle_hours_change_pct"):
            values = [r[metric] for r in matched if r["step_s"] == step]
            mean, lo, hi = interval(values)
            summary.append({"step_s": step, "action_s": step, "metric": metric,
                            "mean": mean, "ci95_lower_exploratory": lo, "ci95_upper_exploratory": hi,
                            "n_matched_seeds": 3, "scope": "conditional exploratory paired t interval, not numerical convergence"})
    write_csv(ROOT / "stage3_settings/paired_effects.csv", matched)
    write_csv(ROOT / "stage3_settings/paired_summary.csv", summary)
    q_effect = {r["step_s"]: r for r in summary if r["metric"] == "Q_change_pct"}
    clock = read_csv(ROOT / "stage3_phase_alignment/clock_alignment_checks.csv")
    aligned = sum(int(r["direct_notification_records"]) for r in clock)
    old_changes = sum(int(r["direct_old_phase_disagreements"]) for r in clock)
    ambiguous = sum(int(r["phase_ambiguous_records"]) for r in clock)
    measurements = json.loads((ROOT / "core_detector_batch/analysis_checks.json").read_text())
    main_summary = read_csv(ROOT / "core_detector_batch/paired_summary.csv")
    main_q = {r["scenario"]: r for r in main_summary if r["metric"] == "throughput_change_pct"}
    warning_ranges = {}
    for scenario in ("baseline", "heavyveh_very_high", "weather_heavy_rain"):
        group = [r for r in core if r["scenario"] == scenario]
        tp = [int(r["teleport_events"]) for r in group]
        collision = [int(float(r["stat_safety_collisions"])) for r in group]
        warning_ranges[scenario] = {"tp_min": min(tp), "tp_max": max(tp),
                                    "collisions_min": min(collision), "collisions_max": max(collision)}
    report = [
        "Scientific Reports 大修：第三阶段进展（2026-10-20）",
        "这是实验与测量核查进展，不是最终修回稿。",
        "",
        "一、已完成的工作",
        "1. 上轮后台的13次新配置实验全部完成；与复用的2次对照组成15个检查案例，没有重新运行已完成的数据。",
        "2. 完成三个种子下的0.5/0.5秒与0.1/0.1秒步长/决策间隔对照，采用显式ballistic积分；基线和tau=0.8共12次运行（6对同种子比较）均记录0碰撞、0传送。急刹车记录仍保留，不据此声称绝对安全。",
        f"3. tau从1.0改为0.8时，0.5/0.5配置的平均吞吐变化为{q_effect[0.5]['mean']:+.2f}%，0.1/0.1配置为{q_effect[0.1]['mean']:+.2f}%。这些是各自配置内的配对变化，不能混写为纯步长效应。",
        "4. 种子42的两个基线开启路口碰撞检查后，吞吐及警告数不变。固定决策间隔0.5秒而将步长设为0.25秒时，基线出现74次非碰撞传送，尚不能宣称固定行为设置下数值已收敛。",
        f"5. 用{aligned}条含同事件stay记录的过线事件核对处理步与相位时钟，修正{old_changes}条旧向下取整相位映射。其余记录按版本对应的插值机制映射，保留{ambiguous}条真正可能跨相位的边界记录，不强制归类。",
        "",
        "二、已推进到重点场景复跑",
        "采用ballistic、0.5秒步长/决策间隔、开启路口碰撞检查，完成基线、24%重车、暴雨各3个种子，共9次检测器复跑。原始不利场景参数与需求保留；未把旧版结果直接当作新结果。",
        f"24%重车相对新配对基线的平均吞吐变化：{float(main_q['heavyveh_very_high']['mean']):+.2f}%。",
        f"暴雨相对新配对基线的平均吞吐变化：{float(main_q['weather_heavy_rain']['mean']):+.2f}%。",
        f"警告范围（传送次数）：基线{warning_ranges['baseline']['tp_min']}–{warning_ranges['baseline']['tp_max']}，重车{warning_ranges['heavyveh_very_high']['tp_min']}–{warning_ranges['heavyveh_very_high']['tp_max']}，暴雨{warning_ranges['weather_heavy_rain']['tp_min']}–{warning_ranges['weather_heavy_rain']['tp_max']}。",
        "重车与暴雨仍存在少量警告，因此这批结果保留警告标记，不称为完全无污染结果，也不据三个种子强行确定两者先后排名。",
        f"测量输出：{measurements['lane_run_pairs']}个车道-运行组合，其中{measurements['exact_count_matches']}组E1过线计数与车道出口计数完全一致；最大差额为{measurements['max_abs_count_difference']}辆。",
        f"已生成{measurements['complete_lane_cycles']}条完整车道-周期记录。它们用于放行与检测范围内排队诊断，不是现场饱和流率。",
        "",
        "三、论文需要据此修改的地方",
        "tau应解释为期望时间间距参数，不能与仿真步长、决策间隔或生理反应时间混为一谈。",
        "Q增加、完成车辆延误下降本身不能被标成artifact；应结合警告、车辆守恒和未完成/未插入车辆负担判断。兼容设置下的小幅正响应与原设置下的大量碰撞传送必须分开报告。",
        "旧的整条边绿灯并集不能继续代替所有车道的绿灯机会；新表按实际车道及相位处理。",
        "正文拟用方法与结果段落已保存为revision_drafts/stage3_methods_and_results.txt，尚未把新旧数据混装成最终PDF。",
        "",
        "四、下一步",
        "对重车/暴雨的少量警告补敏感性审计，并检查队列存在、启动过程及下游阻塞，再形成主文车道级证据。",
        "随后实施冻结规则后的诊断盲测、同任务消融及保持不利条件的干预验证。这些审稿要求尚未完成。",
        "仍需完整主场景配置验证、全文数据替换、图表更新、逐条回复和复现包发布。当前没有向期刊提交。"
    ]
    (ROOT / "第三阶段修稿进展.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    drafts = ROOT / "revision_drafts"
    drafts.mkdir(exist_ok=True)
    text = f"""DRAFT REVISION TEXT: EVIDENCE COMPLETE ONLY FOR THE LISTED BATCHES
Not yet integrated into the manuscript. Original figures and numerical tables must not be silently combined with these results.

Methods: temporal settings
The parameter tau specifies the desired time headway in the car-following model; it is not interchangeable with either the numerical simulation step or the interval between vehicle decisions. We therefore record all three quantities together with the positional integration method. The original shorter-headway case used tau=0.8 s with a 1 s step, whereas the revised exploratory checks used explicit ballistic integration and equal step/action intervals of 0.5 s or 0.1 s. Comparisons of tau were paired within each numerical and behavioral setting and random seed. Jointly reducing the step and action interval changes both numerical resolution and behavioral update frequency, so these checks are not described as a pure numerical-convergence test.

Methods: lane-resolved measurement
Passive detectors were placed at the ends of all 53 signal-controlled external incoming lanes. Front-entry events were distinguished from subsequent detector-leave events, and repeated entries with identical detector, vehicle and timestamp were counted once with their multiplicity retained for audit. Vehicle-front counts were cross-checked against a separate lane-exit output channel. Signal phase assignment used the simulation processing step associated with the event, rather than a floor lookup of the interpolated entry timestamp. Ambiguous rounded boundary events were retained explicitly. Protected and permissive green states were distinguished. Lane-area observations cover at most the final 100 m of each incoming lane and therefore do not necessarily measure the full upstream queue. No saturation-flow estimate is inferred without further queue-present, startup and downstream-blocking checks.

Results: headway and timing audit
Across three matched seeds, reducing tau from 1.0 to 0.8 s increased route-completion throughput by a mean of {q_effect[0.5]['mean']:.2f}% under the 0.5/0.5 s setting and {q_effect[0.1]['mean']:.2f}% under the 0.1/0.1 s setting. These twelve runs had no recorded collisions or teleports, although emergency-braking events remained. This contrasts with the warning-dominated apparent gain under the original incompatible timing. A positive throughput response combined with lower completed-trip delay is therefore not, by itself, evidence of a simulation artifact. At a fixed 0.5 s action interval, the intermediate 0.25 s numerical step still produced noncollision teleports; the study does not claim that decreasing the time step automatically establishes convergence.

Results: focused adverse-scenario transfer
The first instrumented transfer batch used explicit ballistic integration, a 0.5 s step and action interval, junction collision checks, and three matched random seeds. Relative to the newly simulated baseline, the original 24% heavy-vehicle and heavy-rain parameterizations changed mean throughput by {float(main_q['heavyveh_very_high']['mean']):.2f}% and {float(main_q['weather_heavy_rain']['mean']):.2f}%, respectively. Both directions remained adverse, but low-count warning events persisted. These outcomes are reported together with event causes, unique affected vehicles, unfinished populations and total vehicle-hours including insertion waiting; they are not treated as warning-free evidence or a definitive ordering of the two factors. The three-seed intervals are exploratory and conditional on the specified case and settings.

Outstanding before final use
Low-count warning sensitivity, queue/startup/blocking eligibility, full scenario reruns, frozen-rule diagnostic tests and ablations remain necessary. This draft does not claim they have been performed.
"""
    (drafts / "stage3_methods_and_results.txt").write_text(text, encoding="utf-8")
    tracker = read_csv(ROOT / "reviewer_tracker.csv")
    updates = {
        "R1.4": ("partial", "53-lane instrumentation, notification-clock correction and nine focused detector reruns completed; see core_detector_batch analysis checks.", "Queue-present/startup/blocking eligibility, low-warning sensitivity and incremental diagnostic benefit."),
        "R2.2": ("partial", "Three-seed matched tau checks at two equal-step/action settings completed; desired-headway method wording drafted.", "Integrate terminology and revise all figures/tables; do not claim pure time-step convergence."),
        "R2.4": ("partial", "Compatible timing produced small positive Q responses without recorded teleports; draft now explicitly rejects quadrant-only artifact labeling.", "Redraw main diagnostic figures and implement frozen evidence rules/ablation."),
        "R3.3": ("partial", "15 setting checks (13 new), two junction-check baselines, and 9 main-scenario transfer reruns complete.", "Complete setting qualification, low-warning sensitivity and horizon/warm-up evidence."),
        "R3.4": ("partial", "New batch writes all planned trips; waiting/running/count accounting and paired total vehicle-hours included.", "Carry complete-population metrics into the full scenario matrix and final manuscript."),
        "R3.6": ("partial", "Paired three-seed exploratory t intervals generated; no forced heavy-vehicle/weather ordering.", "Predeclared broader seed precision and requested global-sensitivity design remain open.")
    }
    for row in tracker:
        if row["id"] in updates:
            row["status"], row["completed_evidence"], row["remaining_work"] = updates[row["id"]]
    write_csv(ROOT / "reviewer_tracker.csv", tracker)
    response = ["WORKING EVIDENCE RECORD, NOT A SUBMISSION-READY RESPONSE", "Outstanding experiments and manuscript edits are not represented as complete."]
    for row in tracker:
        response.append(f"\n{row['id']}\nReviewer comment: {row['comment_verbatim']}\nStatus: {row['status']}\nCompleted evidence: {row['completed_evidence'] or 'None yet.'}\nRemaining work: {row['remaining_work']}\nFinal response locations: Pending full revision.")
    (ROOT / "response_to_reviewers_working.txt").write_text("\n".join(response), encoding="utf-8")
    status = {"updated_utc": datetime.now(timezone.utc).isoformat(), "stage": "C settings checks and focused detector transfer complete; manuscript integration pending",
              "historical_runs_audited": 240, "complete_revision_runs_excluding_debug": 44,
              "stage3_new_setting_runs": 13, "focused_core_runs": 9,
              "phase_alignment_method_checked": True, "phase_ambiguity_retained": True,
              "focused_setting": "ballistic, step/action 0.5 s, junction checks on; provisional transfer setting, not convergence proof",
              "saturation_flow_validated": False, "main_revision_complete": False, "public_release_complete": False,
              "next": "low-warning sensitivity and queue/blocking eligibility, then frozen-rule blind tests and ablations"}
    (ROOT / "revision_status.json").write_text(json.dumps(status, indent=2))
    print(json.dumps({"settings_Q_effects": q_effect, "core_warning_ranges": warning_ranges, "measurement_checks": measurements}, indent=2))


if __name__ == "__main__":
    main()
