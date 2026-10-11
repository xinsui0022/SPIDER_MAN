"""File-only bounded UI skip callback probe; never opens or modifies a process."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from cinematic_static_probe import Image, GAME, EXPECTED_SHA256, OBJDUMP, disassemble, parse_instructions, cstring, direct_candidates


ROOT = Path(__file__).resolve().parent
UI_OBJECT_RVA = 0x7B84580


def vtable_identity(img, vtable):
    raw = img.data(vtable - 8, 8)
    if len(raw) != 8:
        raise ValueError("Missing RTTI locator pointer")
    locator = struct.unpack("<Q", raw)[0] - img.base
    raw = img.data(locator, 24)
    if len(raw) != 24:
        raise ValueError("Missing RTTI locator")
    signature, offset, ctor_disp, type_descriptor, hierarchy, self_rva = struct.unpack("<6I", raw)
    name = cstring(img, type_descriptor + 16)
    if signature != 1 or self_rva != locator or not name or not name.startswith(".?AV"):
        raise ValueError("Invalid MSVC x64 RTTI locator")
    methods = []
    for slot in range(96):
        pointer = img.data(vtable + slot * 8, 8)
        if len(pointer) != 8:
            break
        target = struct.unpack("<Q", pointer)[0] - img.base
        if not img.executable(target):
            break
        methods.append({"slot": slot, "slot_offset": hex(slot * 8), "target_rva": hex(target),
                        "function": img.function(target)})
    return {"class": name, "vtable": img.location(vtable), "locator": img.location(locator),
            "type_descriptor": img.location(type_descriptor), "object_offset": hex(offset),
            "constructor_displacement": hex(ctor_disp), "hierarchy_rva": hex(hierarchy), "methods": methods}


def unwind_chain(img, address):
    entry = img.function(address)
    if entry is None:
        return []
    result = []
    seen = set()
    for _ in range(16):
        unwind = int(entry["unwind_rva"], 16)
        if unwind in seen:
            raise ValueError("Cyclic chained unwind metadata")
        seen.add(unwind)
        raw = img.data(unwind, 128)
        if len(raw) < 4 or raw[0] & 7 != 1:
            raise ValueError("Unexpected unwind format")
        flags, count = raw[0] >> 3, raw[2]
        chain_pos = 4 + ((count + 1) // 2) * 4
        record = {"runtime_function": entry, "flags": flags, "unwind_code_count": count,
                  "raw_unwind_bytes": raw[:chain_pos + (12 if flags & 4 else 0)].hex(" ")}
        if flags & 4:
            begin, end, parent_unwind = struct.unpack_from("<III", raw, chain_pos)
            entry = {"begin_rva": hex(begin), "end_rva": hex(end), "unwind_rva": hex(parent_unwind),
                     "source": "UNW_FLAG_CHAININFO"}
            record["parent"] = entry
        result.append(record)
        if not flags & 4:
            break
    return result


def confirm_references(img, references):
    cache = {}
    for reference in references:
        function = reference.get("function")
        if function:
            start = int(function["begin_rva"], 16)
            if start not in cache:
                cache[start] = parse_instructions(img, disassemble(img, OBJDUMP, start, int(function["end_rva"], 16)))
            row = next((r for r in cache[start] if r["rva"] == reference["instruction_rva"]), None)
            reference["status"] = "confirmed instruction boundary" if row else "unconfirmed boundary"
            if row:
                reference["decoded_instruction"] = row
    return references


def field_references(img, targets):
    """Bounded encoding coverage; absence is not proof that a field has no writer."""
    patterns = [
        (rb"[\x48-\x4f][\x89\x8b\x8d][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]....", 3, 7),
        (rb"\xc6[\x05\x0d\x15\x1d\x25\x2d\x35\x3d].....", 2, 7),
        (rb"\xc7[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]........", 2, 10),
        (rb"\xf3\x0f[\x10\x11][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]....", 4, 8),
    ]
    result = []
    for section in img.sections:
        if not section["executable"]:
            continue
        raw = img.data(section["rva"], section["raw_size"])
        for pattern, displacement_offset, instruction_size in patterns:
            for match in re.finditer(pattern, raw, re.DOTALL):
                source = section["rva"] + match.start()
                target = source + instruction_size + struct.unpack_from("<i", match.group(), displacement_offset)[0]
                if target in targets:
                    result.append({"instruction_rva": hex(source), "target_rva": hex(target),
                                   "label": targets[target], "bytes": match.group().hex(" "),
                                   "function": img.function(source), "status": "raw encoding candidate"})
    return confirm_references(img, result)


def report(img):
    previous = json.loads((ROOT / "ui_skip_findings.json").read_text(encoding="utf-8"))
    ranges = [
        ("OverlayUI static constructor installs both RTTI-validated vtables", 0x1CF9B0, 0x1CFAB2),
        ("OverlayUI vtable slot +0x10 initializes callback and context; leaf without .pdata", 0x1D1F850, 0x1D1F9E6),
        ("OverlayUI getter returns direct static object; leaf without .pdata", 0x1D20D50, 0x1D20D58),
        ("UI_SKIP_MOVIE input registration", 0x1D21B70, 0x1D21BB7),
        ("Input-registration caller obtains the direct OverlayUI object", 0xC5AE82, 0xC5B017),
        ("Callback setter accepts RDX and R8", 0x1D20A10, 0x1D20A7C),
        ("Clear callback and icon state", 0x1D20970, 0x1D20A05),
        ("OverlayUI vtable slot +0x18 update tail-jumps to hold handler", 0x1D1F9F0, 0x1D1FC98),
        ("Complete hold handler including all chained fragments and epilogues", 0x1D22BE0, 0x1D22E01),
        ("Icon method uses ShowSkipCineIcon and UpdateSkipCineIcon", 0x1D22470, 0x1D225F6),
        ("Rejected slot-offset collision: VultureEngagedBehavior constructor", 0x5B2BB0, 0x5B2E67),
        ("Rejected slot-offset collision: RBP is a stack-frame base", 0x16B0F00, 0x16B0F4F),
    ]
    evidence = []
    for label, start, stop in ranges:
        evidence.append({"label": label, "begin_rva": hex(start), "end_rva": hex(stop),
                         "entry_pdata_fragment": img.function(start),
                         "instructions": parse_instructions(img, disassemble(img, OBJDUMP, start, stop)),
                         "limits": "linear file-only decode; .pdata may describe an unwind fragment, not a full function"})
    setter = 0x1D20A10
    direct = confirm_references(img, direct_candidates(img, {setter: "callback setter"}))
    address = confirm_references(img, img.rip_candidates({setter: ["callback setter"]}))
    absolute = [img.location(rva) for rva in img.occurrences(struct.pack("<Q", img.base + setter))]
    rva32 = [img.location(rva) for rva in img.occurrences(struct.pack("<I", setter))]
    img.pe.parse_data_directories(directories=[0])  # IMAGE_DIRECTORY_ENTRY_EXPORT
    exports = getattr(getattr(img.pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", [])
    setter_exports = [{"name": (row.name or b"").decode("ascii", errors="replace"), "rva": hex(row.address)}
                      for row in exports if setter <= row.address < 0x1D20A7C]
    data = {"schema": 2, "scope": "file-only static UI input and callback research; no process access or writes",
            "game_sha256": EXPECTED_SHA256, "game_path": str(GAME), "image_base": hex(img.base),
            "overlay_sha256": previous["overlay_sha256"], "overlay_methods": previous["overlay_methods"],
            "verified_callable_interfaces": [], "tool_blocker": None,
            "ui_input": previous["ui_input"],
            "ui_identity": {"class": "GUI::OverlayUI", "storage": "direct static object, not a pointer slot",
                            "object_rva": hex(UI_OBJECT_RVA), "object_size_from_destructor": "0x2d0",
                            "getter_rva": "0x1d20d50", "constructor_rva": "0x1cf9b0",
                            "vtables": [vtable_identity(img, 0x4F44980), vtable_identity(img, 0x4F449E0)],
                            "proof": ["0x1cf9c7 loads 0x4f44980; 0x1cf9ce stores it at object RVA 0x7b84580",
                                      "0x1cf9dc loads 0x4f449e0; 0x1cf9ed stores it at object+0x158",
                                      "0x1d20d50 returns ImageBase+0x7b84580 by LEA, without dereferencing a pointer slot"]},
            "hold_handler": {"complete_begin_rva": "0x1d22be0", "complete_end_rva": "0x1d22e01",
                             "unwind_chain_from_callback_fragment": unwind_chain(img, 0x1D22C02),
                             "update_vtable_slot_offset": "0x18", "update_entry_rva": "0x1d1f9f0",
                             "update_tail_jump_rva": "0x1d1fc93", "active_offset": "0x210",
                             "elapsed_time_offset": "0x214", "threshold_offset": "0x218",
                             "callback_offset": "0x220", "context_offset": "0x228",
                             "indirect_call_rva": "0x1d22c9b", "callback_arguments_observed": "RCX=[this+0x228]; no other argument established",
                             "status": "static class and complete entry established; actual callback target remains unknown"},
            "read_only_runtime_targets": {"gate": "Pinned module path/hash and both vtables must match before field reads",
                                          "object_rva": "0x7b84580", "main_vtable_rva": "0x4f44980",
                                          "secondary_vtable_rva": "0x4f449e0", "secondary_vtable_offset": "0x158",
                                          "fields": {"active_raw": "0x7b84790", "elapsed_raw": "0x7b84794",
                                                     "callback": "0x7b847a0", "context": "0x7b847a8"},
                                          "limits": "Do not call the getter or callback; do not follow context; recheck identity and slot stability"},
            "callback_setter": {"begin_rva": hex(setter), "end_rva": "0x1d20a7c", "callback_source": "RDX", "context_source": "R8",
                                "threshold_source": "fifth argument float", "label_source": "R9, copied with limit 128",
                                "direct_call_or_jump_candidates": direct, "rip_address_candidates": address,
                                "absolute_pointer_occurrences": absolute, "rva32_occurrences": rva32,
                                "pe_export_table_count": len(exports), "exports_in_setter_range": setter_exports,
                                "search_limit": "Empty results only describe covered encodings; they do not prove the function is unused or absent"},
            "global_field_rip_references": field_references(img, {UI_OBJECT_RVA+0x210: "active", UI_OBJECT_RVA+0x214: "elapsed",
                                                                  UI_OBJECT_RVA+0x218: "threshold", UI_OBJECT_RVA+0x220: "callback",
                                                                  UI_OBJECT_RVA+0x228: "context"}),
            "global_field_search_limit": "Covered REX MOV/LEA, C6/C7 stores, F3 0F10/11 RIP forms only; not a full decompiler or alias analysis",
            "rejected_offset_collisions": [vtable_identity(img, 0x3870710),
                                           {"function_rva": "0x16b0f00", "reason": "0x16b0f10 LEA RBP,[RSP-0x1d0]; writes to RBP+0x220 concern the stack frame"}],
            "evidence_disassembly": evidence,
            "pending": ["actual callback assignment origin and target", "runtime observation during a naturally played skippable cutscene",
                        "callback thread/lifecycle and full native skip side effects"]}
    baseline_path = ROOT / "ui_skip_runtime_baseline_20261010.jsonl"
    if baseline_path.exists():
        baseline_blob = baseline_path.read_bytes()
        records = [json.loads(line) for line in baseline_blob.decode("utf-8").splitlines() if line.strip()]
        samples = [row for row in records if row.get("record_type") == "overlay_ui_snapshot"]
        data["separate_read_only_baseline_observation"] = {
            "file": baseline_path.name, "sha256": hashlib.sha256(baseline_blob).hexdigest(),
            "source": "ui_skip_runtime_probe.py; this static script only imports the saved JSONL",
            "pid": records[0].get("pid"), "module_base": records[0].get("module_base"),
            "sample_count": len(samples), "sample_statuses": [row["status"] for row in samples],
            "distinct_raw_fields": {offset: sorted({field.get("raw_hex") for row in samples for field in row.get("raw_fields", [])
                                                     if field["offset"] == offset}) for offset in ("0x210", "0x214", "0x220", "0x228")},
            "limits": "Paused baseline label supplied by parent; null callback slots do not establish the active cinematic state or lack of a native skip interface"}
    (ROOT / "ui_skip_findings.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    md = """# UI 原生跳过链：固定构建的只读证据

