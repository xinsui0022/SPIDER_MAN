"""Reversible SMT slot 3 comparison. Only diagnostic and SMT/Save directories are changed.

No DLL/GFX patching, process calls, launching, or ordinary Documents save access.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import sys

import baseline_control as bc


SESSION_PREFIX = "联机NG对照_"
ID_PATTERN = re.compile(r"[0-9]{8}_[0-9]{6}_[0-9a-f]{8}\Z")


@dataclass(frozen=True)
class Environment:
    game_root: Path
    diag_root: Path
    known_hashes: dict[str, str]

    @property
    def saves(self):
        return self.game_root / "SMT" / "Save"

    @property
    def winmm(self):
        return self.game_root / "winmm.dll"


ENV = Environment(bc.GAME_ROOT, bc.DIAG_ROOT, bc.KNOWN_HASHES)


def source_path(env, selected):
    source = bc.contained(bc.lexical(selected), env.diag_root)
    session = source.parent.parent
    if source.name != "slot3-s.save" or source.parent.name != "native_test_save" or \
            session.parent != bc.lexical(env.diag_root) or \
            not session.name.startswith(bc.SESSION_PREFIX) or \
            not ID_PATTERN.fullmatch(session.name[len(bc.SESSION_PREFIX):]):
        raise bc.SafetyError("来源只能是诊断 baseline session/native_test_save/slot3-s.save")
    return source


def plan(env, session_id):
    if not ID_PATTERN.fullmatch(session_id):
        raise bc.SafetyError("无效联机测试 session ID")
    session = bc.contained(env.diag_root / (SESSION_PREFIX + session_id), env.diag_root, direct=True)
    smt = bc.contained(env.game_root / "SMT", env.game_root, direct=True)
    saves = bc.contained(env.saves, smt, direct=True)
    original = bc.contained(smt / ("Save.codex-original-NGtest-" + session_id), smt, direct=True)
    retained = bc.contained(smt / ("Save.codex-result-NGtest-" + session_id), smt, direct=True)
    frozen = bc.contained(session / "frozen_slot3-s.save", session, direct=True)
    result = bc.contained(session / "mod_test_result", session, direct=True)
    if saves.drive.casefold() != original.drive.casefold() or saves.drive.casefold() != retained.drive.casefold():
        raise bc.SafetyError("SMT 原档、备份和保留结果必须位于同一卷")
    return dict(session=session, saves=saves, original=original, retained=retained,
                frozen=frozen, result=result)


def load_session(env, selected):
    session = bc.contained(bc.lexical(selected), env.diag_root, direct=True)
    path = bc.contained(session / "state.json", session, direct=True)
    state = json.loads(path.read_text(encoding="utf8"))
    if state.get("schema") != 1 or state.get("helper") != "mod_save_control" or \
            state.get("known_hashes") != env.known_hashes:
        raise bc.SafetyError("联机测试 session 格式或版本哈希不符")
    paths = plan(env, state["session_id"])
    if session != paths["session"] or state.get("paths") != {k: str(v) for k, v in paths.items()}:
        raise bc.SafetyError("联机测试 session 路径不符合固定范围")
    if str(source_path(env, state["source_path"])) != state["source_path"]:
        raise bc.SafetyError("来源路径不符合固定诊断范围")
    if not re.fullmatch(r"[0-9a-f]{64}", state.get("source_sha256", "")):
        raise bc.SafetyError("session 来源哈希无效")
    return state, paths


def sessions(env):
    bc.reject_reparse(env.diag_root)
    result = []
    for candidate in sorted(env.diag_root.glob(SESSION_PREFIX + "*")):
        bc.reject_reparse(candidate)
        if (candidate / "state.json").is_file():
            state, paths = load_session(env, candidate)
            events = bc.read_events(candidate)
            result.append({"session": str(candidate), "original_exists": paths["original"].exists(),
                           "retained_result_exists": paths["retained"].exists(),
                           "restore_needed": paths["original"].exists(),
                           "last_event": events[-1]["event"] if events else None,
                           "source_sha256": state["source_sha256"]})
    return result


def freeze_source(source, destination, expected):
    if destination.exists():
        raise bc.SafetyError("冻结目标已存在，拒绝覆盖")
    bc.reject_reparse(source)
    bc.reject_reparse(destination)
    shutil.copy2(source, destination)
    if bc.sha256(destination) != expected or bc.sha256(source) != expected:
        raise bc.SafetyError("NG+来源复制双重哈希核验失败")


def restore_files(env, session):
    state, paths = load_session(env, session)
    prior = {entry["event"] for entry in bc.read_events(session)}
    original, saves, retained = paths["original"], paths["saves"], paths["retained"]
    if not original.exists():
        if not saves.is_dir():
            raise bc.SafetyError("原档备份及当前 SMT/Save 都缺失，无法自动恢复")
        bc.manifest(saves)
        if "mod_restored" not in prior and bc.manifest(saves) != state["original_manifest"]:
            raise bc.SafetyError("没有可验证的联机原档备份，拒绝移动当前 Save")
        bc.journal(session, "restored")
        return paths
    if bc.manifest(original) != state["original_manifest"]:
        raise bc.SafetyError("联机原档备份发生变化，拒绝自动恢复")
    if saves.exists() and retained.exists():
        raise bc.SafetyError("当前 Save 和同卷保留结果同时存在，拒绝覆盖")
    test = saves if saves.exists() else retained
    manifest_path = bc.contained(session / "test_result_manifest.json", session, direct=True)
    if test.exists():
        test_manifest = bc.manifest(test)
        if manifest_path.exists():
            if json.loads(manifest_path.read_text(encoding="utf8")) != test_manifest:
                raise bc.SafetyError("已登记的联机测试结果发生变化，保留全部文件并停止")
        else:
            bc.write_new_json(manifest_path, test_manifest)
        if saves.exists():
            bc.journal(session, "retain_test_intent", destination=str(retained))
            bc.rename_preserving(saves, retained)
            bc.journal(session, "test_retained", destination=str(retained))
        if bc.manifest(retained) != test_manifest:
            raise bc.SafetyError("同卷保留结果核验失败")
        if paths["result"].exists():
            if bc.manifest(paths["result"]) != test_manifest:
                raise bc.SafetyError("诊断结果副本不完整或已变化；拒绝覆盖，原档与同卷结果仍保留")
        else:
            bc.journal(session, "copy_result_intent", destination=str(paths["result"]))
            bc.copy_verified(retained, paths["result"], test_manifest)
        bc.journal(session, "result_copy_verified")
    bc.journal(session, "mod_restore_intent")
    bc.rename_preserving(original, saves)
    bc.journal(session, "mod_restored")
    if bc.manifest(saves) != state["original_manifest"]:
        raise bc.SafetyError("联机原档恢复后核验失败；文件已保留")
    bc.journal(session, "restored")
    return paths


def prepare(env, selected, expected_hash):
    bc.require_closed()
    bc.binaries(env, require=True)
    active = [entry for entry in sessions(env) if entry["restore_needed"]]
    if active:
        raise bc.SafetyError("已有待恢复联机对照 session：" + active[-1]["session"])
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise bc.SafetyError("需要完整小写 SHA256 来源哈希")
    source = source_path(env, selected)
    if not source.is_file() or bc.sha256(source) != expected_hash:
        raise bc.SafetyError("来源缺失或 SHA256 与指定值不符，未改联机存档")
    original_manifest = bc.manifest(env.saves)
    if not any(name.startswith("slot") and name.endswith(".save") for name in original_manifest["files"]):
        raise bc.SafetyError("SMT/Save 没有有效命名的槽位，拒绝准备")
    session_id = bc.stamp()
    paths = plan(env, session_id)
    if paths["original"].exists() or paths["retained"].exists():
        raise bc.SafetyError("唯一备份或保留目录已存在，拒绝覆盖")
    paths["session"].mkdir()
    state = {"schema": 1, "helper": "mod_save_control", "session_id": session_id,
             "known_hashes": env.known_hashes, "paths": {k: str(v) for k, v in paths.items()},
             "source_path": str(source), "source_sha256": expected_hash,
             "original_manifest": original_manifest,
             "purpose": "在 SMT 的完整测试副本中仅导入已验证原版 NG+ slot3，对照任务初始化；不覆盖原档"}
    bc.write_new_json(paths["session"] / "state.json", state)
    session = paths["session"]
    try:
        bc.journal(session, "freeze_source_intent")
        freeze_source(source, paths["frozen"], expected_hash)
        bc.journal(session, "source_frozen_verified")
        bc.require_closed()
        if bc.manifest(env.saves) != original_manifest or bc.sha256(source) != expected_hash:
            raise bc.SafetyError("准备期间原档或来源变化，拒绝继续")
        bc.journal(session, "mod_backup_intent")
        bc.rename_preserving(paths["saves"], paths["original"])
        bc.journal(session, "mod_backed_up")
        bc.copy_verified(paths["original"], paths["saves"], original_manifest)
        bc.journal(session, "mod_copy_verified")
        bc.require_closed()
        if bc.manifest(paths["original"]) != original_manifest or bc.sha256(paths["frozen"]) != expected_hash:
            raise bc.SafetyError("导入前原档或冻结副本核验失败")
        destination = bc.contained(paths["saves"] / "slot3-s.save", paths["saves"], direct=True)
        bc.journal(session, "slot3_import_intent", sha256=expected_hash)
        shutil.copy2(paths["frozen"], destination)
        if bc.sha256(destination) != expected_hash or bc.sha256(paths["frozen"]) != expected_hash or \
                bc.sha256(source) != expected_hash or bc.manifest(paths["original"]) != original_manifest:
            raise bc.SafetyError("slot3 导入或原件保留核验失败")
        bc.journal(session, "prepared")
    except Exception as exc:
        try:
            bc.journal(session, "prepare_failed", error=str(exc))
        except OSError:
            pass
        try:
            bc.require_closed()
            restore_files(env, session)
            bc.journal(session, "rollback_completed")
        except Exception as rollback:
            try:
                bc.journal(session, "rollback_failed", error=str(rollback))
            except OSError:
                pass
            raise bc.SafetyError(f"准备失败：{exc}\n回退未完成：{rollback}\n原件和测试文件全部保留；restore --session {session}") from exc
        raise bc.SafetyError(f"准备失败，已恢复原件：{exc}\n诊断记录：{session}") from exc
    print("联机 slot3 测试副本已准备，完整原件保留。助手不会启动游戏。")
    print(f"session：{session}")


def choose_session(env, selected=None):
    if selected:
        session = bc.lexical(selected)
        load_session(env, session)
        return session
    known = sessions(env)
    active = [entry for entry in known if entry["restore_needed"]]
    if len(active) > 1:
        raise bc.SafetyError("多个待恢复联机对照，必须指定 --session")
    if active:
        return Path(active[0]["session"])
    if known:
        return Path(known[-1]["session"])
    raise bc.SafetyError("没有联机测试 session")


def restore(env, selected=None):
    bc.require_closed()
    bc.binaries(env, require=True)
    session = choose_session(env, selected)
    paths = restore_files(env, session)
    print("完整 SMT/Save 原件已恢复；测试结果保留在同卷目录及诊断副本中。")
    print(f"session：{session}\n同卷结果：{paths['retained']}\n诊断结果：{paths['result']}")


def check(env):
    report = {"mode": "只读；不访问 Documents 普通存档", "processes": bc.processes(),
              "binaries": bc.binaries(env), "smt_save_path": str(env.saves), "sessions": sessions(env)}
    if env.saves.exists():
        report["smt_save_manifest"] = bc.manifest(env.saves)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf8")
        sys.stderr.reconfigure(encoding="utf8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="只读检查版本、进程、联机存档和测试状态")
    sub.add_parser("status", help="只读检查测试 session")
    prepare_parser = sub.add_parser("prepare", help="保留联机原件，向完整测试副本导入原版 slot3")
    prepare_parser.add_argument("--source", type=Path, required=True)
    prepare_parser.add_argument("--sha256", required=True)
    restore_parser = sub.add_parser("restore", help="保留全部结果并恢复联机原件")
    restore_parser.add_argument("--session", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check":
            check(ENV)
        elif args.command == "status":
            print(json.dumps({"processes": bc.processes(), "sessions": sessions(ENV)}, ensure_ascii=False, indent=2))
        else:
            with bc.mutation_lock(ENV):
                if args.command == "prepare":
                    prepare(ENV, args.source, args.sha256)
                else:
                    restore(ENV, args.session)
    except (bc.SafetyError, OSError, ValueError, KeyError) as exc:
        print(f"未完成：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
