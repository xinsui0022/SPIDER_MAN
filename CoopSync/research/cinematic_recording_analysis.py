"""Offline analysis of saved Cinematic2/task observations. No process access.

Can read a growing JSONL prefix: a partial final line is reported and omitted.
Writes only its two independent research reports, never changes recorder logs.
Selection-slot zero/nonzero is deliberately not treated as playback/end.
"""
from __future__ import annotations

import argparse
import bisect
import collections
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from cinematic_runtime_probe import EXPECTED_SHA256, COMPONENT_VTABLE_RVA, FIELDS

ROOT = Path(__file__).resolve().parent
DEFAULT = ROOT.parent / "logs/runtime_manual_skip_20261010_returned"


def read_prefix(path):
    raw = path.read_bytes()
    lines = raw.decode("utf-8-sig").splitlines(keepends=True)
    rows, omitted = [], False
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if number == len(lines) and not line.endswith(("\n", "\r")):
                omitted = True
                break
            raise
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{number}: non-object record")
        rows.append(row)
    return rows, {"path": str(path), "captured_bytes": len(raw), "captured_sha256": hashlib.sha256(raw).hexdigest(),
                  "complete_records": len(rows), "partial_trailing_line_omitted": omitted}


def task_map(row):
    result = {}
    for task in row.get("tasks", []):
        mission = (task.get("mission_id_raw"), task.get("mission_name_raw"))
        result[(*mission, None)] = task.get("state_raw")
        for objective in task.get("objectives", []):
            result[(*mission, objective.get("name_raw"))] = objective.get("state_raw")
    return result


def compact_component(row):
    return {"sample": row["sample"], "monotonic_ms": row["monotonic_ms"],
            "component_pointer": row["component_slot"]["value"], "actual_vtable": row["component_slot"]["actual_vtable"],
            "raw_fields": {field["offset"]: field["unsigned_value"] for field in row["runtime_state_fields"]}}


