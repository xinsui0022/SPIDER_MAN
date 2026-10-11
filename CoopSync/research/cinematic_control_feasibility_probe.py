"""Pinned-build, file-only handoff evidence for Cinematic2 control candidates.

Reads only the EXE and existing helper modules. No process access, game launch,
hooks, injection, memory writes, network, or game calls. The report does not
promote any static address to a verified callable interface.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from cinematic_static_probe import (
    Image, GAME, EXPECTED_SHA256, OBJDUMP, cstring, disassemble,
    parse_instructions, enum_descriptor, direct_candidates,
)
from cinematic_native_next_probe import function_fragments
from ui_skip_probe import unwind_chain, vtable_identity

ROOT = Path(__file__).resolve().parent
# Embedded switch tables are deliberately excluded from linear decoding.
RANGES = (
    ("DDL bool-copy width evidence only", 0x261AFB0, 0x261B200),
    ("CineQTEEndAction native EndCinematic caller", 0x627760, 0x62783B),
    ("UI event argument forwarded to command dispatcher, prefix only", 0x7DC400, 0x7DC4F6),
    ("UI numeric command dispatcher, excluding embedded tables", 0x7DE150, 0x7DE39C),
    ("Unreferenced candidate component enumerator", 0x7DE8C0, 0x7DE966),
    ("Skippable-gated resource seek/terminal candidate, complete entry", 0x166C7F0, 0x166C97E),
    ("Request terminal raw state through engine helper", 0x166C4A0, 0x166C4F4),
    ("Native seek, resource validation and track side effects", 0x1666FB0, 0x1667941),
    ("State 12 seeks resource end; state 13 enters cleanup", 0x16693CF, 0x166958C),
    ("Native raw state 13 cleanup, typed event and LastFrame", 0x16695C0, 0x1669972),
    ("Default resource length callback leaf", 0x1671690, 0x16716EF),
    ("Skip-destination event time getter, no located caller", 0x623020, 0x6230A7),
    ("Camera-pane entry, excluding embedded jump tables", 0x165FEF0, 0x1660352),
    ("Camera-pane exit and C7 clear", 0x166AAE0, 0x166ACA5),
    ("System selection enumerates C7-flagged components", 0x1673190, 0x16732F4),
    ("System updates all components, no story-phase classification", 0x1672430, 0x16725BC),
    ("Checked resource pointer to data-pointer use, local instructions", 0x1668AF9, 0x1668B65),
    ("Camera-pane event descriptor leaf", 0x1AE7D80, 0x1AE7D88),
    ("Camera-pane event constructor type association", 0x1AE4E90, 0x1AE4EC0),
)


def metadata(img, descriptor, expected_name):
    def q(off):
        raw = img.data(descriptor + off, 8)
        if len(raw) != 8:
            raise ValueError("Metadata outside mapped file")
        return struct.unpack("<Q", raw)[0] - img.base
    name = cstring(img, q(0))
    if name != expected_name:
        raise ValueError("Pinned descriptor name mismatch")
    count = struct.unpack("<I", img.data(descriptor + 0x18, 4))[0]
    if not 0 < count <= 64:
        raise ValueError("Metadata member bound exceeded")
    hashes, names, offsets, descriptions = (q(off) for off in (0x48, 0x50, 0x78, 0x88))
    rows = []
    for k in range(count):
        rows.append({
            "index": k,
            "name": cstring(img, struct.unpack("<Q", img.data(names + k * 8, 8))[0] - img.base),
            "offset": hex(struct.unpack("<I", img.data(offsets + k * 4, 4))[0]),
            "hash": hex(struct.unpack("<I", img.data(hashes + k * 4, 4))[0]),
            "description": cstring(img, struct.unpack("<Q", img.data(descriptions + k * 8, 8))[0] - img.base),
        })
    return {"descriptor_rva": hex(descriptor), "name": name, "count": count,
            "member_name_table_rva": hex(names), "offset_table_rva": hex(offsets),
            "member_hash_table_rva": hex(hashes), "description_table_rva": hex(descriptions),
            "members": rows,
            "limits": "Metadata offsets belong to this definition/event type, not the runtime component."}


def confirmed_direct_calls(img, targets):
    output = []
    for candidate in direct_candidates(img, targets):
        fn = candidate["function"]
        if not fn:
            candidate["status"] = "raw candidate without fragment boundary"
            output.append(candidate)
            continue
        rows = parse_instructions(img, disassemble(img, OBJDUMP_ACTIVE,
                                  int(fn["begin_rva"], 16), int(fn["end_rva"], 16)))
        row = next((r for r in rows if r["rva"] == candidate["instruction_rva"] and
                    r.get("direct_target_rva") == candidate["target_rva"]), None)
        if row:
            candidate["status"] = "instruction boundary confirmed from .pdata fragment"
            candidate["decoded_instruction"] = row
            candidate["unwind_chain"] = unwind_chain(img, int(row["rva"], 16))
        output.append(candidate)
    return output


def build_report(path, objdump):
    global OBJDUMP_ACTIVE
    OBJDUMP_ACTIVE = objdump
    img = Image(path)
    digest = hashlib.sha256(img.blob).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("EXE hash mismatch: no address interpretation is permitted")
    ranges = []
    for label, a, b in RANGES:
        ranges.append({"label": label, "start_rva": hex(a), "end_rva_exclusive": hex(b),
                       "byte_count": b - a,
                       "instructions": parse_instructions(img, disassemble(img, objdump, a, b)),
                       "limits": "Bounded linear static decode; fragments and reachability are qualified separately."})
    flat = {int(r["rva"], 16): r for group in ranges for r in group["instructions"]}
    checks = (
        (0x166C7F6, "QWORD PTR [rcx+0xb0]"),
        (0x166C809, "QWORD PTR [rcx+0xa8]"),
        (0x166C81A, "QWORD PTR [r8+0x8]"),
        (0x166C85A, "DWORD PTR [r8+0x30]"),
        (0x166C85E, "shr    eax,0x3"),
        (0x166C86E, "0x1460449b8"),
        (0x166C8E6, "DWORD PTR [rsp+0x54],0x10"),
        (0x166C8F3, "call   0x141666fb0"),
        (0x166C914, "DWORD PTR [rbx+0x4c],0x200000"),
        (0x166C961, "call   0x14164f9c0"),
        (0x166C969, "call   0x14166c4a0"),
        (0x7DE341, "call   0x14166c7f0"),
        (0x7DE93D, "call   0x14166c7f0"),
        (0x16716E5, "movss  xmm0,DWORD PTR [rdx+0x3c]"),
        (0x1668B4D, "QWORD PTR [r9+0x10]"),
        (0x16601FB, "BYTE PTR [rdi+0xc7],0x1"),
        (0x166AC7A, "BYTE PTR [rbx+0xc7],0x0"),
        (0x16731C6, "QWORD PTR [rsi+0x11d0],r13"),
        (0x1673268, "QWORD PTR [rsi+0x11d0],rbx"),
        (0x6277DE, "call   0x14166a320"),
        (0x261B173, "BYTE PTR [rsi+0x168]"),
        (0x261B17E, "BYTE PTR [rcx+0x168]"),
    )
    checked = []
    for rva, required in checks:
        row = flat.get(rva)
        if row is None or required not in row["instruction"]:
            raise ValueError(f"Pinned instruction mismatch at {rva:#x}: {required}")
        checked.append(row)
    definitions = [metadata(img, 0x6AA04B0, "Cinematic2Def"),
                   metadata(img, 0x6A9F5B0, "Cinematic2GlobalEventTrackDef"),
                   metadata(img, 0x62430C0, "Cinematic2CameraPaneEvent"),
                   metadata(img, 0x6243840, "Cinematic2SkipDestinationEvent")]
    cine_def = definitions[0]["members"]
    if cine_def[9]["name"] != "Skippable" or cine_def[9]["offset"] != "0x168":
        raise ValueError("Skippable metadata mismatch")
    if cine_def[10]["name"] != "ResetOnFinished" or cine_def[10]["offset"] != "0x169":
        raise ValueError("ResetOnFinished metadata mismatch")
    ui_indices = img.data(0x7DE3C8, 30)
    ui_targets = struct.unpack("<11I", img.data(0x7DE39C, 44))
    if ui_indices[7] != 7 or ui_targets[7] != 0x7DE2C9:
        raise ValueError("UI numeric command mapping mismatch")
    callback = struct.unpack("<Q", img.data(0x60449B8, 8))[0] - img.base
    if callback != 0x1671690:
        raise ValueError("On-disk default callback mismatch")
    known_calls = confirmed_direct_calls(img, {0x166C7F0: "gated seek/terminal candidate",
                           0x7DE150: "UI numeric dispatcher", 0x7DE8C0: "unreferenced enumerator",
                           0x623020: "unreferenced destination-time candidate"})
    return {
        "schema": 1,
        "scope": "Static control-feasibility handoff, not a game adapter or test result",
        "game": {"path": str(path), "sha256": digest, "preferred_image_base": hex(img.base)},
        "process_access": False, "game_operations": False, "hooks": False,
        "verified_callable_interfaces": [], "verified_phase_detector": False,
        "verified_native_skip": False, "verified_story_cleanup": False,
        "resource_runtime_probe": {"created": False, "mock_tests_completed": False,
            "reason": "User changed scope to repository handoff before implementation; do not present it as completed."},
        "limits": {"ranges": len(RANGES), "total_disassembly_bytes": sum(b-a for _, a, b in RANGES),
                   "max_range_bytes": max(b-a for _, a, b in RANGES),
                   "fragment_association_search_bytes_per_entry": 0x4000},
        "metadata": definitions,
        "cinematic_script_commands": enum_descriptor(img, 0x4EF40B0),
        "type_associations": [vtable_identity(img, vt) for vt in (0x387A9C0, 0x4ED4DB0, 0x4ED5140)],
        "instruction_checks": checked,
        "entry_associations": [function_fragments(img, x) for x in (0x166C7F0, 0x166C4A0,
                             0x1666FB0, 0x16695C0, 0x7DE150, 0x7DE8C0, 0x627760,
                             0x165FEF0, 0x166AAE0, 0x1673190, 0x1672430)],
        "direct_call_evidence": known_calls,
        "evidence_disassembly": ranges,
        "findings": {
            "resource_layout": {
                "component_A8": {"width": 8, "role": "checked resource-reference token"},
                "component_B0": {"width": 8, "role": "pointer to external resource object, not embedded object"},
                "resource_8": {"width": 8, "role": "token compared against component A8, high and low 32 bits"},
                "resource_10": {"width": 8, "role": "data pointer consumed after token guard; concrete definition type unclosed"},
                "resource_30": {"width": 4, "role": "native packed flags; bit 3 gates candidate control"},
                "resource_3C": {"width": 4, "role": "float length/end-time candidate from native callback"},
                "definition_object_link_verified": False,
                "limits": "The external resource object is not proven to be Cinematic2Def. Do not read resource+168 as Skippable."},
            "skippable": {"DDL_descriptor": "0x6aa04b0", "member_index": 9,
                "definition_offset": "0x168", "width": 1, "hash": "0xf0dc1233",
                "native_flag_binding_verified": False,
                "native_candidate": "resource DWORD +0x30 bit 3 gates 0x166C7F0",
                "limits": "Definition bool and native flag consumption are separately verified; the conversion between them is not closed."},
            "reset_on_finished": {"definition_offset": "0x169", "width": 1,
                "hash": "0x4aa36328", "runtime_binding_verified": False},
            "native_control_candidate": {"entry_rva": "0x166c7f0",
                "observed_static_this_register": "RCX = component candidate",
                "gates": ["B0 pointer exists", "A8 matches QWORD [B0+8]", "DWORD [B0+30] bit 3 set",
                          "callback destination is later than current component F0 when callback is present"],
                "destination_callback_slot_rva": "0x60449b8",
                "on_disk_default_callback_rva": "0x1671690",
                "default_callback_behavior": "return checked resource float +0x3C, or zero on token/pointer failure",
                "destination": "clamped into [0, resource length]",
                "intermediate_destination": "0x1666FB0 receives packed float/flags 0x10; then AlmostDone forwarding",
                "end_destination": "component +0x4C bit 21 set; actor candidate 0x164F9C0; 0x166C4A0 requests raw 12",
                "continuation": "native update raw 12 seeks resource end, writes raw 13/TimedOut; raw 13 calls 0x16695C0 cleanup and conditional LastFrame",
                "ABI_verified": False, "thread_verified": False,
                "runtime_callback_target_verified": False,
                "limits": "Never invoke this from a sampler thread, call a fragment entry, or replace it by a direct F0 write. Lifetime, owning thread, scene readiness, and mission cleanup still lack runtime proof."},
            "native_callers": {"UI_dispatch_entry": "0x7de150", "numeric_input": 7,
                "numeric_branch": "0x7de2c9", "component_call_instruction": "0x7de341",
                "gates": ["enumerated Cinematic2 component", "0x1661A90 predicate returned true (semantics unclosed)", "raw 58 in 10..11"],
                "UI_event_prefix_entry": "0x7dc400", "call": "0x7dc4e4",
                "argument_source": "Scaleform-like argument [R8+20] after [R8+18]&8F == 4",
                "extra_enumerator_entry": "0x7de8c0", "extra_call": "0x7de93d",
                "extra_enumerator_direct_caller_hits": [],
                "limits": "Numeric UI option 7 is a native control association. Actual user-input delivery and thread are not observed. Covered direct-call scans do not exclude indirect/alias/module callers."},
            "command_counterexample": {"QTE_action_vtable": "0x387a9c0", "slot": "0x50",
                "entry": "0x627760", "call": "0x6277de", "passed_command_index": 6,
                "class": "CineQTEEndAction", "meaning": "EndCinematic has a QTE task-script caller; not evidence that command 6 equals normal skip"},
            "selection_counterexample": {
                "slot_rva": "0x6045c30", "owner": "System +0x11D0",
                "selection": "cleared each enumeration, then overwritten for each Cinematic2 component with C7 != 0; last qualifying component remains",
                "C7_entry_write": "0x16601fb", "C7_exit_write": "0x166ac7a",
                "C7_event_association": "Cinematic2CameraPaneEvent: entry EventType 0; exit EventType 1",
                "system_updates_all_components": "0x1672430",
                "menu_recording_counterexample": {"source": "parent agent's saved-log analysis; not sampled by this script",
                    "samples_total": 350, "matching_component_samples": 36,
                    "resource_candidate": "9a05b474457c6ab3", "EC_F0_change_count": 35,
                    "raw_float_range_approx": [9.828, 10.877]},
                "phase_false": True,
                "limits": "Matching component/asset and changing EC/F0 occur in main menu too; they do not prove the civilian rescue or any story cutscene."},
            "path_forward": [
                "Preserve current diagnostics as raw candidates; phase and callable capability remain false.",
                "Bind one actual mission cinematic using resource metadata plus owner/action/scene identity, accounting for the menu counterexample.",
                "Close Skippable definition conversion to the resource native flag and confirm the current callback slot value without executing it.",
                "Future authorized passive native-call instrumentation can record the complete UI/166C7F0 entry, caller thread and object lifetime before designing a game-thread command queue.",
                "Only after controlled native skip and natural end traces prove mission/door/enemy/checkpoint cleanup should a co-op skip adapter be enabled."
            ],
        },
        "portability": {
            "static_default_game": "cinematic_static_probe.py:21 has local D:/STEAM__/.../Spider-Man.exe; override via --game in this/new-next/static probes",
            "static_default_objdump": "cinematic_static_probe.py:23 has C:/TDM-GCC-64/bin/objdump.exe; override via --objdump in this/new-next/static probes",
            "runtime_game_path": "cinematic_runtime_probe.py:22 is hardcoded; runtime CLI has no --game override",
            "ui_skip_probe": "imports helper GAME/OBJDUMP defaults and has no CLI --game/--objdump override",
            "ui_skip_runtime_probe": "inherits cinematic_runtime_probe's hardcoded game path",
            "historical_command_examples": "native-next/static/ui-skip/recording-analysis generators contain original user's Python path; use python/py on the receiving computer",
            "nonportable_recordings": "saved PIDs, absolute pointers, module base, computer paths and wall-clock observations are historical evidence only; never reuse them for calls",
            "dependencies": ["Python 3.11-compatible runtime", "pefile", "GNU objdump accepting Intel syntax", "same pinned EXE SHA-256"],
        },
    }


def markdown(report):
    f = report["findings"]
    return fr"""# Cinematic2 控制可行性：跨电脑 / AI 交接

