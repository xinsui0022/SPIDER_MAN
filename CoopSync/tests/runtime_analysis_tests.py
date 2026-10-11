"""Ensure incomplete or raw traces cannot be reported as validated game sync."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('runtime_analysis', ROOT / 'tools' / 'analyze_runtime.py')
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def row(now, pointer, **extra):
    return dict(record_type='snapshot', pid=123, monotonic_ms=now,
                status=analysis.ACTIVE if pointer else analysis.IDLE,
                component_slot=dict(value=hex(pointer), identity_match=True, stable_during_reads=True),
                runtime_state_fields=[dict(offset='0x58', unsigned_value=7)], **extra)


def main():
    cases = 0
    result = analysis.summarize([row(100, 0), row(200, 0x10000), row(300, 0)], [])
    assert result['quality'] == 'raw_observations_only'
    assert result['raw_component_episodes'][0]['observation_end'] == 'selection_slot_became_zero'
    assert not result['skip_verified'] and not result['scene_ready_verified'] and not result['full_world_sync_verified']
    cases += 1
    result = analysis.summarize([row(100, 0)], [])
    assert result['quality'] == 'no_selected_component_observed' and not result['raw_component_episodes']
    cases += 1
    unstable = row(100, 0x10000)
    unstable['component_slot']['stable_during_reads'] = False
    result = analysis.summarize([unstable], [])
    assert result['quality'] == 'incomplete_or_ambiguous' and not result['raw_component_episodes']
    cases += 1
    result = analysis.summarize([row(200, 0x10000), row(100, 0)], [])
    assert 'missing_or_nonmonotonic_snapshot_time' in result['problems']
    cases += 1
    result = analysis.summarize([row(100, 0x10000), row(200, 0x20000)], [])
    assert len(result['raw_component_episodes']) == 2
    assert result['raw_component_episodes'][0]['observation_end'] == 'different_component_selected'
    cases += 1
    unknown = dict(record_type='snapshot', monotonic_ms=200, status='component_identity_mismatch_probe_stopped')
    result = analysis.summarize([row(100, 0x10000), unknown], [])
    assert result['quality'] == 'incomplete_or_ambiguous'
    cases += 1
    task = dict(monotonic_ms=110, pid=123, game_attached=True, tasks=[{'mission_name_raw': 'TEST'}])
    result = analysis.summarize([row(100, 0)], [task])
    assert len(result['task_changes']) == 1 and not result['full_world_sync_verified']
    cases += 1
    other_pid = row(200, 0)
    other_pid['pid'] = 456
    result = analysis.summarize([row(100, 0x10000), other_pid], [])
    assert 'multiple_processes_in_one_recording' in result['problems']
    cases += 1
    foreign_task = dict(monotonic_ms=110, pid=456, game_attached=True, tasks=[])
    result = analysis.summarize([row(100, 0x10000)], [foreign_task])
    assert 'task_and_component_processes_differ' in result['problems']
    cases += 1
    gap = dict(monotonic_ms=200, pid=123, status='component_changed_during_reads')
    result = analysis.summarize([row(100, 0x10000), gap, row(300, 0x10000)], [])
    assert result['quality'] == 'incomplete_or_ambiguous' and len(result['raw_component_episodes']) == 2
    assert result['raw_component_episodes'][0]['observation_end'] == 'observation_gap'
    cases += 1
    snapshot = row(100, 0)
    snapshot.pop('pid')
    result = analysis.summarize([dict(record_type='session', pid=123), snapshot], [task])
    assert result['observed_pids'] == [123] and not result['problems']
    cases += 1
    print(f'PASS: {cases} runtime evidence analysis cases (synthetic input only)')


if __name__ == '__main__':
    main()