游戏 SHA-256：`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`。地址均为 RVA。此脚本只读 EXE；不打开进程，不注入，不写游戏内存，不执行游戏函数。完整指令与原始 unwind 字节见同名 JSON。

## 已确认的对象与输入链

RTTI 确认类型为 `GUI::OverlayUI`。直接静态对象位于 `ImageBase+0x7B84580`，并非指针槽。主虚表为 `0x4F44980`，次级虚表为 `0x4F449E0`（对象偏移 `+0x158`）。构造函数 `0x1CF9B0` 的 `0x1CF9CE`、`0x1CF9ED` 将上述虚表分别写入这两个位置；getter `0x1D20D50` 用 LEA 返回对象地址。

`UI_SKIP_MOVIE` 字符串 `0x4F44C48` 在 `0x1D21B79` 被输入注册函数 `0x1D21B70..0x1D21BB7` 引用；它调用 `0x1749A20` 解析输入标识，再以 `RCX=this+0x158`、`EDX=6`、`R8=输入标识` 调用 `0x1D1FE90`。直接调用点 `0xC5AFBB` 在调用 getter 后把返回对象交给此注册函数。这是输入注册链。

主虚表 slot `+0x18` 指向 `0x1D1F9F0`；其 `0x1D1FC93` 尾跳到完整长按处理入口 `0x1D22BE0`。从原回调片段 `0x1D22C02` 读取 `UNW_FLAG_CHAININFO`，依次指向 `0x1D22BF6`、`0x1D22BE0`。完整处理区间含其 epilogue，为 `0x1D22BE0..0x1D22E01`。

