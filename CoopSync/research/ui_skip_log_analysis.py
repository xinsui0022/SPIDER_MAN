"""Analyze existing OverlayUI JSONL only; never opens or records a game process.

Checks saved identity/slot markers against the pinned object evidence, and maps
accepted nonzero callback pointers back to the pinned EXE for static decoding.
Intent labels and directory names are never treated as proof of a manual skip.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from cinematic_static_probe import Image, GAME, EXPECTED_SHA256, OBJDUMP, disassemble, parse_instructions
from cinematic_runtime_probe import path_equal
from ui_skip_probe import unwind_chain


ROOT = Path(__file__).resolve().parent
VTABLES = {"0x0": 0x4F44980, "0x158": 0x4F449E0}
FIELD_SIZES = {"0x210": 1, "0x214": 4, "0x220": 8, "0x228": 8}


def analyze(source):
    blob = source.read_bytes()
    rows, malformed = [], []
    lines = blob.decode("utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            malformed.append(index + 1)
    sessions = [r for r in rows if r.get("record_type") == "overlay_ui_session"]
    if len(sessions) != 1:
        raise ValueError("Expected exactly one OverlayUI session record")
    metadata = sessions[0]
    if metadata.get("game_sha256") != EXPECTED_SHA256 or not path_equal(metadata.get("game_path", ""), GAME):
        raise ValueError("Saved session does not identify the pinned build/path")
    if metadata.get("status") != "ready" or metadata.get("process_path_verified") is not True:
        raise ValueError("Saved session did not pass the runtime setup gates")
    base, module_size = int(metadata["module_base"], 16), metadata["module_size"]
    samples = [r for r in rows if r.get("record_type") == "overlay_ui_snapshot"]
    accepted, rejected = [], []
    previous_state = None
    transitions = []
    callbacks = {}
    for row in samples:
        reason = None
        if row.get("status") != "overlay_identity_match_slots_stable_raw_only" or row.get("slots_stable_during_reads") is not True:
            reason = "snapshot not accepted by sampler"
        elif row.get("object_rva") != "0x7b84580":
            reason = "unexpected object RVA"
        else:
            vtables = {r["offset"]: r for r in row.get("vtables", [])}
            if set(vtables) != set(VTABLES) or len(row.get("vtables", [])) != 2:
                reason = "missing or unexpected vtable record"
            else:
                for offset, target in VTABLES.items():
                    vt = vtables[offset]
                    if (vt.get("expected_rva") != hex(target) or vt.get("actual") != hex(base + target) or
                            vt.get("actual_after") != hex(base + target) or vt.get("identity_match") is not True or
                            vt.get("stable_during_reads") is not True):
                        reason = "dual vtable identity/stability markers fail independent log recheck"
        fields = {f["offset"]: f for f in row.get("raw_fields", [])}
        if reason is None and (set(fields) != set(FIELD_SIZES) or len(row["raw_fields"]) != len(FIELD_SIZES)):
            reason = "unexpected field set"
        if reason is None:
            try:
                for offset, size in FIELD_SIZES.items():
                    if fields[offset].get("size") != size or len(bytes.fromhex(fields[offset]["raw_hex"])) != size:
                        reason = "field size/raw encoding mismatch"
                for offset in ("0x220", "0x228"):
                    raw_value = int.from_bytes(bytes.fromhex(fields[offset]["raw_hex"]), "little")
                    if fields[offset].get("pointer_value") != hex(raw_value):
                        reason = "pointer value/raw bytes mismatch"
            except (ValueError, KeyError):
                reason = "invalid raw field encoding"
        if reason:
            rejected.append({"sample": row.get("sample"), "reason": reason})
            continue
        accepted.append(row)
        state = tuple(fields[offset]["raw_hex"] for offset in FIELD_SIZES)
        if state != previous_state:
            transitions.append({"sample": row["sample"], "monotonic_ms": row["monotonic_ms"],
                                "raw_state": dict(zip(FIELD_SIZES, state))})
        previous_state = state
        callback = int(fields["0x220"]["pointer_value"], 16)
        if callback:
            entry = callbacks.setdefault(callback, {"pointer_value": hex(callback), "first_sample": row["sample"],
                                                     "last_sample": row["sample"], "sample_count": 0, "context_values": set()})
            entry["sample_count"] += 1
            entry["last_sample"] = row["sample"]
            entry["context_values"].add(fields["0x228"]["pointer_value"])
    image = None
    for callback, entry in callbacks.items():
        entry["context_values"] = sorted(entry["context_values"])
        if not base <= callback < base + module_size:
            entry["static_mapping"] = {"status": "outside main module; no module or context scanned"}
            continue
        if image is None:
            image = Image(GAME)
            if hashlib.sha256(image.blob).hexdigest() != EXPECTED_SHA256:
                raise ValueError("Pinned file changed; callback static decoding refused")
        rva = callback - base
        function = image.function(rva)
        mapping = {"status": "saved stable pointer mapped to on-disk PE; not a callable-interface validation",
                   "callback_rva": hex(rva), "location": image.location(rva), "executable_section": image.executable(rva),
                   "pdata_fragment": function, "unwind_chain": unwind_chain(image, rva)}
        if image.executable(rva):
            start = int(function["begin_rva"], 16) if function else rva
            stop = int(function["end_rva"], 16) if function else rva + 0x200
            mapping["decode_start_rva"] = hex(start)
            mapping["instructions"] = parse_instructions(image, disassemble(image, OBJDUMP, start, stop))
            mapping["decode_limit"] = "Existing objdump cap 0x4000 bytes; .pdata can be a fragment; leaf entry candidate without .pdata remains unproved"
        entry["static_mapping"] = mapping
    human_path = source.parent / "human_reports.jsonl"
    human_reports = []
    if human_path.exists():
        for line in human_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                human_reports.append(json.loads(line))
    return {"schema": 1, "scope": "saved-log analysis and pinned EXE static decoding only; no process access",
            "source": str(source.resolve()), "source_bytes": len(blob), "source_sha256_at_analysis": hashlib.sha256(blob).hexdigest(),
            "capture_has_terminal_record": any(r.get("record_type") == "end" for r in rows),
            "malformed_line_numbers": malformed, "session_pid": metadata.get("pid"), "module_base": hex(base),
            "sample_count": len(samples), "accepted_sample_count": len(accepted), "rejected_samples": rejected,
            "first_sample": samples[0].get("sample") if samples else None, "last_sample": samples[-1].get("sample") if samples else None,
            "status_counts": dict(Counter(r.get("status") for r in samples)),
            "distinct_raw_fields": {offset: sorted({f["raw_hex"] for r in accepted for f in r["raw_fields"] if f["offset"] == offset}) for offset in FIELD_SIZES},
            "state_transitions": transitions, "nonzero_callback_targets": list(callbacks.values()),
            "callback_abi_static_observation": "OverlayUI callsite 0x1D22C94 loads RCX from +0x228 then 0x1D22C9B calls +0x220; no further arguments verified",
            "manual_action_evidence": "No skip/action claim derived from intent labels, directory names, null slots or pointer transitions alone",
            "human_report_receipts": human_reports,
            "human_context_from_saved_receipts": [r.get("report") for r in human_reports],
            "coverage_interpretation": "User receipt times are not exact event/load times. No cutscene/skip claim follows from intent labels or raw slots. Retained cinematic memory does not establish an active scene",
            "verified_callable_interfaces": []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "ui_skip_manual_capture_analysis.json")
    args = parser.parse_args()
    result = analyze(args.input)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    md = "# OverlayUI 手动测试记录的只读分析\n\n"
    md += f"来源：`{result['source']}`。本次读取 {result['source_bytes']} 字节，SHA-256 `{result['source_sha256_at_analysis']}`。"
    md += "已捕获结束记录。\n\n" if result["capture_has_terminal_record"] else "采集尚未出现结束记录，本报告是当前检查点。\n\n"
    md += f"共 {result['sample_count']} 个样本，独立复核后接受 {result['accepted_sample_count']} 个；最后 sample `{result['last_sample']}`。接受条件包含固定对象 RVA、双虚表值/前后稳定标记、精确字段集合及指针与原始字节一致性。\n\n"
    md += "| 字段 | 已接受样本的不同原始字节 |\n| --- | --- |\n"
    for offset, values in result["distinct_raw_fields"].items():
        md += f"| `{offset}` | `{' / '.join(values)}` |\n"
    md += f"\n稳定非零回调目标数量：**{len(result['nonzero_callback_targets'])}**。已核验可调用接口数量：**0**。\n\n"
    if result["nonzero_callback_targets"]:
        md += "非零目标的 PE 节、`.pdata`、unwind 链及有限静态指令解码保存在同名 JSON；模块内地址仍不构成可执行/可调用 ABI 核验。\n\n"
    md += "人工报告只作为 receipt 保存：\n\n"
    for receipt in result["human_report_receipts"]:
        md += f"- `{receipt.get('receipt_utc')}`：{receipt.get('report')}。事件时间状态：{receipt.get('event_time_status')}；skip_verified=`{receipt.get('skip_verified')}`。\n"
    md += "\n这些 receipt 不是精确加载、播放或跳过时刻。当前零槽不能证明没有过场；保留的任务/电影对象内存也不能证明存在活动场景。目录的 manual-skip 意图标签不证明玩家实际播放或跳过。分析器只读保存文件；不启动记录器，不打开游戏进程，不解引用上下文或执行游戏函数。\n"
    args.output.with_suffix(".md").write_text(md, encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("capture_has_terminal_record", "sample_count", "accepted_sample_count", "last_sample",
                                                 "distinct_raw_fields", "nonzero_callback_targets")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
