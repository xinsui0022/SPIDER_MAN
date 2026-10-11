"""Fixed e80 candidate switch for account 1037 / session 100115 only.

check is read-only. stage requires game closed and holds the same account-level
lock as account_baseline_control. It preserves every directory and performs no
save-field edits. Native account originals are restored only by the baseline
restore helper, never by this candidate switch.
"""
from __future__ import annotations
import argparse
import json
import sys
import winreg
from pathlib import Path

THIS_DIR = Path(__file__).absolute().parent
ROOT = THIS_DIR.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import baseline_control as bc

ACCOUNT_ID = "76561199191371037"
ACCOUNT_ID32 = 1231105309
SESSION_ID = "20261007_100115_cb21d9cf"
EXPECTED_ACCOUNT_DIR = ROOT / "原版对照_账户76561199191371037"
SESSION = EXPECTED_ACCOUNT_DIR / ("同档对照_" + SESSION_ID)
SOURCE = ROOT / "联机NG对照_20261006_155424_9e9669ed" / "MOD二次载入后_已暂停"
STATE_SHA256 = "4c0b15bbd796b141d29b4e30d7da78216daead1835fdc2a52f31fd6bdcd63df8"
INITIAL_SLOT3_SHA256 = "7c69f619ae0271012c287ccee5a76703fc2cd22e5731bdd98f891b35bcdde475"
PINNED_MANIFEST = {'directories': [],
 'files': {'-userprefs.save': {'sha256': '1fcd7d8cc1180051eb3489ef0f23eae4d7a566247742db1d32edcca92ec5b292',
                               'size': 1476},
           'SMT_SAVE_BACKUP (2).save': {'sha256': '89677dcb78ae6bc763b0ee448bdc2865ae68862d075d46a7600fe92fa12133da',
                                        'size': 138254},
           'SMT_SAVE_BACKUP (3).save': {'sha256': 'd363e6aa65edc8b033e2e1181267872fe1589853e2638411a6306c5c4d5ce473',
                                        'size': 142830},
           'SMT_SAVE_BACKUP.save': {'sha256': '8fa5a5922414fb5d573e3ae49a2e3be139b1808d6fa8647398bc6774e6d93a5e',
                                    'size': 138654},
           'slot0-s-manual-0.save': {'sha256': 'b7dfa63f81649bb7de6dc567c2a1a2311311068d8a3ec26db926077012f3b4b7',
                                     'size': 138686},
           'slot0-s-manual-1.save': {'sha256': 'ae429a673bad76d41cebd4047e90f707537a79540eec9207727535ae29dc75d4',
                                     'size': 136606},
           'slot0-s-manual-2.save': {'sha256': '4bd9bb55f1793ec15739fe36d68fdc80085dd52a96b159b55890c16483ccdfa0',
                                     'size': 146702},
           'slot0-s-manual-3.save': {'sha256': '2f7e971a2fb32e1f9ea77714088e5c0e0a818ee9336f4b1dd6d11bb558b7946f',
                                     'size': 146702},
           'slot0-s-manual-4.save': {'sha256': 'b85a91d1556d470cdc9c3da95d0bd9803535715e2234c2333f353a82ade25c9a',
                                     'size': 150846},
           'slot0-s.save': {'sha256': 'ef63493b8677f9ad5637f902586f8b2fa44a6ef5681b685e4f10892ea2bd8549',
                            'size': 157390},
           'slot0-s.save.backup01': {'sha256': 'f6e0aef114f5e2a15328bbefb97340e8036c8acdad67f4668e1dc01ee277bcb7',
                                     'size': 150766},
           'slot0-s.save.backup02': {'sha256': '19f54a65d739584927d709630d61ed9558938afa54c3c7cd776f4673227336c1',
                                     'size': 150126},
           'slot0-s.save.backup03': {'sha256': '95132c8edd00d80d7420fa2c3985ca5c5f4feee5250dd22d996bc69962ab6624',
                                     'size': 150126},
           'slot0-s.save.backup04': {'sha256': '93920496c9f86fecc82a69a7acfa18cd1ee2f3798f2353622c2d669374723916',
                                     'size': 150126},
           'slot0-s.save.backup05': {'sha256': 'fd818054be2b898988fb690d526a28be5d2b172837b99314b2fefb292e599de7',
                                     'size': 150366},
           'slot0-s.save.backup06': {'sha256': '4d343448389a141075dae118ead9ea7713bd213ed45b1a88366588539ab7942c',
                                     'size': 149182},
           'slot1-s-manual-0.save': {'sha256': 'acc9158a16603a8a0eeb0f23e67563f1d943067bfb576069dd0e319f69755bd9',
                                     'size': 93566},
           'slot1-s-manual-1.save': {'sha256': 'bcc27c8238923052c35d9245cddb5b0d415f5fd11bfa83769995d901c3622866',
                                     'size': 93198},
           'slot1-s.save': {'sha256': 'e88daa5f89a56e37662e82845ebccb980c4fe704dad1ee2eebccfdbdc80c8658',
                            'size': 141502},
           'slot2-s.save': {'sha256': '494987e4a81c45b38763e615f47ab474ef4f388e4f84e661849ba371952e6c2b',
                            'size': 67008},
           'slot3-s.save': {'sha256': 'e80e50fd9758604584be33fd22c7c08e1eff82e9b9ae4f84c3f26aab8f8eee3d',
                            'size': 142974},
           'slot4-s.save': {'sha256': 'c776c1c4a3b025c8db874337a264c2ba6d19a437a6ffade2d51a1adc03fec16b',
                            'size': 93918},
           'slot5-s.save': {'sha256': '5265092b9cc69dc4169989b49a4f70447f1656a3c1cf4b0a4ad79c04e6408c28',
                            'size': 66992}}}
