"""Pinned, file-only Door/Health ECS and native-state evidence probe.

Never opens a process or calls game code. SHA-256 is checked before decoding.
Reads fixed PE locations and at most 40 bounded code ranges (each <= 0x4000).
Uses the PE/disassembly helpers in cinematic_static_probe.py; Python + pefile
and a local GNU objdump are required. Reports are written beside this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import cinematic_static_probe as pe

ROOT = Path(__file__).resolve().parent
EXPECTED_SHA256 = "e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1"
# name, vtable, MSVC RTTI TypeDescriptor, COL, virtual +0x48,
# engine descriptor/map key, constructor
CLASSES = (
    ("Door", 0x4F67720, 0x6C41C78, 0x56F05C8, 0x1F30770, 0x7C32140, 0x1F313E0),
    ("DoorAnimated", 0x4F677C8, 0x6C41C98, 0x56F0648, 0x1F332C0, 0x7C32250, 0x1F33FB0),
    ("DoorSlide", 0x4F67BB8, 0x6C41D70, 0x56F08E0, 0x1F35C60, 0x7C32650, 0x1F36520),
    ("Health", 0x3839E08, 0x6BAA978, 0x5568550, 0x1F155C0, 0x7C2C290, 0x1F163C0),
    ("BotHealth", 0x3839E98, 0x6BAA9F8, 0x55686C8, 0x3CE4E0, 0x6C87910, 0x3CEA90),
)
RANGES = (
    ("Component local-owner handle reconstruction and binding", 0x1676070, 0x16761B0),
    ("Component teardown enumerates compact map", 0x1676720, 0x1676840),
    ("Entity local handle resolver", 0x15A0560, 0x15A0730),
    ("Hashed component lookup and compact-to-hash construction", 0x16799A0, 0x1679C30),
    ("Compact component lookup", 0x167AB40, 0x167AC10),
    ("Door constructor and close native request", 0x1F31360, 0x1F31550),
    ("Door callback registration and state field registration", 0x1F31550, 0x1F31B00),
    ("Door open request, callbacks, and unlock", 0x1F326B0, 0x1F32C90),
    ("Door saved-state restoration", 0x1F30C50, 0x1F30E00),
    ("DoorScriptAction native command dispatcher", 0x1F355B0, 0x1F35703),
    ("DoorAnimated constructor", 0x1F33FB0, 0x1F340A0),
    ("DoorSlide constructor", 0x1F36520, 0x1F36650),
    ("Shared native 12-byte transition state", 0x20DF1C0, 0x20DF310),
    ("Health float getter", 0x32E940, 0x32E950),
    ("Health initial values", 0x1F15740, 0x1F15978),
    ("Health constructor", 0x1F163C0, 0x1F16411),
    ("BotHealth constructor", 0x3CEA90, 0x3CEAE1),
    ("Health native field registration", 0x1F168F0, 0x1F16A20),
    ("Health native state callbacks", 0x1F16CE0, 0x1F16FC0),
    ("Health native value mutation and cap setter", 0x1F16FC0, 0x1F17350),
    ("GameStateRegistry handle enqueue", 0x1F02AB0, 0x1F02C44),
    ("GameStateRegistry deserialization request and completion", 0x1F02C90, 0x1F02E10),
)


def read_exact(img, rva, size):
    data = img.data(rva, size)
    if len(data) != size:
        raise ValueError(f"PE range unavailable: {rva:#x}+{size:#x}")
    return data


def class_proof(img, row):
    name, vt, td, col, getter, engine_type, constructor = row
    actual_name = read_exact(img, td + 16, 96).split(b"\0", 1)[0].decode("ascii")
    if actual_name != f".?AV{name}@@":
        raise ValueError(f"RTTI class mismatch: {name}")
    sig, objoff, cdoff, typ, hierarchy, self_rva = struct.unpack("<6I", read_exact(img, col, 24))
    if (sig, objoff, typ, self_rva) != (1, 0, td, col):
        raise ValueError(f"COL closure mismatch: {name}")
    if struct.unpack("<Q", read_exact(img, vt - 8, 8))[0] != img.base + col:
        raise ValueError(f"vtable COL pointer mismatch: {name}")
    if struct.unpack("<Q", read_exact(img, vt + 0x48, 8))[0] != img.base + getter:
        raise ValueError(f"engine descriptor getter slot mismatch: {name}")
    code = read_exact(img, getter, 8)
    if code[:3] != b"\x48\x8d\x05" or code[7] != 0xC3:
        raise ValueError(f"unexpected descriptor getter encoding: {name}")
    actual_type = getter + 7 + struct.unpack_from("<i", code, 3)[0]
    if actual_type != engine_type:
        raise ValueError(f"engine descriptor target mismatch: {name}")
    return {"name": name, "vtable_rva": hex(vt), "rtti_type_descriptor_rva": hex(td),
            "rtti_name": actual_name, "col_rva": hex(col), "col_object_offset": objoff,
            "col_constructor_displacement": cdoff, "class_hierarchy_rva": hex(hierarchy),
            "engine_descriptor_getter_rva": hex(getter), "engine_descriptor_getter_slot": "0x48",
            "engine_descriptor_getter_bytes": code.hex(" "), "engine_descriptor_rva": hex(engine_type),
            "constructor_rva": hex(constructor), "rtti_and_engine_descriptor_are_distinct": True,
            "association_verified_in_pinned_file": True, "live_instance_verified": False}


def fixed_findings():
    return {
        "owner_and_identity": {
            "generic_binding_entry_rva": "0x1676150",
            "binding": {"component+0x8": "R8: owning entity-table entry",
                        "component+0x10": "owner+0x90 value", "component+0x14": "input local component handle DWORD"},
            "binding_instruction_rvas": ["0x1676156", "0x1676169"],
            "owner_local_handle_helper_rva": "0x1676070",
            "entity_resolver_rva": "0x15a0560", "table_pointer_rva": "0x7a44380",
            "table_count_rva": "0x7a4439c", "entity_stride": "0xc0",
            "entity_local_handle": "(generation_word_at_0x10 << 20) | (index_dword_at_0xC & 0xFFFFF)",
            "generation_mask_in_resolver": "0x7ff", "index_mask_in_resolver": "0xfffff",
            "same_process_lifetime_identity_only": True, "stable_network_identity_verified": False,
            "asset_identity_or_cross_peer_mapping": "unknown"},
        "ecs_component_maps": {
            "compact_pointer_entity_offset": "0x68", "compact_count_word_entity_offset": "0x70",
            "hashed_pointer_entity_offset": "0x80", "hashed_capacity_word_entity_offset": "0x88",
            "entry_stride": 16, "entry_layout": ["engine type descriptor pointer", "component pointer"],
            "compact_resolver_rva": "0x167ab40", "hashed_resolver_rva": "0x16799a0",
            "hashed_constructor_rva": "0x1679a10", "teardown_enumerator_rva": "0x1676720",
            "hashed_start_index": "(engine descriptor pointer >> 4) & (capacity - 1)",
            "hashed_inheritance_aliases_possible": True,
            "sampler": "enumerate capped compact map, exact descriptor key + exact vtable; never execute resolvers"},
        "door_raw_fields": [
            {"offset": "0x48", "size": 12, "source": "0x1f31a90 registers native field index 0; 0x20df1c0 accesses tuple", "meaning": "transition tuple; complete state enum and instance meaning unverified"},
            {"offset": "0xbc", "size": 1, "source": "0x1f31a90 native field index 1", "meaning": "raw byte only"},
            {"offset": "0xc1", "size": 1, "source": "0x1f31a90 native field index 2; 0x1f32820 callback", "meaning": "raw byte; enabled paths do not prove collision readiness"},
            {"offset": "0xbf", "size": 1, "source": "0x1f31a90 native field index 3", "meaning": "raw byte only"},
            {"offset": "0xc2", "size": 1, "source": "0x1f30c50 accesses flag; SaveOpenedState metadata", "meaning": "saved-state-associated flag; runtime correlation unverified"},
            {"offset": "0xc3", "size": 1, "source": "0x1f30c50 restored-state path", "meaning": "saved-state-associated byte; runtime correlation unverified"},
            {"offset": "0xc4", "size": 4, "source": "0x1f30c50 save-component lookup/result", "meaning": "opaque local component-handle candidate; sampler follows no pointer"},
        ],
        "door_excluded_field": {"offset": "0x58", "size": 8, "source": "0x1f31a90 native field index 4",
                                "reason": "opaque pointer/reference representation and full ABI not closed; no runtime read"},
        "door_commands": [
            {"name": "Open", "hash": "0x94e04314", "branch_rva": "0x1f356a8", "callee_rva": "0x1f32710", "DL": 1, "R8B": 0},
            {"name": "Close", "hash": "0xa524d05", "branch_rva": "0x1f35696", "callee_rva": "0x1f31360", "DL": 1, "R8B": 0},
            {"name": "Lock", "hash": "0xb71f5bbe", "branch_rva": "0x1f356de", "callee_rva": "0x1f326b0"},
            {"name": "Unlock", "hash": "0x549cfe88", "branch_rva": "0x1f3568a", "callee_rva": "0x1f32aa0", "RDX": 0},
            {"name": "SnapOpen", "hash": "0x79090c64", "branch_rva": "0x1f35676", "callee_rva": "0x1f32710", "DL": 1, "R8B": 1},
            {"name": "SnapClosed", "hash": "0xf3e3cb9d", "branch_rva": "0x1f356ca", "callee_rva": "0x1f31360", "DL": 1, "R8B": 1},
        ],
        "door_native_state_route": {
            "registration_entry_rva": "0x1f31a90", "common_field_registrar_rva": "0x1984190",
            "cmd0_handler_rva": "0x1f31730", "cmd1_handler_rva": "0x1f31550", "cmd2_handler_rva": "0x1f318a0",
            "field_initial_callback_rva": "0x1f32790", "field_change_callback_rva": "0x1f32820",
            "request_api_route": ["0x1984370", "0x19858e0", "0x1985f20", "0x1985d50"],
            "request_object_owner_offset": "0x18", "payload_length": 16,
            "payload_known_bytes": {"0..7": "opaque R9 64-bit source key", "8": "DL", "9": "R8B"},
            "payload_padding_bytes": "unknown",
            "limitation": "Named script routes and native state registration are static evidence; no GameNet transport/authority/current level instance or safe calling ABI established."},
        "health_raw_fields": [
            {"offset": "0x80", "size": 4, "source": "0x1f168f0 native field index 0; 0x1f16fc0 clamps against it", "meaning": "float cap candidate; runtime value mapping unverified"},
            {"offset": "0x84", "size": 4, "source": "0x1f168f0 native field index 1; change callback uses threshold", "meaning": "float threshold candidate; full meaning unverified"},
            {"offset": "0x88", "size": 4, "source": "0x1f168f0 native field index 2; getter 0x32e940; writes 0x1f17110", "meaning": "float value candidate; real enemy HP/death unverified"},
            {"offset": "0x8c", "size": 4, "source": "0x1f17118 copies prior 0x88", "meaning": "previous value candidate; raw sampling only"},
            {"offset": "0xac", "size": 2, "source": "0x1f168f0 native field index 3", "meaning": "raw flag word only"},
        ],
        "health_native_state_route": {
            "registration_entry_rva": "0x1f168f0", "field_registrar_rva": "0x1984190",
            "initial_callback_rva": "0x1f16ce0", "change_callback_rva": "0x1f16da0",
            "native_set_value_entry_rva": "0x1f16fc0", "native_cap_setter_rva": "0x1f172a0",
            "mark_dirty_call_rva": "0x1676b90",
            "static_behavior": "Set path clamps [0,+0x80], moves old +0x88 into +0x8C, writes +0x88 and marks dirty; callbacks conditionally dispatch events.",
            "limitation": "A Health/BotHealth component is not proof of an enemy. Spawn, AI, damage authority, death consequences and cross-peer identity are unverified."},
        "gamenet_registry": {
            "registry_vtable_rva": "0x4f643a8", "system_vtable_rva": "0x4f64320",
            "queue_entry_rva": "0x1f02ab0", "load_request_entry_rva": "0x1f02c90",
            "load_completion_entry_rva": "0x1f02d40", "deserialize_callee_rva": "0x1986230",
            "known": "Registry stores/resolves entity handles and invokes native deserialization on completion.",
            "unknown": "Current chapter, initial snapshot field coverage, physical collision and remote transport payload meaning; no claim that enabling manager solves door/enemy sync."},
        "runtime_sampler": {
            "interface": "coopsync::runtime::CaptureWorldRaw(uintptr_t base,uint32_t image_size,uint64_t sequence)",
            "caller_prerequisite": "Pinned executable SHA-256/version gate succeeded",
            "reader": "ReadProcessMemory(GetCurrentProcess())", "max_entities_per_tick": 128,
            "max_compact_map_entries_per_entity": 128, "max_hash_capacity_accepted": 128,
            "max_read_calls": 16384, "max_read_bytes": 1048576, "max_records_per_tick": 32,
            "final_table_check_reserved_reads": 2, "final_table_check_reserved_bytes": 12,
            "accepted_record_checks": ["vtable whitelist + exact engine descriptor key", "component owner + nonzero local component handle", "two identical raw field reads", "unchanged component vtable/owner/handle", "unchanged compact map key/value", "unchanged entity index/generation/compact+hash map header", "unchanged global table pointer/count"],
            "coverage": "incomplete rolling diagnostic window", "no_unknown_field_reads": True,
            "engine_calls": False, "hooks": False, "game_writes": False,
            "coherent_snapshot_or_aba_detection_guaranteed": False,
            "limitation": "Before/after equality rejects observed races but cannot rule out ABA or every interleaving. Even accepted records are raw local observations, never world replication proof."},
        "next_evidence_needed": ["Live accepted Door/Health/BotHealth records and raw transitions tied to visible game actions", "Scene/asset key that maps the same actor across peers and reloads", "Door visual and collision readiness correlated to native lifecycle", "Enemy spawn/AI/damage/death authoritative route", "Game-thread/lifetime/ABI evidence before any native control call"]
    }


def markdown(report):
    types = "\n".join(f"| {r['name']} | `{r['vtable_rva']}` | `{r['rtti_type_descriptor_rva']}` | `{r['engine_descriptor_rva']}` | `{r['engine_descriptor_getter_rva']}` |" for r in report["class_proofs"])
    commands = "\n".join(f"| {r['name']} | `{r['hash']}` | `{r['branch_rva']}` | `{r['callee_rva']}` |" for r in report["findings"]["door_commands"])
    return f"""# 门、敌人原生接口静态复核与只读采样