长按处理在 `this+0x214` 累积时间，与 `+0x218` 阈值比较；达到阈值后 `0x1D22C7B` 读取 `+0x220`，`0x1D22C94` 把 `+0x228` 放入 RCX，`0x1D22C9B` 间接调用回调。仅静态确认这个参数传递，不把它作为可调用接口。

## Setter 与尚未找到的回调

`0x1D20A10..0x1D20A7C` 将 RDX 写入 `+0x220`，R8 写入 `+0x228`，栈第 5 个 float 参数写入 `+0x218`，`+0x210` 设 1、计时清零；R9 标签复制到 `+0x230`，上限 128。`0x1D20970` 清理字段。RTTI slot `+0x10` 的 leaf 初始化函数 `0x1D1F850` 也清零回调与上下文；旧 slots 扫描因它无 `.pdata` 而漏报该位置，不能忽略无 `.pdata` 的字节候选。

固定 EXE 的 setter E8/E9 调用或尾跳、覆盖的 RIP 取址、绝对地址指针检索均为空；其 RVA32 唯一命中为 `.pdata` 表项。覆盖的直接全局字段 RIP 编码检索亦为空。这不是“无调用者”或“不支持原生跳过”的证明；别名、不同指令形式、内联及其他模块等仍未穷尽。

