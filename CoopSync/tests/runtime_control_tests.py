"""Synthetic controller/ABI checks. Never attaches to the game."""
import ctypes
import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runtime_control_under_test", ROOT / "tools" / "runtime_control.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

checks = 0


def check(value):
    global checks
    assert value
    checks += 1


def rejects(function, expected=ValueError):
    global checks
    try:
        function()
    except expected:
        checks += 1
        return
    raise AssertionError("Expected refusal")


check(ctypes.sizeof(module.Config) == 40)
check(ctypes.sizeof(module.Status) == 40)
check(module.Config.output_directory.offset == 8)
check(module.Config.sample_interval_ms.offset == 16)
check(module.Status.sample_count.offset == 16)
check(module.Status.game_operations.offset == 24)
check(module.Status.callables.offset == 32)
exports = module.pe_exports(ROOT / "build" / "CoopSyncRuntime.dll")
check(set(exports) == {"CoopSyncRuntimeStart", "CoopSyncRuntimeStop", "CoopSyncRuntimeGetStatus"})
check(all(isinstance(rva, int) and rva > 0 for rva in exports.values()))


class FakeKernel:
    def __init__(self, wait=0):
        self.wait = wait
        self.closed = []
        self.entry = self.argument = None

    def CreateRemoteThread(self, handle, attributes, size, entry, argument, flags, thread_id):
        self.entry, self.argument = entry, argument
        return 777

    def WaitForSingleObject(self, thread, timeout):
        return self.wait

    def GetExitCodeThread(self, thread, result):
        ctypes.cast(result, ctypes.POINTER(module.W.DWORD)).contents.value = 42
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def VirtualFreeEx(self, handle, pointer, size, mode):
        self.closed.append(("freed", pointer))
        return True


controller = object.__new__(module.NativeControl)
controller.pid, controller.timeout_ms = 123, 1000
controller.handle = 321
controller.allocations = {10000, 20000}
controller.pending_allocations = set()
controller.k = FakeKernel()
check(controller.call(0x12345, 10000, (10000,)) == 42)
check(controller.k.entry == 0x12345 and controller.k.argument == 10000)
check(controller.k.closed == [777])
check(not controller.pending_allocations)
controller.k = FakeKernel(wait=258)
rejects(lambda: controller.call(0x12345, 10000, (10000,)), RuntimeError)
check(controller.pending_allocations == {10000})
controller.close()
check(("freed", 10000) not in controller.k.closed)
check(("freed", 20000) in controller.k.closed)
check(controller.handle is None)

controller = object.__new__(module.NativeControl)
controller.allocations = {10000}
rejects(lambda: controller.write(99999, b"x"))
rejects(lambda: controller.read(99999, 40))
rejects(lambda: controller.read(10000, 1000000))
rejects(lambda: controller.read_module({"base": 10000, "size": 40}, 39, 2))
rejects(lambda: controller.read_module({"base": 10000, "size": 10000}, 0, 4097))
rejects(lambda: controller.allocate(b""))
rejects(lambda: controller.allocate(b"x" * 131073))


class FakeStatusController:
    def __init__(self, operations=0, world_sync=0, callables=0, version=1, result=0):
        self.status = module.Status(size=40, version=version, phase=2, sample_count=8,
                                    game_operations=operations, world_sync=world_sync, callables=callables)
        self.result = result

    def allocate(self, blob):
        return 10000

    def call(self, entry, argument, owned_buffers=()):
        return self.result

    def read(self, pointer, count):
        return bytes(self.status)


module_entry = {"base": 0x10000000}
check(module.status_report(FakeStatusController(), module_entry, exports)["sample_count"] == 8)
rejects(lambda: module.status_report(FakeStatusController(operations=1), module_entry, exports))
rejects(lambda: module.status_report(FakeStatusController(world_sync=1), module_entry, exports))
rejects(lambda: module.status_report(FakeStatusController(callables=1), module_entry, exports))
rejects(lambda: module.status_report(FakeStatusController(version=2), module_entry, exports))
rejects(lambda: module.status_report(FakeStatusController(result=5), module_entry, exports), RuntimeError)

image = module.pefile.PE(str(ROOT / "build" / "CoopSyncRuntime.dll"))
loaded = {"base": 0x7FFB00000000, "size": image.OPTIONAL_HEADER.SizeOfImage}
mapped = image.get_memory_mapped_image(ImageBase=loaded["base"])


class FakeMappedController:
    def __init__(self, changed_rva=None):
        self.changed_rva = changed_rva
        self.calls = 0

    def read_module(self, entry, rva, count):
        assert 0 < count <= 4096 and rva + count <= entry["size"]
        self.calls += 1
        data = bytearray(mapped[rva:rva + count])
        if self.changed_rva is not None and rva <= self.changed_rva < rva + count:
            data[self.changed_rva - rva] ^= 1
        return bytes(data)


identity = FakeMappedController()
module.verify_loaded_dll(identity, loaded, ROOT / "build" / "CoopSyncRuntime.dll")
check(identity.calls > 3)
rejects(lambda: module.verify_loaded_dll(identity, dict(loaded, size=loaded["size"] - 1), ROOT / "build" / "CoopSyncRuntime.dll"))
for changed in (image.DOS_HEADER.e_lfanew, image.OPTIONAL_HEADER.DATA_DIRECTORY[0].VirtualAddress,
                exports["CoopSyncRuntimeStart"], exports["CoopSyncRuntimeStop"], exports["CoopSyncRuntimeGetStatus"]):
    rejects(lambda: module.verify_loaded_dll(FakeMappedController(changed), loaded, ROOT / "build" / "CoopSyncRuntime.dll"))

print(f"PASS: {checks} synthetic diagnostic controller / ABI checks; no game attachment")
