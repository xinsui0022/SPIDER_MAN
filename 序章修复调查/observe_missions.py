"""Read-only task-state recorder for the audited Spider-Man/SMT build.

This is a diagnostic tool, not a fix. It never writes process memory, injects
code, invokes game functions, attaches a debugger, or changes saves/configs.
Run with the game closed, then reproduce the join event during --seconds.
"""

import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
from datetime import datetime, timezone

GAME_HASH = "e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1"
MOD_HASH = "b7ab575100f2346af25180d74bf9641e24ce09bf549ce47446be09c3462606c7"
MANAGER_RVA = 0x6EFC1A0
MANAGER_POINTER_RVA = 0x7C3EF70
MODE_RVA = 0x6C65478  # Enum meaning is not established; record the raw value.
DIRECTOR_ENABLED_RVA = 0x6F64AF4
MOD_MANAGER_POINTER_RVA = 0xC0800

K = C.WinDLL("kernel32", use_last_error=True)


class ProcessEntry(C.Structure):
    _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("pid", W.DWORD),
                ("heap", C.c_size_t), ("module", W.DWORD), ("threads", W.DWORD),
                ("parent", W.DWORD), ("priority", W.LONG), ("flags", W.DWORD),
                ("name", W.WCHAR * 260)]


class ModuleEntry(C.Structure):
    _fields_ = [("size", W.DWORD), ("module", W.DWORD), ("pid", W.DWORD),
                ("global_usage", W.DWORD), ("process_usage", W.DWORD),
                ("base", C.c_void_p), ("length", W.DWORD), ("handle", W.HMODULE),
                ("name", W.WCHAR * 256), ("path", W.WCHAR * 260)]


K.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
K.CreateToolhelp32Snapshot.restype = W.HANDLE
K.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]
K.Process32NextW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]
K.Module32FirstW.argtypes = [W.HANDLE, C.POINTER(ModuleEntry)]
K.Module32NextW.argtypes = [W.HANDLE, C.POINTER(ModuleEntry)]
K.CloseHandle.argtypes = [W.HANDLE]
K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
K.OpenProcess.restype = W.HANDLE
K.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                C.POINTER(C.c_size_t)]
K.ReadProcessMemory.restype = W.BOOL
INVALID_HANDLE = C.c_void_p(-1).value


def inventory(pid=None):
    handle = K.CreateToolhelp32Snapshot(2 if pid is None else 0x18, pid or 0)
    if handle == INVALID_HANDLE:
        raise C.WinError(C.get_last_error())
    try:
        entry = ProcessEntry() if pid is None else ModuleEntry()
        entry.size = C.sizeof(entry)
        first = K.Process32FirstW if pid is None else K.Module32FirstW
        next_item = K.Process32NextW if pid is None else K.Module32NextW
        result = []
        ok = first(handle, C.byref(entry))
        while ok:
            if pid is None:
                result.append((entry.pid, entry.name))
            else:
                result.append((entry.name, entry.path, entry.base, entry.length))
            ok = next_item(handle, C.byref(entry))
        return result
    finally:
        K.CloseHandle(handle)


class Reader:
    def __init__(self, pid):
        # PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, no write rights.
        self.handle = K.OpenProcess(0x1010, False, pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())

    def close(self):
        if self.handle:
            K.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, size):
        if not 0x10000 <= address < 0x7FFFFFFFFFFF or not 0 < size <= 0x100000:
            raise ValueError("Invalid or excessive read")
        output = C.create_string_buffer(size)
        received = C.c_size_t()
        if not K.ReadProcessMemory(self.handle, address, output, size,
                                   C.byref(received)) or received.value != size:
            raise OSError(C.get_last_error(), "ReadProcessMemory failed")
        return output.raw

    def u64(self, address):
        return struct.unpack("<Q", self.read(address, 8))[0]

    def i32(self, address):
        return struct.unpack("<i", self.read(address, 4))[0]

    def u32(self, address):
        return struct.unpack("<I", self.read(address, 4))[0]

    def symbol(self, address):
        """Bounded engine string reference: pointer, length, hash."""
        pointer = self.u64(address)
        length = self.u32(address + 8)
        if length == 0:
            return None
        if not pointer or length > 256:
            raise ValueError("Symbol outside audited bounded layout")
        return self.read(pointer, length).decode("utf-8", errors="replace")


def sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def capture(reader, game_base, mod_base, previously_seen):
    manager = game_base + MANAGER_RVA
    manager_pointer = reader.u64(game_base + MANAGER_POINTER_RVA)
    mod_manager = reader.u64(mod_base + MOD_MANAGER_POINTER_RVA) if mod_base else None
    data = {"mode_raw": reader.u32(game_base + MODE_RVA),
            "director_enabled_raw": reader.read(game_base + DIRECTOR_ENABLED_RVA, 1)[0],
            "manager_pointer": hex(manager_pointer),
            "mod_manager_pointer": hex(mod_manager) if mod_manager is not None else None}
    if mod_manager not in (None, 0, manager):
        raise ValueError("Runtime SMT manager address does not match audited layout")
    storage = reader.u64(manager + 0x688B0)
    entries = reader.u64(manager + 0x28)
    entry_count = reader.i32(manager + 0x30)
    data.update(storage=hex(storage), entry_array=hex(entries), entry_count=entry_count)
    if not storage or not entries:
        data["status"] = "task_manager_not_initialized"
        previously_seen.clear()
        return data
    list_count = reader.i32(storage + 0x30320)
    states = reader.u64(storage)
    data.update(candidate_count=list_count, state_array=hex(states))
    if not 0 <= entry_count <= 200000 or not 0 <= list_count <= 64:
        raise ValueError("Task counts outside audited bounded layout")
    if not states:
        data["status"] = "state_array_not_initialized"
        return data
    generation = (storage, entries, states)
    if previously_seen.get("generation") != generation:
        previously_seen.clear()
        previously_seen["generation"] = generation
        previously_seen["indices"] = set()
    indices = (struct.unpack("<" + "i" * list_count,
                            reader.read(storage + 0x120, list_count * 4))
               if list_count else ())
    valid_indices = {j for j in indices if 0 <= j < entry_count}
    previously_seen["indices"].update(valid_indices)
    if len(previously_seen["indices"]) > 128:
        previously_seen["indices"] = valid_indices
    records = []
    for j in sorted(previously_seen["indices"]):
        if j >= entry_count:
            continue
        mission = reader.u64(entries + j * 0x30)
        record = {"index": j, "listed": j in valid_indices,
                  "state_raw": reader.i32(states + j * 4), "object": hex(mission)}
        if mission:
            record["mission_id_raw"] = "0x%08X" % reader.u32(mission + 0x14)
            try:
                record["mission_name_raw"] = reader.symbol(mission + 8)
                if j in valid_indices:
                    position = indices.index(j)
                    count = reader.u32(mission + 0x80)
                    rows = reader.u64(mission + 0x78)
                    if count > 64 or (count and not rows):
                        raise ValueError("Objective definitions outside audited layout")
                    objectives = []
                    for k in range(count):
                        definition = reader.u64(rows + k * 0x18 + 8)
                        objectives.append({
                            "slot": k,
                            "state_raw": reader.i32(storage + 0x220 + position * 0x100 + k * 4),
                            "name_raw": reader.symbol(definition + 8),
                            "description_raw": reader.symbol(definition + 0x18),
                        })
                    record["objectives"] = objectives
            except (OSError, ValueError) as error:
                # Optional detail must not hide a valid mission-state snapshot.
                record["objective_read_error"] = str(error)
        records.append(record)
    data["missions"] = records
    # state_raw==2 is an active candidate, not proof of a functioning objective.
    # The original query also applies an unobserved virtual-function filter.
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--check", action="store_true", help="One snapshot; no log file")
    parser.add_argument("--self-check", action="store_true", help="Verify read-only OS API on this process")
    args = parser.parse_args()
    if C.sizeof(C.c_void_p) != 8:
        raise SystemExit("Requires 64-bit Python")
    if args.self_check:
        import os
        sentinel = C.create_string_buffer(b"SMT_READ_ONLY_OBSERVER")
        reader = Reader(os.getpid())
        try:
            assert reader.read(C.addressof(sentinel), len(sentinel)) == sentinel.raw
            assert any(pid == os.getpid() for pid, _ in inventory())
            assert any(name.lower().startswith("python") for name, *_ in inventory(os.getpid()))
        finally:
            reader.close()
        print("PASS: enumeration, module base addresses and read-only memory access")
        return
    if not 1 <= args.seconds <= 1800:
        raise SystemExit("Duration must be between 1 and 1800 seconds")
    log = None
    if not args.check:
        folder = Path(__file__).resolve().parent / "记录"
        folder.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        log = (folder / (stamp + ".jsonl")).open("x", encoding="utf-8", buffering=1)
        print("Diagnostic only; no game/save changes. Log:", log.name, flush=True)

    def emit(kind, value):
        event = {"utc": datetime.now(timezone.utc).isoformat(), "event": kind, "data": value}
        line = json.dumps(event, ensure_ascii=False, sort_keys=True)
        if log:
            log.write(line + "\n")
        else:
            print(line, flush=True)

    started = time.monotonic()
    reader = None
    pid = None
    game_base = mod_base = None
    seen = {}
    last_value = None
    last_process_check = last_modules_check = last_heartbeat = 0
    try:
        while args.check or time.monotonic() - started < args.seconds:
            now = time.monotonic()
            try:
                if args.check or now - last_process_check >= 1:
                    matches = [p for p, name in inventory() if name.lower() == "spider-man.exe"]
                    last_process_check = now
                    if len(matches) > 1:
                        raise ValueError("Multiple game instances; observation is ambiguous")
                    new_pid = matches[0] if matches else None
                    if new_pid != pid:
                        if reader:
                            reader.close()
                        reader = None
                        pid = new_pid
                        game_base = mod_base = None
                        seen.clear()
                        last_value = None
                        last_modules_check = 0
                        if pid:
                            modules = inventory(pid)
                            game = next(m for m in modules if m[0].lower() == "spider-man.exe")
                            if sha256(game[1]) != GAME_HASH:
                                raise ValueError("Game hash mismatch; addresses must be re-audited")
                            reader = Reader(pid)
                            game_base = game[2]
                            emit("attached_read_only", {"pid": pid, "game_base": hex(game_base),
                                                        "game_sha256": GAME_HASH})
                if not reader:
                    value = {"status": "waiting_for_game"}
                else:
                    if args.check or now - last_modules_check >= 2:
                        modules = inventory(pid)
                        mod = next((m for m in modules if m[0].lower() == "smt.dll"), None)
                        if mod and mod_base != mod[2]:
                            if sha256(mod[1]) != MOD_HASH:
                                raise ValueError("SMT hash mismatch; addresses must be re-audited")
                            mod_base = mod[2]
                            emit("smt_detected", {"smt_base": hex(mod_base), "smt_sha256": MOD_HASH})
                        if not mod:
                            mod_base = None
                        last_modules_check = now
                    value = capture(reader, game_base, mod_base, seen)
            except (OSError, ValueError, StopIteration) as error:
                value = {"status": "read_failed", "reason": str(error)}
                if "mismatch" in str(error) or "re-audited" in str(error):
                    emit("refused_unsupported_build", value)
                    break
            if value != last_value:
                emit("state_change", value)
                last_value = value
                last_heartbeat = now
            elif now - last_heartbeat >= 30:
                emit("heartbeat", {"status": "unchanged", "pid": pid})
                last_heartbeat = now
            if args.check:
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        emit("stopped", {"reason": "keyboard_interrupt"})
    finally:
        if reader:
            reader.close()
        if log:
            log.close()


if __name__ == "__main__":
    main()