这份成果接通了 Door/Health 的真实对象观测路径：从已审计的 ECS 表枚举、严格校验类与 owner，读取少量有代码证据的原始字段。门命令与 native 状态注册链已找到。当前没有执行开门、改血、生成敌人或网络复制；这份报告也不能证明当前机房门故障的原因。

## 固定构建与复现

- 游戏：`{report['input']['path']}`
- SHA-256：`{report['input']['sha256']}`
- 所有地址是该构建的 RVA，实际地址必须加已核验的模块基址。
- 本脚本 `{Path(__file__).name}` 只读 PE 文件，不打开游戏进程；导入同目录 `cinematic_static_probe.py` 的 PE/objdump 帮助函数。
- 运行：`python research/world_native_probe.py`。可用 `--game` 和 `--objdump` 指定本地文件； hash 不符即拒绝。
- 解码 {len(report['evidence_ranges'])} 个固定范围，总 {report['input']['bounded_disassembly_bytes']} 字节，每段最多 `0x4000`。指令、文件位置和 RTTI 闭合结果保存在同名 JSON。

## 对象类型：两种 descriptor 不可混用

| 类 | vtable RVA | MSVC RTTI TypeDescriptor | ECS engine descriptor/map key | virtual +0x48 getter |
|---|---|---|---|---|
{types}

