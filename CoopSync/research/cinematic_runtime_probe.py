"""Bounded, read-only Cinematic2 identity and raw-field sampler.

Never launches the game. One Session verifies the pinned executable digest,
process path and main module, and opens one read/query-only process handle.
Snapshots read only two evidenced static vtables, System's +0x11D0 slot, and
six raw fields from a vtable-verified component. No scanning, writes, injection,
thread creation, hooks or game calls. Default output is compact JSONL.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as wt
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import struct
import time

from runtime_config import game_executable

GAME = game_executable()
EXPECTED_SHA256 = "e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1"
TARGETS = (
    ("Cinematic2Manager", 0x6044830, 0x3CF47B0, "constructor 0x183DC0 writes vtable at 0x183E1C"),
    ("Cinematic2System", 0x6044A60, 0x3CF4C68, "static initialized vtable; registry 0x2BC35A/361 stores object address"),
)
SLOT_RVA = 0x6045C30
COMPONENT_VTABLE_RVA = 0x3CF4100
FIELDS = (
    (0x58, 4, "dispatcher 0x166A320 branches on/writes this value"),
    (0x5C, 4, "SetToEnd branch 0x166A497 writes this value"),
    (0xC0, 4, "SetToEnd/SetToEndAndHide branches 0x166A475/48B write this value"),
    (0xC7, 1, "System update 0x167325F tests this byte before selecting this component"),
    (0xC9, 1, "Hide/Show branches 0x166A4F4/5A8 write this byte"),
    (0xCA, 1, "Cinematic2Action handler 0x167008C writes this byte"),
)
CONTINUABLE = frozenset(("object_identities_match_no_flagged_component",
                        "component_identity_match_raw_state_only", "component_changed_during_reads"))
SUCCESS = CONTINUABLE | {"no_game_process_found", "game_process_exited"}


def path_equal(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class WindowsBackend:
    """The only native operations are process enumeration, query and reads."""

    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.process = None
        pointer = ctypes.c_size_t

        class ProcessEntry(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                        ("th32DefaultHeapID", pointer), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD),
                        ("szExeFile", wt.WCHAR * 260)]

        class ModuleEntry(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
                        ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
                        ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)), ("modBaseSize", wt.DWORD),
                        ("hModule", wt.HMODULE), ("szModule", wt.WCHAR * 256), ("szExePath", wt.WCHAR * 260)]

        self.ProcessEntry, self.ModuleEntry = ProcessEntry, ModuleEntry
        declarations = {
            "CreateToolhelp32Snapshot": ([wt.DWORD, wt.DWORD], wt.HANDLE),
            "CloseHandle": ([wt.HANDLE], wt.BOOL),
            "OpenProcess": ([wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
            "QueryFullProcessImageNameW": ([wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)], wt.BOOL),
            "GetExitCodeProcess": ([wt.HANDLE, ctypes.POINTER(wt.DWORD)], wt.BOOL),
            "ReadProcessMemory": ([wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)], wt.BOOL),
        }
        for name in ("Process32FirstW", "Process32NextW"):
            declarations[name] = ([wt.HANDLE, ctypes.POINTER(ProcessEntry)], wt.BOOL)
        for name in ("Module32FirstW", "Module32NextW"):
            declarations[name] = ([wt.HANDLE, ctypes.POINTER(ModuleEntry)], wt.BOOL)
        for name, (args, result) in declarations.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result

    def _snapshot(self, flags, pid):
        handle = self.kernel.CreateToolhelp32Snapshot(flags, pid)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def candidates(self, pid):
        result = []
        handle = self._snapshot(0x2, 0)
        try:
            entry = self.ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            more = self.kernel.Process32FirstW(handle, ctypes.byref(entry))
            while more:
                if entry.szExeFile.casefold() == GAME.name.casefold() and (pid is None or entry.th32ProcessID == pid):
                    result.append(entry.th32ProcessID)
                more = self.kernel.Process32NextW(handle, ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(handle)
        return result

    def open(self, pid):
        self.process = self.kernel.OpenProcess(0x1010, False, pid)
        if not self.process:
            raise ctypes.WinError(ctypes.get_last_error())

    def path(self):
        size = wt.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not self.kernel.QueryFullProcessImageNameW(self.process, 0, buffer, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.value

    def module(self, pid):
        handle = self._snapshot(0x8 | 0x10, pid)
        try:
            entry = self.ModuleEntry()
            entry.dwSize = ctypes.sizeof(entry)
            more = self.kernel.Module32FirstW(handle, ctypes.byref(entry))
            while more:
                if path_equal(entry.szExePath, GAME):
                    return ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value, entry.modBaseSize
                more = self.kernel.Module32NextW(handle, ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(handle)
        return None, None

    def alive(self):
        code = wt.DWORD()
        if not self.kernel.GetExitCodeProcess(self.process, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259  # STILL_ACTIVE; requires query access only.

    def read(self, address, count):
        buffer = ctypes.create_string_buffer(count)
        received = ctypes.c_size_t()
        if not self.kernel.ReadProcessMemory(self.process, ctypes.c_void_p(address), buffer, count, ctypes.byref(received)) or received.value != count:
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw

    def close(self):
        if self.process:
            self.kernel.CloseHandle(self.process)
            self.process = None


@dataclasses.dataclass
class ReadBudget:
    reads: int = 0
    bytes_read: int = 0

    def check(self, address, count):
        if count not in (1, 4, 8) or not 0x10000 <= address or address + count > 0x0000800000000000:
            raise ValueError("Read address or size outside explicit probe bounds")
        if self.reads >= 15 or self.bytes_read + count > 87:
            raise ValueError("Snapshot read budget exceeded")
        self.reads += 1
        self.bytes_read += count


class Session:
    """Owns one setup/handle; snapshot() never rehashes or reopens the process.

    _backend and _digest are dependency seams for the pure mock check only.
    Use as a context manager, or call close() even after a setup failure.
    """

    def __init__(self, pid=None, *, _backend=None, _digest=None):
        self.backend = _backend
        self.base = self.module_size = None
        self.previous_component = None
        self.previous_sample_valid = False
        self.closed = False
        self.metadata = {
            "schema": 2, "record_type": "session", "scope": "read-only evidenced object identities and raw component fields",
            "game_path": str(GAME), "verified_callable_interfaces": [],
            "limits": {"process_rights": "PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION", "max_reads_per_snapshot": 15,
                       "max_bytes_per_snapshot": 87, "largest_read": 8, "max_samples": 3001, "minimum_interval_ms": 50, "max_duration_ms": 300000},
            "note": "Vtable identity and raw fields do not verify active-cinematic semantics, lifetime or callable ABI.",
        }
        try:
            if _backend is None and os.name != "nt":
                self.metadata["status"] = "unsupported_platform"
                return
            digest = (_digest or file_sha256)(GAME)
            self.metadata["game_sha256"] = digest
            if digest != EXPECTED_SHA256:
                self.metadata["status"] = "build_mismatch_no_process_access"
                return
            if self.backend is None:
                self.backend = WindowsBackend()
            candidates = self.backend.candidates(pid)
            self.metadata["candidate_pids"] = candidates
            if len(candidates) != 1:
                self.metadata["status"] = "no_game_process_found" if not candidates else "multiple_game_processes_refused"
                return
            process_id = candidates[0]
            self.metadata["pid"] = process_id
            self.backend.open(process_id)
            if not path_equal(self.backend.path(), GAME):
                self.metadata["status"] = "process_path_mismatch_no_memory_reads"
                return
            self.metadata["process_path_verified"] = True
            self.base, self.module_size = self.backend.module(process_id)
            if self.base is None:
                self.metadata["status"] = "game_module_not_found_no_memory_reads"
                return
            if any(rva + 8 > self.module_size for _, obj, vt, _ in TARGETS for rva in (obj, vt)) or SLOT_RVA + 8 > self.module_size:
                raise ValueError("Pinned target falls outside verified main module")
            self.metadata["module_base"] = hex(self.base)
            self.metadata["module_size"] = self.module_size
            self.metadata["status"] = "ready"
        except (OSError, ValueError) as error:
            self.metadata.update(status="read_only_probe_setup_error", error=str(error))
            if self.backend is not None and self.metadata.get("pid") is not None:
                try:
                    if not self.backend.alive():
                        self.metadata["status"] = "game_process_exited"
                except OSError:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def close(self):
        if not self.closed:
            if self.backend is not None:
                self.backend.close()
            self.closed = True

    def snapshot(self, sample=0):
        result = {"schema": 2, "record_type": "snapshot", "sample": sample,
                  "monotonic_ms": int(time.monotonic() * 1000), "status": self.metadata["status"],
                  "objects": [], "component_slot": None, "runtime_state_fields": [], "verified_callable_interfaces": []}
        if self.closed:
            result["status"] = "session_closed"
            return result
        if self.metadata["status"] != "ready":
            return result
        budget = ReadBudget()
        stage = "static_object"

        def read(address, count):
            budget.check(address, count)
            raw = self.backend.read(address, count)
            if len(raw) != count:
                raise OSError("Incomplete read")
            return raw

        def qword(address):
            return struct.unpack("<Q", read(address, 8))[0]

        def verify_static(after=False):
            for index, (classname, obj, vt, evidence) in enumerate(TARGETS):
                actual = qword(self.base + obj)
                matches = actual == self.base + vt
                if after:
                    row = result["objects"][index]
                    row["vtable_after"] = hex(actual)
                    row["stable_during_reads"] = row["actual_vtable"] == hex(actual)
                else:
                    result["objects"].append({"class": classname, "storage": "direct static object", "object_rva": hex(obj),
                                              "object_address": hex(self.base + obj), "actual_vtable": hex(actual),
                                              "expected_vtable_rva": hex(vt), "identity_match": matches, "static_evidence": evidence})
                if not matches:
                    return False
            return True

        try:
            if not self.backend.alive():
                result["status"] = "game_process_exited"
                return result
            if not verify_static():
                result["status"] = "identity_mismatch_probe_stopped"
                return result
            stage = "component_slot"
            slot_address = self.base + SLOT_RVA
            component = qword(slot_address)
            slot = {"rva": hex(SLOT_RVA), "owner_offset": "0x11d0", "value": hex(component), "identity_match": False,
                    "stable_during_reads": False, "pointer_changed_since_previous_sample":
                    (component != self.previous_component) if self.previous_sample_valid else None,
                    "evidence": "System update 0x1673190 clears slot and stores type-checked component at 0x1673268 if byte +0xC7 != 0"}
            result["component_slot"] = slot
            if not component:
                after = qword(slot_address)
                slot.update(value_after=hex(after), stable_during_reads=after == 0)
                if not verify_static(after=True):
                    slot["stable_during_reads"] = False
                    result["status"] = "identity_mismatch_probe_stopped"
                else:
                    result["status"] = "object_identities_match_no_flagged_component" if after == 0 else "component_changed_during_reads"
            else:
                stage = "component_identity"
                component_vtable = qword(component)
                slot["actual_vtable"] = hex(component_vtable)
                slot["identity_match"] = component_vtable == self.base + COMPONENT_VTABLE_RVA
                if not slot["identity_match"]:
                    result["status"] = "component_identity_mismatch_probe_stopped"
                    return result
                before_fields = qword(slot_address)
                slot["value_before_fields"] = hex(before_fields)
                if before_fields != component:
                    result["status"] = "component_changed_during_reads"
                    return result
                stage = "component_fields"
                fields = []
                for offset, count, evidence in FIELDS:
                    raw = read(component + offset, count)
                    fields.append({"offset": hex(offset), "size": count, "raw_hex": raw.hex(),
                                   "unsigned_value": int.from_bytes(raw, "little"), "static_evidence": evidence,
                                   "semantic_status": "raw field only, full state meaning unverified"})
                component_vtable_after = qword(component)
                after = qword(slot_address)
                slot.update(vtable_after=hex(component_vtable_after), value_after=hex(after))
                stable = after == component and component_vtable_after == component_vtable
                slot["stable_during_reads"] = stable
                if not verify_static(after=True):
                    slot["stable_during_reads"] = False
                    result["status"] = "identity_mismatch_probe_stopped"
                elif not stable:
                    result["status"] = "component_changed_during_reads"
                else:
                    result["runtime_state_fields"] = fields
                    result["status"] = "component_identity_match_raw_state_only"
            if not self.backend.alive():
                result["status"] = "game_process_exited"
                result["runtime_state_fields"] = []
                slot["stable_during_reads"] = False
            if result["status"] in CONTINUABLE:
                self.previous_component = component
                self.previous_sample_valid = bool(slot["stable_during_reads"])
        except (OSError, ValueError) as error:
            result["runtime_state_fields"] = []
            slot = result["component_slot"]
            if slot is not None:
                slot["stable_during_reads"] = False
            try:
                alive = self.backend.alive()
            except OSError:
                alive = True
            result["status"] = ("game_process_exited" if not alive else
                                "component_invalidated_during_reads" if stage.startswith("component") else "read_only_probe_read_error")
            result["error"] = str(error)
        finally:
            result["read_count"] = budget.reads
            result["read_bytes"] = budget.bytes_read
            if result["status"] not in CONTINUABLE or not (result["component_slot"] or {}).get("stable_during_reads", False):
                self.previous_sample_valid = False
        return result


def probe(pid=None):
    """Compatibility API: one dict, setup metadata plus one snapshot; no JSONL."""
    with Session(pid) as session:
        report = {**session.metadata, **session.snapshot()}
        report.pop("record_type", None)
        return report


class MockBackend:
    """Pure in-memory fake: no game file, native API or process access."""

    def __init__(self, components=(0,), *, fail_at=None, exit_at=None, mismatch=False, path_mismatch=False,
                 component_vtables=(COMPONENT_VTABLE_RVA,), short_read_at=None):
        self.base, self.component = 0x140000000, 0x200000000
        self.components = iter(components)
        self.last_slot = 0
        self.component_vtables = iter(component_vtables)
        self.last_component_vtable = COMPONENT_VTABLE_RVA
        self.short_read_at = short_read_at
        self.fail_at, self.exit_at = fail_at, exit_at
        self.mismatch, self.path_mismatch = mismatch, path_mismatch
        self.calls = {}
        self.read_count = 0
        self.closed = False

    def count(self, method):
        self.calls[method] = self.calls.get(method, 0) + 1

    def candidates(self, pid):
        self.count("candidates")
        return [123]

    def open(self, pid):
        self.count("open")

    def path(self):
        self.count("path")
        return str(GAME) + ".other" if self.path_mismatch else str(GAME)

    def module(self, pid):
        self.count("module")
        return self.base, 0x8600000

    def alive(self):
        return self.exit_at is None or self.read_count < self.exit_at

    def read(self, address, count):
        self.read_count += 1
        if self.read_count == self.fail_at:
            raise OSError("mock object invalidated")
        if self.read_count == self.short_read_at:
            return b""
        for _, obj, vt, _ in TARGETS:
            if address == self.base + obj:
                return struct.pack("<Q", self.base + vt + int(self.mismatch))
        if address == self.base + SLOT_RVA:
            self.last_slot = next(self.components, self.last_slot)
            return struct.pack("<Q", self.last_slot)
        if address == self.component:
            self.last_component_vtable = next(self.component_vtables, self.last_component_vtable)
            return struct.pack("<Q", self.base + self.last_component_vtable)
        for offset, size, _ in FIELDS:
            if address == self.component + offset and count == size:
                return (1).to_bytes(size, "little")
        raise OSError("mock unknown address")

    def close(self):
        self.closed = True
        self.count("close")


def self_check():
    checks = []

    def run(label, backend, statuses, digest=EXPECTED_SHA256):
        hashes = []
        with Session(_backend=backend, _digest=lambda unused: hashes.append(1) or digest) as session:
            reports = [session.snapshot(i) for i in range(len(statuses))]
            assert [r["status"] for r in reports] == statuses, label
            assert all(isinstance(r["verified_callable_interfaces"], list) for r in reports)
            assert all(r.get("read_count", 0) <= 15 and r.get("read_bytes", 0) <= 87 for r in reports)
        assert len(hashes) == 1 and backend.closed
        assert all(backend.calls.get(method, 0) <= 1 for method in ("candidates", "open", "path", "module", "close"))
        checks.append(label)
        return reports

    run("one setup across repeated null samples", MockBackend((0, 0, 0, 0)), ["object_identities_match_no_flagged_component"] * 2)
    component = 0x200000000
    reports = run("stable raw fields and between-sample pointer recheck", MockBackend((0, 0, component, component, component)),
                  ["object_identities_match_no_flagged_component", "component_identity_match_raw_state_only"])
    assert reports[1]["component_slot"]["pointer_changed_since_previous_sample"] is True
    assert len(reports[1]["runtime_state_fields"]) == 6
    for slots, label in (((component, 0), "slot changes before fields"), ((component, component, 0), "slot changes after fields")):
        report = run(label, MockBackend(slots), ["component_changed_during_reads"])[0]
        assert report["runtime_state_fields"] == [] and report["component_slot"]["stable_during_reads"] is False
    run("static identity mismatch stops", MockBackend(mismatch=True), ["identity_mismatch_probe_stopped"])
    run("component read invalidated", MockBackend((component,), fail_at=4), ["component_invalidated_during_reads"])
    run("invalid component pointer is bounded", MockBackend((8,)), ["component_invalidated_during_reads"])
    report = run("component identity mismatch stops", MockBackend((component,), component_vtables=(0,)),
                 ["component_identity_mismatch_probe_stopped"])[0]
    assert report["runtime_state_fields"] == []
    report = run("component identity changes after fields", MockBackend((component,), component_vtables=(COMPONENT_VTABLE_RVA, 0)),
                 ["component_changed_during_reads"])[0]
    assert report["runtime_state_fields"] == []
    run("incomplete component read rejected", MockBackend((component,), short_read_at=6), ["component_invalidated_during_reads"])
    run("process exits during reads", MockBackend((component,), fail_at=6, exit_at=6), ["game_process_exited"])
    run("process already exited", MockBackend(exit_at=0), ["game_process_exited"])
    backend = MockBackend(path_mismatch=True)
    run("path mismatch has zero memory reads", backend, ["process_path_mismatch_no_memory_reads"])
    assert backend.read_count == 0
    backend = MockBackend()
    run("build mismatch has zero process setup", backend, ["build_mismatch_no_process_access"], digest="invalid")
    assert not any(backend.calls.get(method, 0) for method in ("candidates", "open", "path", "module"))
    for address, count in ((0, 8), (0x20000, 9), (0x7FFFFFFFFFFC, 8)):
        try:
            ReadBudget().check(address, count)
        except ValueError:
            pass
        else:
            raise AssertionError("Read bounds accepted an invalid request")
    checks.append("explicit address/size bounds")
    return {"schema": 2, "record_type": "self_check", "status": "passed", "checks": checks,
            "game_file_reads": 0, "game_process_accesses": 0, "verified_callable_interfaces": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, help="Select one existing Spider-Man process")
    parser.add_argument("--samples", type=int, default=1, help="1..3001 samples within 300 seconds")
    parser.add_argument("--interval-ms", type=int, default=100, help="50..300000 milliseconds between samples")
    parser.add_argument("--output", type=Path, help="Also write JSONL to a new file; existing files are refused")
    parser.add_argument("--self-check", "--self-test", dest="self_check", action="store_true", help="Pure mock checks; no game file/process access")
    args = parser.parse_args(argv)
    if args.pid is not None and not 1 <= args.pid <= 0xFFFFFFFF:
        parser.error("PID must be a positive DWORD")
    if not 1 <= args.samples <= 3001 or not 50 <= args.interval_ms <= 300000 or (args.samples - 1) * args.interval_ms > 300000:
        parser.error("Sample count/interval must stay within bounds and 300 seconds total")
    output = None

    def emit(record):
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        print(line, flush=True)
        if output is not None:
            output.write(line + "\n")
            output.flush()

    try:
        if args.output is not None:
            output = args.output.open("x", encoding="utf-8", newline="\n")
        if args.self_check:
            emit(self_check())
            return 0
        with Session(args.pid) as session:
            emit(session.metadata)
            sample_start = time.monotonic()
            count = 0
            reason = "samples_complete"
            for index in range(args.samples):
                if index:
                    delay = args.interval_ms / 1000 - (time.monotonic() - last_sample_start)
                    if delay > 0:
                        time.sleep(delay)
                    if time.monotonic() - sample_start > 300:
                        reason = "duration_limit"
                        break
                last_sample_start = time.monotonic()
                report = session.snapshot(index)
                emit(report)
                count += 1
                if report["status"] not in CONTINUABLE:
                    reason = "terminal_status"
                    break
            emit({"schema": 2, "record_type": "end", "status": report["status"], "samples_emitted": count,
                  "elapsed_ms": int((time.monotonic() - sample_start) * 1000), "reason": reason, "verified_callable_interfaces": []})
            return 0 if report["status"] in SUCCESS else 2
    except KeyboardInterrupt:
        emit({"schema": 2, "record_type": "end", "status": "interrupted", "verified_callable_interfaces": []})
        return 130
    except (OSError, ValueError, AssertionError) as error:
        print(json.dumps({"schema": 2, "record_type": "end", "status": "read_only_probe_error", "error": str(error),
                          "verified_callable_interfaces": []}, ensure_ascii=False, separators=(",", ":")), flush=True)
        return 2
    finally:
        if output is not None:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
