"""One bounded read-only raw entity-key follow-up of accepted world records.

Uses the established WindowsBackend/Session read/query-only handle and pin gate.
Does not scan memory, invoke game functions, inject, hook, or write game memory.
The qword key accessor layout is static evidence, not cross-peer stability proof.
"""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct

from cinematic_runtime_probe import Session, EXPECTED_SHA256

ROOT = Path(__file__).resolve().parent
TABLE_RVA, COUNT_RVA, KEY_ARRAY_RVA = 0x7A44380, 0x7A4439C, 0x7A4A450
ACCESSOR_RVA = 0x159DA80
ACCESSOR_BYTES = bytes.fromhex("8b 51 0c 48 8b 05 c6 c9 4a 06 48 8b 04 d0 c3")
VTABLES = {"Door": 0x4F67720, "DoorAnimated": 0x4F677C8, "DoorSlide": 0x4F67BB8,
           "Health": 0x3839E08, "BotHealth": 0x3839E98}
MAX_OBJECTS, MAX_READS, MAX_BYTES, MAX_LOG = 16, 512, 4096, 64 * 1024 * 1024


class Reader:
    def __init__(self, backend):
        self.backend, self.reads, self.bytes = backend, 0, 0

    def read(self, address, count):
        if count not in (2, 4, 8, 15) or not 0x10000 <= address or address + count > 0x800000000000:
            raise ValueError("read_address_or_size_refused")
        if self.reads >= MAX_READS or self.bytes + count > MAX_BYTES:
            raise ValueError("read_budget_refused")
        self.reads += 1
        self.bytes += count
        data = self.backend.read(address, count)
        if len(data) != count:
            raise ValueError("read_short")
        return data

    def number(self, address, size):
        return int.from_bytes(self.read(address, size), "little")


def source_candidates(path):
    before = path.stat()
    if before.st_size > MAX_LOG:
        raise ValueError("source_log_exceeds_64MiB")
    with path.open("rb") as stream:
        raw = stream.read(MAX_LOG + 1)
    if len(raw) > MAX_LOG:
        raise ValueError("source_log_exceeds_64MiB_during_read")
    raw = raw[:raw.rfind(b"\n") + 1]  # Only complete JSONL lines from an active file.
    session = None
    latest = collections.OrderedDict()
    lines = 0
    for line in raw.splitlines():
        lines += 1
        if len(line) > 65536:
            raise ValueError("source_json_line_exceeds_64KiB")
        row = json.loads(line)
        if row.get("record_type") == "runtime_session":
            session = row
        if row.get("record_type") != "runtime_snapshot":
            continue
        world = row.get("world_components_raw", {})
        if not world.get("global_table_stable") or world.get("game_operations") is not False:
            continue
        for record in world.get("records", []):
            if record.get("type") not in VTABLES:
                continue
            candidate = dict(record)
            candidate.update(source_sequence=row["sequence"], source_pid=row["pid"],
                             source_table_raw=world["table_raw"], source_table_count_raw=world["table_count_raw"])
            identity = (record["type"], record["entity_index"], record["entity_generation_raw"], record["component_handle_local"])
            latest.pop(identity, None)
            latest[identity] = candidate
            if len(latest) > 256:
                latest.popitem(last=False)
    if not session or session.get("status") != "pinned_game_verified" or session.get("game_sha256") != EXPECTED_SHA256:
        raise ValueError("source_session_pin_not_verified")
    # Retain examples of each observed whitelisted class, then the latest others.
    candidates = []
    seen = set()
    reversed_items = list(reversed(list(latest.items())))
    for type_name in VTABLES:
        for identity, record in reversed_items:
            if record["type"] == type_name:
                candidates.append(record)
                seen.add(identity)
                break
    for identity, record in reversed_items:
        if len(candidates) >= MAX_OBJECTS:
            break
        if identity not in seen:
            candidates.append(record)
            seen.add(identity)
    after = path.stat()
    return session, candidates, {"path": str(path.resolve()), "complete_prefix_bytes": len(raw),
                                 "complete_prefix_sha256": hashlib.sha256(raw).hexdigest(), "complete_lines": lines,
                                 "file_changed_during_source_read": (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns),
                                 "source_recording_may_be_active": True, "candidates_selected": len(candidates)}


def global_header(reader, base):
    return (reader.number(base + TABLE_RVA, 8), reader.number(base + COUNT_RVA, 4),
            reader.number(base + KEY_ARRAY_RVA, 8))


def entity_identity(reader, entry):
    return reader.number(entry + 0xC, 4), reader.number(entry + 0x10, 2)


def component_identity(reader, component):
    return (reader.number(component, 8), reader.number(component + 8, 8),
            reader.number(component + 0x14, 4))


