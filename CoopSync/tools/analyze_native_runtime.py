"""Summarize native read-only diagnostics without assigning game-state semantics.

A malformed/truncated JSONL input is rejected. A well-formed recording without
an ended lifecycle record is explicitly active/incomplete. Handles and field
changes describe one local process; they never establish a network entity ID,
door state, health/death state, cinematic phase, or world synchronization.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import math
import struct
import sys

EXPECTED_GAME_SHA256 = "e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1"
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_LINE_BYTES = 65537  # The writer permits 65536 JSON bytes, then one newline.
MAX_CHANGE_DETAILS = 128
MAX_SEGMENT_DETAILS = 128
TYPES = {
    "Door": (0x4F67720, {0x48: 12, 0xBC: 1, 0xBF: 1, 0xC1: 1, 0xC2: 1, 0xC3: 1, 0xC4: 4}),
    "DoorAnimated": (0x4F677C8, {0x48: 12, 0xBC: 1, 0xBF: 1, 0xC1: 1, 0xC2: 1, 0xC3: 1, 0xC4: 4}),
    "DoorSlide": (0x4F67BB8, {0x48: 12, 0xBC: 1, 0xBF: 1, 0xC1: 1, 0xC2: 1, 0xC3: 1, 0xC4: 4}),
    "Health": (0x3839E08, {0x80: 16, 0xAC: 2}),
    "BotHealth": (0x3839E98, {0x80: 16, 0xAC: 2}),
}
PARTS = ("cinematic_raw", "ui_skip_raw", "task_subset_raw", "world_components_raw")
BOOL_CAPABILITIES = {
    "game_operations", "hooks_installed", "world_replication_enabled", "full_world_coverage",
    "scene_ready_verified", "world_sync_verified", "cinematic_phase_verified", "skip_verified",
    "door_sync_verified", "enemy_sync_verified", "door_open_verified", "collision_ready_verified",
    "enemy_health_or_death_verified", "world_replication_verified", "cross_peer_asset_id_verified",
}
HEX = re.compile(r"0x[0-9a-fA-F]+\Z")
BYTES = re.compile(r"[0-9a-fA-F]*\Z")


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("non-finite JSON constant: " + value)


def load_recording(path):
    path = Path(path).resolve()
    before = path.stat()
    if before.st_size > MAX_SOURCE_BYTES:
        raise ValueError("recording exceeds analyzer byte limit")
    digest = hashlib.sha256()
    rows = []
    received_bytes = 0
    with path.open("rb") as source:
        for number, line in enumerate(iter(lambda: source.readline(MAX_LINE_BYTES + 1), b""), 1):
            received_bytes += len(line)
            if received_bytes > MAX_SOURCE_BYTES:
                raise ValueError("recording grew beyond analyzer byte limit")
            digest.update(line)
            if len(line) > MAX_LINE_BYTES:
                raise ValueError(f"line {number}: exceeds diagnostic record limit")
            if not line.endswith(b"\n"):
                raise ValueError(f"line {number}: unterminated/truncated last record; stop or retry recording")
            try:
                row = json.loads(line.decode("utf-8"), object_pairs_hook=strict_pairs,
                                 parse_constant=reject_constant)
            except (UnicodeError, ValueError) as error:
                raise ValueError(f"line {number}: invalid JSONL: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"line {number}: record must be a JSON object")
            rows.append(row)
    after = path.stat()
    if not rows:
        raise ValueError("empty recording")
    return rows, {"path": str(path), "bytes": received_bytes, "sha256": digest.hexdigest(),
                  "changed_during_read": (before.st_size, before.st_mtime_ns)
                  != (after.st_size, after.st_mtime_ns)}


def integer(value, name, minimum=0, maximum=(1 << 64) - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(name + " is outside the integer bounds")
    return value


def pointer(value, name, minimum=0):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError(name + " must be an explicit hexadecimal string")
    return integer(int(value, 16), name, minimum, 0x00007FFFFFFFFFFF)


def capabilities_disabled(value, path="record"):
    if isinstance(value, dict):
        for name, child in value.items():
            if name in BOOL_CAPABILITIES or name.endswith("_verified"):
                if child is not False:
                    raise ValueError(path + "." + name + " must remain false")
            elif name == "verified_callable_interfaces" and child != []:
                raise ValueError(path + ".verified_callable_interfaces must be empty")
            capabilities_disabled(child, path + "." + name)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            capabilities_disabled(child, path + "[" + str(index) + "]")


def require_caps(row, names):
    for name in names:
        if row.get(name) is not False:
            raise ValueError("missing/contradictory disabled capability: " + name)
    if row.get("verified_callable_interfaces") != []:
        raise ValueError("missing/contradictory callable-interface declaration")


def component_key(record, pid, table, module_base):
    kind = record.get("type")
    if kind not in TYPES:
        raise ValueError("raw component type is outside the diagnostic whitelist")
    index = integer(record.get("entity_index"), "entity_index", 0, 0xFFFFF)
    generation = integer(record.get("entity_generation_raw"), "entity_generation_raw", 1, 0x7FF)
    entity_handle = integer(record.get("entity_handle_local"), "entity_handle_local", 1, 0x7FFFFFFF)
    if entity_handle != (generation << 20) | index:
        raise ValueError("local entity handle does not match index/generation")
    component_handle = integer(record.get("component_handle_local"), "component_handle_local", 1, 0xFFFFFFFF)
    component = pointer(record.get("component_raw"), "component_raw", 0x10000)
    owner = pointer(record.get("owner_raw"), "owner_raw", 0x10000)
    vt = pointer(record.get("vtable_raw"), "vtable_raw", 0x10000)
    if vt != module_base + TYPES[kind][0]:
        raise ValueError("raw component virtual table does not match the pinned type")
    if record.get("network_entity_id", "missing") is not None:
        raise ValueError("local component must not claim a network entity ID")
    fields = record.get("fields")
    if not isinstance(fields, list):
        raise ValueError("component fields must be a list")
    values = {}
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError("raw field must be an object")
        offset = pointer(field.get("offset"), "field offset")
        size = integer(field.get("size"), "field size", 1, 16)
        raw = field.get("raw_hex")
        if offset in values or TYPES[kind][1].get(offset) != size:
            raise ValueError("raw field offset/size is outside its whitelist or duplicated")
        if not isinstance(raw, str) or not BYTES.fullmatch(raw) or len(raw) != size * 2:
            raise ValueError("raw field bytes do not match their declared size")
        values[offset] = raw.lower()
    if values.keys() != TYPES[kind][1].keys():
        raise ValueError("raw component field set is incomplete")
    return (pid, table, entity_handle, component_handle, component, owner, kind), values


def opaque_hex(value, name, maximum=(1 << 64) - 1):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError(name + " must be an explicit hexadecimal string")
    return integer(int(value, 16), name, 0, maximum)


def float_bits(value, name):
    bits = opaque_hex(value, name, 0xFFFFFFFF)
    number = struct.unpack("<f", bits.to_bytes(4, "little"))[0]
    return number if math.isfinite(number) else None


def cinematic_summary(snapshots, pid):
    fields32 = ("raw_58", "raw_5c", "raw_c0", "flags408_raw", "flags438_raw")
    fields8 = ("raw_c7", "raw_c9", "raw_ca")
    previous = {}
    instances = set()
    assets = Counter()
    references = Counter()
    changes = Counter()
    changes_detail = []
    segments = []
    current = None
    segment_count = 0
    numeric = {name: {"finite_observations": 0, "nonfinite_observations": 0,
                      "min_raw_number": None, "max_raw_number": None}
               for name in ("ec_float_bits_raw", "f0_float_bits_raw")}
    for snapshot in snapshots:
        value = snapshot["cinematic_raw"]
        if value["status"] != "component_identity_match_raw_only":
            current = None
            continue
        component = pointer(value.get("component"), "cinematic component", 0x10000)
        owner = pointer(value.get("owner_raw"), "cinematic owner")
        handle = integer(value.get("component_handle_local"), "cinematic local handle", 0, 0xFFFFFFFF)
        asset = opaque_hex(value.get("asset_id_a0_raw_candidate"), "cinematic asset candidate")
        reference = opaque_hex(value.get("reference_a8_raw"), "cinematic reference")
        key = (pid, component, owner, handle, asset)
        fields = {name: integer(value.get(name), name, 0, 0xFFFFFFFF) for name in fields32}
        fields.update({name: integer(value.get(name), name, 0, 255) for name in fields8})
        fields["reference_a8_raw"] = hex(reference)
        for name in numeric:
            bits = opaque_hex(value.get(name), name, 0xFFFFFFFF)
            fields[name] = hex(bits)
            number = float_bits(value[name], name)
            bucket = numeric[name]
            if number is None:
                bucket["nonfinite_observations"] += 1
            else:
                bucket["finite_observations"] += 1
                bucket["min_raw_number"] = number if bucket["min_raw_number"] is None else min(number, bucket["min_raw_number"])
                bucket["max_raw_number"] = number if bucket["max_raw_number"] is None else max(number, bucket["max_raw_number"])
        instances.add(key)
        assets[hex(asset)] += 1
        references[hex(reference)] += 1
        if current is None or current["identity"] != key:
            segment_count += 1
            segment = {"component_raw": hex(component), "owner_raw": hex(owner),
                "component_handle_local": handle, "asset_a0_raw_candidate": hex(asset),
                "first_sequence": snapshot["sequence"], "last_sequence": snapshot["sequence"],
                "first_monotonic_ms": snapshot["monotonic_ms"], "last_monotonic_ms": snapshot["monotonic_ms"],
                "sample_count": 0, "raw_58_counts": {}, "raw_5c_counts": {},
                "raw_field_change_count": 0, "phase_verified": False}
            current = {"identity": key, "segment": segment}
            if len(segments) < MAX_SEGMENT_DETAILS:
                segments.append(segment)
        segment = current["segment"]
        segment["sample_count"] += 1
        segment["last_sequence"] = snapshot["sequence"]
        segment["last_monotonic_ms"] = snapshot["monotonic_ms"]
        for state in ("raw_58", "raw_5c"):
            counts = segment[state + "_counts"]
            name = str(fields[state])
            counts[name] = counts.get(name, 0) + 1
        old = previous.get(key)
        if old is not None:
            for name, raw in fields.items():
                if old["fields"][name] != raw:
                    changes[name] += 1
                    segment["raw_field_change_count"] += 1
                    if len(changes_detail) < MAX_CHANGE_DETAILS:
                        detail = {"component_raw": hex(component), "owner_raw": hex(owner),
                            "component_handle_local": handle, "asset_a0_raw_candidate": hex(asset),
                            "field": name, "previous_sequence": old["sequence"], "sequence": snapshot["sequence"],
                            "before_raw": old["fields"][name], "after_raw": raw, "semantic_verified": False}
                        if name in numeric:
                            detail["before_raw_float"] = float_bits(old["fields"][name], name)
                            detail["after_raw_float"] = float_bits(raw, name)
                        changes_detail.append(detail)
        previous[key] = {"sequence": snapshot["sequence"], "fields": fields}
    return {"selected_component_observations": sum(assets.values()),
        "unique_local_component_asset_instances": len(instances),
        "asset_a0_raw_candidate_counts": dict(assets), "reference_a8_raw_counts": dict(references),
        "selection_identity_segment_count": segment_count, "selection_identity_segments": segments,
        "selection_identity_segment_details_limit": MAX_SEGMENT_DETAILS,
        "selection_identity_segment_details_truncated": segment_count > len(segments),
        "raw_field_change_count": sum(changes.values()), "raw_field_changes_by_field": dict(changes),
        "raw_field_change_details": changes_detail, "raw_field_change_details_limit": MAX_CHANGE_DETAILS,
        "raw_field_change_details_truncated": sum(changes.values()) > len(changes_detail),
        "float_bits_raw_numeric_summary": numeric,
        "comparison_identity": "pid_component_owner_local_handle_asset_a0_raw_candidate",
        "selection_gaps_split_segments": True, "comparisons_may_span_unsampled_time": True,
        "phase_verified": False, "cross_peer_asset_id_verified": False, "skip_verified": False}


def summarize(records, source=None):
    if not records:
        raise ValueError("empty recording")
    start = end = session = None
    snapshots = []
    pid = None
    previous_time = None
    for row in records:
        capabilities_disabled(row)
        kind = row.get("record_type")
        if kind == "runtime_lifecycle":
            require_caps(row, ("game_operations", "scene_ready_verified", "world_sync_verified"))
            event = row.get("event")
            if event == "starting" and start is None and session is None and not snapshots and end is None:
                start = row
                pid = integer(row.get("pid"), "lifecycle pid", 1, 0xFFFFFFFF)
                if integer(row.get("sample_count"), "initial sample_count") != 0:
                    raise ValueError("initial lifecycle count must be zero")
            elif event == "ended" and start is not None and end is None:
                end = row
            else:
                raise ValueError("duplicate/out-of-order lifecycle record")
        elif kind == "runtime_session":
            if start is None or session is not None or snapshots or end is not None:
                raise ValueError("duplicate/out-of-order runtime session")
            require_caps(row, ("game_operations", "hooks_installed", "world_replication_enabled"))
            session = row
        elif kind == "runtime_snapshot":
            if session is None or session.get("status") != "pinned_game_verified" or end is not None:
                raise ValueError("snapshot before a pinned session or after lifecycle ended")
            require_caps(row, ("game_operations", "scene_ready_verified", "cinematic_phase_verified",
                               "skip_verified", "door_sync_verified", "enemy_sync_verified"))
            if integer(row.get("sequence"), "snapshot sequence", 1) != len(snapshots) + 1:
                raise ValueError("snapshot sequence is duplicated or discontinuous")
            snapshots.append(row)
        else:
            raise ValueError("unknown native runtime record type")
        if "pid" in row and integer(row["pid"], "record pid", 1, 0xFFFFFFFF) != pid:
            raise ValueError("recording mixes process identities")
        if "monotonic_ms" in row:
            now = integer(row["monotonic_ms"], "monotonic_ms")
            if previous_time is not None and now < previous_time:
                raise ValueError("recording timestamps move backwards")
            previous_time = now
    if start is None or session is None:
        raise ValueError("lifecycle start/session is missing")
    pinned = session.get("status") == "pinned_game_verified"
    module_base = 0
    if pinned:
        if session.get("game_sha256") != EXPECTED_GAME_SHA256:
            raise ValueError("session SHA256 does not match the pinned executable")
        module_base = pointer(session.get("module_base"), "session module base", 0x10000)
        integer(session.get("module_size"), "session module size", max(v[0] for v in TYPES.values()) + 8, 256 * 1024 * 1024)
        if session.get("mode") != "in_process_read_only_diagnostic" or session.get("pid") != pid:
            raise ValueError("unexpected pinned session mode/identity")
    elif session.get("status") != "disabled":
        raise ValueError("unknown session status")
    if end is not None and integer(end.get("sample_count"), "final sample_count") != len(snapshots):
        raise ValueError("final lifecycle count differs from retained snapshots")

    statuses = {part: Counter() for part in PARTS}
    part_gaps = Counter()
    types = Counter()
    entities = defaultdict(set)
    components = defaultdict(set)
    previous_fields = {}
    changes_by_type = Counter()
    changed_fields = Counter()
    change_details = []
    raw_gap_count = 0
    gap_reasons = Counter()
    budget_peaks = {"read_calls": 0, "read_bytes": 0, "entities_attempted": 0, "component_slots_checked": 0}
    exhausted_count = 0
    tables = set()
    accepted_records = 0
    for snapshot in snapshots:
        for part in PARTS:
            value = snapshot.get(part)
            if not isinstance(value, dict) or not isinstance(value.get("status"), str):
                raise ValueError("snapshot part missing status: " + part)
            statuses[part][value["status"]] += 1
            if value["status"] == "observation_gap" or "changed_during_reads" in value["status"] or "mismatch" in value["status"]:
                part_gaps[part] += 1
        world = snapshot["world_components_raw"]
        if world["status"] == "observation_gap":
            continue
        if world.get("game_operations") is not False or world.get("full_world_coverage") is not False:
            raise ValueError("world raw window must retain its disabled/incomplete declarations")
        table = pointer(world.get("table_raw"), "world table")
        if table:
            tables.add(table)
        integer(world.get("table_count_raw"), "world entity count", 0, 0x100000)
        if integer(world.get("sequence"), "world sequence", 1) != snapshot["sequence"]:
            raise ValueError("world sequence differs from snapshot sequence")
        budget = world.get("budget")
        if not isinstance(budget, dict):
            raise ValueError("world read budget is missing")
        for name, maximum in (("read_calls", 16384), ("read_bytes", 1048576)):
            number = integer(budget.get(name), name, 0, maximum)
            budget_peaks[name] = max(budget_peaks[name], number)
        attempted = integer(world.get("entities_attempted"), "entities_attempted", 0, 128)
        slots = integer(world.get("component_slots_checked"), "component_slots_checked", 0, 128 * 128)
        budget_peaks["entities_attempted"] = max(budget_peaks["entities_attempted"], attempted)
        budget_peaks["component_slots_checked"] = max(budget_peaks["component_slots_checked"], slots)
        if type(budget.get("exhausted")) is not bool:
            raise ValueError("budget exhausted marker must be boolean")
        exhausted_count += int(budget["exhausted"])
        raw_gap_count += integer(world.get("gap_count"), "gap_count", 0, 16384)
        gaps = world.get("gaps")
        if not isinstance(gaps, list) or len(gaps) > 16:
            raise ValueError("world gap detail list exceeds bounds")
        for gap in gaps:
            if not isinstance(gap, dict) or not isinstance(gap.get("reason"), str):
                raise ValueError("invalid world gap reason")
            gap_reasons[gap["reason"]] += 1
        raw_records = world.get("records")
        if not isinstance(raw_records, list) or len(raw_records) > 32:
            raise ValueError("world record list exceeds bounds")
        if integer(world.get("records_accepted"), "records_accepted", 0, 32) != len(raw_records):
            raise ValueError("accepted world record count is inconsistent")
        tick_identities = set()
        for record in raw_records:
            if not isinstance(record, dict):
                raise ValueError("raw component must be an object")
            key, fields = component_key(record, pid, table, module_base)
            if key in tick_identities:
                raise ValueError("snapshot duplicates a local component identity")
            tick_identities.add(key)
            kind = record["type"]
            types[kind] += 1
            accepted_records += 1
            entities[kind].add((table, key[2]))
            components[kind].add(key)
            old = previous_fields.get(key)
            if old is not None:
                for offset, value in fields.items():
                    if old["fields"][offset] != value:
                        changes_by_type[kind] += 1
                        changed_fields[kind + ":" + hex(offset)] += 1
                        if len(change_details) < MAX_CHANGE_DETAILS:
                            change_details.append({"type": kind, "entity_handle_local": key[2],
                                "component_handle_local": key[3], "component_raw": hex(key[4]),
                                "offset": hex(offset), "previous_sequence": old["sequence"],
                                "sequence": snapshot["sequence"], "before_raw_hex": old["fields"][offset],
                                "after_raw_hex": value, "semantic_verified": False})
            previous_fields[key] = {"sequence": snapshot["sequence"], "fields": fields}
    source = source or {}
    complete = end is not None and not source.get("changed_during_read", False)
    error_code = integer(end.get("error_code"), "final error_code", 0, 0xFFFFFFFF) if end else None
    if not complete:
        quality = "active_or_incomplete_recording"
    elif not pinned:
        quality = "rejected_session_recording"
    elif error_code:
        quality = "complete_recording_with_runtime_error"
    elif raw_gap_count or sum(part_gaps.values()):
        quality = "complete_raw_recording_with_observation_gaps"
    else:
        quality = "complete_raw_recording"
    start_time = start.get("monotonic_ms")
    end_time = end.get("monotonic_ms") if end else None
    return {"schema": 1, "record_type": "native_runtime_analysis", "quality": quality,
        "source": source, "active_or_incomplete": not complete,
        "lifecycle": {"start_seen": True, "end_seen": end is not None,
            "error_code": error_code, "start_monotonic_ms": start_time,
            "end_monotonic_ms": end_time,
            "duration_ms": end_time - start_time if end_time is not None and start_time is not None else None},
        "session": {"pid": pid, "status_claim": session.get("status"),
            "pin_claim_matches_expected": pinned, "game_sha256_claim": session.get("game_sha256"),
            "module_base_local": session.get("module_base"), "module_size_claim": session.get("module_size")},
        "snapshots": len(snapshots), "part_status_counts": {name: dict(value) for name, value in statuses.items()},
        "cinematic_raw": cinematic_summary(snapshots, pid),
        "world_raw": {"record_observations": accepted_records, "type_observation_counts": dict(types),
            "unique_local_entity_handles_by_type": {kind: len(value) for kind, value in entities.items()},
            "unique_local_component_instances_by_type": {kind: len(value) for kind, value in components.items()},
            "distinct_table_addresses_local": [hex(table) for table in sorted(tables)],
            "identity_scope": "one_process_table_entity_generation_component_identity_only",
            "coverage": "incomplete_rolling_diagnostic_window", "full_world_coverage": False},
        "raw_field_changes": {"count": sum(changes_by_type.values()), "by_type": dict(changes_by_type),
            "by_field": dict(changed_fields), "details": change_details,
            "details_limit": MAX_CHANGE_DETAILS, "details_truncated": sum(changes_by_type.values()) > len(change_details),
            "comparisons_may_span_unsampled_time": True, "semantic_verified": False},
        "observation_gaps": {"part_counts": dict(part_gaps), "world_gap_count": raw_gap_count,
            "world_reported_detail_reason_counts": dict(gap_reasons), "detail_counts_may_be_truncated": True},
        "world_read_budget": {"peaks": budget_peaks, "exhausted_snapshot_count": exhausted_count},
        "game_operations": False, "scene_ready_verified": False, "cinematic_phase_verified": False,
        "skip_verified": False, "door_sync_verified": False, "enemy_sync_verified": False,
        "world_replication_verified": False, "verified_callable_interfaces": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        records, source = load_recording(args.recording)
        report = summarize(records, source)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            output = args.output.resolve()
            if output == args.recording.resolve():
                raise ValueError("analysis output must not replace its raw source recording")
            output.write_text(rendered, encoding="utf-8")
        print(json.dumps({"status": "analyzed", "quality": report["quality"],
            "snapshots": report["snapshots"], "world_record_observations": report["world_raw"]["record_observations"],
            "output": str(args.output) if args.output else None}, ensure_ascii=False))
        if not args.output:
            print(rendered, end="")
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "rejected", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