同偏移扫描可碰到无关类。`0x5B2BB0` 安装 `VultureEngagedBehavior` 虚表 `0x3870710`，不是 OverlayUI。`0x16B0F00` 的 RBP 从 RSP 生成栈帧，向 `RBP+0x220` 的代码地址写入也不能当作 UI 回调赋值。

## 定点只读运行时路径

先核验固定 EXE 路径、SHA-256、模块边界以及对象的双虚表；然后才可读取对象 `+0x210` 原始标志、`+0x214` 原始 float 字节、`+0x220` 回调指针、`+0x228` 上下文。绝对地址由运行时模块基址加 RVA 得到。定点字段 RVA 依次是 `0x7B84790`、`0x7B84794`、`0x7B847A0`、`0x7B847A8`。读取前后复核双虚表与指针槽；不扫描、解引用上下文，不调用 getter 或回调。

尚需在自然播放的可跳过过场中只读观察非零回调，并继续静态确认其目标与原生清理副作用。当前已核验可调用接口数量仍为 **0**。

## Overlay 图标方法与复现

原始 `Overlay.gfx` SHA-256：`401deb23e629567dc539de9029cdc55fb79ced7c4a48029121c34e312f231808`。ABC method 1150/1151/1152 的 `ShowSkipCineIcon`、`UpdateSkipCineIcon`、`HideSkipCineIcon` 只负责图标与进度；不能作为执行跳过接口。`SkipCinematic` UI 配置枚举和 `EndCinematic` 命令的 `TimedOut` 分支也未证明等于用户原生跳过。

