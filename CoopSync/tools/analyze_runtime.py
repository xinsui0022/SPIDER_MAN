"""Summarize raw read-only observations; never infer a callable skip interface."""
import argparse
import json
import math
from pathlib import Path
import struct


ACTIVE = 'component_identity_match_raw_state_only'
IDLE = 'object_identities_match_no_flagged_component'
UI_STABLE = 'overlay_identity_match_slots_stable_raw_only'
UI_VTABLES = {0: 0x4F44980, 0x158: 0x4F449E0}
UI_OBJECT_RVA = 0x7B84580


def read_rows(path):
    rows = []
    with path.open(encoding='utf-8-sig') as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f'{path.name}:{number}: expected a JSON object')
            rows.append(row)
    return rows


def pointer_value(slot):
    value = slot.get('value', slot.get('pointer'))
    if isinstance(value, str):
        return int(value, 0)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError('Missing raw component pointer')


def raw_integer(value, maximum=(1 << 64) - 1):
    if isinstance(value, str):
        value = int(value, 0)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise ValueError('Invalid raw unsigned integer')
    return value


def ui_identity_matches(row, base, module_size):
    try:
        if raw_integer(row.get('object_rva')) != UI_OBJECT_RVA:
            return False
        tables = row.get('vtables')
        if not isinstance(tables, list) or len(tables) != 2:
            return False
        seen = set()
        for table in tables:
            offset = raw_integer(table.get('offset'))
            expected = UI_VTABLES.get(offset)
            if offset in seen or expected is None or expected + 8 > module_size:
                return False
            seen.add(offset)
            if (raw_integer(table.get('expected_rva')) != expected or
                    raw_integer(table.get('actual')) != base + expected or
                    raw_integer(table.get('actual_after')) != base + expected or
                    table.get('identity_match') is not True or
                    table.get('stable_during_reads') is not True):
                return False
        return seen == set(UI_VTABLES)
    except (AttributeError, TypeError, ValueError):
        return False


def ui_raw_fields(row, base, module_size):
    """Validate internally consistent bytes without dereferencing either slot."""
    values = row.get('raw_fields')
    if not isinstance(values, list) or len(values) != 4:
        raise ValueError('Expected the four fixed raw OverlayUI fields')
    fields = {}
    sizes = {0x210: 1, 0x214: 4, 0x220: 8, 0x228: 8}
    for field in values:
        offset = raw_integer(field.get('offset'))
        if (offset in fields or offset not in sizes or isinstance(field.get('size'), bool) or
                field.get('size') != sizes[offset]):
            raise ValueError('Invalid raw field offset or size')
        raw = bytes.fromhex(field['raw_hex'])
        if len(raw) != sizes[offset]:
            raise ValueError('Invalid raw field byte count')
        fields[offset] = (field, raw)
    flag = fields[0x210][1][0]
    if raw_integer(fields[0x210][0].get('unsigned_value'), 255) != flag:
        raise ValueError('Raw flag bytes and value differ')
    elapsed = struct.unpack('<f', fields[0x214][1])[0]
    reported = fields[0x214][0].get('float_value')
    if math.isfinite(elapsed):
        if isinstance(reported, bool) or not isinstance(reported, (float, int)) or reported != elapsed:
            raise ValueError('Raw float bytes and value differ')
    elif reported is not None:
        raise ValueError('Nonfinite raw float must be represented by null')
    callback = int.from_bytes(fields[0x220][1], 'little')
    context = int.from_bytes(fields[0x228][1], 'little')
    if (raw_integer(fields[0x220][0].get('pointer_value')) != callback or
            raw_integer(fields[0x228][0].get('pointer_value')) != context):
        raise ValueError('Raw slot bytes and pointer values differ')
    callback_rva = callback - base if base <= callback < base + module_size else None
    reported_rva = fields[0x220][0].get('main_module_target_rva')
    if ((reported_rva is None) != (callback_rva is None) or
            (reported_rva is not None and raw_integer(reported_rva) != callback_rva)):
        raise ValueError('Reported callback RVA disagrees with the session module')
    return dict(flag=flag, elapsed=elapsed if math.isfinite(elapsed) else None,
                elapsed_raw_hex=fields[0x214][1].hex(), callback=callback, context=context,
                callback_rva=callback_rva,
                context_rva=context - base if base <= context < base + module_size else None)