def analyze(directory, human_reports_path=None):
    cinematic, cine_file = read_prefix(directory / "cinematic.jsonl")
    missions, task_file = read_prefix(directory / "missions.jsonl")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
    sources = [cine_file, task_file]
    human_reports = []
    human_paths = list(dict.fromkeys(path for path in (human_reports_path, directory / "human_reports.jsonl") if path is not None))
    for human_path in human_paths:
        if human_path.is_file():
            human_rows, human_file = read_prefix(human_path)
            human_reports.extend({"source": str(human_path), **row} for row in human_rows)
            sources.append(human_file)
    session = next((row for row in cinematic if row.get("record_type") == "session"), {})
    snapshots = [row for row in cinematic if row.get("record_type") == "snapshot"]
    end = next((row for row in reversed(cinematic) if row.get("record_type") == "end"), None)
    problems = []
    if session.get("game_sha256") != EXPECTED_SHA256:
        problems.append("cinematic_build_not_pinned")
    if any(row.get("game_sha256") != EXPECTED_SHA256 for row in missions if row.get("game_attached")):
        problems.append("mission_build_not_pinned")
    pids = {row.get("pid") for row in missions if row.get("game_attached")}
    pids.add(session.get("pid"))
    if None in pids or len(pids) != 1:
        problems.append("observer_pid_mismatch_or_missing")
    expected_vtable = int(session.get("module_base", "0"), 0) + COMPONENT_VTABLE_RVA
    desired = {hex(offset): count for offset, count, unused in FIELDS}
    stable, unstable_samples = [], []
    object_mismatch_samples, owner_unrechecked_samples, slot_invalid_samples, raw_invalid_samples = [], [], [], []
    times, sample_indices = [], []
    for row in snapshots:
        times.append(row.get("monotonic_ms"))
        sample_indices.append(row.get("sample"))
        slot = row.get("component_slot") or {}
        if any(obj.get("identity_match") is False or obj.get("stable_during_reads") is False for obj in row.get("objects", [])):
            object_mismatch_samples.append(row.get("sample"))
        if any("stable_during_reads" not in obj for obj in row.get("objects", [])):
            owner_unrechecked_samples.append(row.get("sample"))
        if row.get("status") == "component_changed_during_reads":
            unstable_samples.append(row.get("sample"))
            if row.get("runtime_state_fields"):
                raw_invalid_samples.append(row.get("sample"))
        if row.get("status") != "component_identity_match_raw_state_only":
            continue
        try:
            assert slot.get("identity_match") and slot.get("stable_during_reads")
            assert int(slot["value"], 0) != 0 and int(slot["actual_vtable"], 0) == expected_vtable
            assert int(slot["vtable_after"], 0) == expected_vtable
            assert len(row.get("objects", [])) == 2
            assert all(obj.get("identity_match") and obj.get("stable_during_reads") for obj in row["objects"])
        except (AssertionError, KeyError, TypeError, ValueError):
            slot_invalid_samples.append(row.get("sample"))
            continue
        fields = row.get("runtime_state_fields", [])
        try:
            assert len(fields) == len(desired)
            assert {field["offset"]: field["size"] for field in fields} == desired
            assert all(len(bytes.fromhex(field["raw_hex"])) == field["size"] and
                       int.from_bytes(bytes.fromhex(field["raw_hex"]), "little") == field["unsigned_value"] for field in fields)
        except (AssertionError, KeyError, TypeError, ValueError):
            raw_invalid_samples.append(row.get("sample"))
            continue
        stable.append(compact_component(row))
    if any(not isinstance(value, int) or isinstance(value, bool) for value in times) or times != sorted(times):
        problems.append("invalid_or_nonmonotonic_component_time")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in sample_indices):
        problems.append("invalid_sample_index")
    elif sample_indices != list(range(len(sample_indices))):
        problems.append("sample_index_gap_or_duplicate")
    for label, values in (("static_object_identity_or_stability_issue", object_mismatch_samples),
                          ("stable_component_slot_invalid", slot_invalid_samples), ("raw_field_payload_invalid", raw_invalid_samples)):
        if values:
            problems.append(label)
    raw_changes, component_changes = [], []
    groups = {}
    for index, row in enumerate(stable):
        pointer = row["component_pointer"]
        group = groups.setdefault(pointer, {"component_pointer": pointer, "stable_samples": 0,
                                           "first_observed": row, "last_observed": row, "raw_value_sets": {key: set() for key in desired}})
        group["stable_samples"] += 1
        group["last_observed"] = row
        for key, value in row["raw_fields"].items():
            group["raw_value_sets"][key].add(value)
        if not index:
            continue
        previous = stable[index - 1]
        gap = row["sample"] - previous["sample"] - 1
        if pointer != previous["component_pointer"]:
            component_changes.append({"before": previous, "after": row, "intervening_samples": gap,
                                      "meaning": "different observed object address only; not a stable cinematic ID"})
        elif row["raw_fields"] != previous["raw_fields"]:
            changed = {key: {"before": previous["raw_fields"][key], "after": value}
                       for key, value in row["raw_fields"].items() if previous["raw_fields"][key] != value}
            raw_changes.append({"before": previous, "after": row, "changed_fields": changed, "intervening_samples": gap,
                                "meaning": "raw value transition candidate; playback/skip/end meaning unverified"})
    for group in groups.values():
        group["raw_value_sets"] = {key: sorted(values) for key, values in group["raw_value_sets"].items()}
    attached_tasks = [row for row in missions if row.get("game_attached")]
    task_times = [row.get("monotonic_ms") for row in attached_tasks]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in task_times) or task_times != sorted(task_times):
        problems.append("invalid_or_nonmonotonic_task_time")
    task_changes = []
    previous_tasks = None
    stable_times = [row["monotonic_ms"] for row in stable]
    task_observations = []
    for row in attached_tasks:
        current = task_map(row)
        task_observations.append({"monotonic_ms": row.get("monotonic_ms"), "utc": row.get("utc"),
                                  "task_subset_sha256": row.get("task_subset_sha256"), "tasks": row.get("tasks", [])})
        if previous_tasks is not None:
            changed = [{"mission_id_raw": key[0], "mission_name_raw": key[1], "objective_name_raw": key[2],
                        "before_raw": previous_tasks.get(key), "after_raw": current.get(key)}
                       for key in sorted(previous_tasks.keys() | current.keys(), key=str) if previous_tasks.get(key) != current.get(key)]
            position = bisect.bisect_left(stable_times, row["monotonic_ms"])
            task_changes.append({"monotonic_ms": row["monotonic_ms"], "changed_items": changed,
                                 "stable_component_before": stable[position - 1] if position else None,
                                 "stable_component_after": stable[position] if position < len(stable) else None,
                                 "before_distance_ms": row["monotonic_ms"] - stable_times[position - 1] if position else None,
                                 "after_distance_ms": stable_times[position] - row["monotonic_ms"] if position < len(stable) else None,
                                 "meaning": "time ordering with explicit distances only; no causal skip/end claim"})
        previous_tasks = current
    intervals = [after - before for before, after in zip(times, times[1:])] if "invalid_or_nonmonotonic_component_time" not in problems else []
    patterns = collections.Counter(json.dumps(row["changed_fields"], sort_keys=True) for row in raw_changes)
    human_outcomes = [row["human_reported_outcome"] for row in human_reports if row.get("human_reported_outcome")]
    receipt_windows = []
    for human in human_reports:
        receipt = human.get("receipt_monotonic_ms")
        if not isinstance(receipt, int):
            continue
        near = [row for row in snapshots if abs(row.get("monotonic_ms", receipt + 100000) - receipt) <= 1000]
        receipt_windows.append({"receipt_monotonic_ms": receipt, "window_radius_ms": 1000, "samples": len(near),
                                "status_counts": dict(collections.Counter(row["status"] for row in near)),
                                "slot_value_counts": dict(collections.Counter((row.get("component_slot") or {}).get("value", "not_sampled") for row in near)),
                                "limitation": "receipt adjacency only; retrospective exact gameplay event time is unknown"})
    return {"schema": 1, "generated_utc": datetime.now(timezone.utc).isoformat(), "recording_directory": str(directory),
            "manifest": manifest, "source_prefixes": sources, "human_reports": human_reports,
            "human_reported_outcomes": human_outcomes, "human_receipt_windows": receipt_windows,
            "capture_complete": end is not None and manifest.get("status") == "observations_recorded",
            "pid": session.get("pid"), "game_sha256": session.get("game_sha256"), "component_end_record": end,
            "quality_problems": problems, "snapshots": len(snapshots), "stable_component_samples": len(stable),
            "status_counts": dict(collections.Counter(row["status"] for row in snapshots)),
            "selection_slot_value_counts": dict(collections.Counter((row.get("component_slot") or {}).get("value", "not_sampled") for row in snapshots)),
            "component_time_span_ms": times[-1] - times[0] if times and "invalid_or_nonmonotonic_component_time" not in problems else None,
            "sampling_intervals_ms": {"minimum": min(intervals), "maximum": max(intervals), "over_250ms": sum(v > 250 for v in intervals)} if intervals else {},
            "unstable_samples": unstable_samples, "component_groups": list(groups.values()),
            "owner_stability_not_rechecked_samples": owner_unrechecked_samples,
            "raw_state_changes": raw_changes, "observed_component_address_changes": component_changes,
            "repeated_raw_transition_patterns": [{"changed_fields": json.loads(pattern), "count": count} for pattern, count in patterns.items() if count >= 2],
            "task_observations": task_observations, "task_changes": task_changes,
            "verified_callable_interfaces": [], "skip_verified": False, "cinematic_start_end_verified": False,
            "stable_cinematic_id_verified": False, "scene_ready_verified": False, "full_world_sync_verified": False,
            "limitations": ["manual-skip is recording intent; no confirmed manual skip or visual playback event is embedded here",
                            "human reports describe earlier menu/uncertain launch and later loaded objective; receipt timestamps are not exact event times",
                            "retained SECURITY_COUNTDOWN task data before human load confirmation does not prove a currently loaded scene",
                            "zero/nonzero selection slot is not a start/end signal; absent selected component creates an observation gap",
                            "same address does not prove one lifetime or stable ID; raw before/after candidates can cross gaps",
                            "missions observer emits changes only at one-second polling; unchanged live state and observer liveness need separate evidence",
                            "task subset digest is not complete world state; time adjacency is not causality"]}


