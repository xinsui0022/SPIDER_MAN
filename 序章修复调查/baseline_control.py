"""Same-save vanilla comparison. No launch, injection, patching, or deletion.

check/status are read-only. prepare/restore require the game and launcher closed.
Every save directory is preserved. SMT/Save is only ever read by this helper.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import uuid


GAME_ROOT = Path("D:/STEAM__/steamapps/common/Marvel's Spider-Man Remastered")
NATIVE_PARENT = Path("C:/Users/xinsui/Documents/Marvel's Spider-Man Remastered")
ACCOUNT_ID = "76561199372553531"
DIAG_ROOT = Path(__file__).absolute().parent
SESSION_PREFIX = "同档对照_"
KNOWN_HASHES = {
    "game": "e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1",
    "mod": "b7ab575100f2346af25180d74bf9641e24ce09bf549ce47446be09c3462606c7",
    "winmm": "ec59e8537eb9c6ec144897f64ccd8a79618309dd1bb3a62b65ad70b308bcab85",
}
BLOCKED_PROCESSES = {"spider-man.exe", "smt-launcher.exe"}


class SafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Environment:
    game_root: Path
    native_parent: Path
    account_id: str
    diag_root: Path
    known_hashes: dict[str, str]

    @property
    def native(self):
        return self.native_parent / self.account_id

    @property
    def saves(self):
        return self.game_root / "SMT" / "Save"

    @property
    def winmm(self):
        return self.game_root / "winmm.dll"


ENV = Environment(GAME_ROOT, NATIVE_PARENT, ACCOUNT_ID, DIAG_ROOT, KNOWN_HASHES)


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def lexical(path):
    return Path(os.path.abspath(os.fspath(path)))


def reject_reparse(path):
    """Check each existing ancestor before resolving or opening a path."""
    path = lexical(path)
    for item in reversed((path, *path.parents)):
        try:
            info = os.lstat(item)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SafetyError(f"拒绝符号链接/junction/reparse point：{item}")
    return path


def contained(path, parent, *, direct=False):
    path = reject_reparse(path)
    parent = reject_reparse(parent)
    resolved_path = path.resolve(strict=False)
    resolved_parent = parent.resolve(strict=False)
    try:
        relative = resolved_path.relative_to(resolved_parent)
    except ValueError as exc:
        raise SafetyError(f"目标越界：{path} 不在 {parent}") from exc
    if not relative.parts or (direct and len(relative.parts) != 1):
        raise SafetyError(f"目标必须位于指定父目录内：{path}")
    return path


def sha256(path):
    reject_reparse(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest(path):
    path = reject_reparse(path)
    if not path.is_dir():
        raise SafetyError(f"存档目录不存在：{path}")
    files = {}
    directories = []
    for root, dirs, names in os.walk(path, followlinks=False):
        root = Path(root)
        for name in sorted(dirs):
            child = reject_reparse(root / name)
            directories.append(child.relative_to(path).as_posix())
        for name in sorted(names):
            child = reject_reparse(root / name)
            if not child.is_file():
                raise SafetyError(f"拒绝非常规文件：{child}")
            files[child.relative_to(path).as_posix()] = {
                "size": child.stat().st_size, "sha256": sha256(child)
            }
    return {"files": files, "directories": sorted(directories)}


def write_new_json(path, data):
    reject_reparse(path)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def journal(session, event, **details):
    path = contained(session / "journal.jsonl", session, direct=True)
    record = {"time_utc": datetime.now(timezone.utc).isoformat(), "event": event, **details}
    needs_separator = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as previous:
            previous.seek(-1, os.SEEK_END)
            needs_separator = previous.read(1) != b"\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        if needs_separator:
            handle.write("\n")
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_events(session):
    path = reject_reparse(session / "journal.jsonl")
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    events = []
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
            if not isinstance(record, dict) or not isinstance(record.get("event"), str):
                raise ValueError("Invalid journal record")
            events.append(record)
        except json.JSONDecodeError:
            # A partial append can remain between later recovery entries. It is
            # never evidence of a completed operation; manifests and fixed paths
            # remain the authority for recovery.
            events.append({"event": "incomplete_journal_fragment", "line": index + 1})
    return events


@contextmanager
def mutation_lock(env):
    """Serialize this helper's mutations without deleting the lock file."""
    import msvcrt
    path = contained(env.diag_root / "baseline_control.lock", env.diag_root, direct=True)
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise SafetyError("另一个准备/恢复助手正在运行；请等待其完成") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def processes():
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                    ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                    ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                    ("flags", wintypes.DWORD), ("name", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    found = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        ok = kernel.Process32FirstW(handle, ctypes.byref(entry))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        while ok:
            if entry.name.casefold() in BLOCKED_PROCESSES:
                found.append({"name": entry.name, "pid": entry.pid})
            ok = kernel.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)
    return found