def summarize_ui_skip(rows):
    """Summarize stable raw UI slots; no state, callback ABI or skip semantics."""
    problems, statuses, episodes, flags, trends = {}, {}, [], [], []
    observed_pids, session_pids = set(), set()
    sessions = snapshots = accepted = 0
    previous_time, previous, current, trend = None, None, None, None
    base = module_size = session_pid = None
    first_ms = last_ms = None
    nonzero_callback_samples = nonzero_context_samples = pair_changes = 0
    elapsed_stats = dict(finite_samples=0, nonfinite_samples=0, raw_value_changes=0,
                         first_value=None, last_value=None, minimum=None, maximum=None,
                         transitions=dict(increasing=0, decreasing=0, unchanged=0, nonfinite=0))

    def problem(name):
        problems[name] = problems.get(name, 0) + 1

    def gap(reason, now=None):
        nonlocal current, previous, trend
        if current is not None:
            current['observation_end'] = reason
            current['closed_at_observation_ms'] = now
        current, previous, trend = None, None, None

    for row in rows:
        kind = row.get('record_type')
        if kind == 'overlay_ui_session':
            sessions += 1
            gap('new_session_metadata')
            base = module_size = session_pid = None
            try:
                session_pid = raw_integer(row.get('pid'), 0xFFFFFFFF)
                if not session_pid:
                    raise ValueError('Missing session PID')
                observed_pids.add(session_pid)
                session_pids.add(session_pid)
                base = raw_integer(row.get('module_base'))
                module_size = raw_integer(row.get('module_size'))
                if (row.get('status') != 'ready' or row.get('process_path_verified') is not True or
                        not base or UI_OBJECT_RVA + 0x230 > module_size or base + module_size >= 1 << 64):
                    raise ValueError('Unverified session identity')
            except (TypeError, ValueError):
                problem('invalid_or_unready_ui_session_metadata')
                base = module_size = session_pid = None
            continue
        if kind != 'overlay_ui_snapshot':
            continue
        snapshots += 1
        status = row.get('status')
        statuses[str(status)] = statuses.get(str(status), 0) + 1
        now = row.get('monotonic_ms')
        if not isinstance(now, int) or isinstance(now, bool) or now < 0 or (previous_time is not None and now <= previous_time):
            problem('missing_or_nonmonotonic_ui_snapshot_time')
            gap('observation_time_invalid')
            continue
        previous_time = now
        first_ms = now if first_ms is None else first_ms
        last_ms = now
        if row.get('pid') is not None:
            try:
                snapshot_pid = raw_integer(row['pid'], 0xFFFFFFFF)
                if not snapshot_pid:
                    raise ValueError('Zero PID')
                observed_pids.add(snapshot_pid)
                if snapshot_pid != session_pid:
                    problem('ui_snapshot_and_session_processes_differ')
                    gap('process_identity_changed', now)
                    continue
            except (TypeError, ValueError):
                problem('invalid_ui_snapshot_pid')
                gap('process_identity_unverified', now)
                continue
        if base is None:
            problem('ui_snapshot_without_verified_session_metadata')
            gap('session_identity_unverified', now)
            continue
        if status != UI_STABLE:
            problem('callback_slots_changed_during_reads' if status == 'callback_slots_changed_during_reads'
                    else 'ui_observation_refused:' + str(status))
            gap('observation_gap', now)
            continue
        if not ui_identity_matches(row, base, module_size):
            problem('ui_dual_vtable_identity_or_stability_unverified')
            gap('object_identity_unverified', now)
            continue
        if row.get('slots_stable_during_reads') is not True:
            problem('ui_slot_stability_unverified')
            gap('slot_stability_unverified', now)
            continue
        try:
            raw = ui_raw_fields(row, base, module_size)
        except (AttributeError, KeyError, TypeError, ValueError, struct.error):
            problem('invalid_or_inconsistent_ui_raw_fields')
            gap('raw_fields_invalid', now)
            continue
        accepted += 1
        nonzero_callback_samples += int(raw['callback'] != 0)
        nonzero_context_samples += int(raw['context'] != 0)
        pair = raw['callback'], raw['context']
        if previous is not None and pair != previous['pair']:
            pair_changes += 1
        if pair != (0, 0):
            if current is None or (current['callback_pointer'], current['context_pointer']) != tuple(map(hex, pair)):
                if current is not None:
                    current['observation_end'] = 'different_raw_slot_pair'
                    current['closed_at_observation_ms'] = now
                current = dict(callback_pointer=hex(raw['callback']), context_pointer=hex(raw['context']),
                               callback_main_module_rva=hex(raw['callback_rva']) if raw['callback_rva'] is not None else None,
                               context_main_module_rva=hex(raw['context_rva']) if raw['context_rva'] is not None else None,
                               first_observed_ms=now, last_observed_ms=now, samples=0,
                               observation_end='recording_stopped', closed_at_observation_ms=None)
                episodes.append(current)
            current['last_observed_ms'] = now
            current['samples'] += 1
        elif current is not None:
            current['observation_end'] = 'both_raw_slots_became_zero'
            current['closed_at_observation_ms'] = now
            current = None
        if previous is None or raw['flag'] != previous['flag']:
            flags.append(dict(monotonic_ms=now, raw_value=raw['flag'],
                              change='baseline_or_after_observation_gap' if previous is None else 'raw_byte_changed'))
        value = raw['elapsed']
        if value is None:
            elapsed_stats['nonfinite_samples'] += 1
        else:
            elapsed_stats['finite_samples'] += 1
            if elapsed_stats['finite_samples'] == 1:
                elapsed_stats['first_value'] = elapsed_stats['minimum'] = elapsed_stats['maximum'] = value
            elapsed_stats['last_value'] = value
            elapsed_stats['minimum'] = min(elapsed_stats['minimum'], value)
            elapsed_stats['maximum'] = max(elapsed_stats['maximum'], value)
        if previous is not None:
            elapsed_stats['raw_value_changes'] += int(raw['elapsed_raw_hex'] != previous['elapsed_raw_hex'])
            before = previous['elapsed']
            direction = ('nonfinite' if before is None or value is None else
                         'increasing' if value > before else 'decreasing' if value < before else 'unchanged')
            elapsed_stats['transitions'][direction] += 1
            if trend is None or trend['raw_direction'] != direction:
                trend = dict(raw_direction=direction, first_observed_ms=previous['time'],
                             last_observed_ms=now, comparisons=0)
                trends.append(trend)
            trend['last_observed_ms'] = now
            trend['comparisons'] += 1
        previous = dict(pair=pair, flag=raw['flag'], elapsed=value,
                        elapsed_raw_hex=raw['elapsed_raw_hex'], time=now)
    if not sessions:
        problem('no_ui_session_metadata')
    if len(observed_pids) > 1:
        problem('multiple_ui_processes_in_one_recording')
    quality = ('incomplete_or_ambiguous' if problems else
               'raw_observations_only' if episodes else 'no_nonzero_ui_slots_observed')
    return dict(schema=1, quality=quality, sessions=sessions, snapshots=snapshots,
                accepted_raw_snapshots=accepted, rejected_snapshots=snapshots - accepted,
                observed_pids=sorted(observed_pids), session_pids=sorted(session_pids),
                first_snapshot_ms=first_ms, last_snapshot_ms=last_ms, status_counts=statuses,
                nonzero_callback_samples=nonzero_callback_samples, nonzero_context_samples=nonzero_context_samples,
                raw_slot_pair_changes=pair_changes, raw_nonzero_slot_episodes=episodes,
                raw_flag_changes=flags, raw_elapsed_summary=elapsed_stats, raw_elapsed_trends=trends,
                problems=list(problems), problem_counts=problems, game_operations=False,
                verified_callable_interfaces=[], playing_verified=False, skip_verified=False,
                limitations='Stable raw UI slots and sampled changes only. A nonzero callback or flag, a timer change, or slots becoming zero do not prove cinematic playback, a callable ABI, or skipping. Context pointers are never dereferenced.')