PINNED_NATIVE_ORIGINAL = {'directories': [],
 'files': {'-userprefs.save': {'sha256': 'f988b8bb4aecd6b828328126e2ed80434bdb0910bb1ffd4879f5c061ff11f0e9',
                               'size': 1460},
           'slot0-s.save': {'sha256': '5decc6e11f1f5fd5b762138e30134aa40a9c2eb01327a5473cc7ba49c656279c',
                            'size': 94286},
           'steam_autocloud.vdf': {'sha256': 'd60f68325684c093672e51b31f287e8181ddbac53faff5a7dee9ae0bb03c55fe',
                                   'size': 53}}}
ENV = bc.Environment(bc.GAME_ROOT, bc.NATIVE_PARENT, ACCOUNT_ID,
                     EXPECTED_ACCOUNT_DIR, bc.KNOWN_HASHES)

TERMINAL_FAILURES = {"e80_switch_failed_no_native_changes", "e80_switch_rollback_completed"}
FORBIDDEN_BASELINE_EVENTS = {
    "restored", "native_restore_intent", "native_restored",
    "winmm_restore_intent", "winmm_restored", "preserve_test_intent",
    "test_preserved", "prepare_failed", "rollback_completed", "rollback_failed",
}


def stage_status():
    attempts = [r for r in bc.read_events(SESSION)
                if r["event"].startswith("e80_switch_")]
    if not attempts:
        return "not_started"
    event = attempts[-1]["event"]
    if event in TERMINAL_FAILURES:
        return "previous_attempt_rolled_back"
    if event == "e80_switch_complete":
        return "already_complete"
    return "incomplete_attempt_requires_review"


