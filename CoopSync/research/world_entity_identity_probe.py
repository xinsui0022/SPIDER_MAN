"""Pinned file-only entity-key and Health/BotHealth identity evidence report.

Reads fixed PE metadata and <= 16 bounded disassembly ranges. No process use.
The separately saved live raw-key report is summarized without upgrading IDs.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import struct

import cinematic_static_probe as pe
from world_native_probe import CLASSES, class_proof

ROOT = Path(__file__).resolve().parent
RANGES = (
    ("Entity qword key array accessor", 0x159DA80, 0x159DA8F),
    ("Entity-to-opaque-key wrapper", 0x1F7B550, 0x1F7B567),
    ("Entity-to-tagged-opaque-key builder", 0x1F7B8E0, 0x1F7B97B),
    ("Local entity-handle-to-opaque-key builder", 0x1F7B330, 0x1F7B433),
    ("Tagged opaque-key reverse resolver", 0x1F7B760, 0x1F7B845),
    ("Native state local handle resolver", 0x1984400, 0x1984442),
    ("Native state local pointer pool getter", 0x1981770, 0x198178C),
    ("Entity key dictionary lookup", 0x1BCF530, 0x1BCF5AF),
    ("ShotBase engine descriptor getter", 0x207FCC0, 0x207FCC8),
    ("Door action obtains source actor key", 0x1F3563A, 0x1F35654),
)


def inheritance(img, proof):
    ch = int(proof["class_hierarchy_rva"], 16)
    raw = img.data(ch, 16)
    if len(raw) != 16:
        raise ValueError("RTTI hierarchy unavailable")
    sig, attrs, count, array = struct.unpack("<4I", raw)
    if not 0 < count <= 32:
        raise ValueError("RTTI inheritance count bound refused")
    result = []
    for index in range(count):
        bcd = struct.unpack("<I", img.data(array + index * 4, 4))[0]
        td, contained, mdisp, pdisp, vdisp, flags = struct.unpack("<IIiiiI", img.data(bcd, 24))
        result.append({"name": pe.cstring(img, td + 16, 128), "descriptor_rva": hex(bcd),
                       "rtti_type_descriptor_rva": hex(td), "contained_bases": contained,
                       "member_displacement": mdisp, "vbtable_displacement": pdisp,
                       "vbase_displacement": vdisp, "attributes": flags})
    return {"class": proof["name"], "hierarchy_rva": hex(ch), "signature": sig,
            "attributes": attrs, "base_array_rva": hex(array), "bases": result}


def live_summary(path):
    if not path.exists():
        return {"status": "saved_live_report_not_present", "path": str(path)}
    if path.stat().st_size > 128 * 1024:
        raise ValueError("Saved live key report exceeds bound")
    row = json.loads(path.read_text(encoding="utf-8"))
    accepted = row.get("accepted", [])
    keys = [r["candidate_key_u64"] for r in accepted]
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "pid": row.get("pid"), "utc": row.get("utc"), "status": row.get("status"),
            "counts": dict(collections.Counter(r["type"] for r in accepted)),
            "accepted": len(accepted), "gaps": len(row.get("gaps", [])),
            "distinct_raw_keys_in_this_small_window": len(set(keys)),
            "high_bit_set": sum(r["candidate_key_high_bit_set"] for r in accepted),
            "budget": row.get("budget"), "global_headers_unchanged": row.get("global_headers_unchanged"),
            "source_prefix": row.get("source"), "peer_id_verified": False,
            "cross_reload_stability_verified": False, "cross_peer_stability_verified": False}


def markdown(report):
    live = report["saved_live_raw_candidate_observation"]
    return f"""# 门、Health 实例身份候选：阶段成果

找到并实际读取了独立于 entity local handle 的 64-bit 数组键。当前只称 raw candidate；来源、跨存档加载稳定性、跨主客机映射和动态 spawn 唯一性仍未核验。不能把它直接升级为 network entity ID。

## 固定构建与证据

