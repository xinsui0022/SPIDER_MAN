"""Offline SMT 0.5.1 traversal/coordinate audit. Writes only its own report files."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import struct
import subprocess
import sys

sys.dont_write_bytecode = True
from parse_title_abc import ABC, abc_blocks

ROOT = Path(__file__).resolve().parent
GAME = Path("D:/STEAM__/steamapps/common/Marvel's Spider-Man Remastered")
CORE = GAME / "SMT/Scripts/smt.dll"
OBJDUMP = Path("C:/TDM-GCC-64/bin/objdump.exe")


def main():
    blob = CORE.read_bytes()
    pe = struct.unpack_from("<I", blob, 0x3c)[0]
    table = pe + 24 + struct.unpack_from("<H", blob, pe + 20)[0]
    sections = []
    for number in range(struct.unpack_from("<H", blob, pe + 6)[0]):
        offset = table + 40 * number
        _, rva, size, file_offset = struct.unpack_from("<IIII", blob, offset + 8)
        sections.append((rva, size, file_offset))

    def rva_at(offset):
        for rva, size, file_offset in sections:
            if file_offset <= offset < file_offset + size:
                return rva + offset - file_offset
        return None

    def data_at(rva, count):
        for start, size, file_offset in sections:
            if start <= rva < start + size:
                return blob[file_offset + rva - start:file_offset + rva - start + count]
        return b""

    terms = re.compile(rb"noclip|no.?clip|collision|\bfly\b|flying|teleport|floorpushback|autodetach|traversal|physics|transform", re.I)
    strings = []
    for match in re.finditer(rb"[\x20-\x7e]{4,}", blob):
        if terms.search(match.group()):
            strings.append({"fo": hex(match.start()), "rva": hex(rva_at(match.start()) or 0), "value": match.group().decode()})

    ui = {}
    for path in sorted((GAME / "SMT/UI").glob("*.gfx")):
        values = [value for _, block in abc_blocks(path.read_bytes()) for value in ABC(block).strings]
        ui[path.name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "constant_pool_string_count": len(values),
            "traversal_matches": [value for value in values if terms.search(value.encode("utf8"))],
        }

    disassembly = {}
    ranges = {
        "coordinate_registration": (0x35dc0, 0x35f32),
        "coordinate_invoke": (0x43f40, 0x44140),
        "local_entity_resolver": (0x25c80, 0x25d97),
        "local_storage_locator": (0x2d050, 0x2d13e),
        "traversal_settings": (0x65e30, 0x66001),
        "physics_component_reference": (0x57450, 0x574f4),
        "player_menu_teleport": (0x67ec0, 0x67fd8),
    }
    image_base = 0x180000000
    for name, (start, end) in ranges.items():
        result = subprocess.run([
            str(OBJDUMP), "-D", "-Mintel",
            f"--start-address={hex(image_base + start)}",
            f"--stop-address={hex(image_base + end)}", str(CORE)
        ], check=True, capture_output=True, text=True)
        disassembly[name] = result.stdout

    fixed_strings = {hex(rva): data_at(rva, 200).split(b"\0")[0].decode("ascii") for rva in (
        0x77730, 0x7a0b8, 0x7e3f8, 0x7e408, 0x7e438, 0x7e44c, 0x7e8d8, 0x80f18, 0x80f30,
    )}
    report = {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Offline file reads only. No game process, UI, save, config, install or original package mutations; only this audit's own report files are written.",
        "core_sha256": hashlib.sha256(blob).hexdigest(),
        "core_size": len(blob),
        "preferences": json.loads((GAME / "SMT/Preferences.json").read_text(encoding="utf8")),
        "multiplayer": json.loads((GAME / "SMT/Multiplayer.json").read_text(encoding="utf8")),
        "core_string_matches": strings,
        "ui": ui,
        "fixed_strings": fixed_strings,
        "coordinate_vtable": {hex(0x7ea60 + index * 8): hex(value - image_base) for index, value in enumerate(struct.unpack("<7Q", data_at(0x7ea60, 56)))},
        "confirmed_coordinate_chain": [
            "/tpc <x> <y> <z> is registered at SMT RVA 0x35ebe-0x35eeb, name tpc, callback vtable 0x7ea60, invoke slot +0x10 = 0x43f40.",
            "Invoke 0x43f40 passes format %f %f %f to 0x46360 and requires return value 3 at 0x43f97.",
            "Read storage = *(uint64_t*)(smt_base+0xbecf0); local_descriptor = *(uint64_t*)(storage+0x158); entity_wrapper = resolver(local_descriptor+4).",
            "Resolver thunk 0x25c80 tail-jumps to *(uint64_t*)(smt_base+0xbedf0). Entity = *(uint64_t*)entity_wrapper.",
            "0x44025-0x44034 writes the three parsed float values to entity+0x30, +0x34, +0x38.",
            "PLAYERS TELEPORT invoke 0x67ec0 uses the same local resolver and writes the same three fields from target entity coordinates.",
        ],
        "collision_conclusion": "No confirmed noclip/fly/collision toggle in inspected configs, native string references or all five UI ABC constant pools. PhysicsComponent reference 0x57497 is only a candidate component path; its two indirect calls have not been proved collision-enable/disable operations.",
        "limits": [
            "Native string absence and UI constant-pool absence are evidence limits, not proof no hidden feature exists.",
            "No runtime movement, axis orientation, gravity suppression, collision bypass, story trigger, scene streaming or object lifetime behavior was tested.",
            "The existing coordinate writes support a bounded teleport implementation; repeating those writes alone does not prove a continuous collision-disabled noclip implementation.",
            "All RVAs and byte identities apply only to the pinned SMT binary hash; addresses must be computed from the loaded SMT module base.",
        ],
        "disassembly": disassembly,
    }
    out = ROOT / "穿墙现有接口只读审计_20261007.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"report": str(out), "core_sha256": report["core_sha256"], "coordinate_invoke": "0x43f40", "verified_collision_toggle": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