def validate(*, require_closed=False, ignore_attempt=False, native_required=True):
    """Read fixed paths and pinned manifests; this function has no file writes."""
    if bc.lexical(THIS_DIR) != bc.lexical(EXPECTED_ACCOUNT_DIR):
        raise bc.SafetyError("脚本仅可在固定账户诊断目录运行，拒绝复制后改路径使用")
    bc.contained(SESSION, EXPECTED_ACCOUNT_DIR, direct=True)
    bc.contained(SOURCE, ROOT)
    if bc.sha256(SESSION / "state.json") != STATE_SHA256:
        raise bc.SafetyError("原始会话 state.json 已变化，拒绝候选切换")
    state, paths = bc.load_session(ENV, SESSION)
    if state["session_id"] != SESSION_ID or state.get("source_kind") != "smt":
        raise bc.SafetyError("会话或来源不是固定 100115 SMT 对照")
    if state.get("source_path") != str(ENV.saves):
        raise bc.SafetyError("SMT 来源路径不符")
    if state["native_original_manifest"] != PINNED_NATIVE_ORIGINAL:
        raise bc.SafetyError("原版三个原件的固定清单不符")
    if state["source_manifest"]["files"]["slot3-s.save"]["sha256"] != INITIAL_SLOT3_SHA256:
        raise bc.SafetyError("本轮初始 slot3 清单不符")
    events = bc.read_events(SESSION)
    prepared = [i for i, r in enumerate(events) if r["event"] == "prepared"]
    if not prepared or any(r["event"] in FORBIDDEN_BASELINE_EVENTS
                           for r in events[prepared[-1] + 1:]):
        raise bc.SafetyError("会话不是尚未恢复的 prepared 对照")
    attempt = stage_status()
    if not ignore_attempt and attempt not in {"not_started", "previous_attempt_rolled_back"}:
        raise bc.SafetyError("已有完成或未闭合候选操作，拒绝再次切换：" + attempt)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r"Software\Valve\Steam\ActiveProcess") as key:
        active, _ = winreg.QueryValueEx(key, "ActiveUser")
    if int(active) != ACCOUNT_ID32:
        raise bc.SafetyError("Steam 当前账户不是固定 1037，拒绝切换")
    running = bc.processes()
    if require_closed:
        bc.require_closed()
    original = bc.manifest(paths["original"])
    if original != PINNED_NATIVE_ORIGINAL:
        raise bc.SafetyError("1037 原版原件备份发生变化")
    if not paths["disabled"].is_file() or bc.sha256(paths["disabled"]) != ENV.known_hashes["winmm"]:
        raise bc.SafetyError("本轮 disabled 代理缺失或哈希错误")
    if ENV.winmm.exists():
        raise bc.SafetyError("游戏目录 winmm.dll 已出现，拒绝切换")
    for name, f in (("game", ENV.game_root / "Spider-Man.exe"),
                    ("mod", ENV.game_root / "SMT" / "Scripts" / "smt.dll")):
        if bc.sha256(f) != ENV.known_hashes[name]:
            raise bc.SafetyError("原始游戏或核心版本发生变化：" + name)
    source = bc.manifest(SOURCE)
    if source != PINNED_MANIFEST:
        raise bc.SafetyError("e80 全部 23 个源文件与固定清单不符")
    smt = bc.manifest(ENV.saves)
    frozen = bc.manifest(paths["freeze"])
    if smt != state["source_manifest"] or frozen != state["source_manifest"]:
        raise bc.SafetyError("SMT 原件或本轮冻结输入发生变化")
    native = None
    if native_required:
        native = bc.manifest(paths["native"])
        if "slot3-s.save" not in native["files"]:
            raise bc.SafetyError("当前 native 测试目录缺 slot3，拒绝移动")
    return {"session": str(SESSION), "source": str(SOURCE),
            "paths": {k: str(v) for k, v in paths.items()},
            "running_processes": running, "game_closed": not running,
            "stage_status": attempt, "source_manifest": source,
            "native_original_manifest": original, "SMT_manifest": smt,
            "frozen_manifest": frozen, "native_test_manifest": native,
            "candidate_slot3": PINNED_MANIFEST["files"]["slot3-s.save"],
            "read_only": True}


def best_effort_journal(folder, event, **data):
    try:
        bc.journal(folder, event, **data)
    except Exception:
        pass  # Never hide the original error or suppress rollback attempts.


