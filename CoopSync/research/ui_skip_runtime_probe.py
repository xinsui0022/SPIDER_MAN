"""Minimal read-only sampler for the statically proved GUI::OverlayUI object.

Reuses cinematic_runtime_probe.Session only for pinned SHA-256, process-path,
main-module and read/query handle setup. Does not call its cinematic snapshot.
No game calls, injection, writes, hooks, scanning or context dereferencing.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
from pathlib import Path
import struct
import time

from cinematic_runtime_probe import Session, MockBackend, GAME, EXPECTED_SHA256


OBJECT_RVA = 0x7B84580
VTABLES = ((0, 0x4F44980), (0x158, 0x4F449E0))
FIELD_OFFSETS = {"active_raw": (0x210, 1), "elapsed_raw": (0x214, 4),
                 "callback_context_pair": (0x220, 16)}
CONTINUABLE = frozenset(("overlay_identity_match_slots_stable_raw_only", "callback_slots_changed_during_reads"))
SUCCESS = CONTINUABLE | {"no_game_process_found", "game_process_exited"}


@dataclasses.dataclass
class ReadBudget:
    reads: int = 0
    bytes_read: int = 0

    def check(self, offset, count):
        allowed = {(0, 8), (0x158, 8), (0x210, 1), (0x214, 4), (0x220, 16)}
        if (offset, count) not in allowed or self.reads >= 8 or self.bytes_read + count > 69:
            raise ValueError("Read outside explicit OverlayUI fields or snapshot budget")
        self.reads += 1
        self.bytes_read += count


def snapshot(session, sample=0):
    result = {"schema": 1, "record_type": "overlay_ui_snapshot", "sample": sample,
              "monotonic_ms": int(time.monotonic() * 1000), "status": session.metadata["status"],
              "object_rva": hex(OBJECT_RVA), "vtables": [], "raw_fields": [],
              "verified_callable_interfaces": []}
    if session.closed:
        result["status"] = "session_closed"
        return result
    if session.metadata["status"] != "ready":
        return result
    budget = ReadBudget()

    def read(offset, count):
        budget.check(offset, count)
        if OBJECT_RVA + offset + count > session.module_size:
            raise ValueError("Pinned OverlayUI field is outside verified main module")
        raw = session.backend.read(session.base + OBJECT_RVA + offset, count)
        if len(raw) != count:
            raise OSError("Incomplete read")
        return raw

    def vtables(after=False):
        matches = True
        for index, (offset, expected_rva) in enumerate(VTABLES):
            actual = struct.unpack("<Q", read(offset, 8))[0]
            matches = matches and actual == session.base + expected_rva
            if after:
                row = result["vtables"][index]
                row.update(actual_after=hex(actual), stable_during_reads=row["actual"] == hex(actual))
            else:
                result["vtables"].append({"offset": hex(offset), "expected_rva": hex(expected_rva),
                                           "actual": hex(actual), "identity_match": actual == session.base + expected_rva})
        return matches

    try:
        if not session.backend.alive():
            result["status"] = "game_process_exited"
            return result
        if OBJECT_RVA + 0x230 > session.module_size or any(vt + 8 > session.module_size for _, vt in VTABLES):
            raise ValueError("OverlayUI identity target falls outside verified main module")
        if not vtables():
            result["status"] = "overlay_identity_mismatch_probe_stopped"
            return result
        pair = read(0x220, 16)
        active = read(0x210, 1)
        elapsed = read(0x214, 4)
        pair_after = read(0x220, 16)
        identity_after = vtables(after=True)
        if not session.backend.alive():
            result["status"] = "game_process_exited"
            return result
        if not identity_after:
            result["status"] = "overlay_identity_changed_during_reads_probe_stopped"
            return result
        result["slots_stable_during_reads"] = pair == pair_after
        if pair != pair_after:
            result["status"] = "callback_slots_changed_during_reads"
            return result
        callback, context = struct.unpack("<QQ", pair)
        elapsed_float = struct.unpack("<f", elapsed)[0]
        result["raw_fields"] = [
            {"offset": "0x210", "size": 1, "raw_hex": active.hex(), "unsigned_value": active[0],
             "semantic_status": "raw byte; setter/hold-handler relation is static only"},
            {"offset": "0x214", "size": 4, "raw_hex": elapsed.hex(),
             "float_value": elapsed_float if math.isfinite(elapsed_float) else None,
             "semantic_status": "raw float; complete cinematic-state meaning unverified"},
            {"offset": "0x220", "size": 8, "raw_hex": pair[:8].hex(), "pointer_value": hex(callback),
             "main_module_target_rva": hex(callback - session.base) if session.base <= callback < session.base + session.module_size else None,
             "semantic_status": "stable pointer slot only; not verified executable or callable"},
            {"offset": "0x228", "size": 8, "raw_hex": pair[8:].hex(), "pointer_value": hex(context),
             "semantic_status": "stable context slot only; never dereferenced"},
        ]
        result["status"] = "overlay_identity_match_slots_stable_raw_only"
    except (OSError, ValueError) as error:
        result["raw_fields"] = []
        result["slots_stable_during_reads"] = False
        try:
            alive = session.backend.alive()
        except OSError:
            alive = True
        result.update(status="read_only_overlay_probe_read_error" if alive else "game_process_exited", error=str(error))
    finally:
        result["read_count"] = budget.reads
        result["read_bytes"] = budget.bytes_read
    return result


class OverlayMock(MockBackend):
    def __init__(self, *, wrong_vtable=False, vtable_changed_after=False, slots_changed=False, fail_at=None, exit_at=None, path_mismatch=False):
        super().__init__(fail_at=fail_at, exit_at=exit_at, path_mismatch=path_mismatch)
        self.wrong_vtable, self.slots_changed = wrong_vtable, slots_changed
        self.vtable_changed_after = vtable_changed_after
        self.pair_reads = 0

    def read(self, address, count):
        self.read_count += 1
        if self.read_count == self.fail_at:
            raise OSError("mock OverlayUI invalidated")
        offset = address - self.base - OBJECT_RVA
        for location, target in VTABLES:
            if offset == location and count == 8:
                mismatch = self.wrong_vtable or (self.vtable_changed_after and self.read_count >= 7)
                return struct.pack("<Q", self.base + target + int(mismatch))
        if offset == 0x220 and count == 16:
            self.pair_reads += 1
            return struct.pack("<QQ", self.base + 0x123456 + int(self.slots_changed and self.pair_reads % 2 == 0), 0x200000000)
        if offset == 0x210 and count == 1:
            return b"\x01"
        if offset == 0x214 and count == 4:
            return struct.pack("<f", 0.5)
        raise OSError("mock unapproved address")


def self_check():
    checks = []

    def run(label, backend, expected, digest=EXPECTED_SHA256):
        with Session(_backend=backend, _digest=lambda unused: digest) as session:
            report = snapshot(session)
            assert report["status"] == expected, (label, report)
            assert report.get("read_count", 0) <= 8 and report.get("read_bytes", 0) <= 69
            assert report["verified_callable_interfaces"] == []
        assert backend.closed
        checks.append(label)
        return report

    report = run("stable dual-vtable and pointer slots", OverlayMock(), "overlay_identity_match_slots_stable_raw_only")
    assert report["read_count"] == 8 and report["read_bytes"] == 69
    assert report["raw_fields"][2]["main_module_target_rva"] == "0x123456"
    assert report["raw_fields"][3]["pointer_value"] == "0x200000000"
    report = run("identity mismatch stops before fields", OverlayMock(wrong_vtable=True), "overlay_identity_mismatch_probe_stopped")
    assert report["read_count"] == 2 and not report["raw_fields"]
    report = run("identity change after reads withholds fields", OverlayMock(vtable_changed_after=True), "overlay_identity_changed_during_reads_probe_stopped")
    assert not report["raw_fields"]
    report = run("slot race withholds raw fields", OverlayMock(slots_changed=True), "callback_slots_changed_during_reads")
    assert not report["raw_fields"]
    report = run("read failure withholds raw fields", OverlayMock(fail_at=6), "read_only_overlay_probe_read_error")
    assert not report["raw_fields"]
    run("process exit during reads", OverlayMock(exit_at=8), "game_process_exited")
    backend = OverlayMock(path_mismatch=True)
    run("path mismatch makes zero memory reads", backend, "process_path_mismatch_no_memory_reads")
    assert backend.read_count == 0
    backend = OverlayMock()
    run("hash mismatch makes zero process setup", backend, "build_mismatch_no_process_access", "wrong")
    assert backend.read_count == 0 and not backend.calls.get("open", 0)
    for offset, count in ((0x228, 16), (0x230, 8), (0x220, 8), (0x214, 8)):
        try:
            ReadBudget().check(offset, count)
        except ValueError:
            pass
        else:
            raise AssertionError("Unapproved field read accepted")
    checks.append("only exact evidenced offsets and sizes allowed")
    return {"schema": 1, "record_type": "self_check", "status": "passed", "checks": checks,
            "game_file_reads": 0, "game_process_accesses": 0, "verified_callable_interfaces": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval-ms", type=int, default=100)
    parser.add_argument("--output", type=Path, help="Write JSONL to a new file; existing output refused")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)
    if args.pid is not None and not 1 <= args.pid <= 0xFFFFFFFF:
        parser.error("PID must be a positive DWORD")
    if not 1 <= args.samples <= 3001 or not 50 <= args.interval_ms <= 300000 or (args.samples - 1) * args.interval_ms > 300000:
        parser.error("Sampling must fit 1..3001 samples, interval >=50 ms, duration <=300 seconds")
    output = None

    def emit(record):
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        print(line, flush=True)
        if output:
            output.write(line + "\n")
            output.flush()

    try:
        if args.output:
            output = args.output.open("x", encoding="utf-8", newline="\n")
        if args.self_check:
            emit(self_check())
            return 0
        with Session(args.pid) as session:
            metadata = {**session.metadata, "schema": 1, "record_type": "overlay_ui_session",
                        "scope": "shared pinned-build/path/handle gate; independent fixed OverlayUI field probe",
                        "limits": {"process_rights": "PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION",
                                   "max_reads_per_snapshot": 8, "max_bytes_per_snapshot": 69, "largest_read": 16,
                                   "max_samples": 3001, "minimum_interval_ms": 50, "max_duration_ms": 300000},
                        "note": "Dual RTTI-vtable identity and stable slots only; no context dereference or callable claim"}
            emit(metadata)
            start = time.monotonic()
            count = 0
            reason = "samples_complete"
            for index in range(args.samples):
                if index:
                    remaining = args.interval_ms / 1000 - (time.monotonic() - last_sample_start)
                    if remaining > 0:
                        time.sleep(remaining)
                    if time.monotonic() - start > 300:
                        reason = "duration_limit"
                        break
                last_sample_start = time.monotonic()
                report = snapshot(session, index)
                emit(report)
                count += 1
                if report["status"] not in CONTINUABLE:
                    reason = "terminal_status"
                    break
            emit({"schema": 1, "record_type": "end", "status": report["status"], "samples_emitted": count,
                  "elapsed_ms": int((time.monotonic()-start)*1000), "reason": reason, "verified_callable_interfaces": []})
            return 0 if report["status"] in SUCCESS else 2
    except KeyboardInterrupt:
        emit({"schema": 1, "record_type": "end", "status": "interrupted", "verified_callable_interfaces": []})
        return 130
    except (OSError, ValueError, AssertionError) as error:
        emit({"schema": 1, "record_type": "end", "status": "read_only_overlay_probe_error", "error": str(error), "verified_callable_interfaces": []})
        return 2
    finally:
        if output:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