def markdown(report):
    manifest = report["manifest"]
    lines = ["# 用户返回后的组件/任务实录", "", f"生成时间：`{report['generated_utc']}`。来源：`{report['recording_directory']}`。",
             "", f"记录标签 `{manifest.get('label')}` 仅表示意图；当前记录状态 `{manifest.get('status')}`，完整结束记录 `{report['capture_complete']}`。",
             "没有操作游戏或重新启动记录器；分析器只读取已保存的 JSONL，PID/hash 与样本稳定性作为证据门控。",
             "", f"PID `{report['pid']}`；固定构建 SHA-256 `{report['game_sha256']}`。",
             "", f"组件样本 {report['snapshots']}，时间跨度 {report['component_time_span_ms']}ms，稳定非空组件样本 {report['stable_component_samples']}。",
             f"状态计数：`{json.dumps(report['status_counts'])}`。", f"选择槽值计数：`{json.dumps(report['selection_slot_value_counts'])}`。",
             f"质量问题：`{json.dumps(report['quality_problems'])}`；采样中组件变化 {len(report['unstable_samples'])} 次，这些样本不用于字段判断。",
             f"另有 {len(report['owner_stability_not_rechecked_samples'])} 个失稳样本在字段读取前停下，未再复核 owner；缺少复核记录不等于 owner vtable 实际不匹配。",
             "", "## 人工状态补充", "",
             "任务保留数据不能独立证明已进入/正在关卡。人工状态如有收据则列在下方，时间均为消息收据时间，不能作为精确加载、播放或跳过时刻。"]
    for row in report["human_reports"]:
        lines += ["", f"- 收据 monotonic `{row.get('receipt_monotonic_ms')}` / UTC `{row.get('receipt_utc')}`：{row.get('report')}（{row.get('event_time_status')}）。"]
    if "natural_end_without_skip_option" in report["human_reported_outcomes"]:
        lines += ["", "用户已报告该段剧情自然结束、没有跳过选项、随后恢复战斗。可以保留这个人工自然结束事实；没有执行手动跳过，manual-skip 标签仍是原始记录意图。"]
    else:
        lines += ["", "人工结果如未给出则仍等待确认；manual-skip 标签不升级为完成事件。"]
    for row in report["human_receipt_windows"]:
        if row["samples"]:
            lines += ["", f"收据 `{row['receipt_monotonic_ms']}` 前后各 1 秒捕获 {row['samples']} 个组件样本：`{json.dumps(row['status_counts'])}`，槽值 `{json.dumps(row['slot_value_counts'])}`。只对齐收据，不能当作精确剧情起止。"]
    lines += [
             "", "## 稳定组件与原始字段", "", "| 组件指针 | 稳定样本 | 首末样本 | 原始值集合 |", "|---|---|---|---|"]
    for row in report["component_groups"]:
        lines.append(f"| `{row['component_pointer']}` | {row['stable_samples']} | {row['first_observed']['sample']}..{row['last_observed']['sample']} | `{json.dumps(row['raw_value_sets'])}` |")
    lines += ["", f"同地址稳定样本的字段变化 {len(report['raw_state_changes'])} 次；稳定组件地址变化 {len(report['observed_component_address_changes'])} 次；重复出现至少两次的同字段变化模式 {len(report['repeated_raw_transition_patterns'])} 个。",
              "槽清零/重选只记为选择变化，不能标注播放开始/结束。原始状态 10 不命名为 Playing。相同地址也不能证明组件完整生命期或跨端稳定 cinematic_id。",
              "", "## 任务记录与时间邻近", "", f"任务观察记录 {len(report['task_observations'])} 条，相邻任务记录中发生变化 {len(report['task_changes'])} 次。任务观察器以一秒间隔轮询且仅输出变化；最后一条记录不等于该时刻之后的持续心跳。"]
    for index, row in enumerate(report["task_observations"]):
        active_raw = [obj["name_raw"] for task in row["tasks"] for obj in task["objectives"] if obj["state_raw"] == 1]
        lines += ["", f"任务记录 {index}：monotonic `{row['monotonic_ms']}`，digest `{row['task_subset_sha256']}`；state_raw=1 项：`{json.dumps(active_raw)}`。"]
    for row in report["task_changes"]:
        before_distance = f"{row['before_distance_ms']}ms" if row["before_distance_ms"] is not None else "未观测"
        after_distance = f"{row['after_distance_ms']}ms" if row["after_distance_ms"] is not None else "未观测"
        lines += ["", f"任务变化时间 `{row['monotonic_ms']}`：`{json.dumps(row['changed_items'], ensure_ascii=False)}`。",
                  f"最近前/后稳定组件样本：`{(row['stable_component_before'] or {}).get('sample')}` / `{(row['stable_component_after'] or {}).get('sample')}`；距离 {before_distance} / {after_distance}，不能把长观察空缺当作紧邻关系。"]
    lines += ["", "## 可复查结论", ""]
    if not report["raw_state_changes"] and not report["task_changes"]:
        lines += ["该已捕获前缀尚未出现稳定原始字段变化或任务变化，无法提出可重复的过场前/后组合。"]
    elif "natural_end_without_skip_option" in report["human_reported_outcomes"]:
        lines += ["用户报告了自然结束事实，JSON 保存任务推进和最近稳定样本；但组件字段没有前后变化，播放/结束收据附近均为空选择槽。现有候选不足以构造自动开始/结束检测，更没有手动跳过验证。"]
    else:
        lines += ["JSON 中保存了原始字段/任务变化及最近稳定样本，供继续对照；尚不能给原始字段赋予 skip 或 completion 语义。"]
    lines += ["没有经过验证的跳过接口、过场开始/结束接口、稳定 ID、场景就绪或完整世界同步证据；`verified_callable_interfaces=[]`，所有验收标志保持 false。",
              "", "## 复现", "", "```powershell", "& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\cinematic_recording_analysis.py", "```",
              "", "记录期间可以重新生成报告以捕获新前缀；报告写入独立 research 文件，不改原始日志。JSON 保存源前缀字节数/hash、字段转换、指针身份与任务变化。"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, default=DEFAULT)
    parser.add_argument("--output-stem", type=Path, default=ROOT / "cinematic_recording_returned_20261010")
    parser.add_argument("--human-reports", type=Path, help="Optional explicit human receipt source from another recording")
    parser.add_argument("--watch", action="store_true", help="Watch saved logs only; emits meaningful raw/task changes or completion")
    parser.add_argument("--watch-seconds", type=int, default=330, help="1..600 second bounded offline watch")
    args = parser.parse_args()
    if not 1 <= args.watch_seconds <= 600:
        parser.error("watch-seconds must be in 1..600")
    deadline = time.monotonic() + args.watch_seconds
    previous = None
    while True:
        report = analyze(args.recording.resolve(), args.human_reports)
        meaningful = {"capture_complete": report["capture_complete"], "manifest_status": report["manifest"].get("status"),
                      "human_reports": report["human_reports"],
                      "raw_state_changes": report["raw_state_changes"], "task_changes": report["task_changes"],
                      "observed_component_address_changes": report["observed_component_address_changes"],
                      "component_value_sets": {row["component_pointer"]: row["raw_value_sets"] for row in report["component_groups"]},
                      "quality_problems": report["quality_problems"]}
        signature = json.dumps(meaningful, sort_keys=True)
        if signature != previous or not args.watch or time.monotonic() >= deadline:
            args.output_stem.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            args.output_stem.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
            print(json.dumps({"snapshots": report["snapshots"], "stable_component_samples": report["stable_component_samples"],
                              **meaningful, "skip_verified": False}, ensure_ascii=False), flush=True)
            previous = signature
        if not args.watch or report["capture_complete"] or time.monotonic() >= deadline:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
