import ctypes as C
import ctypes.wintypes as W
import datetime
import json
import pathlib
import struct
import subprocess

ROOT = pathlib.Path(__file__).parent
GAME = pathlib.Path("D:/STEAM__/steamapps/common/Marvel's Spider-Man Remastered/Spider-Man.exe")
OUT = ROOT / '短距传送时机只读核对_20261007.json'
DLL = C.WinDLL('kernel32', use_last_error=True)
PSAPI = C.WinDLL('psapi', use_last_error=True)
DLL.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
DLL.OpenProcess.restype = W.HANDLE
DLL.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
DLL.ReadProcessMemory.restype = W.BOOL
DLL.CloseHandle.argtypes = [W.HANDLE]
PSAPI.EnumProcessModulesEx.argtypes = [W.HANDLE, C.POINTER(W.HMODULE), W.DWORD, C.POINTER(W.DWORD), W.DWORD]
PSAPI.GetModuleFileNameExW.argtypes = [W.HANDLE, W.HMODULE, W.LPWSTR, W.DWORD]

pid = int(subprocess.check_output(['powershell', '-NoProfile', '-Command', '(Get-Process -Name Spider-Man).Id'], text=True).strip())
handle = DLL.OpenProcess(0x410, False, pid)
if not handle:
    raise C.WinError(C.get_last_error())

def read(address, count):
    buf = C.create_string_buffer(count)
    actual = C.c_size_t()
    if not DLL.ReadProcessMemory(handle, C.c_void_p(address), buf, count, C.byref(actual)) or actual.value != count:
        raise OSError(f'ReadProcessMemory failed at {address:x} for {count}')
    return buf.raw

def number(address, fmt):
    return struct.unpack(fmt, read(address, struct.calcsize(fmt)))[0]

