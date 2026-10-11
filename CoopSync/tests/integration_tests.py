"""Real two-process TCP tests using explicitly simulated game adapters."""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def rows(text):
    return [json.loads(line) for line in text.splitlines() if line.startswith('{')]


def scenario(exe, name, output):
    host_log = output / f'{name}_host.jsonl'
    guest_log = output / f'{name}_guest.jsonl'
    host = subprocess.Popen([str(exe), 'host', '--simulate', '--port', '0',
                             '--scenario', name, '--log', str(host_log)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding='utf-8')
    first_rows = []
    port = []
    error = []
    def read_listening():
        try:
            for _ in range(4):
                line = host.stdout.readline()
                if not line:
                    raise RuntimeError('Host exited before listening')
                first_rows.append(line)
                record = json.loads(line)
                if record['event'] == 'listening':
                    port.append(record['port'])
                    return
            raise RuntimeError('Missing host listening event')
        except Exception as exc:
            error.append(str(exc))
    reader = threading.Thread(target=read_listening, daemon=True)
    reader.start()
    reader.join(8)
    try:
        if reader.is_alive() or error or not port:
            raise RuntimeError(f'Host startup failure: {error}')
        guest = subprocess.run([str(exe), 'guest', '--simulate', '--host', '127.0.0.1',
                                '--port', str(port[0]), '--log', str(guest_log)],
                               capture_output=True, text=True, encoding='utf-8', timeout=12)
        stdout, stderr = host.communicate(timeout=8)
        host_rows = rows(''.join(first_rows) + stdout)
        guest_rows = rows(guest.stdout)
        expected = 2 if name in ('mismatch-end', 'disconnect') else 0
        assert host.returncode == expected, (name, host.returncode, stderr, host_rows)
        assert guest.returncode == expected, (name, guest.returncode, guest.stderr, guest_rows)
        assert all(r['mode'] == 'simulation' and not r['game_operations'] for r in host_rows + guest_rows)
        host_events = [r['event'] for r in host_rows]
        guest_events = [r['event'] for r in guest_rows]
        if expected == 0:
            assert host_events.count('released') == guest_events.count('released') == 1
            assert host_events.count('start_local_simulated') == guest_events.count('start_local_simulated') == 1
            skips = 0 if name == 'natural' else 1
            assert host_events.count('skip_local_simulated') == guest_events.count('skip_local_simulated') == skips
            assert host_events.index('peer_ready') < host_events.index('start_local_simulated')
            assert guest_events.index('ready_sent') < guest_events.index('start_local_simulated')
            assert host_events.index('peer_ended') < host_events.index('released')
        else:
            assert 'blocked' in host_events
            assert 'released' not in host_events + guest_events
        return {'scenario': name, 'passed': True, 'host_exit': host.returncode,
                'guest_exit': guest.returncode, 'host_log': str(host_log),
                'guest_log': str(guest_log), 'game_operations': False}
    finally:
        if host.poll() is None:
            host.kill()
            host.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, default=ROOT / 'build' / 'CoopSync.exe')
    parser.add_argument('--output', type=Path, default=ROOT / 'logs')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for name in ('natural', 'host-skip', 'guest-skip', 'mismatch-end', 'disconnect'):
        results.append(scenario(args.exe.resolve(), name, args.output.resolve()))
        print(f'PASS {name}', flush=True)
    refusal = subprocess.run([str(args.exe.resolve()), 'host'], capture_output=True,
                             text=True, encoding='utf-8', timeout=3)
    assert refusal.returncode == 1 and 'not implemented' in refusal.stderr
    results.append({'scenario': 'refuse_unimplemented_game_adapter', 'passed': True})
    report = {'scope': 'coordinator and real local TCP with simulated game adapters',
              'game_integration_verified': False, 'results': results}
    report_path = args.output / 'integration_summary.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Report: {report_path}')


if __name__ == '__main__':
    main()