本轮确认了正规跳转/结束候选的完整入口 `0x166C7F0` 及其原生 UI 调用链，仍未验证可调用 ABI、线程、剧情实例身份或任务收尾。**可调用接口、真实剧情 phase、正常玩家 Skip 和世界收尾能力全部保持 false。** 用户已改任务为整理上传 GitHub，本轮不再测试游戏。

游戏固定 SHA-256：`{report['game']['sha256']}`。所有地址为 RVA，运行时需加重新核验的模块基址。脚本只读磁盘 EXE，不打开进程、不 hook、不注入、不调用游戏函数。JSON 保存元数据、指令字节、原生调用点和 unwind 片段关联。

## 当前交接状态

- 已完成：固定构建静态证据整理、资源布局消费路径、原生跳尾候选及 UI 数字命令调用链。
- 未完成：`cinematic_resource_runtime_probe.py` 没有创建，也没有 mock 自检；中断前只是计划，不能算成果。
- 未完成：DDL `Skippable` 到资源 packed flag 的转换绑定；跨资源类型、生命周期、线程、任务门/敌人/检查点收尾的实录。
- 本轮不修改已加载 DLL、不启动新测试。原有只读诊断与历史日志保持原来的语义边界。

## A8/B0 的真实读取布局

| 位置 | 宽度 | 已核验的静态含义 |
|---|---:|---|
| Component `+A8` | 8 B | checked resource-reference token |
| Component `+B0` | 8 B | 指向外部资源对象的指针，非内嵌资源对象 |
| Resource `+8` | 8 B | 与 A8 高/低 32 位逐一核对的 token |
| Resource `+10` | 8 B | 校验后取出的 data 指针；尚未闭合到 Cinematic2Def 类型 |
| Resource `+30` | 4 B | packed flags；bit 3 门控 `166C7F0` |
| Resource `+3C` | 4 B | `movss` 消费的时长 / end-time 候选 |

