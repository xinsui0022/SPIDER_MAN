"""Synthetic raw UI traces and fake observer processes; no game process access."""
import contextlib
import io
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import analyze_runtime as analysis
import record_runtime as recorder

BASE = 0x140000000
SIZE = 140496896


def session(pid=123):
    return dict(record_type='overlay_ui_session', pid=pid, status='ready',
                process_path_verified=True, module_base=hex(BASE), module_size=SIZE)


def snapshot(now, callback=0, context=0, flag=0, elapsed=0.0):
    return dict(record_type='overlay_ui_snapshot', monotonic_ms=now, status=analysis.UI_STABLE,
                object_rva=hex(analysis.UI_OBJECT_RVA), slots_stable_during_reads=True,
                vtables=[dict(offset=hex(offset), expected_rva=hex(rva), actual=hex(BASE + rva),
                              actual_after=hex(BASE + rva), identity_match=True, stable_during_reads=True)
                         for offset, rva in analysis.UI_VTABLES.items()],
                raw_fields=[
                    dict(offset='0x210', size=1, raw_hex=bytes([flag]).hex(), unsigned_value=flag),
                    dict(offset='0x214', size=4, raw_hex=struct.pack('<f', elapsed).hex(),
                         float_value=elapsed if math.isfinite(elapsed) else None),
                    dict(offset='0x220', size=8, raw_hex=callback.to_bytes(8, 'little').hex(),
                         pointer_value=hex(callback),
                         main_module_target_rva=hex(callback - BASE) if BASE <= callback < BASE + SIZE else None),
                    dict(offset='0x228', size=8, raw_hex=context.to_bytes(8, 'little').hex(), pointer_value=hex(context)),
                ])


def check_safe(report):
    assert report['verified_callable_interfaces'] == []
    assert report['playing_verified'] is False and report['skip_verified'] is False
    assert report['game_operations'] is False
    # No nonfinite JSON values may escape the raw-float representation.
    json.dumps(report, allow_nan=False)