脚本逐一核验 RTTI 类名 → COL → vtable 前置指针；再核验 virtual `+0x48` 的 `lea/ret` 确实返回对应 ECS engine descriptor。constructor 和派生初始化的指令证据也保留在 JSON。类型证据只能确定类关联，不能确定实时对象仍然存活或它就是玩家眼前某扇门、某个敌人。

## owner 与本地实例身份

`0x1676150` 将 component `+0x8` 绑定到实体表 entry，将输入 handle DWORD 放入 `+0x14`。`0x1676070` 从 owner 的 `+0xC/+0x10` 重组实体 handle；`0x15A0560` 拆成 20 位 index 和 11 位 generation，从全局 `0x7A44380`、count `0x7A4439C` 及 stride `0xC0` 解析并检查 generation。

这些是当前进程内的 lifetime handle。另一台电脑、重载后的同一实体可能不同；它们没有被当成 network ID。跨主客机的稳定 actor/asset key 仍缺证据。

compact component map 位于 entity `+0x68`，WORD count 位于 `+0x70`； hashed map 位于 `+0x80`，WORD capacity 位于 `+0x88`。每个 entry 是 16 字节的 descriptor/component 指针对。`0x167AB40` 是 compact lookup，`0x16799A0` 是 hash lookup，`0x1679A10` 用 compact map 构造 hash map，`0x1676720` teardown 也枚举 compact map。hash 中可有继承别名，所以采样器只枚举 compact map 并要求 exact key 和 exact vtable；缺失/未知都记 coverage gap。