def summarize(cinematics, missions, ui_skip=None):
    episodes, problems, statuses = [], [], []
    current = None
    previous_time = -1
    observed_pids = set()
    snapshots = 0
    for row in cinematics:
        if row.get('pid') is not None:
            observed_pids.add(row['pid'])
        if row.get('record_type') in ('session', 'end'):
            continue
        if 'status' not in row:
            continue
        snapshots += 1
        status = row['status']
        statuses.append(status)
        now = row.get('monotonic_ms')
        if not isinstance(now, int) or isinstance(now, bool) or now < previous_time:
            problems.append('missing_or_nonmonotonic_snapshot_time')
            break
        previous_time = now
        slot = row.get('component_slot', {})
        if status == ACTIVE:
            try:
                pointer = pointer_value(slot)
            except (ValueError, TypeError):
                problems.append('invalid_component_pointer')
                break
            if not pointer or not slot.get('identity_match') or not slot.get('stable_during_reads'):
                problems.append('active_component_identity_or_stability_unverified')
                if current is not None:
                    current['observation_end'] = 'observation_gap'
                    current = None
                continue
            if current is None or current['component_pointer'] != hex(pointer):
                if current is not None:
                    current['last_observed_ms'] = now
                    current['observation_end'] = 'different_component_selected'
                current = dict(component_pointer=hex(pointer), first_observed_ms=now,
                               last_observed_ms=now, observation_end='recording_stopped', raw_states=[])
                episodes.append(current)
            current['last_observed_ms'] = now
            current['raw_states'].append(dict(monotonic_ms=now, fields=row.get('runtime_state_fields', [])))
        elif status == IDLE:
            try:
                pointer = pointer_value(slot)
            except (ValueError, TypeError):
                problems.append('missing_idle_pointer')
                continue
            if pointer != 0:
                problems.append('idle_status_with_nonzero_pointer')
                continue
            if current is not None:
                current['last_observed_ms'] = now
                current['observation_end'] = 'selection_slot_became_zero'
                current = None
        elif status == 'component_changed_during_reads':
            problems.append('component_changed_during_reads')
            if current is not None:
                current['observation_end'] = 'observation_gap'
                current = None
        elif status not in ('no_game_process_found', 'waiting_for_game'):
            problems.append(status)
            if current is not None:
                current['observation_end'] = 'observation_refused'
                current = None
    if len(observed_pids) > 1:
        problems.append('multiple_processes_in_one_recording')
    task_changes = [dict(monotonic_ms=row.get('monotonic_ms'), utc=row.get('utc'),
                         pid=row.get('pid'), status=row.get('status'), tasks=row.get('tasks', []),
                         task_subset_sha256=row.get('task_subset_sha256'))
                    for row in missions if row.get('game_attached')]
    task_pids = {row['pid'] for row in task_changes if row['pid'] is not None}
    if task_pids and observed_pids and task_pids != observed_pids:
        problems.append('task_and_component_processes_differ')
    task_times = [row['monotonic_ms'] for row in task_changes]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in task_times):
        problems.append('missing_task_monotonic_time')
    elif task_times != sorted(task_times):
        problems.append('nonmonotonic_task_time')
    quality = ('incomplete_or_ambiguous' if problems else
               ('raw_observations_only' if episodes else 'no_selected_component_observed'))
    report = dict(schema=1, quality=quality, snapshots=snapshots, observed_pids=sorted(observed_pids),
                observed_statuses=list(dict.fromkeys(statuses)), raw_component_episodes=episodes,
                task_changes=task_changes, problems=list(dict.fromkeys(problems)),
                game_operations=False, verified_callable_interfaces=[], scene_ready_verified=False,
                skip_verified=False, full_world_sync_verified=False,
                limitations='Raw component selection and task subset only. Slot becoming zero does not prove cinematic completion or skipping.')
    if ui_skip is not None:
        ui_report = summarize_ui_skip(ui_skip)
        report['ui_skip_raw'] = ui_report
        for source, pids in (('component', observed_pids), ('task', task_pids)):
            if pids and ui_report['observed_pids'] and set(ui_report['observed_pids']) != pids:
                report['problems'].append('ui_and_' + source + '_processes_differ')
        if report['problems'] or ui_report['problems']:
            report['quality'] = 'incomplete_or_ambiguous'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    args = parser.parse_args()
    ui_path = args.recording / 'ui_skip.jsonl'
    report = summarize(read_rows(args.recording / 'cinematic.jsonl'),
                       read_rows(args.recording / 'missions.jsonl'),
                       read_rows(ui_path) if ui_path.exists() else None)
    path = args.recording / 'analysis.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(quality=report['quality'], episodes=len(report['raw_component_episodes']),
                         skip_verified=False, output=str(path)), ensure_ascii=False))


if __name__ == '__main__':
    main()