SHA-256：`{report['game_sha256']}`。脚本 `research/world_entity_identity_probe.py` 只读游戏 PE 文件，复核 {len(report['evidence_ranges'])} 个固定反汇编范围与 RTTI inheritance。JSON 保存指令字节和 RVA。所有 native 入口只用于静态核对，没有调用。

`0x159DA80` 是 15 字节 leaf getter：从 `[entity+0xC]` 取 index，从 `[game+0x7A4A450]` 取数组指针，再读 `array[index*8]`，返回 qword。索引/8-byte 布局已闭合；数组 allocation/capacity 和键的生产者尚未闭合。

`0x1F7B550 → 0x1F7B8E0` 被 DoorScriptAction `0x1F35643` 调用来构造 source actor key。builder 有三条路径：

| 路径 | 来源 | reverse resolver | 判断边界 |
|---|---|---|---|
| 高位为 1 的 qword | `0x159DA80` 数组键 | `0x1F7B760` 经字典 `game+0x7A4A458` / `0x1BCF530` 查 entity | 目前最有价值的稳定 actor 身份候选；仍未知生产/存档/跨机来源 |
| tag `0x1000000000000` | entity `+0xA8` 经 `0x1984400` 得 state object 的 `+4` DWORD | 低 DWORD 又交 `0x1984400`，查本地 pool `game+0x7A65F00`，核对 generation byte `+0x11D` | native state/pool handle 路径，不能当已验证的跨机稳定 ID |
| tag `0x2000000000000` | component engine descriptor `0x7C54E80` 的 `+0x104` DWORD | 经 `0x215F100` 与 entity local resolver | RTTI/vtable getter 将 descriptor 闭合到 ShotBase，属于剧情镜头对象；不适合当通用门/敌人 ID |

builder 优先 state 路径；否则只有数组键高位为 1 时直接返回它，非负数组值还会查 ShotBase。数组值本身与这些 tagged 表示必须区分。`ActorUID` 名称在静态 metadata `0x4FD4678` 出现，是进一步查找 actor 身份的线索；尚未把该类型名称和上述无符号函数链闭合，名称也不能证明每个 raw 数值具备稳定语义。

## 已实现的一次有界只读验证

`research/world_identity_runtime_probe.py` 只从已完成的 JSONL 行选择最多 16 个 previously accepted Door/Health 实例，使用既有 `WindowsBackend/Session` 的 executable hash / PID / process path / module gate；另外复核 live getter 的 15 字节与固定构建一致。只使用读/查询权限，不 scan 全进程、不调用游戏函数、不注入、不 hook、不写游戏。

读取前后验证 global entity table/count/key-array pointer；每个对象验证 entity index/generation、component vtable/owner/local handle、两次 raw qword key。原始 source table/count/identity 不匹配就拒绝。限制 512 reads / 4096 bytes，最大单读 15 bytes；array capacity 仍明确 unknown。前后相等不保证排除 ABA。

纯 mock `research/world_identity_probe_selfcheck.py` 已通过 22 项检查：身份/键/全局 header 变化、错误 vtable、短读、16-object 与 reads/bytes 配额。没有使用游戏进程。

实际新进程 PID `{live.get('pid')}` 的成功保存结果：accepted `{live.get('accepted')}`、gaps `{live.get('gaps')}`，类型 `{live.get('counts')}`，其中高位为 1 的 key `{live.get('high_bit_set')}`；实际 budget `{live.get('budget')}`。见 `{Path(live['path']).name}`。初次读取旧 scene 记录时全部16候选在 entity identity 重验失败，未接受key，说明场景切换时不能沿用旧handle。

一扇 DoorAnimated 的 raw key 是 `0x966E09ABC9EE1EF3`，只是在当前进程内该观测窗口不变。后续应在同一保存点重载及第二台主客机验证同一场景 actor 的一致性，并检查多实例/dynamic spawn 会否重复；目前没有完成这些检验。

## Health 与 BotHealth 的实际关系