def require_closed():
    found = processes()
    if found:
        raise SafetyError("请先正常退出游戏和 SMT-Launcher；检测到：" +
                          ", ".join(f"{item['name']} PID {item['pid']}" for item in found))


def file_version(path):
    """Read the existing PE version resource; never load the target executable."""
    api = ctypes.WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                 ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    ignored = wintypes.DWORD()
    size = api.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None
    pointer = ctypes.c_void_p()
    length = wintypes.UINT()
    if not api.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        return None
    if length.value < 52:
        return None
    fixed = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 13)).contents
    return ".".join(str(x) for x in (fixed[2] >> 16, fixed[2] & 65535,
                                    fixed[3] >> 16, fixed[3] & 65535))


def binaries(env, require=False):
    paths = {"game": env.game_root / "Spider-Man.exe",
             "mod": env.game_root / "SMT" / "Scripts" / "smt.dll",
             "winmm": env.winmm}
    result = {}
    for name, path in paths.items():
        reject_reparse(path)
        actual = sha256(path) if path.is_file() else None
        result[name] = {"path": str(path), "sha256": actual,
                        "expected": env.known_hashes[name],
                        "matches": actual == env.known_hashes[name]}
        if require and not result[name]["matches"]:
            raise SafetyError(f"{name} 缺失或 SHA256 与已审计版本不符：{path}")
    result["game"]["file_version"] = file_version(paths["game"]) if paths["game"].is_file() else None
    return result


def plan(env, session_id, source_kind="smt"):
    if source_kind not in {"smt", "native"}:
        raise SafetyError("无效存档来源；只允许 smt 或 native")
    if len(session_id) != 24 or session_id[8] != "_" or session_id[15] != "_":
        raise SafetyError("无效 session ID")
    if not session_id[:8].isdigit() or not session_id[9:15].isdigit() or \
            any(c not in "0123456789abcdef" for c in session_id[16:]):
        raise SafetyError("无效 session ID")
    session = contained(env.diag_root / (SESSION_PREFIX + session_id), env.diag_root, direct=True)
    native = contained(env.native, env.native_parent, direct=True)
    original = contained(env.native_parent / (env.account_id + ".codex-original-" + session_id),
                         env.native_parent, direct=True)
    disabled = contained(env.game_root / ("winmm.dll.codex-disabled-" + session_id),
                         env.game_root, direct=True)
    freeze = contained(session / ("frozen_" + source_kind + "_save"), session, direct=True)
    if native.drive.casefold() != session.drive.casefold():
        raise SafetyError("普通存档与诊断目录必须在同一卷；拒绝跨卷恢复移动")
    return {"session": session, "native": native, "original": original,
            "disabled": disabled, "freeze": freeze}


def load_session(env, session):
    session = contained(session, env.diag_root, direct=True)
    state_path = contained(session / "state.json", session, direct=True)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("schema") != 1 or state.get("known_hashes") != env.known_hashes:
        raise SafetyError("session 格式或版本哈希不符")
    source_kind = state.get("source_kind", "smt")  # Existing sessions predate source selection.
    expected = plan(env, state["session_id"], source_kind)
    if session != expected["session"] or state.get("paths") != {k: str(v) for k, v in expected.items()}:
        raise SafetyError("session 记录的路径不符合固定安全范围")
    if "source_path" in state:
        source = env.saves if source_kind == "smt" else expected["native"]
        if state["source_path"] != str(source):
            raise SafetyError("session 记录的来源不符合固定存档路径")
    return state, expected


def sessions(env):
    reject_reparse(env.diag_root)
    result = []
    for candidate in sorted(env.diag_root.glob(SESSION_PREFIX + "*")):
        reject_reparse(candidate)
        if (candidate / "state.json").is_file():
            state, paths = load_session(env, candidate)
            events = read_events(candidate)
            result.append({"session": str(candidate), "original_exists": paths["original"].exists(),
                           "disabled_winmm_exists": paths["disabled"].exists(),
                           "last_event": events[-1]["event"] if events else None,
                           "restore_needed": paths["original"].exists() or paths["disabled"].exists()})
    return result


def copy_verified(source, destination, expected):
    if destination.exists():
        raise SafetyError(f"复制目标已存在，拒绝覆盖：{destination}")
    reject_reparse(source)
    reject_reparse(destination)
    shutil.copytree(source, destination, copy_function=shutil.copy2, symlinks=False)
    copied = manifest(destination)
    source_again = manifest(source)
    if copied != expected or source_again != expected:
        raise SafetyError("存档复制双重核验失败：源文件变化或副本哈希不一致")