def main():
    checks = []

    def run(label, rows):
        report = analysis.summarize_ui_skip(rows)
        check_safe(report)
        checks.append(label)
        return report

    report = run('all-zero samples compress to one baseline and trend',
                 [session()] + [snapshot(100 + i * 100) for i in range(500)])
    assert report['quality'] == 'no_nonzero_ui_slots_observed'
    assert report['accepted_raw_snapshots'] == 500 and not report['raw_nonzero_slot_episodes']
    assert len(report['raw_flag_changes']) == len(report['raw_elapsed_trends']) == 1

    callback, context = BASE + 0x123456, 0x200000000
    report = run('stable nonzero pair has raw RVA and sampled bounds',
                 [session(), snapshot(100), snapshot(200, callback, context, 1, 0.5),
                  snapshot(300, callback, context, 1, 1.0), snapshot(400)])
    episode = report['raw_nonzero_slot_episodes'][0]
    assert report['quality'] == 'raw_observations_only' and report['nonzero_callback_samples'] == 2
    assert episode['callback_main_module_rva'] == '0x123456' and episode['context_main_module_rva'] is None
    assert (episode['first_observed_ms'], episode['last_observed_ms'], episode['closed_at_observation_ms']) == (200, 300, 400)
    assert episode['observation_end'] == 'both_raw_slots_became_zero'
    assert report['raw_elapsed_summary']['transitions']['decreasing'] == 1

    report = run('outside-module callback stays a pointer without guessed RVA',
                 [session(), snapshot(100, 0x300000000, BASE + 0x12345)])
    assert report['raw_nonzero_slot_episodes'][0]['callback_main_module_rva'] is None
    assert report['raw_nonzero_slot_episodes'][0]['context_main_module_rva'] == '0x12345'

    report = run('context-only nonzero slot is raw evidence', [session(), snapshot(100, 0, context)])
    assert report['nonzero_callback_samples'] == 0 and report['nonzero_context_samples'] == 1

    race = dict(record_type='overlay_ui_snapshot', monotonic_ms=200,
                status='callback_slots_changed_during_reads', slots_stable_during_reads=False)
    report = run('read race splits sampled episodes and withholds fields',
                 [session(), snapshot(100, callback, context), race, snapshot(300, callback, context)])
    assert len(report['raw_nonzero_slot_episodes']) == 2 and report['rejected_snapshots'] == 1
    assert report['raw_nonzero_slot_episodes'][0]['observation_end'] == 'observation_gap'

    for label, mutate in (
            ('primary identity mismatch', lambda row: row['vtables'][0].update(identity_match=False)),
            ('secondary identity mismatch', lambda row: row['vtables'][1].update(actual=hex(BASE + 5))),
            ('identity changes after reads', lambda row: row['vtables'][1].update(actual_after=hex(BASE + 6))),
            ('stable flag missing', lambda row: row['vtables'][0].pop('stable_during_reads')),
            ('duplicate vtable offsets', lambda row: row['vtables'][1].update(offset='0x0')),
            ('slot-stability flag false', lambda row: row.update(slots_stable_during_reads=False)),
            ('wrong direct object', lambda row: row.update(object_rva='0x1234')),
            ('raw pointer conflicts with byte payload', lambda row: row['raw_fields'][2].update(pointer_value='0x1')),
            ('raw float conflicts with byte payload', lambda row: row['raw_fields'][1].update(float_value=99.0)),
            ('boolean field size is not a byte count', lambda row: row['raw_fields'][0].update(size=True)),
            ('raw callback RVA conflicts with session', lambda row: row['raw_fields'][2].update(main_module_target_rva='0x1'))):
        altered = snapshot(100, callback, context)
        mutate(altered)
        report = run(label, [session(), altered])
        assert report['quality'] == 'incomplete_or_ambiguous' and report['accepted_raw_snapshots'] == 0
        assert not report['raw_nonzero_slot_episodes']

    for label, invalid_time in (('descending time', 50), ('duplicate time', 100), ('boolean time', True),
                                ('missing time', None), ('negative time', -1)):
        report = run(label, [session(), snapshot(100, callback, context), snapshot(invalid_time, callback, context)])
        assert 'missing_or_nonmonotonic_ui_snapshot_time' in report['problems']
        assert report['accepted_raw_snapshots'] == 1

    report = run('unverified session prevents acceptance', [snapshot(100, callback, context)])
    assert report['accepted_raw_snapshots'] == 0 and 'no_ui_session_metadata' in report['problems']
    bad_session = session()
    bad_session['process_path_verified'] = False
    report = run('failed path gate prevents acceptance', [bad_session, snapshot(100, callback, context)])
    assert report['accepted_raw_snapshots'] == 0

    foreign = snapshot(200, callback, context)
    foreign['pid'] = 456
    report = run('snapshot PID differs from session', [session(), snapshot(100), foreign])
    assert report['observed_pids'] == [123, 456] and report['accepted_raw_snapshots'] == 1
    assert 'ui_snapshot_and_session_processes_differ' in report['problems']
    report = run('new session separates same pointer observations',
                 [session(), snapshot(100, callback, context), session(456), snapshot(200, callback, context)])
    assert len(report['raw_nonzero_slot_episodes']) == 2 and len(report['session_pids']) == 2

    report = run('nonfinite raw elapsed is retained as null without phase inference',
                 [session(), snapshot(100, callback, context, elapsed=float('nan')),
                  snapshot(200, callback, context, elapsed=float('inf'))])
    assert report['accepted_raw_snapshots'] == 2 and report['raw_elapsed_summary']['nonfinite_samples'] == 2

    ignored = snapshot(100, callback, context)
    ignored['record_type'] = 'snapshot'
    report = run('foreign snapshot type ignored', [session(), ignored, snapshot(200)])
    assert report['snapshots'] == 1 and not report['raw_nonzero_slot_episodes']

    cine = [dict(record_type='session', pid=123),
            dict(record_type='snapshot', status=analysis.IDLE, monotonic_ms=100,
                 component_slot=dict(value='0x0'))]
    mission = [dict(pid=123, monotonic_ms=100, game_attached=True, tasks=[], status='observed')]
    combined = analysis.summarize(cine, mission, [session(456), snapshot(100)])
    assert combined['quality'] == 'incomplete_or_ambiguous'
    assert 'ui_and_component_processes_differ' in combined['problems']
    assert 'ui_and_task_processes_differ' in combined['problems']
    assert combined['verified_callable_interfaces'] == [] and combined['skip_verified'] is False
    checks.append('cross-observer PID mismatch cannot produce clean quality')
    assert 'ui_skip_raw' not in analysis.summarize(cine, mission)
    checks.append('original two-argument summary remains compatible')

    # Exercise the recorder's final analysis integration and console throttling
    # using completed fake subprocesses, never launching or reading the game.
    ui_rows = [session()] + [snapshot(100 + i * 100) for i in range(30)]
    cine_rows = [cine[0]] + [dict(record_type='snapshot', status=analysis.ACTIVE if i % 2 else analysis.IDLE,
                                 monotonic_ms=100 + i * 100,
                                 component_slot=dict(value=hex(0x10000 if i % 2 else 0),
                                                     identity_match=True, stable_during_reads=True))
                           for i in range(30)]

    class FakeProcess:
        def __init__(self, command, **unused):
            source = ('ui_skip' if 'ui_skip_runtime_probe.py' in command[4] else
                      'cinematic' if 'cinematic_runtime_probe.py' in command[4] else 'missions')
            rows = ui_rows if source == 'ui_skip' else cine_rows if source == 'cinematic' else mission
            payload = ''.join(json.dumps(row) + '\n' for row in rows)
            self.stdout = io.StringIO(payload)
            if source == 'missions':
                Path(command[command.index('--output') + 1]).write_text(payload, encoding='utf-8')

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp) / 'capture'
        output = io.StringIO()
        with mock.patch.object(recorder.subprocess, 'Popen', FakeProcess), contextlib.redirect_stdout(output):
            assert recorder.capture(1, 'manual-skip', directory) == 0
        final = json.loads((directory / 'analysis.json').read_text(encoding='utf-8'))
        assert final['ui_skip_raw']['accepted_raw_snapshots'] == 30
        assert len(analysis.read_rows(directory / 'timeline.jsonl')) == len(ui_rows) + len(cine_rows) + len(mission)
        console = output.getvalue().splitlines()
        assert any(line.startswith('READY:') for line in console)
        state_lines = [json.loads(line) for line in console if line.startswith('{')]
        assert len([row for row in state_lines if row.get('source') == 'cinematic']) == 1
    checks.append('recorder integrates UI and throttles console without dropping raw rows')

    ui_rows = [session(), snapshot(100), dict(record_type='overlay_ui_snapshot', monotonic_ms=200,
                                            status='overlay_identity_mismatch_probe_stopped')]
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp) / 'capture'
        output = io.StringIO()
        with mock.patch.object(recorder.subprocess, 'Popen', FakeProcess), contextlib.redirect_stdout(output):
            assert recorder.capture(1, 'unmarked', directory) == 2
        state_lines = [json.loads(line) for line in output.getvalue().splitlines() if line.startswith('{')]
        ui_console = [row for row in state_lines if row.get('source') == 'ui_skip']
        assert len(ui_console) == 2 and ui_console[-1]['status'] == 'overlay_identity_mismatch_probe_stopped'
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        assert manifest['status'] == 'ui_skip_observation_refused'
        final = json.loads((directory / 'analysis.json').read_text(encoding='utf-8'))
        assert final['ui_skip_raw']['rejected_snapshots'] == 1 and final['skip_verified'] is False
    checks.append('terminal UI error prints immediately inside the throttle window')
    print(f'PASS: {len(checks)} UI runtime evidence analysis cases (synthetic input / fake subprocesses only)')


if __name__ == '__main__':
    main()