准确指令：`166C7F6 MOV R8,QWORD [RCX+B0]`；`166C809 MOV RDX,QWORD [RCX+A8]`；`166C81A MOV RAX,QWORD [R8+8]`。高/低 32 位不全等直接退出。通过后 `166C85A MOV EAX,DWORD [R8+30]` → `166C85E SHR EAX,3` → TEST AL,1。`1668B4D` 另一路读取 `QWORD [R9+10]`；`16716E5` 读取 `float [RDX+3C]`。

这套布局允许将来设计有界只读资源快照。届时需要前后复查 System/vtable/selection、component vtable/owner/handle、A8/B0 和 resource+8；失稳丢弃。不执行 getter 或 callback。当前**没有**这样的新增运行时采样器。

## 可跳过属性与运行时门控分开

`Cinematic2Def` descriptor `6AA04B0` 有 47 字段：names `51174A0`、offsets `5117D80`、hashes `5117380`、descriptions `5118370`。

- index 9 `Skippable`，定义对象 `+168`，hash `F0DC1233`，游戏自带说明 “Allows cinematic to be skipped in game.”
- index 10 `ResetOnFinished`，定义对象 `+169`，hash `4AA36328`，说明结束后可重新初始化到 ready。
- DDL 字段复制函数 `261AFB0` 的 `261B173 MOVZX BYTE [RSI+168]` / `261B17E MOV BYTE [RCX+168]` 证明确为 1 字节属性；ResetOnFinished 的相邻 byte 复制见 JSON 指令。
- `Cinematic2GlobalEventTrackDef` descriptor `6A9F5B0` 有 `IgnoreOnSkip +C8`（hash `AE4CF01E`），说明跳过时可忽略该轨道动作。因此不同跳跃标志可能改变任务事件执行，不能任意 seek。

