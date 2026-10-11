"""Load/control only our diagnostic DLL in the pinned, user-authorized game.

Uses Windows LoadLibraryW plus our explicitly exported Start/Status/Stop entry
points. Does not execute engine addresses, patch hooks, restore SMT, or write
saves. Remote writes cover only newly allocated argument buffers. Stop ends the
observer; the initial LoadLibrary reference remains until the game exits.
"""
from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from cinematic_runtime_probe import WindowsBackend, GAME, EXPECTED_SHA256, path_equal, file_sha256


class Config(C.Structure):
    _fields_ = [("size", W.DWORD), ("version", W.DWORD), ("output_directory", C.c_void_p),
                ("sample_interval_ms", W.DWORD), ("reserved", W.DWORD * 4)]


class Status(C.Structure):
    _fields_ = [("size", W.DWORD), ("version", W.DWORD), ("phase", W.DWORD),
                ("last_error", W.DWORD), ("sample_count", C.c_uint64),
                ("game_operations", W.DWORD), ("world_sync", W.DWORD),
                ("callables", W.DWORD), ("reserved", W.DWORD)]


class MemoryInfo(C.Structure):
    _fields_ = [("base", C.c_void_p), ("allocation_base", C.c_void_p),
                ("allocation_protect", W.DWORD), ("partition_id", W.WORD),
                ("region_size", C.c_size_t), ("state", W.DWORD),
                ("protect", W.DWORD), ("kind", W.DWORD)]


def pe_exports(path):
    image = pefile.PE(str(path), fast_load=True)
    if image.FILE_HEADER.Machine != 0x8664 or image.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("Diagnostic DLL must be AMD64 PE32+")
    image.parse_data_directories(directories=[0])
    exports = {}
    for row in image.DIRECTORY_ENTRY_EXPORT.symbols:
        if row.name:
            name = row.name.decode("ascii")
            if row.forwarder:
                raise ValueError("Diagnostic DLL forwarded exports are unsupported")
            exports[name] = row.address
    for name in ("CoopSyncRuntimeStart", "CoopSyncRuntimeGetStatus", "CoopSyncRuntimeStop"):
        if name not in exports or not 0 < exports[name] < image.OPTIONAL_HEADER.SizeOfImage:
            raise ValueError("Required diagnostic export missing or outside image: " + name)
        section = image.get_section_by_rva(exports[name])
        if section is None or not section.Characteristics & 0x20000000:
            raise ValueError("Diagnostic export is not in an executable PE section")
    return exports


def verify_loaded_dll(control, module, path):
    """Reject stale loaded builds before using any disk-derived export RVA."""
    image = pefile.PE(str(path))
    if image.OPTIONAL_HEADER.SizeOfImage != module["size"] or not 0 < module["size"] <= 8 * 1024 * 1024:
        raise ValueError("Loaded diagnostic DLL image size differs; restart the game before loading a new build")
    mapped = image.get_memory_mapped_image(max_virtual_address=8 * 1024 * 1024, ImageBase=module["base"])
    spans = [(image.DOS_HEADER.e_lfanew, 24)]
    directory = image.OPTIONAL_HEADER.DATA_DIRECTORY[0]
    if not 0 < directory.Size <= 65536:
        raise ValueError("Diagnostic export directory outside bounds")
    spans.append((directory.VirtualAddress, directory.Size))
    spans.extend((section.VirtualAddress, section.Misc_VirtualSize)
                 for section in image.sections if section.Characteristics & 0x20000000)
    if not any(section.Characteristics & 0x20000000 for section in image.sections):
        raise ValueError("Diagnostic DLL has no executable section")
    for rva, length in spans:
        if not 0 < length <= 4 * 1024 * 1024 or rva + length > len(mapped):
            raise ValueError("Diagnostic identity comparison outside image bounds")
        for offset in range(0, length, 4096):
            count = min(4096, length - offset)
            if control.read_module(module, rva + offset, count) != mapped[rva + offset:rva + offset + count]:
                raise ValueError("Loaded diagnostic DLL differs from this build; restart the game before using its exports")


