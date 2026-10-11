"""One fixed import: complete native auto69 -> SMT profile4 only.

This never imports manual saves, prefs, cloud metadata or diagnostic JSON.
check is read-only. stage is allowed only after the current native baseline
has been restored and every game process has exited.
"""
from __future__ import annotations
import argparse
import copy
import json
import shutil
import sys
import winreg
from pathlib import Path

HERE = Path(__file__).absolute().parent
ROOT = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import baseline_control as bc

ACCOUNT_DIR = ROOT / "原版对照_账户76561199191371037"
SESSION = ACCOUNT_DIR / "同档对照_20261007_100115_cb21d9cf"
SOURCE = SESSION / "机房检查点_首次退出_20261007_102802_0fec3a97" / "slot3-s.save"
STATE_SHA256 = "4c0b15bbd796b141d29b4e30d7da78216daead1835fdc2a52f31fd6bdcd63df8"
AUTO_PIN = {"size": 142398, "sha256":
            "69d891dd71de75a97028d59de930656960f3b8268159921e7b490d8ee79b9747"}
ENV = bc.Environment(bc.GAME_ROOT, bc.NATIVE_PARENT, "76561199191371037",
                     ACCOUNT_DIR, bc.KNOWN_HASHES)


def safe_log(folder, event, **details):
    try:
        bc.journal(folder, event, **details)
    except Exception:
        pass  # Logging failure must never block recovery renames.


def validate(require_closed=False):
    """No writes; only this session, this account and the fixed source."""
    if bc.lexical(HERE) != bc.lexical(ACCOUNT_DIR):
        raise bc.SafetyError("脚本不在固定账户诊断目录，拒绝执行")
    bc.contained(SESSION, ACCOUNT_DIR, direct=True)
    bc.contained(SOURCE, SESSION)
    if bc.sha256(SESSION / "state.json") != STATE_SHA256:
        raise bc.SafetyError("固定会话 state.json 变化，拒绝导回")
    state, paths = bc.load_session(ENV, SESSION)
    if state["session_id"] != "20261007_100115_cb21d9cf" or state.get("source_kind") != "smt":
        raise bc.SafetyError("不是固定 100115 SMT 对照")
    if state.get("source_path") != str(ENV.saves):
        raise bc.SafetyError("SMT 原件路径不符")
    events = bc.read_events(SESSION)
    if not any(r["event"] == "restored" for r in events):
        raise bc.SafetyError("请先用 account_baseline_control restore 恢复原版环境")
    if paths["original"].exists() or paths["disabled"].exists():
        raise bc.SafetyError("原版备份或禁用代理仍在，会话尚未完成恢复")
    if bc.manifest(paths["native"]) != state["native_original_manifest"]:
        raise bc.SafetyError("1037 普通原版三个原件与原清单不符")
    if len(state["native_original_manifest"]["files"]) != 3:
        raise bc.SafetyError("普通原版原件数量不符")
    if not ENV.winmm.is_file() or bc.sha256(ENV.winmm) != ENV.known_hashes["winmm"]:
        raise bc.SafetyError("恢复后的游戏代理缺失或哈希错误")
    for name, path in (("game", ENV.game_root / "Spider-Man.exe"),
                       ("mod", ENV.game_root / "SMT" / "Scripts" / "smt.dll")):
        if bc.sha256(path) != ENV.known_hashes[name]:
            raise bc.SafetyError("游戏或核心版本变化：" + name)
    pending = [r for r in bc.sessions(ENV) if r["restore_needed"]]
    if pending:
        raise bc.SafetyError("当前账户仍有未恢复 baseline 会话")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r"Software\Valve\Steam\ActiveProcess") as key:
        active, _ = winreg.QueryValueEx(key, "ActiveUser")
    if int(active) != 1231105309:
        raise bc.SafetyError("Steam 当前账户已变化，拒绝导回")
    if SOURCE.stat().st_size != AUTO_PIN["size"] or bc.sha256(SOURCE) != AUTO_PIN["sha256"]:
        raise bc.SafetyError("固定原版自动档69与 pin 不符")
    source_manifest = bc.manifest(ENV.saves)
    if source_manifest != state["source_manifest"] or len(source_manifest["files"]) != 23:
        raise bc.SafetyError("SMT 当前23原件与本轮起点不同，拒绝覆盖")
    if bc.manifest(paths["freeze"]) != state["source_manifest"]:
        raise bc.SafetyError("本轮冻结SMT起点变化")
    ops = [r for r in events if r["event"].startswith("smt_auto69_import_")]
    if ops and ops[-1]["event"] not in {"smt_auto69_import_failed_unchanged",
                                      "smt_auto69_import_rollback_completed"}:
        raise bc.SafetyError("已有完成或未闭合导回操作，请先审查记录")
    running = bc.processes()
    if require_closed:
        bc.require_closed()
    return state, paths, source_manifest, running