在 CoopSync 目录运行（Python 3.11、pefile、已有 GNU objdump）：

```powershell
& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\ui_skip_probe.py --report
& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\ui_skip_probe.py --unwind 0x1D22C02
& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\ui_skip_probe.py --rtti 0x4F44980 0x4F449E0
& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\ui_skip_probe.py --range 0x1D22BE0 0x1D22E01
```
"""
    baseline = data.get("separate_read_only_baseline_observation")
    if baseline:
        md += "\n## 独立只读基线记录\n\n"
        md += f"父任务标注为 paused baseline 的 PID `{baseline['pid']}` 已保存到 `{baseline['file']}`；{baseline['sample_count']} 个采样均完成双虚表与槽前后复核。\n\n"
        for offset, values in baseline["distinct_raw_fields"].items():
            md += f"- `{offset}` 已接受采样的不同原始字节：`{' / '.join(values)}`。\n"
        md += "\n上述当前零值不能证明不存在过场或缺少原生跳过路径。`ui_skip_runtime_probe.py` 每个快照最多 8 次、69 字节定点读取；16 字节读取仅覆盖相邻且静态确立的 callback/context 两槽。复用 Session 的 SHA/path/module/只读 handle 门控，不调用 cinematic snapshot。槽或类型变化时丢弃字段，不调用函数，不解引用 context。\n\n"
        md += "```powershell\n& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\ui_skip_runtime_probe.py --self-check\n& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\ui_skip_runtime_probe.py --pid 25612 --samples 201 --interval-ms 100 --output .\\research\\ui_skip_observer_new.jsonl\n```\n\n输出文件必须是新文件；已存在时拒绝覆盖。PID 必须来自重新核验的当前游戏进程。\n"
    (ROOT / "ui_skip_findings.md").write_text(md, encoding="utf-8")
    return {"schema": 2, "evidence_ranges": len(evidence), "ui_object_rva": hex(UI_OBJECT_RVA),
            "setter_direct_refs": len(direct), "setter_address_refs": len(address),
            "setter_absolute_refs": len(absolute), "verified_callable_interfaces": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--range", nargs=2, metavar=("START_RVA", "END_RVA"))
    parser.add_argument("--strings", action="store_true")
    parser.add_argument("--slots", action="store_true")
    parser.add_argument("--direct", nargs="+", metavar="TARGET_RVA")
    parser.add_argument("--address", nargs="+", metavar="TARGET_RVA")
    parser.add_argument("--rtti", nargs="+", metavar="VTABLE_RVA")
    parser.add_argument("--unwind", nargs="+", metavar="CODE_RVA")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    img = Image(GAME)
    if hashlib.sha256(img.blob).hexdigest() != EXPECTED_SHA256:
        raise SystemExit("Pinned executable build mismatch")
    if args.report:
        print(json.dumps(report(img), ensure_ascii=False))
    if args.rtti:
        for target in args.rtti:
            print("RTTI", json.dumps(vtable_identity(img, int(target, 0))))
    if args.unwind:
        for target in args.unwind:
            print("UNWIND_CHAIN", json.dumps(unwind_chain(img, int(target, 0))))
    if args.strings:
        terms = ("SkipMovie", "UI_SKIP_MOVIE", "ShowSkipCineIcon", "UpdateSkipCineIcon", "HideSkipCineIcon")
        targets = {}
        for term in terms:
            hits = img.occurrences(term.encode() + b"\0")
            print("STRING", term, ", ".join(hex(hit) for hit in hits))
            for hit in hits:
                targets[hit] = [term]
        for ref in img.rip_candidates(targets):
            print("REF", json.dumps(ref))
    if args.range:
        start, end = (int(value, 0) for value in args.range)
        for row in parse_instructions(img, disassemble(img, OBJDUMP, start, end)):
            print(row["rva"], row["bytes"], row["instruction"])
    if args.direct:
        targets = {int(value, 0): value for value in args.direct}
        for reference in direct_candidates(img, targets):
            function = reference["function"]
            if function:
                rows = parse_instructions(img, disassemble(img, OBJDUMP,
                    int(function["begin_rva"], 16), int(function["end_rva"], 16)))
                reference["status"] = "confirmed instruction boundary" if reference["instruction_rva"] in {row["rva"] for row in rows} else "unconfirmed boundary"
            print("DIRECT_REF", json.dumps(reference))
    if args.address:
        targets = {int(value, 0): [value] for value in args.address}
        for reference in img.rip_candidates(targets):
            function = reference["function"]
            if function:
                rows = parse_instructions(img, disassemble(img, OBJDUMP,
                    int(function["begin_rva"], 16), int(function["end_rva"], 16)))
                reference["status"] = "confirmed instruction boundary" if reference["instruction_rva"] in {row["rva"] for row in rows} else "unconfirmed boundary"
            print("ADDRESS_REF", json.dumps(reference))
        for target in targets:
            for pointer in img.occurrences(struct.pack("<Q", img.base + target)):
                record = {"pointer_location": img.location(pointer), "target_rva": hex(target), "rtti_vtable_candidates": []}
                # Backtrack at most 512 vtable slots. Absolute qwords by themselves
                # are only data references; a matching MSVC COL validates association.
                for slot in range(512):
                    locator_pointer = pointer - 8 * (slot + 1)
                    raw_pointer = img.data(locator_pointer, 8)
                    if len(raw_pointer) != 8:
                        break
                    locator = struct.unpack("<Q", raw_pointer)[0] - img.base
                    raw_locator = img.data(locator, 24)
                    if len(raw_locator) != 24:
                        continue
                    signature, object_offset, ctor_disp, type_descriptor, hierarchy, self_rva = struct.unpack("<6I", raw_locator)
                    if signature != 1 or self_rva != locator:
                        continue
                    name = cstring(img, type_descriptor + 16)
                    if not name or not name.startswith(".?AV"):
                        continue
                    record["rtti_vtable_candidates"].append({"class": name, "slot": slot,
                        "slot_offset": hex(slot * 8), "vtable_rva": hex(locator_pointer + 8),
                        "complete_object_locator_rva": hex(locator), "object_offset": hex(object_offset)})
                    # The nearest valid COL is the relevant vtable start. Do not
                    # report earlier neighboring tables as if this were their slot.
                    break
                print("ABSOLUTE_POINTER", json.dumps(record))
    if args.slots:
        # Candidate scanner only. Each reported function must be independently
        # decoded from a .pdata start to confirm writes to the callback fields.
        functions = {}
        for section in img.sections:
            if not section["executable"]:
                continue
            data = img.data(section["rva"], section["raw_size"])
            for m in re.finditer(rb"[\x48-\x4f]\x89[\x80-\xbf][\x20\x28]\x02\x00\x00", data):
                source = section["rva"] + m.start()
                function = img.function(source)
                if function:
                    functions.setdefault(function["begin_rva"], []).append(hex(source))
                else:
                    print("SLOT_WRITE_WITHOUT_PDATA", hex(source), m.group().hex(" "), "raw candidate; independent boundary confirmation required")
        for function, references in sorted(functions.items(), key=lambda pair: int(pair[0], 16)):
            print("SLOT_WRITE_CANDIDATE", function, references)


if __name__ == "__main__":
    main()
