"""Prepare a reversible vanilla NG+ reference test; never edit save fields."""
from pathlib import Path
import argparse
import json
import shutil
import struct
import sys

import baseline_control as bc

REFERENCE = bc.DIAG_ROOT / 'NG初始化测试档_20261006' / 'slot3-s.save'
EXPECTED = 'ae64678c0e02ccba5b2721770af3d08cdbc0810866421232349e09e97835e7d5'


def check_reference():
    bc.contained(REFERENCE, bc.DIAG_ROOT)
    if bc.sha256(REFERENCE) != EXPECTED:
        raise bc.SafetyError('原版 NG+ 初始参考档哈希不符；拒绝准备')
    data = REFERENCE.read_bytes()
    if len(data) != 143038 or struct.unpack_from('<4I', data) != (0x44415431, 8, 143038, 28):
        raise bc.SafetyError('参考档结构不符；拒绝准备')


def prepare():
    check_reference()
    bc.require_closed()
    with bc.mutation_lock(bc.ENV):
        if any(s['restore_needed'] for s in bc.sessions(bc.ENV)):
            raise bc.SafetyError('已有待恢复的测试；请先恢复联机环境')
        smt_before = bc.manifest(bc.ENV.saves)
        bc.prepare(bc.ENV, 'native')
        active = [s for s in bc.sessions(bc.ENV) if s['restore_needed']]
        if len(active) != 1:
            raise bc.SafetyError('新会话数量异常；保留备份，不继续替换')
        session = Path(active[0]['session'])
        try:
            bc.require_closed()
            state, paths = bc.load_session(bc.ENV, session)
            target = bc.contained(paths['native'] / 'slot3-s.save', paths['native'], direct=True)
            reference_copy = session / '用于对照_原版NG初始档.save'
            if reference_copy.exists():
                raise bc.SafetyError('参考副本目标已存在；拒绝覆盖')
            shutil.copy2(REFERENCE, reference_copy)
            if bc.sha256(reference_copy) != EXPECTED:
                raise bc.SafetyError('参考副本哈希失败')
            bc.write_new_json(session / '原版NG测试来源.json', {
                'purpose': '原版初始化档在完全无 MOD 环境推进、退出、重载；区分持久化故障',
                'source_path': str(REFERENCE), 'source_sha256': EXPECTED,
                'source_size': 143038, 'target_slot': 'slot3-s.save',
                'previous_test_slot_sha256': bc.sha256(target) if target.exists() else None,
                'smt_original_manifest': smt_before,
                'live_runtime_observation': '尚未开始，不将准备完成计为验证通过',
            })
            bc.journal(session, 'native_ng_reference_copy_intent', source=str(reference_copy),
                       target=str(target), source_sha256=EXPECTED)
            shutil.copy2(reference_copy, target)
            if bc.sha256(target) != EXPECTED or bc.manifest(bc.ENV.saves) != smt_before:
                raise bc.SafetyError('复制核验或 SMT 原件核验失败')
            if bc.manifest(paths['original']) != state['native_original_manifest']:
                raise bc.SafetyError('普通原档备份核验失败')
            bc.journal(session, 'native_ng_reference_verified', sha256=EXPECTED)
        except Exception as error:
            bc.journal(session, 'native_ng_reference_failed', error=str(error))
            bc.require_closed()
            bc.restore_files(bc.ENV, session)
            raise bc.SafetyError(f'准备失败并已恢复原环境：{error}') from error
    print('\n原版 NG+ 参考测试已准备：请选择设定档4（50级 NG+、0%），再继续。')
    print('请直接运行原游戏。完成摆荡和街头战斗，正常退出后重进同一设定档。')
    print('这是独立测试副本，现有联机存档未覆盖，不能视作已修复。')
    print('结果保留目录：' + str(session))
    print('测试后关闭游戏并运行“恢复联机环境.cmd”。')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    try:
        check_reference()
        if args.prepare:
            prepare()
        else:
            print(json.dumps({'reference_sha256': EXPECTED, 'size': REFERENCE.stat().st_size,
                              'mode': '只读核验；准备测试需 --prepare',
                              'processes': bc.processes(), 'sessions': bc.sessions(bc.ENV)},
                             ensure_ascii=False, indent=2))
    except (bc.SafetyError, OSError, ValueError, KeyError) as error:
        print('未完成：' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