RTTI hierarchy 明确 `BotHealth → Health → Component`，三个 subobject displacement 都为 0。Health 和 BotHealth 可沿用已闭合的 base Health 字段读取布局。RTTI 名称没有把实际 actor 标注为玩家或敌人；直接把所有 Health 算玩家、只把 BotHealth 算敌人会漏掉待核实对象。

本轮 log 已观测许多 Health、少量 DoorAnimated/DoorSlide，尚未观测 BotHealth；这属于 incomplete rolling window 的采样分布，不能证明游戏没有 BotHealth，或某个 Health 必然是敌人。成功的 raw key probe 为 15 Health + 1 DoorAnimated。

## 下一版合理的采样改进

当前 table count 为 92160，滚动每窗口最多128，所以理想条件也需720窗口才遍历一圈；采样间隔100ms时至少约72秒。真实记录还会遇到 map/budget/record cap。因此该发现扫描可以找实例，却难以捕捉短时间伤害或门变化。

下一版可保留 discovery 的 rolling window，并另设最多16或32个已发现实例的持续采样 cache，每 tick 重新检查 table/owner/generation/component handle/vtable/map binding 后读 raw 字段；身份变化立即移除，metadata声明coverage不完整和缓存上限。Health 与 BotHealth 都保留；按可见战斗动作、已有任务时间、同owner的已审计 AI/Player component 类型关联确定角色，而不按类名猜测。

同样可给已审计数组候选键加一次 raw 记录，为主客机同场景/重载比较收集证据。这些只读改进须在下一次构建/重载模块时实施；本轮没有改已加载 DLL 源码，也没有启用世界控制或复制。
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=pe.GAME)
    parser.add_argument("--objdump", type=Path, default=pe.OBJDUMP)
    parser.add_argument("--runtime-report", type=Path, default=ROOT / "world_entity_identity_runtime_20261011_10516_level.json")
    args = parser.parse_args()
    img = pe.Image(args.game)
    sha = hashlib.sha256(img.blob).hexdigest()
    if sha != pe.EXPECTED_SHA256:
        raise SystemExit("REFUSED: pinned executable mismatch")
    if len(RANGES) > 16 or any(stop <= start or stop-start > 0x4000 for _, start, stop in RANGES):
        raise SystemExit("REFUSED: bounded disassembly budget")
    proof = class_proof(img, ("ShotBase", 0x38388E8, 0x6BAA5E8, 0x5567A70, 0x207FCC0, 0x7C54E80, 0))
    raw = img.data(0x159DA80, 15)
    if raw != bytes.fromhex("8b 51 0c 48 8b 05 c6 c9 4a 06 48 8b 04 d0 c3"):
        raise ValueError("Entity key accessor encoding mismatch")
    health_rows = [class_proof(img, row) for row in CLASSES if row[0] in ("Health", "BotHealth")]
    report = {"format": 1, "scope": "entity raw key candidate; stability unknown", "game_path": str(args.game),
              "game_sha256": sha, "process_access": False, "game_calls": False, "game_writes": False,
              "stable_network_identity_verified": False, "actor_uid_metadata": img.location(0x4FD4678),
              "entity_key_accessor": {"rva": "0x159da80", "bytes": raw.hex(" "),
                                      "layout": "qword *(game+0x7A4A450)[DWORD(entity+0xC)]", "array_capacity_unknown": True,
                                      "key_producer_unknown": True, "cross_reload_or_cross_peer_stability_unknown": True},
              "shot_base_descriptor_proof": proof, "health_inheritance": [inheritance(img, row) for row in health_rows],
              "saved_live_raw_candidate_observation": live_summary(args.runtime_report),
              "evidence_ranges": pe.evidence_ranges(img, args.objdump, RANGES)}
    (ROOT / "world_entity_identity_findings.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "world_entity_identity_findings.md").write_text(markdown(report), encoding="utf-8")
    print("Pinned entity-key evidence: 10 bounded ranges, RTTI Health/BotHealth and ShotBase closure; reports written.")


if __name__ == "__main__":
    main()