## 门：已找到的命令与状态注册

DoorScriptAction `0x1F355B0` 的命令 enum descriptor 是 `0x50AE260`，具有下列六个名称/hash；分支调用在代码中可核对。

| 命令名称 | hash | dispatcher 分支 | native callee |
|---|---|---|---|
{commands}

Open/Close 路径进入 component `+0x18` 的 native 状态请求对象，再调用 `0x1984370 → 0x19858E0 → 0x1985F20 → 0x1985D50`。请求有 16 字节 payload，其中前 8 字节来自 opaque R9 key，第 8/9 字节来自 DL/R8B，其他表示和调用上下文尚未闭合。此静态链证明游戏存在原生命令入口，尚不足以安全执行调用。

Door `0x1F31A90` 用共同 registrar `0x1984190` 注册 `+0x48[12]`、`+0xBC[1]`、`+0xC1[1]`、`+0xBF[1]`、`+0x58[8]`； callback 注册指向 `0x1F32790/0x1F32820`。采样器读取前四项和有 saved-state 路径证据的 `+0xC2[1]`、`+0xC3[1]`、`+0xC4[4]`；`+0x58` 的表示未闭合，故不读取。

`SaveOpenedState`/ActorSaveComponent 的描述以及 `0x1F30C50` 的恢复路径表明存在门状态存档机制。`+0xC1` callback 涉及 entity enabled 流程，但尚不能等同于物理碰撞就绪。原始字节不会被解释成“已打开”“客机可穿过”。旧 DoorStep 只是玩家位置移动；其中使用指针的 scene hash 也不能用于跨进程身份。