def capture(reader, base, candidates):
    accepted, gaps = [], []
    table, count, array = global_header(reader, base)
    if not table or not array or not 0 < count <= 0x100000:
        raise ValueError("candidate_global_table_or_array_unavailable")
    for candidate in candidates[:MAX_OBJECTS]:
        try:
            index, generation = candidate["entity_index"], candidate["entity_generation_raw"]
            if not isinstance(index, int) or not isinstance(generation, int) or not 0 <= index < count or not 0 < generation <= 0x7FF:
                raise ValueError("source_index_generation_refused")
            entry, component = table + index * 0xC0, int(candidate["component_raw"], 16)
            if int(candidate["source_table_raw"], 16) != table or candidate["source_table_count_raw"] != count:
                raise ValueError("source_global_table_no_longer_matches")
            expected = (base + VTABLES[candidate["type"]], entry, candidate["component_handle_local"])
            if not expected[2] or int(candidate["owner_raw"], 16) != entry or int(candidate["vtable_raw"], 16) != expected[0]:
                raise ValueError("source_component_binding_refused")
            before_entity = entity_identity(reader, entry)
            if before_entity != (index, generation):
                raise ValueError("source_entity_identity_no_longer_matches")
            before_component = component_identity(reader, component)
            if before_component != expected:
                raise ValueError("source_component_identity_no_longer_matches")
            key_address = array + index * 8
            key = reader.read(key_address, 8)
            key_after = reader.read(key_address, 8)
            after_component = component_identity(reader, component)
            after_entity = entity_identity(reader, entry)
            if key != key_after or before_component != after_component or before_entity != after_entity:
                raise ValueError("entity_component_or_raw_key_changed_during_reads")
            accepted.append({"type": candidate["type"], "source_sequence": candidate["source_sequence"],
                             "entity_index_local": index, "entity_generation_local": generation,
                             "component_handle_local": expected[2], "component_raw": hex(component),
                             "candidate_key_array_raw": hex(array), "candidate_key_raw_hex": key.hex(),
                             "candidate_key_u64": hex(int.from_bytes(key, "little")),
                             "candidate_key_high_bit_set": bool(key[7] & 0x80),
                             "raw_identity_and_key_unchanged_during_reads": True,
                             "stable_network_entity_id_verified": False, "peer_id": None})
        except (OSError, ValueError, KeyError, TypeError) as error:
            gaps.append({"type": candidate.get("type"), "source_sequence": candidate.get("source_sequence"),
                         "entity_index_local": candidate.get("entity_index"), "reason": str(error)})
    after = global_header(reader, base)
    stable = (table, count, array) == after
    if not stable:
        accepted.clear()
        gaps.append({"reason": "global_entity_table_count_or_key_array_changed_during_reads"})
    status = ("accepted_raw_candidate_keys_only" if accepted else "stable_headers_no_accepted_candidate_keys") if stable else "global_headers_changed_rejected"
    return {"status": status,
            "global_headers_unchanged": stable, "global_table_raw": hex(table), "global_count_raw": count,
            "candidate_key_array_raw": hex(array), "accepted": accepted, "gaps": gaps}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "world_entity_identity_runtime_20261011.json")
    args = parser.parse_args()
    source_session, candidates, source = source_candidates(args.source)
    result = {"schema": 1, "scope": "one bounded raw entity-key candidate observation",
              "utc": datetime.now(timezone.utc).isoformat(), "pid": args.pid, "source": source,
              "game_operations": False, "game_calls": False, "game_writes": False, "hooks": False,
              "peer_id_verified": False, "cross_process_stability_verified": False,
              "key_array_capacity_unknown": True, "key_origin_unknown": True,
              "coverage_incomplete": True, "max_objects": MAX_OBJECTS,
              "limitations": "Raw qword array candidate only; no stable actor/asset ID meaning, ABA guarantee, cross-peer match or replication claim."}
    with Session(args.pid) as session:
        result["process_gate"] = {key: value for key, value in session.metadata.items() if key != "limits"}
        result["process_gate"]["use"] = "setup_gate_only_no_cinematic_snapshot_called"
        if session.metadata["status"] != "ready":
            result["status"] = "process_gate_refused_no_observation"
        elif source_session.get("pid") != args.pid or int(source_session["module_base"], 16) != session.base or source_session["module_size"] != session.module_size:
            result["status"] = "source_process_module_mismatch_no_observation"
        else:
            reader = Reader(session.backend)
            try:
                if any(rva + size > session.module_size for rva, size in ((TABLE_RVA,8),(COUNT_RVA,4),(KEY_ARRAY_RVA,8),(ACCESSOR_RVA,15))):
                    raise ValueError("pinned_rva_outside_module")
                if reader.read(session.base + ACCESSOR_RVA, 15) != ACCESSOR_BYTES:
                    raise ValueError("key_accessor_live_bytes_do_not_match_pinned_file")
                result.update(capture(reader, session.base, candidates))
            except (OSError, ValueError) as error:
                result.update(status="observation_refused", accepted=[], reason=str(error))
            result["budget"] = {"read_calls": reader.reads, "read_bytes": reader.bytes,
                                "max_read_calls": MAX_READS, "max_read_bytes": MAX_BYTES}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "accepted": len(result.get("accepted", [])),
                      "gaps": len(result.get("gaps", [])), "budget": result.get("budget"),
                      "report": str(args.output.resolve()), "peer_id_verified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
