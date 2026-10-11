"""File-only pinned-build Cinematic2 notification/resource evidence.

No process access, hooks, injection, game calls, network, or game-file writes.
Writes only cinematic_native_next.json/md beside this script. Requires local
Python 3.11 with pefile and the existing local objdump executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from cinematic_static_probe import (
    Image, GAME, EXPECTED_SHA256, OBJDUMP, cstring, disassemble,
    parse_instructions, enum_descriptor,
)
from ui_skip_probe import unwind_chain, vtable_identity

ROOT = Path(__file__).resolve().parent
MAX_FRAGMENT_SEARCH_BYTES = 0x4000
MAX_FUNCTION_FRAGMENTS = 64
# Explicitly excludes the command dispatcher's embedded switch table.
RANGES = (
    ("Component initialization and Prius asset-ID binding", 0x165F2F0, 0x165F722),
    ("Triggered command target: requests raw state, resolves resource", 0x1668150, 0x16683D3),
    ("Command dispatcher: full entry through RET; no inline jump table", 0x166A320, 0x166A6DF),
    ("Conditional component notification forwarder", 0x166B890, 0x166B8FC),
    ("Timeline update including Completed threshold-crossing notification", 0x166DD60, 0x166DFF9),
    ("Leaf threshold predicate with resource-reference identity validation", 0x1666E90, 0x1666F0B),
    ("Raw state setter with OnReady/TimedOut branches", 0x166C3B0, 0x166C49E),
    ("Preparation/state transition and OnReady/OnExitLoop notifications", 0x1669A20, 0x1669E82),
    ("Raw state 13 cleanup and LastFrame notification", 0x16695C0, 0x1669972),
    ("Script Action resolves component and command hash", 0x166FFF0, 0x167020D),
    ("Manager wrapper receiving component raw A0 resource ID", 0x166FE30, 0x166FE6B),
    ("Action notification sends hash to local script before listener lookup", 0x1670F30, 0x1670F93),
    ("System listener lookup before recipient notification", 0x1672EE0, 0x1672F98),
    ("Recipient leaf thunk", 0x1670EB0, 0x1670EB9),
    ("Other script node's Started literal: excluded from C2 start claims", 0xC7BC40, 0xC7BCE7),
    ("Prius type name/hash/descriptor leaf methods", 0x1AC1660, 0x1AC16F0),
)


def function_fragments(img, entry):
    """Bounded unwind association; no assumption that fragments are entries."""
    fragments = []
    for begin, end, _ in img.functions:
        if entry <= begin < entry + MAX_FRAGMENT_SEARCH_BYTES:
            chain = unwind_chain(img, begin)
            if chain and int(chain[-1]["runtime_function"]["begin_rva"], 16) == entry:
                fragments.append({"fragment_begin_rva": hex(begin), "fragment_end_rva": hex(end),
                                  "unwind_chain": chain})
    if len(fragments) > MAX_FUNCTION_FRAGMENTS:
        raise ValueError("Fragment bound exceeded")
    return {"entry_rva": hex(entry), "association": ".pdata plus UNW_FLAG_CHAININFO",
            "fragments": fragments, "invoke_abi_verified": False,
            "note": "Entry is a file/static association, not permission or proof to invoke/hook it."}


def prius_members(img):
    # Table binding is independently supported by initializer instructions.
    count = struct.unpack("<I", img.data(0x62392B8, 4))[0]
    if count != 9:
        raise ValueError("Unexpected Cinematic2ComponentPrius member count")
    names = struct.unpack("<9Q", img.data(0x4EC5CF0, 72))
    offsets = struct.unpack("<9I", img.data(0x4EC5E20, 36))
    hashes = struct.unpack("<9I", img.data(0x4EC5CC0, 36))
    descriptions = struct.unpack("<9Q", img.data(0x4EC5E70, 72))
    rows = [{"index": k, "name": cstring(img, names[k] - img.base),
             "hash": hex(hashes[k]), "prius_offset": hex(offsets[k]),
             "description": cstring(img, descriptions[k] - img.base)} for k in range(9)]
    if rows[1]["name"] != "CinematicAssetId" or offsets[1] != 0x20:
        raise ValueError("Pinned Prius field mapping mismatch")
    return {"descriptor_rva": "0x62392a0", "name_table_rva": "0x4ec5cf0",
            "offset_table_rva": "0x4ec5e20", "member_hash_table_rva": "0x4ec5cc0",
            "members": rows}


def event_table(img):
    hashes = struct.unpack("<26I", img.data(0x6253410, 104))
    names = struct.unpack("<26Q", img.data(0x6253478, 208))
    rows = [{"index": k, "hash": hex(hashes[k]), "name": cstring(img, names[k] - img.base)}
            for k in range(26)]
    for index, expected in ((1, "OnReady"), (4, "Started"), (7, "Completed"), (9, "Skipped")):
        if rows[index]["name"] != expected:
            raise ValueError("Pinned event mapping mismatch")
    return rows


def verify_instruction(rows, rva, prefix):
    row = next((x for x in rows if int(x["rva"], 16) == rva), None)
    if not row or not row["instruction"].startswith(prefix):
        raise ValueError(f"Unexpected pinned instruction at {rva:#x}")
    return row


def build_report(path, tool):
    img = Image(path)
    digest = hashlib.sha256(img.blob).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("Game hash mismatch; refusing address interpretation")
    ranges = []
    for label, start, stop in RANGES:
        rows = parse_instructions(img, disassemble(img, tool, start, stop))
        ranges.append({"label": label, "start_rva": hex(start), "end_rva_exclusive": hex(stop),
                       "byte_count": stop - start, "instructions": rows,
                       "limits": "linear bounded decode; all addresses are static RVA, ABI remains unverified"})
    all_rows = [row for group in ranges for row in group["instructions"]]
    required = (
        (0x165F5D4, "mov    rax,QWORD PTR [rdi+0x20]"),
        (0x165F5D8, "mov    QWORD PTR [rbx+0xa0],rax"),
        (0x165F5F8, "mov    QWORD PTR [rbx+0xa0],rcx"),
        (0x1668167, "mov    rdx,QWORD PTR [rcx+0xa0]"),
        (0x166DFDC, "mov    edx,0x9a610b3e"),
        (0x166DFE4, "call   0x14166b890"),
        (0x166C3ED, "mov    edx,0x2872cb8"),
    )
    checked = [verify_instruction(all_rows, rva, prefix) for rva, prefix in required]
    duration_epsilon = struct.unpack("<f", img.data(0x382E128, 4))[0]
    if duration_epsilon != 0.5:
        raise ValueError("Pinned completion threshold constant mismatch")
    events = event_table(img)
    literal_refs = []
    for event in events[:10]:
        occurrences = img.occurrences(struct.pack("<I", int(event["hash"], 16)))
        code = [rva for rva in occurrences if img.executable(rva)]
        local = [rva for rva in code if 0x165F000 <= rva < 0x1671100]
        literal_refs.append({"name": event["name"], "hash": event["hash"],
                             "whole_exe_code_literal_occurrences": [hex(x) for x in code],
                             "bounded_cinematic_region_occurrences": [hex(x) for x in local],
                             "limits": "literal occurrences only; indirect/table-based emission is not excluded"})
    table = prius_members(img)
    full_entries = (0x165F2F0, 0x1668150, 0x166A320, 0x166B890, 0x166DD60,
                    0x166C3B0, 0x1669A20, 0x16695C0, 0x166FFF0, 0x166FE30,
                    0x1670F30, 0x1672EE0, 0xC7BC40)
    return {
        "schema": 1, "scope": "file-only Cinematic2 native notifications and identity candidates",
        "game": {"path": str(path), "sha256": digest, "preferred_image_base": hex(img.base)},
        "game_operations": False, "process_access": False, "hook_operations": False,
        "verified_callable_interfaces": [], "verified_phase_detector": False,
        "verified_world_cleanup": False, "verified_cross_process_cinematic_id": False,
        "limits": {"bounded_disassembly_ranges": len(RANGES),
                   "bounded_disassembly_total_bytes": sum(b - a for _, a, b in RANGES),
                   "fragment_search_bytes_per_entry": MAX_FRAGMENT_SEARCH_BYTES,
                   "max_fragments_per_entry": MAX_FUNCTION_FRAGMENTS},
        "rtti": [vtable_identity(img, x) for x in (0x3CF4100, 0x3CF4908, 0x4EC60C0)],
        "prius_members": table, "events": events,
        "commands": enum_descriptor(img, 0x4EF40B0),
        "event_literal_reference_scope": literal_refs,
        "completion_threshold_constant": {"rva": "0x382e128", "float": duration_epsilon},
        "verified_static_instruction_checks": checked,
        "complete_function_entry_associations": [function_fragments(img, x) for x in full_entries],
        "evidence_disassembly": ranges,
        "findings": {
            "asset_binding": {
                "component_field": "0xa0", "prius_field": "0x20", "member_name": "CinematicAssetId",
                "copy_instructions": ["0x165f5d4", "0x165f5d8"],
                "fallback_resolver_call": "0x165f5f0", "fallback_resolver_target": "0x1bb25d0",
                "fallback_asset_path_prius_offset": "0x8", "overwrite_instruction": "0x165f5f8",
                "manager_wrapper": "0x166fe30", "triggered_caller": "0x166817b",
                "reference_pair": {"token_offset": "0xa8", "pointer_offset": "0xb0",
                                   "writes": ["0x166818e", "0x1668195"]},
                "limits": "A0 is the asset-ID candidate; A8 is a checked reference token. Neither has cross-reload or cross-process runtime proof. Asset ID alone does not identify one invocation."},
            "start": {
                "script_action_entry": "0x166fff0", "dispatcher_entry": "0x166a320",
                "triggered_enum_index": 2, "triggered_dispatch_branch": "0x166a410",
                "triggered_target_entry": "0x1668150", "requested_raw_state": 10,
                "state10_notification": "OnReady", "state10_notification_hash": "0x02872cb8",
                "ontriggered_helper": "0x1666e10", "ontriggered_helper_used_by": "InterruptLoop command index 4",
                "started_hash": "0x860d82c3", "started_in_cinematic_region_literal_hits": [],
                "limits": "Triggered is a request, OnReady is a notification candidate. Neither proves actual playback began. OnTriggered is not the Triggered command's start callback. Table-based Started emission remains unlocated."},
            "completion": {
                "timeline_function_entry": "0x166dd60", "timeline_ret_rva": "0x166dff8",
                "current_time_candidate_offset": "0xf0", "previous_time_candidate_offset": "0xec",
                "active_timeline_gate_offset": "0x408", "active_timeline_gate_mask": 1,
                "predicate_entry": "0x1666e90", "resource_threshold_candidate_offset": "0x3c",
                "predicate": "input float >= [validated resource pointer+0x3C] - 0.5",
                "threshold_crossing_checks": ["0x166dfbf", "0x166dfd3"],
                "event_name": "Completed", "event_hash": "0x9a610b3e",
                "literal_instruction": "0x166dfdc", "forwarder_call": "0x166dfe4",
                "limits": "A threshold-crossing notification can precede the timeline resource threshold by 0.5 units; duration units need runtime proof. It does not assign state 13 and does not prove door/collision/enemy/task/checkpoint cleanup."},
            "terminal": {
                "raw_state13_cleanup_entry": "0x16695c0",
                "cleanup_almost_done_call": "0x166971a", "cleanup_lastframe_call": "0x16698df",
                "dispatcher_endcinematic_branch": "0x166a45f", "dispatcher_endcinematic_state": 13,
                "dispatcher_endcinematic_notification": "TimedOut", "limits": "State 13 has TimedOut command and natural exhaustion paths; cannot classify it as natural end or user skip by itself."},
            "passive_instrumentation_candidates": [
                {"entry_rva": "0x166a320", "record_only": "Observed component argument register RCX, enum index EDX; component identity/asset candidate and native caller/thread", "semantic_boundary": "native command requested, not executed phase completion"},
                {"entry_rva": "0x166b890", "record_only": "Observed component register RCX, event hash EDX; log native callback path plus identity", "semantic_boundary": "attempted conditional forwarding, not delivery/cleanup proof"},
                {"entry_rva": "0x1670f30", "record_only": "Raw action object RCX, event hash EDX, native caller/thread", "semantic_boundary": "action forwards to script only when +58 exists; broader than cinematic component"},
            ],
            "passive_extra_fields": [{"offset": x, "interpretation": y} for x, y in (
                ("0xa0", "raw asset-ID candidate"), ("0xa8", "raw checked resource-reference token"),
                ("0xec", "raw previous time candidate"), ("0xf0", "raw current time candidate"),
                ("0x408", "raw timeline gate flags"), ("0x438", "raw transition flags"))],
            "remaining": ["actual Started event path", "stable invocation identity/generation",
                          "resource-ready and scene-ready runtime proof", "normal user skip callback and cleanup",
                          "thread/object lifetime and callable ABI", "post-cutscene world consistency"],
        },
    }


def markdown(report):
    f = report["findings"]
    members = report["prius_members"]["members"]
    lines = ["# Cinematic2 原生事件与资源身份：下一阶段静态证据", "",
             "这轮闭合了资产字段绑定、原生命令入口和 Completed 时间阈值通知；仍没有可直接使用的真实播放开始/最终结束检测器，也没有可调用的跳过接口。",
             "", f"固定 EXE SHA-256：`{report['game']['sha256']}`。所有地址均为 RVA。脚本只读磁盘 EXE，不访问进程，不 hook，不注入，不调用游戏函数。",
             "", "## 资产 ID 与实例 ID 分开", "",
             "`Cinematic2ComponentPrius` RTTI vtable `0x4EC60C0` 的 +0x38 叶函数 `0x1AC16B0` 返回 descriptor `0x62392A0`。该描述符的名称表 `0x4EC5CF0`、offset 表 `0x4EC5E20` 列出以下成员；游戏初始化指令独立验证了其中的资产字段绑定。",
             "", "| Prius 字段 | 偏移 | 游戏自带说明 |", "|---|---|---|"]
    for row in members:
        lines.append(f"| {row['name']} | `{row['prius_offset']}` | {row['description']} |")
    lines += ["", "组件初始化完整入口 `0x165F2F0`：`0x165F5D4` 读取 Prius `+0x20`，`0x165F5D8` 写入 Component `+0xA0`。如果该值高 32 位被测试为非负，则用 Prius `+0x8` 经 `0x1BB25D0` 解析，`0x165F5F8` 覆写 `+0xA0`。",
              "", "命令 Triggered 的目标 `0x1668150` 读取 Component `+0xA0`，经 Manager `0x166FE30` 返回引用；组件 `+0xA8/+0xB0` 取的是返回引用的 token/指针组合。因此 A0 是 `CinematicAssetId` 的静态候选，A8 是引用一致性 token，不能混为一个跨端实例 ID。A0 是否跨重载、跨进程稳定仍需实录；相同资产可能重复播放，还需要独立的调用 epoch/实例代数。",
              "", "## 开始路径还未闭合", "",
              "`Cinematic2Action` vtable `0x3CF4908` 槽 `+0x50` → 完整入口 `0x166FFF0`：从 Action `+0x58` 以 hash `0xDB2783F1` 解析目标 actor，类型描述符 `0x7462DD0` 找到 Cinematic2Component，然后把命令 hash 解码为枚举并进入 `0x166A320`。",
              "", "`Triggered` 枚举 2 → 分支 `0x166A410` → `0x1668150`，只是请求原始状态 10（某些标志请求 14）。状态 10 的转换分支 `0x166C3ED`/`0x1669C52` 发送的是 **OnReady**，所以不能凭 raw 10 将组件命名为 Playing。",
              "", "`OnTriggered` hash `0x318B1410` 在辅助函数 `0x1666E10`；实际命令索引 4 `InterruptLoop` 调用这个辅助函数，不是 Triggered 的真实开始回调。`Started` hash `0x860D82C3` 在 Cinematic2 有界局部区间 `0x165F000..0x1671100` 无代码立即数，整 EXE 的 `0xC7BCC4` 属于另一个脚本节点。间接/表驱动发送仍可能存在，本轮没有闭合。",
              "", "## Completed 通知早于最终收尾", "",
              "完整 timeline 更新入口为 `0x166DD60`，RET 在 `0x166DFF8`；`.pdata` 把它拆成 6 个 unwind 片段，`0x166DF8A` 只是其中一片，不能作为完整函数入口。入口检查组件 `+0x408 & 1`。",
              "", "`0x1666E90` 先核对组件 `+0xA8` 与 `[+0xB0 指针+8]` 的引用一致性，然后执行 float 比较 `输入 >= [资源+0x3C] - 0.5`（常量 RVA `0x382E128`）。timeline 更新在 `0x166DFBF` 检查旧 `+0xEC`、`0x166DFD3` 检查当前 `+0xF0`；只有旧值未到、当前值达到该阈值时，`0x166DFDC` 将 **Completed** hash `0x9A610B3E` 传入 `0x166B890`。",
              "", "这闭合了游戏自身的阈值跨越通知，不能等同最终结束：它可能比资源阈值早 0.5 个时间单位（单位还需实录），没有在这个分支赋值 raw state 13，也不证明任务、门、碰撞、敌人或检查点收尾。`0x166B890` 还会检查 owner 虚函数、Action actor 引用和描述符；收到入口参数只是发送尝试，仍可能不转发。",
              "", "raw state 13 的更新分支进入 `0x16695C0`，有 actor 处理、AlmostDone 和 LastFrame 路径。显式 EndCinematic 同样写 raw 13 并发 TimedOut，所以单独看到 13 也不能归因为自然结束或玩家跳过。",
              "", "## 被动记录候选与边界", "",
              "当前模块仍以只读快照为范围。未来若实现保留所有原始寄存器/栈/返回值的被动记录器，可优先验证下列完整入口；这些条目不授权直接执行游戏 ABI，也不表示已 hook。",
              "", "| 完整入口 | 原生调用时可以记录的已见寄存器 | 不得推导 |", "|---|---|---|"]
    for row in f["passive_instrumentation_candidates"]:
        lines.append(f"| `{row['entry_rva']}` | {row['record_only']} | {row['semantic_boundary']} |")
    lines += ["", "补充快照候选：A0、A8、EC、F0、408、438。组件 vtable/owner/引用需要前后核验；存量选择槽的零/非零仍只表示选择变化，不用于触发开始/结束。优先记录 command、native caller/thread、原始字段、任务变化和人工播放收据的同一时基，先建立实际顺序再决定 phase。",
              "", "## 可复现与证据范围", "", "```powershell",
              "& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' -X utf8 -B .\\research\\cinematic_native_next_probe.py",
              "```", "", f"反汇编限定 {report['limits']['bounded_disassembly_ranges']} 个范围，总计 {report['limits']['bounded_disassembly_total_bytes']} 字节；函数 unwind 片段关联每入口最多检查后续 0x4000 字节。报告保存 hash、RTTI、字段表、事件表、必需指令核验和全部有界反汇编。没有网络下载或新依赖。",
              "", "`verified_callable_interfaces=[]`；actual Started、原生跳过、资源/场景就绪、实例 generation、线程/生命周期、结束后世界一致性仍未验证。上一轮真实轨迹中 raw10 恒定、人工播放/结束收据附近选择槽为空，正是不能仅靠旧槽构造 phase 的运行证据；本报告不重标原始轨迹。"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=GAME)
    parser.add_argument("--objdump", type=Path, default=OBJDUMP)
    args = parser.parse_args()
    report = build_report(args.game.resolve(), args.objdump.resolve())
    (ROOT / "cinematic_native_next.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "cinematic_native_next.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"sha256": report["game"]["sha256"], "ranges": len(RANGES),
                      "static_checks": len(report["verified_static_instruction_checks"]),
                      "game_operations": False, "callable_interfaces": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
