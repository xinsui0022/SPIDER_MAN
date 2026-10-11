"""Read-only pinned DAT1 comparison. Writes diagnostic outputs beside this script."""
from pathlib import Path
import hashlib
import json
import struct
import datetime
from read_save_metadata import Parser

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'NG_reload_source_20261006.dat1'
CURRENT = ROOT / 'NG_reload_reload_20261006.dat1'
EXPECTED = {
    SOURCE: 'ae64678c0e02ccba5b2721770af3d08cdbc0810866421232349e09e97835e7d5',
    CURRENT: 'de29a47bfd6d4925069523e9f940eb1ecac0ebb6c9adac9962e9c0f364b7a0b7',
}

def decode(path):
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    assert sha == EXPECTED[path], (str(path), sha)
    magic, version, size, count = struct.unpack_from('<4I', data)
    assert magic == 0x44415431 and size == len(data)
    result = {'path': str(path), 'sha256': sha, 'size': size,
              'version': version, 'sections': {}}
    marker = bytes.fromhex('0000000044001503')
    for i in range(count):
        tag, start, length = struct.unpack_from('<3I', data, 16 + i*12)
        assert start + length <= size
        raw = data[start:start+length]
        roots, failures = [], []
        pos = start
        while True:
            pos = data.find(marker, pos, start+length)
            if pos < 0:
                break
            try:
                root = Parser(data, pos, start+length).obj()
                roots.append({'relative_offset': pos-start, 'object': root})
            except (AssertionError, ValueError, KeyError, UnicodeError, struct.error) as e:
                failures.append({'relative_offset': pos-start, 'error': str(e)})
            pos += 8
        result['sections'][hex(tag)] = {
            'start': start, 'size': length,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'objects': roots, 'failures': failures,
        }
    return result, data

def diff(a, b, path=''):
    if type(a) != type(b):
        return [{'path': path, 'before': a, 'after': b}]
    if isinstance(a, dict):
        out = []
        for key in sorted(a.keys() | b.keys()):
            child = path + '.' + key if path else key
            if key not in a or key not in b:
                out.append({'path': child, 'before': a.get(key), 'after': b.get(key),
                            'presence_changed': True})
            else:
                out.extend(diff(a[key], b[key], child))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [{'path': path, 'before_count': len(a), 'after_count': len(b),
                     'before': a, 'after': b}]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(diff(x, y, path + f'[{i}]'))
        return out
    return [] if a == b else [{'path': path, 'before': a, 'after': b}]

def main():
    a, ad = decode(SOURCE)
    b, bd = decode(CURRENT)
    changes = []
    for tag in a['sections']:
        x, y = a['sections'][tag], b['sections'][tag]
        changes.append({'tag': tag, 'before_size': x['size'], 'after_size': y['size'],
                        'bytes_equal': x['sha256'] == y['sha256'],
                        'before_objects': len(x['objects']), 'after_objects': len(y['objects']),
                        'object_changes': diff(x['objects'], y['objects'])})
    # MSFX prologue records are compared as raw words. Objective labels come
    # from the independently observed runtime order, not from decoding a save
    # symbol table or assuming a particular enum meaning.
    names = ['INTRO', 'UNLOAD_APT', 'START', 'FIRST_STOP', 'FIRST_STOP_INTRO',
             'FIRST_STOP_MELEE', 'FIRST_STOP_DODGE', 'FIRST_STOP_WEBSTRIKE',
             'SECOND_STOP', 'SECOND_STOP_FINISH', 'GET_TO_FISK']
    objective_tables = []
    for label, decoded, data in [('before', a, ad), ('after', b, bd)]:
        section = decoded['sections']['0xeb364589']
        raw = data[section['start']:section['start']+section['size']]
        tables = []
        for offset, stride in [(0xdcb, 0x18), (0x2e98, 0x14)]:
            assert struct.unpack_from('<2I', raw, offset) == (0x3705d72b, 11)
            rows = []
            for i in range(11):
                at = offset + 8 + i*stride
                words = list(struct.unpack_from('<'+'I'*(stride//4), raw, at))
                rows.append({'index': i, 'runtime_label': names[i],
                             'section_relative_offset': hex(at),
                             'objective_hash_raw': hex(words[0]), 'words_raw': words})
            tables.append({'header_offset': hex(offset), 'stride': stride, 'rows': rows})
        objective_tables.append({'label': label, 'tables': tables})
    payload = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'before': a, 'after': b, 'section_comparison': changes,
               'raw_MSFX_objective_tables': objective_tables}
    out = ROOT / 'NG二次进入完整差异_20261006.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in changes:
        if row['bytes_equal']:
            continue
        print(row['tag'], row['before_size'], '->', row['after_size'],
              'objects', row['before_objects'], row['after_objects'],
              'field_changes', len(row['object_changes']))
        for item in row['object_changes']:
            s = json.dumps(item, ensure_ascii=False)
            print(s[:700])
    print('Output:', out)

if __name__ == '__main__':
    main()