def rename_preserving(source, destination):
    reject_reparse(source)
    reject_reparse(destination)
    if not source.exists() or destination.exists():
        raise SafetyError(f"重命名源缺失或目标已有文件，拒绝覆盖：{source} -> {destination}")
    source.rename(destination)


def restore_files(env, session):
    """Internal recovery engine. Public callers check running processes first."""
    state, paths = load_session(env, session)
    original = paths["original"]
    native = paths["native"]
    disabled = paths["disabled"]
    prior = {item["event"] for item in read_events(session)}
    # Finish all checks before moving any original directory or DLL.
    if original.exists():
        if manifest(original) != state["native_original_manifest"]:
            raise SafetyError("普通存档原件备份发生变化；拒绝自动恢复，请检查 session")
        if native.exists():
            manifest(native)  # Reject any junctions introduced during the test.
    elif not native.is_dir():
        raise SafetyError("普通存档原件备份和当前普通存档都缺失；无法确认恢复")
    elif "native_restored" not in prior:
        if manifest(native) != state["native_original_manifest"]:
            raise SafetyError("找不到可验证的普通原档；拒绝移动当前普通存档")
    if disabled.exists():
        if not disabled.is_file() or sha256(disabled) != env.known_hashes["winmm"]:
            raise SafetyError("待恢复 winmm 原件的 SHA256 不符")
        if env.winmm.exists():
            raise SafetyError("winmm.dll 与禁用备份同时存在；拒绝覆盖，请检查")
    elif not env.winmm.is_file() or sha256(env.winmm) != env.known_hashes["winmm"]:
        raise SafetyError("找不到可验证的 winmm 原件")
    if original.exists():
        if native.exists():
            result = contained(session / "native_test_save", session, direct=True)
            if result.exists():
                result = contained(session / ("native_test_save_recovery_" + stamp()), session, direct=True)
            journal(session, "preserve_test_intent", destination=str(result))
            rename_preserving(native, result)
            journal(session, "test_preserved", destination=str(result))
        journal(session, "native_restore_intent")
        rename_preserving(original, native)
        journal(session, "native_restored")
    if disabled.exists():
        journal(session, "winmm_restore_intent")
        rename_preserving(disabled, env.winmm)
        if sha256(env.winmm) != env.known_hashes["winmm"]:
            raise SafetyError("恢复后的 winmm SHA256 核验失败")
        journal(session, "winmm_restored")
    journal(session, "restored")
    return paths


def prepare(env, source_kind="smt"):
    if source_kind not in {"smt", "native"}:
        raise SafetyError("无效存档来源；只允许 smt 或 native")
    require_closed()
    binaries(env, require=True)
    unresolved = [item for item in sessions(env) if item["restore_needed"]]
    if unresolved:
        raise SafetyError("已有未恢复的对照 session；先执行 restore：" + unresolved[-1]["session"])
    source = env.saves if source_kind == "smt" else env.native
    source_label = "SMT/Save" if source_kind == "smt" else "普通存档"
    source_manifest = manifest(source)
    original_manifest = manifest(env.native)
    if not any(name.startswith("slot") and name.endswith(".save") for name in source_manifest["files"]):
        raise SafetyError(f"{source_label}没有有效命名的槽位文件，拒绝准备")
    session_id = stamp()
    paths = plan(env, session_id, source_kind)
    if paths["original"].exists() or paths["disabled"].exists():
        raise SafetyError("唯一备份目标已存在，拒绝覆盖")
    paths["session"].mkdir()
    state = {"schema": 1, "session_id": session_id, "known_hashes": env.known_hashes,
             "paths": {k: str(v) for k, v in paths.items()},
             "source_kind": source_kind, "source_path": str(source),
             "source_manifest": source_manifest, "native_original_manifest": original_manifest,
             "purpose": ("用 SMT 存档副本完全关闭 MOD 做单人对照；需核对槽位和任务阶段，不证明合作功能"
                         if source_kind == "smt" else
                         "用普通存档副本完全关闭 MOD 做单人对照；不导入 SMT 存档，原件完整保留")}
    if source_kind == "smt":
        state["smt_source_manifest"] = source_manifest  # Preserve the existing diagnostic field.
    write_new_json(paths["session"] / "state.json", state)
    session = paths["session"]
    try:
        journal(session, "freeze_intent", source_kind=source_kind, source_path=str(source))
        copy_verified(source, paths["freeze"], source_manifest)
        write_new_json(session / "frozen_manifest.json", source_manifest)
        journal(session, "freeze_verified")
        require_closed()
        if manifest(env.native) != original_manifest or manifest(source) != source_manifest:
            raise SafetyError("准备期间存档变化，拒绝继续")
        journal(session, "native_backup_intent")
        rename_preserving(paths["native"], paths["original"])
        journal(session, "native_backed_up")
        journal(session, "native_copy_intent")
        copy_verified(paths["freeze"], paths["native"], source_manifest)
        journal(session, "native_copy_verified")
        require_closed()
        if sha256(env.winmm) != env.known_hashes["winmm"]:
            raise SafetyError("准备期间 winmm 原件变化，拒绝禁用")
        journal(session, "winmm_disable_intent")
        rename_preserving(env.winmm, paths["disabled"])
        journal(session, "winmm_disabled")
        retained_source = env.saves if source_kind == "smt" else paths["original"]
        if manifest(retained_source) != source_manifest:
            raise SafetyError(f"{source_label}原件在准备过程中变化；停止并回退")
        journal(session, "prepared")
    except Exception as exc:
        try:
            journal(session, "prepare_failed", error=str(exc))
        except OSError:
            pass  # A journal I/O failure must not suppress a recovery attempt.
        try:
            require_closed()
            restore_files(env, session)
            journal(session, "rollback_completed")
        except Exception as rollback_error:
            try:
                journal(session, "rollback_failed", error=str(rollback_error))
            except OSError:
                pass
            raise SafetyError(f"准备失败：{exc}\n自动回退未完成：{rollback_error}\n保留所有文件，运行 restore --session \"{session}\"") from exc
        raise SafetyError(f"准备失败，已恢复普通原档及 winmm：{exc}\n记录保留：{session}") from exc
    print(f"同档单人对照已准备完成，来源：{source_label}。原存档均已保留，SMT/Save 未修改。")
    print(f"session：{session}")
    print("请直接启动 Spider-Man.exe（不要 -mp），手动选择原故障槽位。助手不会启动游戏。")
    print("观察后正常退出游戏，运行“恢复联机环境.cmd”。")


