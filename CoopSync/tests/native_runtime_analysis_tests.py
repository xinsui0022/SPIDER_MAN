"""Offline synthetic-record checks; these never observe or control the game."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import analyze_native_runtime as analyzer


def fixture():
    lifecycle = {"record_type": "runtime_lifecycle", "pid": 123, "monotonic_ms": 100,
        "event": "starting", "sample_count": 0, "error_code": 0,
        "game_operations": False, "scene_ready_verified": False,
        "world_sync_verified": False, "verified_callable_interfaces": []}
    session = {"record_type": "runtime_session", "pid": 123, "status": "pinned_game_verified",
        "game_sha256": analyzer.EXPECTED_GAME_SHA256, "module_base": "0x140000000",
        "module_size": 140496896, "mode": "in_process_read_only_diagnostic",
        "game_operations": False, "hooks_installed": False, "world_replication_enabled": False,
        "verified_callable_interfaces": []}
    health = {"type": "Health", "entity_index": 1, "entity_generation_raw": 2,
        "entity_handle_local": (2 << 20) | 1, "component_handle_local": 10,
        "component_raw": "0x30000", "owner_raw": "0x200c0", "vtable_raw": "0x143839e08",
        "network_entity_id": None, "fields": [{"offset": "0x80", "size": 16,
        "raw_hex": "00" * 16}, {"offset": "0xac", "size": 2, "raw_hex": "0000"}]}
    world = {"status": "stable_raw_window_only", "sequence": 1, "game_operations": False,
        "full_world_coverage": False, "table_raw": "0x20000", "table_count_raw": 2,
        "entities_attempted": 2, "component_slots_checked": 4, "records_accepted": 1,
        "budget": {"read_calls": 40, "read_bytes": 160, "exhausted": False},
        "gap_count": 0, "gaps": [], "records": [health]}
    snapshot = {"record_type": "runtime_snapshot", "pid": 123, "sequence": 1, "monotonic_ms": 200,
        "cinematic_raw": {"status": "no_selected_component_raw_only", "component": "0x0"},
        "ui_skip_raw": {"status": "dual_identity_match_slots_stable_raw_only", "callback_raw": "0x0"},
        "task_subset_raw": {"status": "manager_not_initialized"}, "world_components_raw": world,
        "game_operations": False, "scene_ready_verified": False, "cinematic_phase_verified": False,
        "skip_verified": False, "door_sync_verified": False, "enemy_sync_verified": False,
        "verified_callable_interfaces": []}
    second = deepcopy(snapshot)
    second.update(sequence=2, monotonic_ms=300)
    second["world_components_raw"]["sequence"] = 2
    second["world_components_raw"]["records"][0]["fields"][0]["raw_hex"] = "01" + "00" * 15
    ended = deepcopy(lifecycle)
    ended.update(event="ended", monotonic_ms=400, sample_count=2)
    return [lifecycle, session, snapshot, second, ended]


def cine():
    return {"status": "component_identity_match_raw_only", "component": "0x50000",
        "owner_raw": "0x60000", "component_handle_local": 15,
        "asset_id_a0_raw_candidate": "0x9a05b474457c6ab3", "reference_a8_raw": "0x9a05b474457c6ab3",
        "raw_58": 10, "raw_5c": 10, "raw_c0": 0, "raw_c7": 1, "raw_c9": 0, "raw_ca": 0,
        "flags408_raw": 0, "flags438_raw": 0, "ec_float_bits_raw": "0x3f800000", "f0_float_bits_raw": "0x0",
        "cross_peer_asset_id_verified": False}


class AnalysisTests(unittest.TestCase):
    def test_complete_raw_statistics_have_no_game_semantics(self):
        result = analyzer.summarize(fixture())
        self.assertEqual(result["quality"], "complete_raw_recording")
        self.assertEqual(result["snapshots"], 2)
        self.assertEqual(result["world_raw"]["type_observation_counts"], {"Health": 2})
        self.assertEqual(result["world_raw"]["unique_local_component_instances_by_type"], {"Health": 1})
        self.assertEqual(result["raw_field_changes"]["count"], 1)
        self.assertFalse(result["enemy_sync_verified"])
        self.assertFalse(result["raw_field_changes"]["semantic_verified"])

    def test_active_recording_is_not_completion(self):
        result = analyzer.summarize(fixture()[:-1])
        self.assertTrue(result["active_or_incomplete"])
        self.assertEqual(result["quality"], "active_or_incomplete_recording")

    def test_changed_source_cannot_be_complete(self):
        self.assertTrue(analyzer.summarize(fixture(), {"changed_during_read": True})["active_or_incomplete"])

    def test_runtime_error_is_preserved(self):
        rows = fixture()
        rows[-1]["error_code"] = 5
        result = analyzer.summarize(rows)
        self.assertEqual(result["quality"], "complete_recording_with_runtime_error")
        self.assertEqual(result["lifecycle"]["error_code"], 5)

    def test_rejected_host_does_not_claim_pin(self):
        rows = fixture()
        session = {"record_type": "runtime_session", "status": "disabled",
            "game_operations": False, "hooks_installed": False, "world_replication_enabled": False,
            "verified_callable_interfaces": []}
        rows[-1]["sample_count"] = 0
        rows[-1]["error_code"] = 193
        result = analyzer.summarize([rows[0], session, rows[-1]])
        self.assertFalse(result["session"]["pin_claim_matches_expected"])
        self.assertEqual(result["quality"], "rejected_session_recording")

    def test_component_replacement_prevents_comparison(self):
        rows = fixture()
        rows[3]["world_components_raw"]["records"][0]["component_handle_local"] = 11
        result = analyzer.summarize(rows)
        self.assertEqual(result["raw_field_changes"]["count"], 0)
        self.assertEqual(result["world_raw"]["unique_local_component_instances_by_type"], {"Health": 2})

    def test_raw_gaps_are_counted(self):
        rows = fixture()
        world = rows[3]["world_components_raw"]
        world.update(status="partial_raw_window_with_gaps", gap_count=1,
                     gaps=[{"reason": "read_failed_or_short"}])
        result = analyzer.summarize(rows)
        self.assertEqual(result["observation_gaps"]["world_gap_count"], 1)
        self.assertEqual(result["quality"], "complete_raw_recording_with_observation_gaps")

    def test_unavailable_part_does_not_create_world_coverage(self):
        rows = fixture()
        rows[3]["world_components_raw"] = {"status": "observation_gap", "reason": "read failed"}
        result = analyzer.summarize(rows)
        self.assertEqual(result["world_raw"]["record_observations"], 1)
        self.assertFalse(result["world_raw"]["full_world_coverage"])

    def test_cinematic_raw_float_changes_and_opaque_assets(self):
        rows = fixture()
        rows[2]["cinematic_raw"] = cine()
        rows[3]["cinematic_raw"] = cine()
        rows[3]["cinematic_raw"]["ec_float_bits_raw"] = "0x40000000"
        result = analyzer.summarize(rows)["cinematic_raw"]
        self.assertEqual(result["asset_a0_raw_candidate_counts"], {"0x9a05b474457c6ab3": 2})
        self.assertEqual(result["raw_field_change_count"], 1)
        self.assertEqual(result["float_bits_raw_numeric_summary"]["ec_float_bits_raw"]["max_raw_number"], 2)
        self.assertEqual(result["selection_identity_segment_count"], 1)
        self.assertFalse(result["phase_verified"])

    def test_cinematic_new_asset_or_handle_starts_new_identity(self):
        for field, value in (("asset_id_a0_raw_candidate", "0x1"), ("component_handle_local", 16)):
            with self.subTest(field=field):
                rows = fixture()
                rows[2]["cinematic_raw"] = cine()
                rows[3]["cinematic_raw"] = cine()
                rows[3]["cinematic_raw"][field] = value
                rows[3]["cinematic_raw"]["ec_float_bits_raw"] = "0x40000000"
                result = analyzer.summarize(rows)["cinematic_raw"]
                self.assertEqual(result["raw_field_change_count"], 0)
                self.assertEqual(result["selection_identity_segment_count"], 2)

    def test_selection_gap_splits_segments_but_is_not_a_phase(self):
        rows = fixture()
        rows[2]["cinematic_raw"] = cine()
        rows[3]["cinematic_raw"] = {"status": "selection_changed_during_reads"}
        third = deepcopy(rows[2])
        third.update(sequence=3, monotonic_ms=350)
        third["world_components_raw"]["sequence"] = 3
        third["cinematic_raw"]["ec_float_bits_raw"] = "0x40000000"
        rows.insert(-1, third)
        rows[-1]["sample_count"] = 3
        result = analyzer.summarize(rows)
        self.assertEqual(result["cinematic_raw"]["selection_identity_segment_count"], 2)
        self.assertEqual(result["observation_gaps"]["part_counts"], {"cinematic_raw": 1})
        self.assertFalse(result["cinematic_phase_verified"])

    def test_duplicate_component_in_one_tick_is_rejected(self):
        rows = fixture()
        world = rows[2]["world_components_raw"]
        world["records"].append(deepcopy(world["records"][0]))
        world["records_accepted"] = 2
        with self.assertRaises(ValueError):
            analyzer.summarize(rows)

    def test_nonfinite_float_bits_retained_without_json_nan(self):
        rows = fixture()
        rows[2]["cinematic_raw"] = cine()
        rows[2]["cinematic_raw"]["ec_float_bits_raw"] = "0x7fc00000"
        result = analyzer.summarize(rows)
        self.assertEqual(result["cinematic_raw"]["float_bits_raw_numeric_summary"]["ec_float_bits_raw"]["nonfinite_observations"], 1)
        json.dumps(result, allow_nan=False)

    def test_identity_order_capability_and_bounds_rejections(self):
        def mutate_record(rows, index, key, value):
            rows[index][key] = value
        cases = [
            ("bad pin", lambda r: mutate_record(r, 1, "game_sha256", "bad")),
            ("mixed pid", lambda r: mutate_record(r, 3, "pid", 124)),
            ("sequence gap", lambda r: mutate_record(r, 3, "sequence", 4)),
            ("backward time", lambda r: mutate_record(r, 3, "monotonic_ms", 50)),
            ("end count", lambda r: mutate_record(r, 4, "sample_count", 9)),
            ("capability true", lambda r: mutate_record(r, 3, "door_sync_verified", True)),
            ("missing capability", lambda r: r[3].pop("enemy_sync_verified")),
            ("callable enabled", lambda r: mutate_record(r, 3, "verified_callable_interfaces", ["skip"])),
            ("unknown record", lambda r: mutate_record(r, 3, "record_type", "other")),
            ("before session", lambda r: r.__setitem__(slice(1, 3), [r[2], r[1]])),
            ("after end", lambda r: r.append(deepcopy(r[2]))),
            ("duplicate session", lambda r: r.insert(2, deepcopy(r[1]))),
            ("world sequence", lambda r: r[3]["world_components_raw"].update(sequence=99)),
            ("record count", lambda r: r[3]["world_components_raw"].update(records_accepted=2)),
            ("budget", lambda r: r[3]["world_components_raw"]["budget"].update(read_calls=16385)),
            ("world capability", lambda r: r[3]["world_components_raw"].update(full_world_coverage=True)),
            ("unknown type", lambda r: r[3]["world_components_raw"]["records"][0].update(type="Enemy")),
            ("wrong vtable", lambda r: r[3]["world_components_raw"]["records"][0].update(vtable_raw="0x10000")),
            ("wrong handle", lambda r: r[3]["world_components_raw"]["records"][0].update(entity_handle_local=12)),
            ("network ID", lambda r: r[3]["world_components_raw"]["records"][0].update(network_entity_id="guest")),
            ("wrong field length", lambda r: r[3]["world_components_raw"]["records"][0]["fields"][0].update(raw_hex="00")),
            ("unlisted field", lambda r: r[3]["world_components_raw"]["records"][0]["fields"][0].update(offset="0x81")),
            ("missing field", lambda r: r[3]["world_components_raw"]["records"][0]["fields"].pop()),
        ]
        for name, mutation in cases:
            with self.subTest(case=name):
                rows = fixture()
                mutation(rows)
                with self.assertRaises(ValueError):
                    analyzer.summarize(rows)

    def test_strict_jsonl_rejects_incomplete_duplicates_nonfinite_and_oversize(self):
        sources = [b'{"record_type":', b'{}', b'{"a":1,"a":2}\n', b'{"x":NaN}\n',
                   b'\n', b'[]\n', b'{"x":"' + b'x' * 65537 + b'"}\n']
        with tempfile.TemporaryDirectory(prefix="CoopSyncNativeAnalysisTests_") as temp:
            path = Path(temp) / "recording.jsonl"
            for source in sources:
                with self.subTest(source=source[:25]):
                    path.write_bytes(source)
                    with self.assertRaises(ValueError):
                        analyzer.load_recording(path)

    def test_complete_jsonl_hash_and_metadata(self):
        with tempfile.TemporaryDirectory(prefix="CoopSyncNativeAnalysisTests_") as temp:
            path = Path(temp) / "recording.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in fixture()), encoding="utf-8")
            rows, source = analyzer.load_recording(path)
            self.assertEqual(len(rows), 5)
            self.assertFalse(source["changed_during_read"])
            self.assertEqual(len(source["sha256"]), 64)
            self.assertEqual(analyzer.summarize(rows, source)["quality"], "complete_raw_recording")


if __name__ == "__main__":
    unittest.main()