try:
    mods = (W.HMODULE * 1024)()
    needed = W.DWORD()
    if not PSAPI.EnumProcessModulesEx(handle, mods, C.sizeof(mods), C.byref(needed), 3):
        raise C.WinError(C.get_last_error())
    base = None
    for mod in mods[:needed.value // C.sizeof(W.HMODULE)]:
        name = C.create_unicode_buffer(32768)
        PSAPI.GetModuleFileNameExW(handle, mod, name, len(name))
        if pathlib.Path(name.value).name.lower() == 'spider-man.exe':
            if pathlib.Path(name.value) != GAME:
                raise RuntimeError('Unexpected executable path')
            base = int(mod)
            break
    if not base:
        raise RuntimeError('Game module missing')

    with GAME.open('rb') as stream:
        header = stream.read(4096)
        pe = struct.unpack_from('<I', header, 0x3c)[0]
        sections_count = struct.unpack_from('<H', header, pe + 6)[0]
        optional_size = struct.unpack_from('<H', header, pe + 20)[0]
        sections = []
        for i in range(sections_count):
            pos = pe + 24 + optional_size + i * 40
            name, vsize, rva, rawsize, raw = struct.unpack_from('<8sIIII', header, pos)
            sections.append((rva, max(vsize, rawsize), raw))

        def disk_bytes(rva, length):
            for start, size, raw in sections:
                if start <= rva and rva + length <= start + size:
                    stream.seek(raw + rva - start)
                    return stream.read(length)
            raise ValueError(hex(rva))

        functions = {
            'standard_post_job_commit': 0x1fbd440,
            'native_mover_warp': 0x1fc1c50,
            'normalized_matrix_read': 0x5c6530,
            'native_handle_resolve': 0x15a0560,
            'large_component_lookup': 0x16799a0,
            'small_component_lookup': 0x167ab40,
            'base_empty_commit_return': 0x1fb80f0,
        }
        prologs = {}
        for name, rva in functions.items():
            disk = disk_bytes(rva, 32)
            runtime = read(base + rva, 32)
            prologs[name] = {'rva': hex(rva), 'length': 32, 'file_hex': disk.hex(' '), 'runtime_hex': runtime.hex(' '), 'matches': disk == runtime}

    local_record = number(base + 0x5d9dd00 + 0x158, '<Q')
    local_handle = number(local_record + 4, '<I')
    generation = (local_handle >> 20) & 0x7ff
    index = local_handle & 0xfffff
    count = number(base + 0x7a4439c, '<I')
    if not generation or index >= count:
        raise RuntimeError('Invalid local handle')
    entry = number(base + 0x7a44380, '<Q') + index * 0xc0
    if number(entry + 0x10, '<H') != generation:
        raise RuntimeError('Local handle generation mismatch')
    capacity = number(entry + 0x88, '<H')
    buckets = number(entry + 0x80, '<Q')
    descriptor = base + 0x7c40bf0
    start_index = (descriptor >> 4) & (capacity - 1)
    mover = None
    for offset in range(capacity):
        slot = (start_index + offset) & (capacity - 1)
        key, value = struct.unpack('<QQ', read(buckets + slot * 16, 16))
        if key == descriptor:
            mover = value
            break
        if not key:
            break
    if not mover:
        raise RuntimeError('Exact MoverStandard descriptor not found')
    vtable = number(mover, '<Q')
    runtime_identity = {
        'pid': pid, 'base': hex(base), 'localRecord': hex(local_record), 'handle': hex(local_handle),
        'entry': hex(entry), 'descriptorRva': hex(descriptor-base), 'mover': hex(mover),
        'exactMoverVtableRva': hex(vtable-base), 'moverEntryMatches': number(mover + 8, '<Q') == entry,
        'virtual58Rva': hex(number(vtable + 0x58, '<Q')-base),
        'virtual60Rva': hex(number(vtable + 0x60, '<Q')-base),
    }

    audit = json.loads(OUT.read_text(encoding='utf-8'))
    audit['entry_byte_verification'] = {
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'method': 'File PE section mapping compared with ReadProcessMemory of 32 bytes at each function entry; read-only process handle access 0x410.',
        'all_match': all(item['matches'] for item in prologs.values()),
        'functions': prologs,
        'runtime_local_identity_recheck': runtime_identity,
    }
    audit['signature_evidence'] = {
        'commit': {
            'recommended_abi': 'void (__fastcall*)(void* self)',
            'argument_evidence': '0x1fbd446 copies RCX to RBX, calls 0x1fc3610 with RCX self, restores RCX self, then tails to 0x1fb80f0. No reads of RDX/R8/R9/XMM argument registers.',
            'return_evidence': 'Tail target 0x1fb80f0 is RET 0 and has no value-producing code. The only reviewed caller at 0x1fb87ad immediately advances loop without reading RAX or XMM0. Therefore void is ABI-compatible; original source-level return type cannot be proven without symbols.',
        },
        'normalized_matrix_read': 'float* (__fastcall*)(void* entry, float* outMatrix); return instruction 0x5c6612 MOV RAX,RDX returns output pointer on non-null spatial path.',
        'warp': 'void (__fastcall*)(void* mover, const float* normalizedMatrix, float dt); RCX/RDX/XMM2 based on whole body and native callers using XORPS XMM2,XMM2 before CALL.',
        'resolve': 'void* (__fastcall*)(const uint32_t* handle)',
        'large_lookup': 'void* (__fastcall*)(void* containerEntryPlus80, void* descriptor)',
        'small_lookup': 'void* (__fastcall*)(void* containerEntryPlus58, void* descriptor)',
    }
    OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    md_path = ROOT / '短距传送时机只读核对_20261007.md'
    md = '''# 短距离传送 hook 时机及只读核对\n\n0x1fb80d0 不适合当前本地玩家：它是 MoverBase 的 virtual +0x58，而实际玩家为 MoverStandard，override 为 0x1fbd1b0，未调用 base。\n\n建议在 0x1fbd440 原函数返回后处理热键请求。该函数是 MoverStandard virtual +0x60，0x1fb85b0 在完成 Mover worker job 的 wait/join 后，于串行 loop 0x1fb87a0 至 0x1fb87b8 调用它。能确认为调用 update 的线程及 job 完成后时机；没有独立记录 Windows main-thread ID。\n\n建议 ABI 为 `void (__fastcall*)(void* self)`。函数只保留并恢复 RCX self，调用 0x1fc3610 后 tail-jump 到 0x1fb80f0 的 `ret 0`。caller 不读取 RAX/XMM0 返回值，因此 void 声明 ABI 兼容；没有符号，不能证明源代码的原始返回类型。\n\n运行只读核对：\n\n'''
    md += f'- PID {pid}，游戏 base {base:#x}。\n- 精确 descriptor RVA 0x7c40bf0 lookup 得到 Mover {mover:#x}，vtable RVA {vtable-base:#x}，self+8 等于 local entry。\n- vtable +0x58 = {number(vtable+0x58,"<Q")-base:#x}，+0x60 = {number(vtable+0x60,"<Q")-base:#x}。\n\n'
    md += '| 函数 | RVA | 文件/运行前 32 字节一致 | 文件字节 |\n|---|---:|---|---|\n'
    for name, item in prologs.items():
        md += f'| {name} | {item["rva"]} | {item["matches"]} | `{item["file_hex"]}` |\n'
    md += '\n矩阵读取函数 0x5c6530 的 non-null 路径返回 RDX 输出指针。Warp 0x1fc1c50 使用 RCX Mover、RDX normalized matrix、XMM2 dt；原生 caller 使用 dt=0。矩阵至少 16 字节对齐，以 +0x20 第三基向量投影 X/Z 后归一化得到水平步进，平移位于 +0x30。保留规范化原矩阵供返回，并以 local handle generation 和 Mover 身份约束返回状态。\n\n此次仅 OpenProcess(0x410)、模块枚举及 ReadProcessMemory；未调用游戏函数、写入进程、控制 UI、修改存档或游戏配置。尚未执行候选 DLL 或穿墙功能，不能声称实际穿墙已验证。\n'
    md_path.write_text(md, encoding='utf-8')
    print(json.dumps({'all_match': audit['entry_byte_verification']['all_match'], 'local': runtime_identity, 'prologs': prologs, 'json': str(OUT), 'md': str(md_path)}, ensure_ascii=False, indent=2))
finally:
    DLL.CloseHandle(handle)
