"""Run three read-only observers together, preserving raw evidence and errors."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

from analyze_runtime import read_rows, summarize

ROOT = Path(__file__).resolve().parents[1]


def pump(process, source, events):
    try:
        for line in process.stdout:
            events.put((source, line))
    finally:
        events.put((source, None))


def capture(seconds, label, directory):
    directory.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema=1, utc=datetime.now(timezone.utc).isoformat(), seconds_requested=seconds,
                    label=label, label_is_test_intent_only=True, mode='read_only_observation',
                    game_operations=False, game_launched_by_tool=False, status='initializing',
                    child_exit_codes={})
    path = directory / 'manifest.json'
    processes, threads, handles = {}, [], []
    events = queue.Queue()
    snapshot_seen = set()
    last_status = {}
    last_console_time = {}
    pending_status_changes = {}
    observer_pids = {}
    stop_reason = None
    try:
        commands = {
            'cinematic': [sys.executable, '-X', 'utf8', '-B', str(ROOT / 'research' / 'cinematic_runtime_probe.py'),
                          '--samples', str(seconds * 10 + 1), '--interval-ms', '100'],
            'missions': [sys.executable, '-X', 'utf8', '-B', str(ROOT / 'tools' / 'observe_game.py'),
                         '--seconds', str(seconds), '--output', str(directory / 'missions.jsonl')],
            'ui_skip': [sys.executable, '-X', 'utf8', '-B', str(ROOT / 'research' / 'ui_skip_runtime_probe.py'),
                        '--samples', str(seconds * 10 + 1), '--interval-ms', '100'],
        }
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        for source, command in commands.items():
            error_stream = (directory / f'{source}.stderr.txt').open('w', encoding='utf-8')
            handles.append(error_stream)
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=error_stream, text=True, encoding='utf-8', creationflags=flags)
            processes[source] = process
            thread = threading.Thread(target=pump, args=(process, source, events), daemon=True)
            thread.start()
            threads.append(thread)
        manifest['status'] = 'observers_started'
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        deadline = time.monotonic() + seconds + 15
        closed = set()
        with (directory / 'cinematic.jsonl').open('w', encoding='utf-8', buffering=1) as cine_output, \
             (directory / 'ui_skip.jsonl').open('w', encoding='utf-8', buffering=1) as ui_output, \
             (directory / 'timeline.jsonl').open('w', encoding='utf-8', buffering=1) as timeline:
            while len(closed) != len(processes):
                if time.monotonic() > deadline:
                    stop_reason = 'observer_deadline_exceeded'
                    break
                try:
                    source, line = events.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    closed.add(source)
                    continue
                if source == 'cinematic':
                    cine_output.write(line)
                elif source == 'ui_skip':
                    ui_output.write(line)
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError('Observer did not emit an object')
                except (ValueError, TypeError) as error:
                    stop_reason = f'{source}_invalid_json: {error}'
                    break
                timeline.write(json.dumps(dict(source=source, received_monotonic_ms=int(time.monotonic() * 1000),
                                               observation=row), ensure_ascii=False) + '\n')
                status = row.get('status')
                if row.get('pid') is not None:
                    observer_pids[source] = row['pid']
                    if len(set(observer_pids.values())) > 1:
                        stop_reason = 'observer_process_identities_differ'
                        break
                if row.get('record_type', 'snapshot') in ('snapshot', 'overlay_ui_snapshot') and status:
                    snapshot_seen.add(source)
                    if last_status.get(source) != status:
                        last_status[source] = status
                        pending_status_changes[source] = pending_status_changes.get(source, 0) + 1
                    nonterminal = {
                        'cinematic': ('object_identities_match_no_flagged_component',
                                      'component_identity_match_raw_state_only', 'component_changed_during_reads'),
                        'missions': ('observed', 'observation_recorded', 'read_only_observation'),
                        'ui_skip': ('overlay_identity_match_slots_stable_raw_only', 'callback_slots_changed_during_reads'),
                    }
                    # Mission status names vary; only its explicit refusal / missing-game states stop capture.
                    terminal = (status in ('no_game_process_found', 'waiting_for_game', 'observation_refused') or
                                source in ('cinematic', 'ui_skip') and status not in nonterminal[source])
                    console_now = time.monotonic()
                    if terminal or (pending_status_changes.get(source, 0) and
                                    console_now - last_console_time.get(source, float('-inf')) >= 10):
                        print(json.dumps(dict(source=source, status=status,
                                              status_changes_since_last_output=pending_status_changes.get(source, 0)),
                                         ensure_ascii=False), flush=True)
                        pending_status_changes[source] = 0
                        last_console_time[source] = console_now
                    if status in ('no_game_process_found', 'waiting_for_game'):
                        stop_reason = 'game_not_running_no_runtime_test'
                        break
                    if source == 'cinematic' and status not in (
                            'object_identities_match_no_flagged_component',
                            'component_identity_match_raw_state_only', 'component_changed_during_reads'):
                        stop_reason = 'cinematic_observation_refused'
                        break
                    if source == 'missions' and status == 'observation_refused':
                        stop_reason = 'mission_observation_refused'
                        break
                    if source == 'ui_skip' and status not in (
                            'overlay_identity_match_slots_stable_raw_only', 'callback_slots_changed_during_reads'):
                        stop_reason = 'ui_skip_observation_refused'
                        break
                if snapshot_seen == set(commands) and not manifest.get('all_observers_ready'):
                    manifest['all_observers_ready'] = True
                    manifest['observer_pids'] = observer_pids
                    manifest['status'] = 'recording_read_only'
                    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                    print('READY: all three read-only observers produced a baseline; game interfaces remain unverified.', flush=True)
    except KeyboardInterrupt:
        stop_reason = 'recording_interrupted'
    except (OSError, ValueError) as error:
        stop_reason = f'recording_error: {error}'
    finally:
        for process in processes.values():
            if stop_reason is not None and process.poll() is None:
                process.terminate()
        for source, process in processes.items():
            try:
                manifest['child_exit_codes'][source] = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                manifest['child_exit_codes'][source] = process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=2)
        for process in processes.values():
            if process.stdout is not None:
                process.stdout.close()
        for handle in handles:
            handle.close()
        manifest['status'] = stop_reason or ('observations_recorded' if snapshot_seen == {'cinematic', 'missions', 'ui_skip'}
                                             and all(code == 0 for code in manifest['child_exit_codes'].values())
                                             else 'incomplete_observer_output')
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    cine_path, mission_path = directory / 'cinematic.jsonl', directory / 'missions.jsonl'
    if cine_path.exists() and mission_path.exists():
        try:
            ui_path = directory / 'ui_skip.jsonl'
            analysis = summarize(read_rows(cine_path), read_rows(mission_path),
                                 read_rows(ui_path) if ui_path.exists() else None)
            (directory / 'analysis.json').write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        except (OSError, ValueError) as error:
            manifest['analysis_error'] = str(error)
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=manifest['status'], recording=str(directory)), ensure_ascii=False), flush=True)
    return 0 if manifest['status'] in ('observations_recorded', 'game_not_running_no_runtime_test', 'recording_interrupted') else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--label', choices=['unmarked', 'natural-end', 'manual-skip'], default='unmarked')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error('seconds must be in 1..300')
    directory = args.output_dir or ROOT / 'logs' / ('runtime_' + datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8])
    return capture(args.seconds, args.label, directory.resolve())


if __name__ == '__main__':
    raise SystemExit(main())