def stage():
    with bc.mutation_lock(ENV):
        before = validate(require_closed=True)
        paths = {k: Path(v) for k, v in before["paths"].items()}
        run = bc.contained(SESSION / ("e80_candidate_switch_" + bc.stamp()),
                           SESSION, direct=True)
        if run.exists():
            raise bc.SafetyError("唯一操作目录已存在，拒绝覆盖")
        run.mkdir()
        staging = bc.contained(run / "candidate_staging", run, direct=True)
        retained = bc.contained(run / "native_test_before", run, direct=True)
        failed = bc.contained(run / "candidate_failed_native", run, direct=True)
        if any(p.exists() for p in (staging, retained, failed)):
            raise bc.SafetyError("唯一目标已存在，拒绝覆盖")
        if paths["native"].drive.casefold() != run.drive.casefold():
            raise bc.SafetyError("测试原目录与保存目录不在同一卷，拒绝移动")
        plan = {"scope": "Fixed account1037/session100115; no native-original restore",
                "state_sha256": STATE_SHA256, "run": str(run),
                "paths": {"source": str(SOURCE), "native": str(paths["native"]),
                          "staging": str(staging), "retained_test": str(retained),
                          "failed_candidate": str(failed)},
                "candidate_manifest": PINNED_MANIFEST,
                "native_before_manifest": before["native_test_manifest"],
                "native_original_manifest": PINNED_NATIVE_ORIGINAL,
                "SMT_source_manifest": before["SMT_manifest"]}
        bc.write_new_json(run / "plan.json", plan)
        native_moved = False
        candidate_installed = False
        try:
            bc.journal(SESSION, "e80_switch_begin", run=str(run))
            bc.journal(run, "candidate_copy_intent")
            bc.copy_verified(SOURCE, staging, PINNED_MANIFEST)
            # copy_verified already hashes source and destination; repeat before moving.
            if bc.manifest(staging) != PINNED_MANIFEST or bc.manifest(SOURCE) != PINNED_MANIFEST:
                raise bc.SafetyError("候选副本第二轮双重哈希核验失败")
            bc.journal(run, "candidate_copy_double_verified",
                       candidate_manifest=PINNED_MANIFEST)
            again = validate(require_closed=True, ignore_attempt=True)
            if again["native_test_manifest"] != before["native_test_manifest"]:
                raise bc.SafetyError("复制期间 native 测试目录变化，拒绝移动")
            bc.journal(run, "native_preserve_intent", source=str(paths["native"]),
                       destination=str(retained))
            bc.rename_preserving(paths["native"], retained)
            native_moved = True
            if bc.manifest(retained) != before["native_test_manifest"]:
                raise bc.SafetyError("原测试目录移入保存位置后哈希核验失败")
            bc.journal(run, "native_preserved")
            validate(require_closed=True, ignore_attempt=True, native_required=False)
            if paths["native"].exists():
                raise bc.SafetyError("native 路径意外重新出现，拒绝覆盖")
            bc.journal(run, "candidate_install_intent")
            bc.rename_preserving(staging, paths["native"])
            candidate_installed = True
            final = validate(require_closed=True, ignore_attempt=True)
            if final["native_test_manifest"] != PINNED_MANIFEST:
                raise bc.SafetyError("安装后 native 23 文件候选哈希不符")
            if bc.manifest(retained) != before["native_test_manifest"]:
                raise bc.SafetyError("保存的原测试目录变化")
            bc.write_new_json(run / "installed_manifest.json",
                              {"native_candidate": final["native_test_manifest"],
                               "retained_test": bc.manifest(retained),
                               "source": bc.manifest(SOURCE),
                               "SMT": final["SMT_manifest"],
                               "native_original": final["native_original_manifest"]})
            bc.journal(run, "candidate_installed_verified")
            bc.journal(SESSION, "e80_switch_complete", run=str(run),
                       native_slot3=PINNED_MANIFEST["files"]["slot3-s.save"])
        except BaseException as exc:
            best_effort_journal(run, "candidate_switch_failed", error=str(exc),
                                native_moved=native_moved,
                                candidate_installed=candidate_installed)
            rollback_error = None
            try:
                # A cancellation can arrive just after an atomic rename returns,
                # before its Python flag assignment. Reserved paths and hashes
                # remain the authority for deciding whether rollback is needed.
                if retained.exists():
                    native_moved = True
                if native_moved:
                    bc.require_closed()
                    if bc.manifest(retained) != before["native_test_manifest"]:
                        raise bc.SafetyError("原测试保存目录不匹配，拒绝自动回退")
                    if paths["native"].exists():
                        if not candidate_installed and not staging.exists():
                            candidate_installed = bc.manifest(paths["native"]) == PINNED_MANIFEST
                        if not candidate_installed:
                            raise bc.SafetyError("native 路径被外部重新创建，拒绝移动未知目录")
                        current = bc.manifest(paths["native"])
                        bc.journal(run, "failed_candidate_preserve_intent", manifest=current)
                        bc.rename_preserving(paths["native"], failed)
                        bc.journal(run, "failed_candidate_preserved")
                    bc.journal(run, "test_rollback_intent")
                    bc.rename_preserving(retained, paths["native"])
                    if bc.manifest(paths["native"]) != before["native_test_manifest"]:
                        raise bc.SafetyError("回退原测试目录后清单不符")
                    bc.journal(run, "test_rollback_verified")
                    bc.journal(SESSION, "e80_switch_rollback_completed", run=str(run))
                else:
                    bc.journal(SESSION, "e80_switch_failed_no_native_changes", run=str(run))
            except BaseException as recovery:
                rollback_error = recovery
                best_effort_journal(run, "test_rollback_blocked", error=str(recovery))
                best_effort_journal(SESSION, "e80_switch_rollback_blocked",
                                    run=str(run), error=str(recovery))
            if rollback_error:
                raise bc.SafetyError(
                    "候选切换失败，自动回退未完成。全部文件均保留；请先关闭游戏并检查固定计划："
                    + str(run / "plan.json") + "\n失败：" + str(exc)
                    + "\n回退受阻：" + str(rollback_error)) from exc
            raise bc.SafetyError("候选切换未完成，原测试目录已保留或回退；未删任何文件："
                                 + str(exc) + "\n记录：" + str(run)) from exc
        print("已在 native 测试目录安装完整 e80 候选；尚未验证游戏任务推进。")
        print("原测试结果保留：" + str(retained))
        print("完整操作清单：" + str(run / "plan.json"))
        print("1037 原版三个原件仍由 account_baseline_control restore 恢复。")


def main():
    cli = argparse.ArgumentParser(description="固定范围 e80 完整副本切换助手")
    cli.add_argument("command", choices=["check", "stage"])
    args = cli.parse_args()
    try:
        if args.command == "check":
            report = validate()
            report["can_stage_now"] = report["game_closed"]
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            stage()
        return 0
    except (bc.SafetyError, OSError, ValueError, KeyError) as exc:
        print("未完成：" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