## Health：原生状态登记与数值路径

Health `0x1F168F0` 登记 `+0x80[4]`、`+0x84[4]`、`+0x88[4]`、`+0xAC[2]`； `0x32E940` 读取 `+0x88` float。`0x1F16FC0` 的静态代码将输入限制到 `[0,+0x80]`、保存旧 `+0x88` 至 `+0x8C`、写新值并调用 `0x1676B90` 标记状态变化。callbacks `0x1F16CE0/0x1F16DA0` 根据数值和 flags 有条件触发事件。

采样器只输出 `+0x80[16]` 与 `+0xAC[2]` 的 raw hex。上述代码支持 cap/value/previous-value 的候选解释，但尚未把真实实例对应到可见敌人，也未核验伤害、死亡、AI、奖励及 spawn 生命周期。不能仅复制一个 float 就宣称敌人同步完成。

## GameNet 结论的边界

先前 `序章修复调查/电梯门初始化_GameNet只读复核_20261007.md/json` 已复核 GameNet manager、GameStateSystem 与 registry。这里补核 registry `0x1F02AB0` 队列以及 `0x1F02C90/0x1F02D40` 请求/完成，确有本地实体 handle 解析及 `0x1986230` deserialize 调用。Door 与 Health 自身有 native 状态登记，使它们成为合理的进一步调查目标；但当前场景初始快照、network transport、host authority 和碰撞覆盖仍没有闭合。不能据此说启用 GameNet 即解决门或怪不一致。

