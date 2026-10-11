"""Read-only slot3 metadata / mission table snapshot for the repeated load audit."""
from pathlib import Path
import datetime
import hashlib
import json
import struct
from read_save_metadata import Parser, select

ROOT = Path(__file__).resolve().parent
CURRENT = Path(r"D:\STEAM__\steamapps\common\Marvel's Spider-Man Remastered\SMT\Save\slot3-s.save")
PREVIOUS = ROOT / 'NG_reload_reload_20261006.dat1'
NAMES = ['INTRO', 'UNLOAD_APT', 'START', 'FIRST_STOP', 'FIRST_STOP_INTRO',
         'FIRST_STOP_MELEE', 'FIRST_STOP_DODGE', 'FIRST_STOP_WEBSTRIKE',
         'SECOND_STOP', 'SECOND_STOP_FINISH', 'GET_TO_FISK']
HASHES = [0x96ef1f34, 0xee49fa3b, 0x13938f9b, 0x51d959a5, 0x9c5bd5dc,
          0x49b96b5d, 0x1731da72, 0xad48a1ca, 0xb70583f4, 0xf43e958c,
          0xab721a52]

def capture(path):
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), 'Save changed during read'
    magic, version, size, count = struct.unpack_from('<4I', data)
    assert magic == 0x44415431 and len(data) == size and count < 100
    result = {'path': str(path), 'size': size, 'sha256': hashlib.sha256(data).hexdigest(),
              'mtime_utc': datetime.datetime.fromtimestamp(after.st_mtime, datetime.timezone.utc).isoformat(),
              'DAT1_version': version, 'DAT1_sections': count, 'metadata_roots': [],
              'prologue_objective_tables': [], 'section_sizes_and_hashes': {}}
    marker = bytes.fromhex('0000000044001503')
    signature = struct.pack('<2I', 0x3705d72b, 11)
    for i in range(count):
        tag, start, length = struct.unpack_from('<3I', data, 16+i*12)
        assert start + length <= size
        raw = data[start:start+length]
        result['section_sizes_and_hashes'][hex(tag)] = {'size': length, 'sha256': hashlib.sha256(raw).hexdigest()}
        pos = start
        while True:
            pos = data.find(marker, pos, start+length)
            if pos < 0:
                break
            try:
                values = select(Parser(data, pos, start+length).obj())
                if values:
                    result['metadata_roots'].append({'section_tag': hex(tag), 'file_offset': hex(pos), 'fields': values})
            except (AssertionError, ValueError, KeyError, UnicodeError, struct.error):
                pass
            pos += 8
        if tag != 0xeb364589:
            continue
        pos = 0
        while True:
            pos = raw.find(signature, pos)
            if pos < 0:
                break
            for stride in (20, 24):
                if pos+8+11*stride > length:
                    continue
                words = [list(struct.unpack_from('<'+'I'*(stride//4), raw, pos+8+j*stride)) for j in range(11)]
                if [row[0] for row in words] != HASHES:
                    continue
                result['prologue_objective_tables'].append({'section_relative_offset': hex(pos), 'stride': stride,
                    'rows': [{'runtime_label': name, 'objective_hash': hex(row[0]), 'words_raw': row} for name, row in zip(NAMES, words)]})
            pos += 1
    return result

if __name__ == '__main__':
    old = capture(PREVIOUS)
    assert old['sha256'] == 'de29a47bfd6d4925069523e9f940eb1ecac0ebb6c9adac9962e9c0f364b7a0b7'
    new = capture(CURRENT)
    payload = {'snapshot_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'previous_0724_snapshot': old, 'current_slot3': new}
    out = ROOT / '设定档4再次对照前核验_20261006.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    for label, item in [('previous', old), ('current', new)]:
        print(label, 'size', item['size'], 'sha256', item['sha256'], 'mtime', item['mtime_utc'])
        for node in item['metadata_roots']:
            print(json.dumps(node['fields'], ensure_ascii=False))
        for table in item['prologue_objective_tables']:
            print('MSFX', table['section_relative_offset'], 'stride', table['stride'], 'states', [row['words_raw'][1] for row in table['rows']])
    print('Diagnostic:', out)
