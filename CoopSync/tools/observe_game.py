"""Read-only game bridge: reports task observations, never claims scene readiness."""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT.parent / '序章修复调查' / 'observe_missions.py'


def load_helper():
    spec = importlib.util.spec_from_file_location('audited_mission_reader', HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError('Audited read-only mission observer is missing')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_tasks(raw):
    """Only stable task identifiers/state, not pointers or complete world data."""
    tasks = []
    for mission in raw.get('missions', []):
        if not mission.get('listed'):
            continue
        tasks.append(dict(mission_id_raw=mission.get('mission_id_raw'),
                          mission_name_raw=mission.get('mission_name_raw'),
                          state_raw=mission.get('state_raw'),
                          objectives=[dict(name_raw=o.get('name_raw'), state_raw=o.get('state_raw'))
                                      for o in mission.get('objectives', [])]))
    return sorted(tasks, key=lambda t: t.get('mission_id_raw') or '')


def sample(helper, verification):
    pids = [pid for pid, name in helper.inventory() if name.lower() == 'spider-man.exe']
    if len(pids) > 1:
        raise RuntimeError('Multiple Spider-Man processes; observation is ambiguous')
    if not pids:
        verification.clear()
        return dict(status='waiting_for_game', game_attached=False)
    pid = pids[0]
    modules = helper.inventory(pid)
    game = next(m for m in modules if m[0].lower() == 'spider-man.exe')
    smt = next((m for m in modules if m[0].lower() == 'smt.dll'), None)
    files = [game] + ([smt] if smt else [])
    signature = tuple((pid, module[2], module[1], Path(module[1]).stat().st_size,
                       Path(module[1]).stat().st_mtime_ns) for module in files)
    if verification.get('signature') != signature:
        if helper.sha256(game[1]) != helper.GAME_HASH:
            raise RuntimeError('Unsupported game hash; refusing fixed-address reads')
        if smt and helper.sha256(smt[1]) != helper.MOD_HASH:
            raise RuntimeError('Unsupported SMT hash; refusing fixed-address reads')
        verification['signature'] = signature
    reader = helper.Reader(pid)
    try:
        raw = helper.capture(reader, game[2], smt[2] if smt else None, {})
    finally:
        reader.close()
    tasks = canonical_tasks(raw)
    digest = hashlib.sha256(json.dumps(tasks, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    return dict(status=raw.get('status', 'task_observation_available'), game_attached=True,
                pid=pid, game_sha256=helper.GAME_HASH, smt_loaded=bool(smt),
                tasks=tasks, task_subset_sha256=digest)


def envelope(data):
    return dict(schema=1, utc=datetime.now(timezone.utc).isoformat(),
                monotonic_ms=int(time.monotonic() * 1000),
                process_access='read_only', game_operations=False,
                scene_ready_verified=False, cinematic_id=None, full_world_digest=None,
                limitations='Task subset only; not a scene-ready signal or complete world snapshot', **data)


def self_check(helper):
    sentinel = ctypes.create_string_buffer(b'COOPSYNC_READ_ONLY_BRIDGE')
    reader = helper.Reader(os.getpid())
    try:
        assert reader.read(ctypes.addressof(sentinel), len(sentinel)) == sentinel.raw
    finally:
        reader.close()
    raw = dict(missions=[dict(listed=True, object='private_pointer', mission_id_raw='0x1234',
        mission_name_raw='TEST', state_raw=2, objectives=[dict(name_raw='TEST_START', state_raw=1)])])
    tasks = canonical_tasks(raw)
    assert tasks[0]['mission_name_raw'] == 'TEST' and 'object' not in tasks[0]
    assert envelope({})['scene_ready_verified'] is False
    print('PASS: read-only process access and task-subset bridge limitations')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Read one observation and exit')
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--output', type=Path, default=ROOT / 'logs' / 'game_observer.jsonl')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('seconds must be in 1..600')
    helper = load_helper()
    if args.self_check:
        self_check(helper)
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    previous = None
    verification = {}
    started = time.monotonic()
    with args.output.open('w', encoding='utf-8', buffering=1) as output:
        while True:
            try:
                data = sample(helper, verification)
            except Exception as exc:
                row = envelope(dict(status='observation_refused', reason=str(exc), game_attached=False))
                output.write(json.dumps(row, ensure_ascii=False) + '\n')
                print(json.dumps(row, ensure_ascii=False), flush=True)
                raise SystemExit(2)
            if data != previous:
                row = envelope(data)
                line = json.dumps(row, ensure_ascii=False, sort_keys=True)
                output.write(line + '\n')
                print(line, flush=True)
                previous = data
            if args.check or time.monotonic() - started >= args.seconds:
                break
            time.sleep(1)


if __name__ == '__main__':
    main()
