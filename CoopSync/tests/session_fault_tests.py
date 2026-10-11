"""Exercise the native session with hostile or out-of-order local TCP peers."""
import argparse
import json
from pathlib import Path
import socket
import struct
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[1]
TICKET = dict(epoch=1, revision=1, scene=101, cinematic=b'simulated_fisk_intro', x=0., y=1., z=0.)


def frame(kind, session=123, sequence=1, ticket=None, end_revision=0, digest=0, reason=b''):
    t = ticket or dict(epoch=0, revision=0, scene=0, cinematic=b'', x=0., y=0., z=0.)
    payload = b'CSY1' + struct.pack('!HHQQQQIfffQQH', 1, kind, session, sequence,
        t['epoch'], t['revision'], t['scene'], t['x'], t['y'], t['z'],
        end_revision, digest, len(t['cinematic'])) + t['cinematic'] + struct.pack('!H', len(reason)) + reason
    return struct.pack('!I', len(payload)) + payload


def exact(sock, length):
    result = bytearray()
    while len(result) < length:
        part = sock.recv(length - len(result))
        if not part:
            raise EOFError('peer closed')
        result.extend(part)
    return bytes(result)


def receive(sock):
    length = struct.unpack('!I', exact(sock, 4))[0]
    assert 76 <= length <= 1024
    data = exact(sock, length)
    magic, version, kind, session, sequence, epoch, revision, scene, x, y, z, end_revision, digest, size = struct.unpack_from('!4sHHQQQQIfffQQH', data)
    assert magic == b'CSY1' and version == 1
    cinematic = data[74:74+size]
    return dict(kind=kind, session=session, sequence=sequence,
                ticket=dict(epoch=epoch, revision=revision, scene=scene, cinematic=cinematic, x=x, y=y, z=z))


def fake_host(exe, name, operation, expected_text):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(5)
        guest = subprocess.Popen([str(exe), 'guest', '--simulate', '--host', '127.0.0.1',
                                  '--port', str(listener.getsockname()[1])],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        try:
            with listener.accept()[0] as peer:
                peer.settimeout(5)
                assert receive(peer)['kind'] == 1
                peer.sendall(frame(2, reason=b'natural'))
                operation(peer)
                stdout, stderr = guest.communicate(timeout=6)
            assert guest.returncode == 1 and expected_text in stderr, (name, guest.returncode, stderr, stdout)
            assert '"event":"released"' not in stdout, (name, stdout)
            return dict(scenario=name, passed=True, exit=guest.returncode, game_operations=False)
        finally:
            if guest.poll() is None:
                guest.kill()
                guest.wait(timeout=3)


def prepared(peer):
    peer.sendall(frame(3, sequence=2, ticket=TICKET))
    ready = receive(peer)
    assert ready['kind'] == 4 and ready['sequence'] == 2


def after_prepare(kind, **kwargs):
    def send(peer):
        prepared(peer)
        peer.sendall(frame(kind, sequence=3, ticket=TICKET, **kwargs))
    return send


def fake_guest(exe, name, operation, expected_exit=2):
    host = subprocess.Popen([str(exe), 'host', '--simulate', '--port', '0'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    initial = []
    ports = []
    def read_port():
        for _ in range(3):
            line = host.stdout.readline()
            if not line:
                return
            initial.append(line)
            item = json.loads(line)
            if item['event'] == 'listening':
                ports.append(item['port'])
                return
    reader = threading.Thread(target=read_port, daemon=True)
    reader.start()
    reader.join(6)
    try:
        assert not reader.is_alive() and ports, (name, initial)
        with socket.create_connection(('127.0.0.1', ports[0]), timeout=5) as peer:
            operation(peer)
            stdout, stderr = host.communicate(timeout=6)
        stdout = ''.join(initial) + stdout
        assert host.returncode == expected_exit, (name, host.returncode, stderr, stdout)
        assert '"event":"released"' not in stdout, (name, stdout)
        if expected_exit == 2:
            assert '"event":"blocked"' in stdout
        return dict(scenario=name, passed=True, exit=host.returncode, game_operations=False)
    finally:
        if host.poll() is None:
            host.kill()
            host.wait(timeout=3)


def host_ticket(peer):
    peer.sendall(frame(1, session=321))
    welcome = receive(peer)
    assert welcome['kind'] == 2
    prepare = receive(peer)
    assert prepare['kind'] == 3
    return welcome['session'], prepare['ticket']


def wrong_ticket(peer):
    session, ticket = host_ticket(peer)
    ticket['cinematic'] = b'other_cinematic'
    peer.sendall(frame(4, session, 2, ticket))


def role_inversion(peer):
    session, ticket = host_ticket(peer)
    peer.sendall(frame(5, session, 2, ticket))


def wrong_block(peer):
    prepared(peer)
    wrong = dict(TICKET, epoch=2)
    peer.sendall(frame(10, sequence=3, ticket=wrong, reason=b'old scene'))


def sequence_gap(peer):
    prepared(peer)
    peer.sendall(frame(5, sequence=4, ticket=TICKET))


def truncated_header(peer):
    peer.sendall(b'\0\0')
    peer.shutdown(socket.SHUT_WR)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, default=ROOT / 'build' / 'CoopSync.exe')
    parser.add_argument('--output', type=Path, default=ROOT / 'logs')
    args = parser.parse_args()
    exe = args.exe.resolve()
    results = [
        fake_host(exe, 'start_without_prepare', lambda s: s.sendall(frame(5, sequence=2)), 'prepared scene'),
        fake_host(exe, 'wrong_epoch_blocked', wrong_block, 'current cinematic'),
        fake_host(exe, 'release_before_ended', after_prepare(9, end_revision=2, digest=0x53494D554C415445), 'matching terminal state'),
        fake_host(exe, 'wrong_session', after_prepare(5, session=124), 'another session'),
        fake_host(exe, 'sequence_gap', sequence_gap, 'sequence gap'),
        fake_host(exe, 'skip_before_start', after_prepare(7), 'current cinematic'),
        fake_guest(exe, 'wrong_cinematic_ready', wrong_ticket),
        fake_guest(exe, 'guest_sends_start', role_inversion),
        fake_guest(exe, 'oversized_handshake_frame', lambda s: s.sendall(struct.pack('!I', 1025)), 1),
        fake_guest(exe, 'truncated_handshake_header', truncated_header, 1),
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / 'session_fault_summary.json'
    output.write_text(json.dumps(dict(game_integration_verified=False, results=results), indent=2), encoding='utf-8')
    for result in results:
        print('PASS', result['scenario'])
    print('Report:', output)


if __name__ == '__main__':
    main()
