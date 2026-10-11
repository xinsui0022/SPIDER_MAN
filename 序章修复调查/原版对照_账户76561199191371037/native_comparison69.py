"""Fixed, reversible replacement of the isolated 110827 native test auto only."""
import copy
import json
from pathlib import Path
import shutil
import sys
import winreg

HERE = Path(__file__).absolute().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent))
import baseline_control as bc

ENV = bc.Environment(bc.GAME_ROOT, bc.NATIVE_PARENT, '76561199191371037', HERE, bc.KNOWN_HASHES)
SESSION = HERE / '同档对照_20261007_110827_188252fd'
SOURCE = HERE / '同档对照_20261007_100115_cb21d9cf' / '机房检查点_首次退出_20261007_102802_0fec3a97' / 'slot3-s.save'
STATE_PIN = '7fff26bd23d16c578a7474e55d08748af8b316044745d65b3f61c3708b024014'
AUTO_PIN = {'size': 142398, 'sha256': '69d891dd71de75a97028d59de930656960f3b8268159921e7b490d8ee79b9747'}
CLOSED_NATIVE_PIN = 'd4f8c0f39a39c5357b6c51c272ee248c178a85e654a19d073575685787e8ce79'
SMT_PIN = '20196723940a8d1d4e392e2acbd1ef520bdf2be8e4bd4fb69b5b6a31c7884e7a'


def safe_log(folder, event, **values):
    try:
        bc.journal(folder, event, **values)
    except Exception:
        pass


def guard():
    bc.require_closed()
    bc.contained(SESSION, HERE, direct=True)
    bc.contained(SOURCE, HERE)
    if bc.sha256(SESSION / 'state.json') != STATE_PIN:
        raise bc.SafetyError('110827 state changed')
    state, paths = bc.load_session(ENV, SESSION)
    events = bc.read_events(SESSION)
    if events[-1]['event'] != 'prepared':
        raise bc.SafetyError('Not the untouched prepared 110827 test')
    if bc.manifest(paths['original']) != state['native_original_manifest']:
        raise bc.SafetyError('Ordinary original backup differs')
    if ENV.winmm.exists() or bc.sha256(paths['disabled']) != ENV.known_hashes['winmm']:
        raise bc.SafetyError('Proxy is not verifiably disabled')
    if bc.manifest(ENV.saves) != state['source_manifest'] or bc.manifest(paths['freeze']) != state['source_manifest']:
        raise bc.SafetyError('SMT201 source/freeze changed')
    if bc.sha256(ENV.saves / 'slot3-s.save') != SMT_PIN:
        raise bc.SafetyError('SMT201 wrong auto')
    if SOURCE.stat().st_size != AUTO_PIN['size'] or bc.sha256(SOURCE) != AUTO_PIN['sha256']:
        raise bc.SafetyError('Native69 source changed')
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam\ActiveProcess') as key:
        account, _ = winreg.QueryValueEx(key, 'ActiveUser')
    if int(account) != 1231105309:
        raise bc.SafetyError('Steam account changed')
    before = bc.manifest(paths['native'])
    if before['files']['slot3-s.save']['sha256'] != CLOSED_NATIVE_PIN:
        raise bc.SafetyError('Closed native test auto changed')
    return state, paths, before


def main():
    with bc.mutation_lock(ENV):
        state, paths, before = guard()
        run = bc.contained(SESSION / ('native69_comparison_' + bc.stamp()), SESSION, direct=True)
        run.mkdir()
        stage = bc.contained(run / 'native_stage', run, direct=True)
        old = bc.contained(run / 'native_before', run, direct=True)
        failed = bc.contained(run / 'native_failed_candidate', run, direct=True)
        native = bc.contained(paths['native'], ENV.native_parent, direct=True)
        if len({p.drive.casefold() for p in (native, stage, old, failed)}) != 1:
            raise bc.SafetyError('Swap is not on the same volume')
        after = copy.deepcopy(before)
        after['files']['slot3-s.save'] = dict(AUTO_PIN)
        bc.write_new_json(run / 'plan.json', {
            'native': str(native), 'preserved': str(old), 'stage': str(stage),
            'failed': str(failed), 'source_auto': str(SOURCE),
            'before': before, 'after': after,
            'scope': 'Only full slot3 in isolated native test; SMT201 and ordinary originals untouched'})
        bc.copy_verified(native, stage, before)
        bc.reject_reparse(stage / 'slot3-s.save')
        shutil.copy2(SOURCE, stage / 'slot3-s.save')
        if bc.manifest(stage) != after:
            raise bc.SafetyError('Stage differs from slot3-only plan')
        guard()
        if bc.manifest(native) != before:
            raise bc.SafetyError('Native test changed during copy')
        moved = False
        installed = False
        try:
            bc.rename_preserving(native, old)
            moved = True
            bc.require_closed()
            bc.rename_preserving(stage, native)
            installed = True
            bc.require_closed()
            if bc.manifest(native) != after or bc.manifest(old) != before:
                raise bc.SafetyError('Post-swap manifests differ')
            if bc.manifest(ENV.saves) != state['source_manifest'] or bc.manifest(paths['original']) != state['native_original_manifest']:
                raise bc.SafetyError('Protected originals changed')
            bc.write_new_json(run / 'installed.json', {'native_after': after, 'preserved_before': before})
            bc.journal(SESSION, 'native69_comparison_staged', run=str(run))
        except BaseException:
            if old.exists():
                moved = True
            if moved:
                bc.require_closed()
                if bc.manifest(old) != before:
                    raise bc.SafetyError('Preserved native changed; review plan')
                if native.exists():
                    if not installed and not stage.exists():
                        installed = bc.manifest(native) == after
                    if not installed:
                        raise bc.SafetyError('Unknown native directory; review plan')
                    bc.rename_preserving(native, failed)
                bc.rename_preserving(old, native)
                safe_log(SESSION, 'native69_comparison_rollback', run=str(run))
            raise
        print(json.dumps({'staged': True, 'run': str(run), 'native_count': len(after['files']),
                          'only_changed_file': 'slot3-s.save', 'auto': AUTO_PIN,
                          'SMT_untouched': True, 'ordinary_originals_preserved': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