## 已实现的只读模块与验证

接口：`coopsync::runtime::CaptureWorldRaw(base, image_size, sequence)`，源码 `src/runtime/runtime_world.h/.cpp`。调用者须先通过固定构建 hash gate。它只使用 `ReadProcessMemory(GetCurrentProcess())`：每次滚动最多 128 entity，map 最多 128 slot，最多 16384 read / 1MiB，并保留最终 global table 校验预算；最多接受 32 component，输出控制在世界采样 48KiB 配额内。

每份接受记录要求两次 raw 字段相同、component vtable/owner/handle 相同、map key/value 相同、entity index/generation/map header 相同，以及最终 global table pointer/count 相同。失败、预算耗尽、map 超限都显式记录 gap。前后相等不能排除所有 interleaving/ABA，因此它只是局部原始观察，没有 coherent 全世界 snapshot 保证。

输出始终声明 coverage 不完整、local handle 不是 network ID，并将 door-open/collision-ready/enemy-health-or-death/world-replication verified 设为 false。没有 hook、game calls、game writes。纯 mock 测试 `research/runtime_world_mock_tests.cpp` 直接编译生产实现，已通过 37 项确定性检查，覆盖读取中变化、短读拒绝、预算、游标及 33 Door 下记录/输出配额。MSVC `/std:c++17 /W4 /WX` 编译通过；测试没有使用游戏进程。

下一步需要真实 Door/Health 接受记录与可见开门/战斗动作的对应证据，再闭合跨主客机 actor key、门视觉/碰撞状态以及敌人 spawn/AI/伤害/死亡 authority；最后核实 game-thread、对象生命周期和调用 ABI，才能启用控制。
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=pe.GAME)
    parser.add_argument("--objdump", type=Path, default=pe.OBJDUMP)
    args = parser.parse_args()
    img = pe.Image(args.game)
    sha = hashlib.sha256(img.blob).hexdigest()
    if sha != EXPECTED_SHA256:
        raise SystemExit("REFUSED: executable SHA-256 does not match the pinned build")
    if len(RANGES) + len(CLASSES) > 40 or any(stop <= start or stop-start > 0x4000 for _, start, stop in RANGES):
        raise SystemExit("REFUSED: static disassembly budget")
    proofs = [class_proof(img, row) for row in CLASSES]
    ranges = list(RANGES) + [(f"{row[0]} engine descriptor getter", row[4], row[4] + 8) for row in CLASSES]
    report = {"format": 1, "scope": "pinned file-only native-world interface evidence",
              "input": {"path": str(args.game.resolve()), "sha256": sha, "image_base_preferred": hex(img.base),
                        "image_size": hex(img.pe.OPTIONAL_HEADER.SizeOfImage),
                        "bounded_disassembly_bytes": sum(stop-start for _, start, stop in ranges)},
              "capabilities": {"process_access": False, "injection": False, "game_calls": False,
                               "writes_to_game": False, "network_sync_implemented": False},
              "class_proofs": proofs, "door_command_enum": pe.enum_descriptor(img, 0x50AE260),
              "findings": fixed_findings(), "evidence_ranges": pe.evidence_ranges(img, args.objdump, ranges)}
    declared = {r["name"]: int(r["hash"], 16) for r in report["findings"]["door_commands"]}
    actual = {r["name"]: int(r["hash"], 16) for r in report["door_command_enum"]["values"]}
    if declared != actual:
        raise ValueError("Door command name/hash metadata mismatch")
    (ROOT / "world_native_findings.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "world_native_findings.md").write_text(markdown(report), encoding="utf-8")
    print(f"Pinned world evidence: {len(proofs)} RTTI/engine-descriptor proofs, {len(ranges)} bounded ranges; reports written.")


if __name__ == "__main__":
    main()