**尚未证明 Skippable 的 +168 转换成 Resource+30 bit3。** 这两个证据彼此相关但还没有编译/装载转换闭环。Resource+10 的 data 指针也不能直接按 Cinematic2Def 解读，尤其不能对资源 `+168` 读 bool。

## 166C7F0 正规控制候选

完整入口 `166C7F0`，RET `166C97D`；`166C8E0` 是链式 unwind 片段，绝不能当函数入口。静态观察 RCX 为 component 候选。执行前必须有 B0、A8/B0 token 一致、Resource+30 bit3 为 1。

候选从 `60449B8` 取原生回调，传入 component RCX，取得 float 目的地；回调存在且目的地不晚于当前 F0 时退出。磁盘默认回调是 leaf `1671690`，校验 token 后返回 Resource+3C float，失败返回零。**运行中 callback 可被替换，当前值未验证。**

目的地被 clamp 到 `[0, length]`：

- 中间目的地：以 packed float / flags `0x10` 调 `1666FB0`，再有条件转发 AlmostDone。Seek 本身会解析 shot/clip、改变 actor 状态并处理轨道事件，绝不等于写一个时间值。
- 到尾部：设置 Component+4C bit21，找 actor 并调 `164F9C0`，然后 `166C4A0` 请求 / 切换 raw state 12，走原生更新。
- raw 12 更新 `16694DC` 从资源 `+3C` 取 float，按组件 flags 构造 seek 参数，调 `1666FB0`；然后写 raw13 并发 TimedOut。raw13 更新进入 `16695C0`，有 actor/typed event、原生清理和有条件 LastFrame 转发。