def stage():
    with bc.mutation_lock(ENV):
        state, paths, before, _ = validate(require_closed=True)
        smt_parent = bc.contained(ENV.game_root / "SMT", ENV.game_root, direct=True)
        bc.contained(ENV.saves, smt_parent, direct=True)
        tag = bc.stamp()
        run = bc.contained(SESSION / ("smt_auto69_import_" + tag), SESSION, direct=True)
        staging = bc.contained(smt_parent / ("Save.codex-stage-auto69-" + tag),
                               smt_parent, direct=True)
        original = bc.contained(smt_parent / ("Save.codex-original-auto69-" + tag),
                                smt_parent, direct=True)
        failed = bc.contained(smt_parent / ("Save.codex-failed-auto69-" + tag),
                              smt_parent, direct=True)
        if any(p.exists() for p in (run, staging, original, failed)):
            raise bc.SafetyError("唯一目标已存在，拒绝覆盖")
        if len({p.drive.casefold() for p in (ENV.saves, staging, original, failed)}) != 1:
            raise bc.SafetyError("SMT 原件、暂存及回退目录不在同一卷")
        after = copy.deepcopy(before)
        after["files"]["slot3-s.save"] = dict(AUTO_PIN)
        run.mkdir()
        frozen = bc.contained(run / "SMT_before_full", run, direct=True)
        plan = {"source_auto": str(SOURCE), "source_auto_pin": AUTO_PIN,
                "paths": {"Save": str(ENV.saves), "staging": str(staging),
                          "original": str(original), "failed": str(failed),
                          "frozen_full": str(frozen)},
                "before_manifest": before, "after_manifest": after,
                "native_original_manifest": state["native_original_manifest"],
                "scope": "Replace only complete slot3-s.save; keep all other22 byte-identical"}
        bc.write_new_json(run / "plan.json", plan)
        moved = False
        installed = False
        try:
            bc.journal(SESSION, "smt_auto69_import_begin", run=str(run))
            bc.journal(run, "full_freeze_intent")
            bc.copy_verified(ENV.saves, frozen, before)
            bc.journal(run, "full_freeze_verified", manifest=before)
            bc.copy_verified(ENV.saves, staging, before)
            bc.reject_reparse(staging / "slot3-s.save")
            bc.reject_reparse(SOURCE)
            shutil.copy2(SOURCE, staging / "slot3-s.save")
            if bc.manifest(staging) != after or bc.sha256(SOURCE) != AUTO_PIN["sha256"]:
                raise bc.SafetyError("暂存候选或其他22文件双重核验失败")
            if bc.manifest(ENV.saves) != before or bc.manifest(frozen) != before:
                raise bc.SafetyError("复制期间SMT原件或冻结副本变化")
            # Recheck process/account/original native files before activation.
            # Own import_begin is intentionally excluded from this second guard.
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Valve\Steam\ActiveProcess") as key:
                active, _ = winreg.QueryValueEx(key, "ActiveUser")
            if int(active) != 1231105309:
                raise bc.SafetyError("复制期间Steam账户变化")
            bc.require_closed()
            if bc.manifest(paths["native"]) != state["native_original_manifest"]:
                raise bc.SafetyError("复制期间普通原版原件变化")
            if paths["original"].exists() or paths["disabled"].exists() or \
                    bc.sha256(ENV.winmm) != ENV.known_hashes["winmm"]:
                raise bc.SafetyError("复制期间原版环境变化")
            bc.journal(run, "preserve_Save_intent")
            bc.rename_preserving(ENV.saves, original)
            moved = True
            if bc.manifest(original) != before:
                raise bc.SafetyError("D卷原Save保存后清单不符")
            bc.require_closed()
            bc.journal(run, "install_stage_intent")
            bc.rename_preserving(staging, ENV.saves)
            installed = True
            bc.require_closed()
            if bc.manifest(ENV.saves) != after or bc.manifest(original) != before or \
                    bc.manifest(frozen) != before or bc.sha256(SOURCE) != AUTO_PIN["sha256"]:
                raise bc.SafetyError("导回完成前全清单复核失败")
            bc.write_new_json(run / "installed_manifest.json",
                              {"SMT_after": bc.manifest(ENV.saves),
                               "SMT_original_D": bc.manifest(original),
                               "SMT_frozen_C": bc.manifest(frozen)})
            bc.journal(run, "installed_verified")
            bc.journal(SESSION, "smt_auto69_import_complete", run=str(run))
        except BaseException as exc:
            safe_log(run, "import_failed", error=str(exc))
            recovery_error = None
            try:
                # Detect completed atomic renames even if interrupted before flags.
                if original.exists():
                    moved = True
                if moved:
                    bc.require_closed()
                    if bc.manifest(original) != before:
                        raise bc.SafetyError("原Save保存目录变化，拒绝自动回退")
                    if ENV.saves.exists():
                        if not installed and not staging.exists():
                            installed = bc.manifest(ENV.saves) == after
                        if not installed:
                            raise bc.SafetyError("Save被外部重新创建，拒绝移动未知目录")
                        current = bc.manifest(ENV.saves)
                        safe_log(run, "failed_candidate_preserve_intent", manifest=current)
                        bc.rename_preserving(ENV.saves, failed)
                        safe_log(run, "failed_candidate_preserved")
                    safe_log(run, "rollback_intent")
                    bc.rename_preserving(original, ENV.saves)
                    if bc.manifest(ENV.saves) != before:
                        raise bc.SafetyError("回退后SMT清单不符")
                    safe_log(run, "rollback_verified")
                    safe_log(SESSION, "smt_auto69_import_rollback_completed", run=str(run))
                else:
                    safe_log(SESSION, "smt_auto69_import_failed_unchanged", run=str(run))
            except BaseException as recovery:
                recovery_error = recovery
                safe_log(run, "rollback_blocked", error=str(recovery))
                safe_log(SESSION, "smt_auto69_import_rollback_blocked", run=str(run))
            if recovery_error:
                raise bc.SafetyError("导回失败且回退受阻；所有文件保留，请关闭游戏审查："
                                     + str(run / "plan.json") + "\n原因：" + str(exc)
                                     + "\n回退：" + str(recovery_error)) from exc
            raise bc.SafetyError("导回未完成；SMT原目录已保持或恢复，文件均保留："
                                 + str(exc) + "\n记录：" + str(run)) from exc
        print("仅完整slot3自动档69已导回；MOD重载与剧情推进仍需实测。")
        print("D卷原件回退目录：" + str(original))
        print("C卷完整冻结/操作清单：" + str(run))


def main():
    parser = argparse.ArgumentParser(description="固定auto69完整文件导回SMT槽位4")
    parser.add_argument("command", choices=["check", "stage"])
    args = parser.parse_args()
    try:
        if args.command == "stage":
            stage()
        else:
            state, paths, manifest, running = validate()
            print(json.dumps({"read_only": True, "can_stage_now": not running,
                "running_processes": running, "source_auto": str(SOURCE),
                "source_auto_pin": AUTO_PIN, "SMT_original_manifest": manifest,
                "native_original": str(paths["native"]),
                "slot3_only": True, "other22_unchanged": True},
                ensure_ascii=False, indent=2))
        return 0
    except (bc.SafetyError, OSError, ValueError, KeyError) as exc:
        print("未完成：" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