class NativeControl:
    def __init__(self, pid, timeout_ms):
        self.pid, self.timeout_ms = pid, timeout_ms
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.handle = None
        self.allocations = set()
        self.pending_allocations = set()
        self.module_backend = WindowsBackend()
        declarations = {
            "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            "CloseHandle": ([W.HANDLE], W.BOOL),
            "QueryFullProcessImageNameW": ([W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL),
            "VirtualAllocEx": ([W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD], C.c_void_p),
            "VirtualFreeEx": ([W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD], W.BOOL),
            "WriteProcessMemory": ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
            "ReadProcessMemory": ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
            "CreateRemoteThread": ([W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)], W.HANDLE),
            "WaitForSingleObject": ([W.HANDLE, W.DWORD], W.DWORD),
            "GetExitCodeThread": ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
            "GetModuleHandleW": ([W.LPCWSTR], W.HMODULE),
            "GetProcAddress": ([W.HMODULE, C.c_char_p], C.c_void_p),
            "VirtualQuery": ([C.c_void_p, C.POINTER(MemoryInfo), C.c_size_t], C.c_size_t),
            "GetModuleFileNameW": ([W.HMODULE, W.LPWSTR, W.DWORD], W.DWORD),
            "IsWow64Process2": ([W.HANDLE, C.POINTER(W.WORD), C.POINTER(W.WORD)], W.BOOL),
        }
        for name, (args, result) in declarations.items():
            function = getattr(self.k, name)
            function.argtypes, function.restype = args, result

    def open(self):
        # Win32 rights required by CreateRemoteThread, plus bounded RPM/query.
        self.handle = self.k.OpenProcess(0x43A, False, self.pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        size = W.DWORD(32768)
        path = C.create_unicode_buffer(size.value)
        if not self.k.QueryFullProcessImageNameW(self.handle, 0, path, C.byref(size)):
            raise C.WinError(C.get_last_error())
        if not path_equal(path.value, GAME):
            raise ValueError("Refusing process outside the pinned Spider-Man executable path")
        guest, native = W.WORD(), W.WORD()
        if not self.k.IsWow64Process2(self.handle, C.byref(guest), C.byref(native)):
            raise C.WinError(C.get_last_error())
        if guest.value != 0 or native.value != 0x8664 or C.sizeof(C.c_void_p) != 8:
            raise ValueError("Both controller and target must be native AMD64")

    def modules(self):
        backend = self.module_backend
        snapshot = backend._snapshot(0x8 | 0x10, self.pid)
        rows = []
        try:
            entry = backend.ModuleEntry()
            entry.dwSize = C.sizeof(entry)
            more = backend.kernel.Module32FirstW(snapshot, C.byref(entry))
            while more:
                rows.append(dict(path=entry.szExePath,
                                 base=C.cast(entry.modBaseAddr, C.c_void_p).value,
                                 size=entry.modBaseSize))
                more = backend.kernel.Module32NextW(snapshot, C.byref(entry))
        finally:
            backend.kernel.CloseHandle(snapshot)
        return rows

    def module(self, path):
        matches = [m for m in self.modules() if path_equal(m["path"], path)]
        if len(matches) > 1:
            raise ValueError("Ambiguous module identity")
        return matches[0] if matches else None

    def allocate(self, blob):
        if not 0 < len(blob) <= 131072:
            raise ValueError("Remote argument buffer outside fixed size bound")
        pointer = self.k.VirtualAllocEx(self.handle, None, len(blob), 0x3000, 0x04)
        if not pointer:
            raise C.WinError(C.get_last_error())
        self.allocations.add(pointer)
        self.write(pointer, blob)
        return pointer

    def write(self, pointer, blob):
        if pointer not in self.allocations:
            raise ValueError("Writes are restricted to our fresh argument allocation base")
        buffer = C.create_string_buffer(blob)
        count = C.c_size_t()
        if not self.k.WriteProcessMemory(self.handle, pointer, buffer, len(blob), C.byref(count)) or count.value != len(blob):
            raise C.WinError(C.get_last_error())

    def read(self, pointer, count):
        if pointer not in self.allocations or count != C.sizeof(Status):
            raise ValueError("Readback is restricted to our fixed Status argument buffer")
        output = C.create_string_buffer(count)
        received = C.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, pointer, output, count, C.byref(received)) or received.value != count:
            raise C.WinError(C.get_last_error())
        return output.raw

    def read_module(self, module, rva, count):
        if not 0 < count <= 4096 or rva < 0 or rva + count > module["size"]:
            raise ValueError("Diagnostic module identity read outside bounds")
        output = C.create_string_buffer(count)
        received = C.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, module["base"] + rva, output, count, C.byref(received)) or received.value != count:
            raise C.WinError(C.get_last_error())
        return output.raw

    def call(self, entry, argument, owned_buffers=()):
        thread_id = W.DWORD()
        thread = self.k.CreateRemoteThread(self.handle, None, 0, entry, argument, 0, C.byref(thread_id))
        if not thread:
            raise C.WinError(C.get_last_error())
        try:
            wait = self.k.WaitForSingleObject(thread, self.timeout_ms)
            if wait != 0:
                # Never free an argument still potentially used by a live thread
                # and never terminate a thread inside a DLL or loader operation.
                self.pending_allocations.update(owned_buffers)
                raise RuntimeError("Remote export wait incomplete; argument buffers retained until process exit")
            result = W.DWORD()
            if not self.k.GetExitCodeThread(thread, C.byref(result)):
                raise C.WinError(C.get_last_error())
            return result.value
        finally:
            self.k.CloseHandle(thread)

    def loader_entry(self):
        local = self.k.GetProcAddress(self.k.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        info = MemoryInfo()
        if not local or not self.k.VirtualQuery(local, C.byref(info), C.sizeof(info)):
            raise ValueError("Unable to resolve local LoadLibraryW owner")
        path = C.create_unicode_buffer(32768)
        if not self.k.GetModuleFileNameW(info.allocation_base, path, len(path)):
            raise C.WinError(C.get_last_error())
        remote = self.module(path.value)
        if not remote or not 0 <= local - info.allocation_base < remote["size"]:
            raise ValueError("Same Windows loader module not found in game")
        return remote["base"] + local - info.allocation_base

    def close(self):
        if self.handle:
            for pointer in self.allocations - self.pending_allocations:
                self.k.VirtualFreeEx(self.handle, pointer, 0, 0x8000)
            self.k.CloseHandle(self.handle)
            self.handle = None


def status_report(control, module, exports):
    status = Status(size=C.sizeof(Status), version=1)
    pointer = control.allocate(bytes(status))
    result = control.call(module["base"] + exports["CoopSyncRuntimeGetStatus"], pointer, (pointer,))
    if result:
        raise RuntimeError("Diagnostic GetStatus failed: " + str(result))
    status = Status.from_buffer_copy(control.read(pointer, C.sizeof(Status)))
    if status.size != 40 or status.version != 1 or status.game_operations or status.world_sync or status.callables:
        raise ValueError("Unexpected diagnostic ABI or enabled game controls")
    return {field: getattr(status, field) for field, _ in Status._fields_}


def run(args):
    if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
        raise ValueError("This diagnostic controller requires 64-bit Windows Python")
    if C.sizeof(Config) != 40 or C.sizeof(Status) != 40:
        raise ValueError("Unexpected diagnostic ABI packing")
    dll = (ROOT / "build" / "CoopSyncRuntime.dll").resolve()
    if not dll.is_file():
        raise ValueError("Build CoopSyncRuntime.dll before loading")
    exports = pe_exports(dll)
    if file_sha256(GAME) != EXPECTED_SHA256:
        raise ValueError("Game executable hash changed; refusing attach or control")
    pids = WindowsBackend().candidates(args.pid)
    if len(pids) != 1:
        raise ValueError("Exactly one running pinned Spider-Man process is required")
    report = dict(schema=1, utc=datetime.now(timezone.utc).isoformat(), action=args.action,
                  pid=pids[0], dll=str(dll), dll_sha256=file_sha256(dll), game_sha256=EXPECTED_SHA256,
                  engine_functions_called=False, game_code_patched=False, saves_modified=False,
                  world_replication_enabled=False)
    directory = None
    if args.action == "attach":
        directory = (args.output_dir or ROOT / "logs" / ("native_runtime_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8])).resolve()
        if str(directory).startswith("\\\\") or not directory.is_absolute():
            raise ValueError("Output must be an absolute local directory")
        directory.mkdir(parents=True, exist_ok=False)
        report["output_directory"] = str(directory)
    control = NativeControl(pids[0], args.timeout_ms)
    try:
        control.open()
        module = control.module(dll)
        if not module and args.action == "attach":
            argument = control.allocate((str(dll) + "\0").encode("utf-16-le"))
            # DWORD thread exit status truncates HMODULE on x64. Find the full
            # module address through the module list instead of trusting it.
            control.call(control.loader_entry(), argument, (argument,))
            module = control.module(dll)
            report["dll_loaded_this_call"] = module is not None
        if not module:
            raise ValueError("Diagnostic DLL is not loaded")
        verify_loaded_dll(control, module, dll)
        report["loaded_dll_identity_verified"] = True
        report["module_base"] = hex(module["base"])
        if args.action == "attach":
            path_pointer = control.allocate((str(directory) + "\0").encode("utf-16-le"))
            config = Config(size=C.sizeof(Config), version=1, output_directory=path_pointer,
                            sample_interval_ms=args.interval_ms)
            config_pointer = control.allocate(bytes(config))
            result = control.call(module["base"] + exports["CoopSyncRuntimeStart"], config_pointer,
                                  (path_pointer, config_pointer))
            report["start_result"] = result
            if result:
                raise RuntimeError("Diagnostic Start failed: " + str(result))
        elif args.action == "stop":
            result = control.call(module["base"] + exports["CoopSyncRuntimeStop"], args.stop_timeout_ms)
            report["stop_result"] = result
            if result:
                raise RuntimeError("Diagnostic Stop failed: " + str(result))
        report["runtime_status"] = status_report(control, module, exports)
        report["status"] = "diagnostic_export_returned"
    except (OSError, ValueError, RuntimeError) as error:
        report.update(status="failed", error=str(error), argument_buffers_retained=len(control.pending_allocations))
        raise
    finally:
        control.close()
        if directory:
            (directory / "controller.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("attach", "status", "stop"))
    parser.add_argument("--pid", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--interval-ms", type=int, default=100)
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--stop-timeout-ms", type=int, default=5000)
    args = parser.parse_args()
    if not 50 <= args.interval_ms <= 2000 or not 1000 <= args.timeout_ms <= 30000 or not 0 <= args.stop_timeout_ms <= 10000:
        parser.error("Sampling or wait duration outside diagnostic bounds")
    if args.pid is not None and not 1 <= args.pid <= 0xFFFFFFFF:
        parser.error("PID outside DWORD range")
    try:
        print(json.dumps(run(args), ensure_ascii=False))
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps(dict(status="failed", error=str(error)), ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