这比直接调用 `166A320(EndCinematic)` 或修改 F0 更接近游戏自己的路径，但仍不是已验证 mod 接口。完整函数入口不意味着拥有正确线程、this 生命周期、资源/场景前置或无重入保证。不能从只读 sampler 线程执行它。

## 原生调用者

`7DC400` 的 `7DC4E4` 从输入对象 `[R8+20]` 传数字命令给 `7DE150`，先验证 `[R8+18]&8F == 4`。`7DE150` 的内嵌映射表 `7DE3C8` / `7DE39C` 把数字 7 映射到 `7DE2C9`：枚举 Cinematic2 类型组件，经 `1661A90` predicate，且 raw58 为 10 或 11，再在 `7DE341` 调完整 `166C7F0`。predicate 的完整业务语义和 UI 输入实际送达尚未实录。

另一个入口 `7DE8C0` 有同样的组件枚举 / predicate / raw58 门控，在 `7DE93D` 调 `166C7F0`。本轮覆盖的全 EXE E8/E9 直接引用、绝对函数指针、部分 REX MOV/LEA RIP 取址未找到 `7DE8C0` 的引用，不能据此声明不可达。

`623020` 用 `Cinematic2SkipDestinationEvent` hash `3E955A02` 找事件时间，失败退回 checked Resource+3C；也是静态候选，本轮未找到原生调用者。该 typed event 是轨道目的地数据，不能作为“用户请求跳过”事件。