def choose_session(env, selected=None):
    if selected:
        path = lexical(selected)
        load_session(env, path)
        return path
    available = sessions(env)
    active = [item for item in available if item["restore_needed"]]
    if len(active) > 1:
        raise SafetyError("多个待恢复 session，使用 restore --session 指定路径")
    if active:
        return Path(active[0]["session"])
    if available:
        return Path(available[-1]["session"])
    raise SafetyError("没有对照 session")


def restore(env, selected=None):
    require_closed()
    session = choose_session(env, selected)
    restore_files(env, session)
    print("普通游戏原存档和 winmm 已恢复；SMT/Save 原件未修改。")
    print(f"对照运行产生的存档与冻结副本保留在：{session}")


def check(env):
    running = processes()
    report = {"mode": "只读检查；没有创建或修改任何文件", "processes": running,
              "prepare_allowed_processes": not running, "binaries": binaries(env),
              "smt_version_reference": "已审计 SMT v0.5.1，身份以 SHA256 为准",
              "native_account_path": str(env.native), "smt_save_path": str(env.saves)}
    for name, path in (("native_original", env.native), ("smt_save", env.saves)):
        if path.exists():
            data = manifest(path)
            report[name] = {"file_count": len(data["files"]),
                            "directory_count": len(data["directories"]),
                            "total_bytes": sum(item["size"] for item in data["files"].values()),
                            "slot_files": {key: value for key, value in data["files"].items()
                                           if key.startswith("slot") and key.endswith(".save")}}
        else:
            report[name] = {"exists": False}
    report["sessions"] = sessions(env)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="同一存档、完全关闭 SMT 的可回退对照助手")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("check", help="只读核查进程、版本、哈希和存档计数")
    subcommands.add_parser("status", help="只读查看 session 与恢复状态")
    prepare_parser = subcommands.add_parser("prepare", help="游戏退出后冻结同档、保存原档并禁用本地 winmm")
    prepare_parser.add_argument("--source", choices=("smt", "native"), default="smt",
                                help="冻结存档来源：smt 联机存档（默认），native 当前普通存档")
    restore_parser = subcommands.add_parser("restore", help="游戏退出后保留测试结果并恢复原环境")
    restore_parser.add_argument("--session", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check":
            check(ENV)
        elif args.command == "status":
            print(json.dumps({"processes": processes(), "sessions": sessions(ENV)},
                             ensure_ascii=False, indent=2))
        elif args.command == "prepare":
            with mutation_lock(ENV):
                prepare(ENV, args.source)
        else:
            with mutation_lock(ENV):
                restore(ENV, args.session)
    except (SafetyError, OSError, ValueError, KeyError) as exc:
        print(f"未完成：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
