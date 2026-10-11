"""Scoped same-save comparison for the currently verified Steam account.

Uses the existing backup/manifest/recovery implementation unchanged. Sessions
stay in this directory so older account sessions retain their original paths.
"""
from pathlib import Path
import sys
import winreg

THIS_DIR = Path(__file__).absolute().parent
sys.path.insert(0, str(THIS_DIR.parent))
import baseline_control as baseline

OLD_ENV = baseline.ENV
ACCOUNT_ID = "76561199191371037"
ACCOUNT_ID32 = 1231105309
baseline.ENV = baseline.Environment(
    OLD_ENV.game_root, OLD_ENV.native_parent, ACCOUNT_ID,
    THIS_DIR, OLD_ENV.known_hashes,
)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "prepare":
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Valve\Steam\ActiveProcess") as key:
                active, _ = winreg.QueryValueEx(key, "ActiveUser")
            if active != ACCOUNT_ID32:
                raise baseline.SafetyError("Steam 当前账户已变化；请重新核对，拒绝准备副本")
            baseline.require_closed()
            pending = [s for s in baseline.sessions(OLD_ENV) if s["restore_needed"]]
            if pending:
                raise baseline.SafetyError("旧账户还有未恢复的对照；拒绝同时禁用代理")
        except (OSError, baseline.SafetyError) as exc:
            print(f"未完成：{exc}", file=sys.stderr)
            return 1
    return baseline.main()


if __name__ == "__main__":
    raise SystemExit(main())