反例：RTTI `CineQTEEndAction` vtable `387A9C0` 槽50→`627760`；`6277DE` 对解析出的 component 传命令6 EndCinematic。此 QTE 脚本调用只证明原生显式结束用途，不能把命令6等同正常玩家 Skip。

## 菜单反例必须保留

父任务的离线日志分析：主菜单完整350 samples，其中36 samples匹配同一 component / 资源候选 `9a05b474457c6ab3`，EC/F0变化35次，raw float约9.828..10.877。这里是父任务保存的观察摘要，本脚本没有采样游戏。

因此关卡70个匹配样本、同资源和计时变化**不能证明捕获了救平民剧情**。`6045C30` 是 System+11D0 枚举选择槽：每次清空，随后每个 C7!=0 的 Cinematic2 component 都覆写，最后一个满足条件的组件留在槽里。`165FEF0` 构造 RTTI `Cinematic2CameraPaneEvent`（vtable `4ED4DB0`），EventType 0，置 C7=1；`166AAE0` 发相同类型 EventType 1，清 C7。System `1672430` 给所有组件更新，不是单独的剧情导演。

这支持“标记的 camera-pane component 候选”，仍无法区分菜单背景、环境镜头和任务过场；phase 保持 false。真实剧情绑定要把资源和 owner/action/scene/mission 身份连起来，不能只用选择槽、raw10或时间变化。

