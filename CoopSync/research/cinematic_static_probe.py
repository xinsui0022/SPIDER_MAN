"""Reproducible, file-only cinematic interface probe for the pinned game build.

Reads the PE and invokes objdump for bounded disassembly. Does not open a game
process, launch the game, inject, patch, or call game functions. Writes only its
two reports beside this script. Python 3.11 + pefile; local GNU objdump required.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

import pefile

from runtime_config import game_executable, objdump_executable

GAME = game_executable()
EXPECTED_SHA256 = "e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1"
OBJDUMP = objdump_executable()
ROOT = Path(__file__).resolve().parent
STRINGS = ("SkipCinematic", "SkipMovieNode", "EndCinematic", "SetToEnd", "SetToEndAndHide",
           "LastFrame", "Skipped", "Cinematic2Component", "Cinematic2Manager", "Cinematic2System")
RTTI_NAMES = (".?AVCinematic2Component@@", ".?AVCinematic2Manager@@", ".?AVCinematic2System@@",
              ".?AVCinematic2Action@@", ".?AVCinematic2ActionPrius@@", ".?AVCinematic2ListenerAction@@",
              ".?AVCinematic2ListenerActionPrius@@")
MAX_FUNCTION_BYTES = 0x4000
MAX_XREF_FUNCTIONS = 90
MAX_VTABLE_METHODS = 96


class Image:
    def __init__(self, path: Path):
        self.path = path
        self.blob = path.read_bytes()
        self.pe = pefile.PE(data=self.blob, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.sections = []
        for s in self.pe.sections:
            self.sections.append({"name": s.Name.decode("ascii").rstrip("\0"),
                                  "rva": s.VirtualAddress, "file_offset": s.PointerToRawData,
                                  "raw_size": s.SizeOfRawData, "virtual_size": s.Misc_VirtualSize,
                                  "executable": bool(s.Characteristics & 0x20000000),
                                  "writable": bool(s.Characteristics & 0x80000000)})
        pdata = next(s for s in self.sections if s["name"] == ".pdata")
        pd = self.data(pdata["rva"], pdata["raw_size"])
        self.functions = sorted((a, b, unwind) for a, b, unwind in struct.iter_unpack("<III", pd[:len(pd)//12*12]) if a and b > a)
        self.starts = [a for a, _, _ in self.functions]

    def section(self, rva):
        return next((s for s in self.sections if s["rva"] <= rva < s["rva"] + s["raw_size"]), None)

    def data(self, rva, size):
        s = self.section(rva)
        if s is None:
            return b""
        off = s["file_offset"] + rva - s["rva"]
        return self.blob[off:off + min(size, s["rva"] + s["raw_size"] - rva)]

    def location(self, rva):
        s = self.section(rva)
        return {"rva": hex(rva), "preferred_va": hex(self.base + rva),
                "file_offset": hex(s["file_offset"] + rva - s["rva"]) if s else None,
                "section": s["name"] if s else None}

    def function(self, rva):
        n = bisect.bisect_right(self.starts, rva) - 1
        if n >= 0 and self.functions[n][0] <= rva < self.functions[n][1]:
            a, b, u = self.functions[n]
            return {"begin_rva": hex(a), "end_rva": hex(b), "unwind_rva": hex(u), "source": ".pdata"}
        return None

    def executable(self, rva):
        s = self.section(rva)
        return bool(s and s["executable"])

    def occurrences(self, needle):
        out = []
        for s in self.sections:
            blob = self.data(s["rva"], s["raw_size"])
            for m in re.finditer(re.escape(needle), blob):
                out.append(s["rva"] + m.start())
        return out

    def rip_candidates(self, targets):
        out = []
        for s in self.sections:
            if not s["executable"]:
                continue
            blob = self.data(s["rva"], s["raw_size"])
            # Candidate scanner only; objdump at .pdata entry independently checks
            # the real instruction boundary of the registration uses below.
            for m in re.finditer(rb"[\x48-\x4f][\x8d\x8b][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]....", blob, re.DOTALL):
                src = s["rva"] + m.start()
                dst = src + 7 + struct.unpack_from("<i", m.group(), 3)[0]
                if dst in targets:
                    out.append({"instruction_rva": hex(src), "target_rva": hex(dst), "labels": targets[dst],
                                "bytes": m.group().hex(" "), "status": "raw RIP-relative candidate", "function": self.function(src)})
        return out


def disassemble(img, tool, start, stop):
    stop = min(stop, start + MAX_FUNCTION_BYTES)
    p = subprocess.run([str(tool), "-d", "--wide", "-M", "intel", f"--start-address={hex(img.base + start)}",
                        f"--stop-address={hex(img.base + stop)}", str(img.path)], capture_output=True, text=True, timeout=30)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    lines = [line.strip() for line in p.stdout.splitlines() if re.match(r"\s*[0-9a-f]+:\s", line)]
    return lines


def parse_instructions(img, lines):
    out = []
    for line in lines:
        m = re.match(r"([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)", line)
        if not m:
            continue
        va = int(m.group(1), 16)
        raw = bytes.fromhex(m.group(2))
        text = m.group(3).strip()
        row = {"rva": hex(va - img.base), "bytes": raw.hex(" "), "instruction": text}
        if raw[:1] in (b"\xe8", b"\xe9") and len(raw) == 5:
            row["direct_target_rva"] = hex(va - img.base + 5 + struct.unpack_from("<i", raw, 1)[0])
        if "#" in text:
            m2 = re.search(r"#\s*(?:0x)?([0-9a-f]+)", text)
            if m2:
                row["rip_target_rva"] = hex(int(m2.group(1), 16) - img.base)
        out.append(row)
    return out


def rtti(img):
    out = []
    for name in RTTI_NAMES:
        for string_rva in img.occurrences(name.encode() + b"\0"):
            td = string_rva - 16
            for ptype in img.occurrences(struct.pack("<I", td)):
                col = ptype - 12
                raw = img.data(col, 24)
                if len(raw) != 24:
                    continue
                sig, objoff, cdoff, typ, cls, self_ = struct.unpack("<6I", raw)
                if sig != 1 or typ != td or self_ != col:
                    continue
                for pointer in img.occurrences(struct.pack("<Q", img.base + col)):
                    vt = pointer + 8
                    methods = []
                    for k in range(MAX_VTABLE_METHODS):
                        rawptr = img.data(vt + k * 8, 8)
                        if len(rawptr) != 8:
                            break
                        fn = struct.unpack("<Q", rawptr)[0] - img.base
                        if not img.executable(fn):
                            break
                        methods.append({"slot": k, "slot_offset": hex(k * 8), "target_rva": hex(fn), "function": img.function(fn)})
                    out.append({"name": name, "type_descriptor": img.location(td), "complete_object_locator": img.location(col),
                                "object_offset": hex(objoff), "constructor_displacement": hex(cdoff), "class_hierarchy_rva": hex(cls),
                                "vtable": img.location(vt), "methods": methods,
                                "note": "RTTI validates class association; slot semantics and runtime object lifetime remain unknown."})
    return out


def cstring(img, rva, limit=512):
    raw = img.data(rva, limit).split(b"\0", 1)[0]
    return raw.decode("ascii") if raw and all(32 <= c < 127 for c in raw) else None


def enum_descriptor(img, rva):
    raw = img.data(rva, 0x50)
    identifier, count = struct.unpack_from("<II", raw)
    if not 0 < count <= 256:
        raise ValueError("Unexpected enum count")
    hash_table, name_table, description_table = (struct.unpack_from("<Q", raw, off)[0] - img.base for off in (0x18, 0x20, 0x28))
    rows = []
    for k in range(count):
        hash_ = struct.unpack("<I", img.data(hash_table + k * 4, 4))[0]
        name_rva = struct.unpack("<Q", img.data(name_table + k * 8, 8))[0] - img.base
        description_rva = struct.unpack("<Q", img.data(description_table + k * 8, 8))[0] - img.base
        rows.append({"index": k, "hash": hex(hash_), "name": cstring(img, name_rva), "name_location": img.location(name_rva),
                     "description": cstring(img, description_rva), "description_rva": hex(description_rva)})
    return {"descriptor": img.location(rva), "identifier": hex(identifier), "count": count,
            "hash_table_rva": hex(hash_table), "name_table_rva": hex(name_table), "description_table_rva": hex(description_table), "values": rows}


def direct_candidates(img, targets):
    out = []
    for s in img.sections:
        if not s["executable"]:
            continue
        blob = img.data(s["rva"], s["raw_size"])
        for m in re.finditer(rb"(?=([\xe8\xe9]....))", blob, re.DOTALL):
            raw = m.group(1)
            src = s["rva"] + m.start()
            dst = src + 5 + struct.unpack_from("<i", raw, 1)[0]
            if dst in targets:
                out.append({"instruction_rva": hex(src), "target_rva": hex(dst), "label": targets[dst],
                            "bytes": raw.hex(" "), "status": "raw direct-call/jump candidate", "function": img.function(src)})
    return out


def evidence_ranges(img, objdump, ranges):
    out = []
    for label, start, stop in ranges:
        rows = parse_instructions(img, disassemble(img, objdump, start, stop))
        out.append({"label": label, "start_rva": hex(start), "end_rva": hex(stop),
                    "entry_runtime_function_fragment": img.function(start), "instructions": rows,
                    "note": "Linear bounded static decode. .pdata entries can be unwind fragments; decoded lines alone do not prove reachability."})
    return out


def state_identity_evidence(img):
    branches = struct.unpack("<8I", img.data(0x16695A0, 32))
    assert branches[4] == 0x1669496
    return {
        "status": "static selection, equality check and conditional forwarding established; full state/ID semantics unverified",
        "selection_slot": {"owner_class": "Cinematic2System", "owner_rva": "0x6044a60", "offset": "0x11d0", "slot_rva": "0x6045c30",
                           "clear_instruction_rvas": ["0x16730f5", "0x16731c6"], "select_instruction_rva": "0x1673268",
                           "selection_test": "component type descriptor check and byte +0xC7 != 0",
                           "component_type_proof": "RTTI component vtable +0x48 points to 0x165f170, which returns 0x7462dd0; update compares against this same descriptor",
                           "meaning": "selected flagged component pointer only; update clears before enumeration, and zero/nonzero is not a start/end event"},
        "raw_fields": [
            {"offset": "0x58", "size": 4, "proof": "dispatch reads/writes +0x58; update 0x1669228 reads it before switch", "semantics": "full enum meaning unverified"},
            {"offset": "0x5c", "size": 4, "proof": "SetToEnd 0x166a49d requests value 12 here", "semantics": "raw requested-state candidate, full meaning unverified"},
            {"offset": "0xc0", "size": 4, "proof": "SetToEnd/SetToEndAndHide 0x166a477/48b write 0/1 here", "semantics": "raw command-associated value only"},
            {"offset": "0xc7", "size": 1, "proof": "selection test 0x167325f", "semantics": "nonzero selects component; not independently proven playing flag"},
            {"offset": "0xc9", "size": 1, "proof": "Hide/Show 0x166a4f4/5a8 write 1/0; update 0x16688c0 exits when nonzero", "semantics": "raw Hide/Show-associated byte, full meaning unverified"},
            {"offset": "0xca", "size": 1, "proof": "action handler 0x167008c writes here", "semantics": "raw field only"}],
        "state_switch": {"read_instruction_rva": "0x1669228", "jump_table_rva": "0x16695a0", "index_base": 6,
                         "entries": [{"raw_value": k + 6, "branch_rva": hex(value)} for k, value in enumerate(branches)],
                         "observed_value_10_path": "branch 0x1669496 calls 0x16699b0; 0x16699c5 calls 0x166dd60 then reads float-like +0xF0; no name mapping established"},
        "reference_identity_candidate": {"key_offset": "0xa8", "pointer_offset": "0xb0", "validator_rva": "0x166b750",
                                         "proof": "validator compares all 64 key bits with qword [pointer+8] via upper/lower-32-bit equality; returns pointer only on match",
                                         "secondary_use": "update 0x1668af9..0x1668b51 repeats equality check before reading [pointer+0x10]",
                                         "cross_process_stable_id_verified": False, "runtime_fields_added": False,
                                         "limitation": "Equality key does not prove a cinematic ID, asset ID, lifetime generation, or stable identity across peers/reloads."},
        "conditional_notification": {"entry_rva": "0x166b890", "route": ["0x166b890", "0x1670f30", "0x1672ee0", "0x1670eb0", "0x1923a90"],
                                     "gates": ["component virtual slot +0x30 returns nonzero", "resolver for component+0xB8 returns an object", "lookup by descriptor 0x746DB50 finds an object", "forwarder has nonnull +0x58 and nonzero virtual +0x58 result", "System lookup yields nonnull recipients"],
                                     "vtable_gate_proof": "RTTI component slot +0x30 is 0x1675fc0; it loads object+8 and tail-jumps 0x159e040",
                                     "end_command": "0x166a45f passes TimedOut 0x3DCA3882; 0x166a4cf passes AlmostDone 0xDA8C6E3A into the gated route",
                                     "limitation": "Passing an event hash does not prove delivery, natural completion, full mission cleanup, or that this route is callable by the mod."},
    }


def recorded_runtime_observations():
    """Summarize existing probe logs, never open a process or sample here."""
    reports = []
    for relative in ("logs/cinematic_identity_runtime_20261010.json",
                     "logs/cinematic_readonly_baseline_20261010_current.jsonl",
                     "logs/runtime_baseline_20261010_recovered/cinematic.jsonl"):
        path = ROOT.parent / relative
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8-sig")
        records = [json.loads(line) for line in content.splitlines() if line.strip()] if path.suffix == ".jsonl" else [json.loads(content)]
        setup = next((r for r in records if r.get("record_type") == "session"), records[0])
        if setup.get("game_sha256") != EXPECTED_SHA256:
            raise ValueError(f"Recorded runtime build mismatch: {relative}")
        samples = [r for r in records if r.get("record_type") == "snapshot"] if path.suffix == ".jsonl" else records
        stable = [r for r in samples if r.get("status") == "component_identity_match_raw_state_only"]
        reports.append({"source": relative, "pid": setup.get("pid"), "game_sha256": setup["game_sha256"], "samples": len(samples),
                        "status_counts": dict(collections.Counter(r["status"] for r in samples)),
                        "slot_value_counts": dict(collections.Counter((r.get("component_slot") or {}).get("value", "not_sampled") for r in samples)),
                        "stable_raw_field_values": {offset: sorted({field["unsigned_value"] for r in stable for field in r["runtime_state_fields"] if field["offset"] == offset})
                                                    for offset in sorted({field["offset"] for r in stable for field in r["runtime_state_fields"]})},
                        "evidence_scope": "existing read-only log only; no independently observed user playback or skip, scene readiness, or world cleanup",
                        "verified_callable_interfaces": []})
    return reports


def cinematic_chain(img, objdump):
    commands = enum_descriptor(img, 0x4EF40B0)
    events = {"kind": "flattened output event metadata, not an enum descriptor", "count": 26,
              "hash_table_rva": "0x6253410", "name_table_rva": "0x6253478", "values": []}
    for k in range(26):
        name_rva = struct.unpack("<Q", img.data(0x6253478 + k * 8, 8))[0] - img.base
        events["values"].append({"index": k, "hash": hex(struct.unpack("<I", img.data(0x6253410 + k * 4, 4))[0]),
                                 "name": cstring(img, name_rva), "name_location": img.location(name_rva)})
    menu = enum_descriptor(img, 0x3A73810)
    assert commands["count"] == 17 and commands["values"][6]["name"] == "EndCinematic"
    assert events["values"][9]["name"] == "Skipped"
    assert menu["values"][7]["name"] == "SkipCinematic"
    branches = struct.unpack("<17I", img.data(0x166A6E0, 17 * 4))
    for row, branch in zip(commands["values"], branches):
        row["switch_branch_rva"] = hex(branch)
        assert img.executable(branch)
    # Windows reached through enum/table/RTTI references; never called or hooked.
    ranges = [
        ("Cinematic2Action slot +0x50 resolves command enum then dispatches", 0x166FFF0, 0x167020D),
        ("Cinematic2Component command dispatch, including chained .pdata fragments; excludes jump table", 0x166A320, 0x166A6E0),
        ("Metadata constructor for Cinematic2ActionPrius; installs RTTI-validated vtable", 0x1B32320, 0x1B32338),
        ("Metadata callback tail-calls object's vtable slot +0x50", 0x1B32340, 0x1B32347),
        ("Cinematic2ActionPrius returns its metadata descriptor", 0x1670DF0, 0x1670DF8),
        ("Cinematic2ActionPrius slot +0x28 is a null-return stub; not an action factory", 0x1670E20, 0x1670E23),
        ("Metadata serialization callback names Cinematic2ActionPrius descriptor", 0x1B32270, 0x1B322A4),
        ("Static Cinematic2Manager constructor stores RTTI vtable into direct global object", 0x183DC0, 0x183E34),
        ("Engine registry stores address of static Cinematic2System object", 0x2BC000, 0x2BCAD9),
        ("Menu enum consumer: decodes hash to index and stores UI config", 0x72E443, 0x72E49F),
        ("Menu enum consumer: serializes 123 UI config options", 0x730D70, 0x730E11),
        ("Menu enum consumer: converts hash to index", 0x1147680, 0x114769E),
        ("Cinematic event compilation maps event type to Skipped hash; excludes embedded switch table", 0x2500670, 0x2500AC4),
        ("System component selection clears slot then selects type-checked +C7 component", 0x1673190, 0x16732F4),
        ("System alternate update clears slot and iterates component update", 0x16730E0, 0x1673183),
        ("Component RTTI vtable +48 returns the descriptor used in System type check", 0x165F170, 0x165F178),
        ("Component raw reference identity equality validator", 0x166B750, 0x166B7A5),
        ("Component update reads raw state and validates A8/B0 identity before lookup", 0x16688B0, 0x1668CA2),
        ("Component raw state dispatch values 6..13; excludes embedded switch table", 0x1669228, 0x16695A0),
        ("Raw state value 10 branch target", 0x16699B0, 0x1669A18),
        ("Conditional component event forwarding, not an unconditional completion callback", 0x166B890, 0x166B8FC),
        ("Component vtable +30 gate loads owner and tail-jumps", 0x1675FC0, 0x1675FC9),
        ("Resolved event forwarder feeds System lookup", 0x1670F30, 0x1670F93),
        ("System resolves recipients before forwarding", 0x1672EE0, 0x1672F98),
        ("Resolved recipient tail-jumps through its +58 member", 0x1670EB0, 0x1670EB9),
    ]
    decoded = evidence_ranges(img, objdump, ranges)
    call_refs = direct_candidates(img, {0x166A320: "Cinematic2Component command dispatcher"})
    for candidate in call_refs:
        fn = candidate["function"]
        if fn:
            rows = parse_instructions(img, disassemble(img, objdump, int(fn["begin_rva"], 16), int(fn["end_rva"], 16)))
            candidate["status"] = ("instruction boundary confirmed by linear decode from .pdata fragment start"
                                   if candidate["instruction_rva"] in {x["rva"] for x in rows} else "unconfirmed boundary")
    global_objects = [
        {"class": "Cinematic2Manager", "object_rva": "0x6044830", "expected_vtable_rva": "0x3cf47b0",
         "storage": "direct static object, not a pointer slot", "constructor_rva": "0x183dc0",
         "proof": "0x183e15 LEA vtable; 0x183e1c MOV [ImageBase+0x6044830],RAX.",
         "runtime_validation": "limited vtable observations in separately recorded logs; no callable ABI verified", "state_fields": []},
        {"class": "Cinematic2System", "object_rva": "0x6044a60", "expected_vtable_rva": "0x3cf4c68",
         "storage": "direct static object, not a pointer slot", "registry_function_rva": "0x2bc000",
         "proof": "On-disk qword at 0x6044a60 points to RTTI-validated vtable; 0x2bc35a/361 registers this object address.",
         "runtime_validation": "limited vtable observations in separately recorded logs; no callable ABI verified", "state_fields": []},
    ]
    return {"status": "static command, raw-state and conditional notification evidence; UI_SKIP_MOVIE is tracked separately and runtime call ABI remains unverified",
            "commands": commands, "events": events, "menu_options": menu,
            "command_descriptor_pointer_rva": "0x6253080", "menu_descriptor_pointer_rva": "0x5ebcc08",
            "dispatch_rva": "0x166a320", "dispatch_jump_table_rva": "0x166a6e0",
            "dispatch_argument_observation": "Static instructions move RCX to RBX and sign-extend EDX to RDI (object and enum index candidates). Runtime object/thread validity unverified.",
            "dispatch_direct_reference_candidates": call_refs,
            "global_objects_for_read_only_identity_probe": global_objects, "evidence_disassembly": decoded,
            "state_and_identity_evidence": state_identity_evidence(img),
            "findings": [
                "SkipCinematic is UI option enum index 7 (hash 0xC96C7F67) in a 123-value descriptor. Located consumers serialize/deserialize UI config; they do not establish a manual-skip handler.",
                "Cinematic2Action RTTI vtable 0x3CF4908 slot +0x50 targets 0x166FFF0. It resolves component, enum and calls native dispatcher 0x166A320.",
                "EndCinematic index 6 branches to 0x166A45F; writes state +0x58=13, passes TimedOut hash 0x3DCA3882 to conditional forwarder 0x166B890, then common cleanup passes AlmostDone hash 0xDA8C6E3A. Actual delivery and equivalence to manual skip are not proven.",
                "SetToEnd index 8 and SetToEndAndHide index 9 branch to 0x166A475/48B. They write +0xC0 differently and request state 12. Their names/descriptions and distinct branches do not prove complete mission cleanup.",
                "Skipped hash 0x5D74A037 has one raw immediate occurrence in executable bytes, decoded MOV EBX at 0x2500818 inside event compilation. That occurrence is not a manual-skip entry point.",
                "Known global locations are direct objects. Runtime sampler checks their vtables, then selected component identity and six raw fields; no full state enum has been semantically validated.",
                "System +0x11D0 is cleared within updates before component selection. Its zero/nonzero transitions are selection observations, not reliable start/end notifications.",
                "Component +0xA8/+0xB0 has a statically verified 64-bit equality check. Cross-process stable cinematic identity remains unverified; the sampler does not read this candidate pair.",
            ]}


def probe(path, objdump):
    img = Image(path)
    digest = hashlib.sha256(img.blob).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit("Build mismatch: refusing to interpret addresses or overwrite pinned-build evidence.")
    targets = {}
    strings = []
    for name in STRINGS:
        hits = img.occurrences(name.encode() + b"\0")
        for rva in hits:
            targets.setdefault(rva, []).append(name)
        strings.append({"name": name, "locations": [img.location(rva) for rva in hits]})
    tables = rtti(img)
    for table in tables:
        for kind in ("type_descriptor", "vtable"):
            rva = int(table[kind]["rva"], 16)
            targets.setdefault(rva, []).append(table["name"] + ":" + kind)
    candidates = img.rip_candidates(targets)
    function_starts = sorted({int(row["function"]["begin_rva"], 16) for row in candidates if row["function"]})[:MAX_XREF_FUNCTIONS]
    disassembly = []
    for start in function_starts:
        info = img.function(start)
        stop = int(info["end_rva"], 16)
        decoded = parse_instructions(img, disassemble(img, objdump, start, stop))
        refs = [row for row in candidates if row["function"] and int(row["function"]["begin_rva"], 16) == start]
        decoded_addresses = {row["rva"] for row in decoded}
        for row in refs:
            row["status"] = "instruction boundary confirmed by objdump from .pdata function start" if row["instruction_rva"] in decoded_addresses else "not an instruction boundary in bounded objdump decode"
        disassembly.append({"function": info, "truncated": stop - start > MAX_FUNCTION_BYTES,
                            "references": refs, "instructions": decoded})
    pointer_refs = []
    for target, labels in targets.items():
        for source in img.occurrences(struct.pack("<Q", img.base + target)):
            pointer_refs.append({"source": img.location(source), "target_rva": hex(target), "labels": labels,
                                 "note": "Absolute pointer occurrence, not proof of callable registration."})
    chain = cinematic_chain(img, objdump)
    return {"schema": 2, "scope": "file-only pinned-build bounded static probe",
            "game": {"path": str(path), "sha256": digest, "image_base": hex(img.base), "size": len(img.blob), "sections": img.sections},
            "limits": {"max_function_bytes": MAX_FUNCTION_BYTES, "max_xref_functions": MAX_XREF_FUNCTIONS, "max_vtable_methods": MAX_VTABLE_METHODS},
            "dependencies": {"decoder": str(objdump), "pe_parser": pefile.__version__},
            "strings": strings, "rtti": tables, "rip_reference_candidates": candidates,
            "absolute_pointer_occurrences": pointer_refs, "xref_function_disassembly": disassembly,
            "static_dispatch_chain": chain,
            "recorded_runtime_observations": recorded_runtime_observations(),
            "verified_callable_interfaces": [],
            "limitations": ["Recorded logs contain limited runtime vtable/raw-field observations; no argument semantics, thread, active-state mapping, or callable lifecycle verified.",
                            "Neither strings nor RTTI slots are approved call addresses.",
                            "This static probe does not launch or access a game process, inject, write game memory, or call game functions."]}


def markdown(report):
    lines = ["# 过场接口：只读定位与已保存基线", "", "本报告由 `cinematic_static_probe.py` 从固定游戏构建生成，并汇总已保存的只读探针日志。生成器没有启动游戏、访问进程或修改游戏。",
             "", f"游戏 SHA-256：`{report['game']['sha256']}`。PE ImageBase：`{report['game']['image_base']}`。",
             "", "## 字符串映射", "", "| 名称 | 文件偏移 | RVA | 节 |", "|---|---|---|---|"]
    for row in report["strings"]:
        for loc in row["locations"]:
            lines.append(f"| {row['name']} | `{loc['file_offset']}` | `{loc['rva']}` | {loc['section']} |")
    lines += ["", "## RTTI 与虚函数表", "", "RTTI 证明类型关联，不能证明虚函数槽的语义。下列地址均为候选研究地址，不可直接调用。", ""]
    for row in report["rtti"]:
        lines.append(f"- `{row['name']}`：descriptor `{row['type_descriptor']['rva']}`，COL `{row['complete_object_locator']['rva']}`，对象偏移 `{row['object_offset']}`，vtable `{row['vtable']['rva']}`，连续代码指针 {len(row['methods'])} 个。")
    lines += ["", "## 引用与函数边界", "", "| 引用指令 RVA | 目标 | .pdata 函数起点 | 状态 |", "|---|---|---|---|"]
    for row in report["rip_reference_candidates"]:
        lines.append(f"| `{row['instruction_rva']}` | {', '.join(row['labels'])} | `{row['function']['begin_rva'] if row['function'] else 'unknown'}` | {row['status']} |")
    chain = report["static_dispatch_chain"]
    lines += ["", "## 已闭合的静态命令分发链", "",
              "`Cinematic2Action` RTTI vtable `0x3CF4908` 槽 `+0x50` → `0x166FFF0` → 读取命令描述符指针 `0x6253080`（内容指向 `0x4EF40B0`）→ 枚举解码 → 调用 `0x166A320` → 17 项 switch 表 `0x166A6E0`。",
              "`Cinematic2ActionPrius` 元数据描述符 `0x6253EF0` 的构造回调 `0x1B32320` 安装 RTTI vtable `0x3CF4A80`；数据回调 `0x1B32340` 跳转到对象虚函数槽 `+0x50`。这些是元数据/类型关联，不代表已核验游戏内调用。",
              "", "| 命令 | 枚举索引 | 分支 RVA | 游戏内描述 |", "|---|---|---|---|"]
    for row in chain["commands"]["values"]:
        if row["name"] in ("Triggered", "EndCinematic", "SetToEnd", "SetToEndAndHide"):
            lines.append(f"| {row['name']} | {row['index']} | `{row['switch_branch_rva']}` | {row['description']} |")
    lines += ["", "**不能把 EndCinematic 当作用户跳过接口。** 索引 6 的分支写入状态值 13，将 `TimedOut` 哈希 `0x3DCA3882` 传入有条件转发函数 `0x166B890`，公共收尾又传入 `AlmostDone` 哈希 `0xDA8C6E3A`；实际事件送达未验证，索引 8/9 的终态分支也不同。",
              "", "## 用户手动 Skip 的定位状态", "",
              "`SkipCinematic` 是 123 项 UI 选项枚举中的索引 7，哈希 `0xC96C7F67`。描述符 `0x3A73810` 由全局指针 `0x5EBCC08` 引用；代码使用处 `0x72E443`、`0x730D70`、`0x1147680` 是配置序列化/枚举转换，尚未连到手动跳过回调。",
              "`SkipMovieNode` 当前只有元数据名称线索。`Skipped` 输出事件哈希为 `0x5D74A037`；唯一代码立即数引用位于 `0x2500818`，其上下文是事件编译，不能当作跳过接口。",
              "另一路 `UI_SKIP_MOVIE` → `OverlayUI` 更新与 hold callback 的证据由 [ui_skip_findings.md](ui_skip_findings.md) 单独维护；callback 赋值来源/执行目标仍未闭合，不能声明原生 skip ABI 已可调用。",
              "", "## 已确认的全局对象候选", "",
              "| 类型 | 直接对象 RVA | 预期 vtable RVA | 静态证据 |", "|---|---|---|---|"]
    for row in chain["global_objects_for_read_only_identity_probe"]:
        lines.append(f"| {row['class']} | `{row['object_rva']}` | `{row['expected_vtable_rva']}` | {row['proof']} |")
    lines += ["", "它们是直接静态对象。配套 `cinematic_runtime_probe.py` 在已运行的固定构建中核验 SHA/path/module，只读核验两个对象 vtable，再读 System `+0x11D0` 的组件选择槽。组件非空且 vtable 为 `0x3CF4100` 时才读取以下原始字段；样本前后复核对象、指针与组件 vtable，失稳则丢弃字段。单样本最多 15 次/87 字节，只请求读取/查询权限。", "",
              "## 组件选择槽与原始状态", "",
              "`0x16731C6` 和另一更新路径 `0x16730F5` 都先清空 System `+0x11D0`；`0x1673268` 在类型检查通过、组件 `+0xC7 != 0` 时选入指针。组件 RTTI vtable `+0x48` → `0x165F170` 返回描述符 `0x7462DD0`，与更新中的类型检查目标一致。清零/非零变化只证明组件选择变化，不能视为开始/结束。",
              "", "| 字段偏移 | 字节数 | 静态证据 | 语义边界 |", "|---|---|---|---|"]
    state = chain["state_and_identity_evidence"]
    for row in state["raw_fields"]:
        lines.append(f"| `{row['offset']}` | {row['size']} | {row['proof']} | {row['semantics']} |")
    lines += ["", "`0x1669228` 读取 `+0x58`，八项表 `0x16695A0` 以原始值 6 为基准。值 10 → `0x1669496` → `0x16699B0`，随后调用 `0x166DD60` 并读取浮点式 `+0xF0`；尚无独立枚举名称映射，因此不把 10 命名为 Playing。",
              "", "## 身份候选与结束转发边界", "",
              "`0x166B750` 以组件 `+0xA8` 的 64 位值与 `[组件+0xB0 指针+8]` 比较，分别核对高/低 32 位；只有全等才返回 `+0xB0` 指针。`0x1668AF9..0x1668B51` 重复此核验后读取 `[指针+0x10]`。这证明内部引用一致性检查，仍不能证明该值是可跨端/重载稳定的 cinematic_id、asset_id 或 generation；当前 runtime probe 未加入这组字段。",
              "`0x166B890` 先调用组件虚表 `+0x30`（`0x1675FC0` 加载 owner `+8` 后跳 `0x159E040`），再解析组件 `+0xB8` 和描述符查找结果，均通过才转入 `0x1670F30` → `0x1672EE0` → `0x1670EB0` → `0x1923A90`。沿途有非空和虚函数结果门控，传入事件哈希不等于事件已送达，也不证明任务/门/碰撞/检查点收尾完成。",
              "", "## 已保存只读运行日志", "",
              "下列记录没有用户自然播放/手动跳过对照，也没有画面观察或场景就绪/世界收尾核验。", "",
              "| 日志 | PID | 样本数 | 状态计数 | 槽值计数 |", "|---|---|---|---|---|"]
    for row in report["recorded_runtime_observations"]:
        lines.append(f"| [{row['source']}](../{row['source']}) | {row['pid']} | {row['samples']} | {json.dumps(row['status_counts'])} | {json.dumps(row['slot_value_counts'])} |")
        if row["stable_raw_field_values"]:
            lines += ["", f"该日志稳定非空样本的原始字段：`{json.dumps(row['stable_raw_field_values'])}`。", ""]
    lines += ["", "三秒基线出现同一组件 `0x208807e7c30` 与空槽交替，并有一次采样中指针变化；这与更新中先清零再选择的静态行为一致。它提供了保守处理选择变化的证据，不能单独确定正在播放或已结束。没有可调用接口被升级为 verified。",
              "", "## runtime probe API 与复现", "",
              "`probe(pid=None)` 保留单次 dict API；`with Session(pid) as session` 做一次 setup，`session.metadata` 返回会话记录，`session.snapshot(i)` 返回只读样本。CLI 默认每行一个 compact JSON，record_type 为 session/snapshot/end；snapshot 顶层保留 sample、monotonic_ms、status、component_slot、runtime_state_fields、verified_callable_interfaces（始终列表）。",
              "`--output` 额外保存到独占创建的新文件，已有路径拒绝覆盖。`--self-check`/`--self-test` 同义，只执行内存 mock，不读游戏文件或进程。采样数量 1..3001，间隔至少 50ms，总计划时长不超过 300 秒，退出/失效会输出状态并停止；零/非零过渡仍不能证明组件整个生命期，瞬间 ABA 也无法由这些快照排除。",
              "", "```powershell", "& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\cinematic_runtime_probe.py --self-check",
              "& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\cinematic_runtime_probe.py --pid 25612 --samples 31 --interval-ms 100 --output .\\logs\\new_baseline.jsonl", "```",
              "", "## 真实适配状态", "", "目前没有通过运行时核验的过场开始、跳过、结束、场景加载完成接口。",
              "文件偏移、RVA、RTTI、vtable 匹配与原始字段不是可调用接口；未知参数、线程和生命周期不能凭名称推测。",
              "", "## 下一步证据", "", "1. 继续闭合 UI hold callback 的赋值来源与目标，核对参数和线程。",
              "2. 对身份候选核对资源元数据类型和跨重载稳定性，再决定是否加入只读字段。",
              "3. 后续受控自然播放/手动跳过对照需单独记录，不把现有静止/未知画面基线算作该验收。",
              "4. 确认结束转发和任务、门/碰撞、检查点的实际收尾关系，再决定游戏适配器范围。",
              "", "## 复现", "", "```powershell", "& 'C:\\Users\\xinsui\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' .\\research\\cinematic_static_probe.py", "```",
              "", "环境依赖：上述 Python 已有 `pefile`；反汇编器为 `C:\\TDM-GCC-64\\bin\\objdump.exe`。不需要 capstone 或联网安装。",
              "JSON 包含有界反汇编、原始指令字节、.pdata 片段边界与引用证据。`.pdata` 可能拆分单个函数，线性解码也可能包含内嵌数据，不等同完整控制流恢复。脚本哈希不匹配时停止，不覆盖固定构建证据。"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=GAME)
    parser.add_argument("--objdump", type=Path, default=OBJDUMP)
    args = parser.parse_args()
    report = probe(args.game.resolve(), args.objdump.resolve())
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "cinematic_interface_findings.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "cinematic_interface_findings.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"sha256": report["game"]["sha256"], "string_count": sum(len(x["locations"]) for x in report["strings"]),
                      "rtti_tables": len(report["rtti"]), "rip_candidates": len(report["rip_reference_candidates"]),
                      "xref_functions": len(report["xref_function_disassembly"]), "callable_interfaces": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