## 后续实际路径与缺证据

1. 保存 raw 诊断与菜单对照，先闭合一个真实任务过场实例身份及调用 epoch。
2. 补上 DDL Skippable→Resource flags 转换、装载类型和 callback slot 的运行值，保留所有失败门控。
3. 在以后授权的测试阶段，被动记录完整 `7DE150` / `166C7F0` 原生调用的线程、caller、component identity 和事件顺序；不先执行未知 ABI。
4. 用原生 Skip 与自然结束分别验证任务、门/碰撞、敌人、检查点收尾，再设计游戏线程命令队列和主机权威联机 adapter。

## 跨电脑路径清单

| 文件 | 迁移注意 |
|---|---|
| `cinematic_static_probe.py:21/23` | GAME 默认 D:/STEAM__/...；OBJDUMP 默认 C:/TDM-GCC-64/bin/objdump.exe。CLI 可 `--game` / `--objdump` 覆盖 |
| `cinematic_native_next_probe.py` / 本 probe | 导入以上默认，均支持覆盖参数 |
| `cinematic_runtime_probe.py:22` | GAME 绝对路径硬编码；CLI没有 `--game`。跨电脑需由接手者参数化后再使用 |
| `ui_skip_probe.py` | 导入静态默认，CLI没有 game/objdump覆盖参数 |
| `ui_skip_runtime_probe.py` | 继承 cinematic_runtime_probe 的 GAME 与 Windows 进程环境 |
| 上述生成器及 `cinematic_recording_analysis.py` | 历史 Markdown命令含 C:/Users/xinsui/...Python311；使用接手电脑的 python/py命令 |
| 历史日志 | PID、absolute pointer、module base、路径是历史证据，不可复制当有效调用参数 |

依赖为 Python、`pefile` 与 GNU objdump（Intel syntax）。读取不同 EXE hash 时停止；不能把这批 RVA 用于其他版本。

## 有界复现

在项目根目录运行（按接手电脑实际路径替换参数）：

```powershell
python -X utf8 -B .\research\cinematic_control_feasibility_probe.py --game 'D:\YourSteamLibrary\steamapps\common\Marvel''s Spider-Man Remastered\Spider-Man.exe' --objdump 'C:\YourTools\bin\objdump.exe'
```

本次整理限定 {report['limits']['ranges']} 个反汇编范围，共 {report['limits']['total_disassembly_bytes']} 字节；每段最多 {report['limits']['max_range_bytes']} 字节。{len(report['instruction_checks'])} 条 pinned 指令断言、描述符成员断言和 UI table/callback 默认值断言通过，仅证明静态包复现，不是运行时功能验收。新的资源 runtime probe 和 mock tests 没有实现。
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=GAME)
    parser.add_argument("--objdump", type=Path, default=OBJDUMP)
    parser.add_argument("--output-stem", type=Path, default=ROOT / "cinematic_control_feasibility")
    args = parser.parse_args()
    report = build_report(args.game, args.objdump)
    args.output_stem.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_stem.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(args.output_stem), "ranges": report["limits"]["ranges"],
                     "bytes": report["limits"]["total_disassembly_bytes"],
                     "instruction_checks": len(report["instruction_checks"]),
                     "verified_callable_interfaces": [], "resource_runtime_probe_created": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
