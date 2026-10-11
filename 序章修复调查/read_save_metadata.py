"""Read-only DAT1 metadata snapshot; writes JSON only inside diagnosis directory."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import struct


class Parser:
    def __init__(self, data, pos, end):
        self.data, self.pos, self.root, self.end = data, pos, pos, end

    def take(self, fmt):
        size = struct.calcsize(fmt)
        assert self.pos + size <= self.end
        value = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return value[0] if len(value) == 1 else value

    def align(self):
        self.pos += (4 - (self.pos - self.root) % 4) % 4

    def obj(self):
        zero, tag, count, length = self.take('<4I')
        assert zero == 0 and tag == 0x03150044 and count <= 4096
        start = self.pos
        heads = [self.take('<IHBB') for _ in range(count)]
        names = [self.take('<I') for _ in range(count)]
        out = {}
        for head, offset in zip(heads, names):
            name = self.data[offset:self.data.index(0, offset)].decode()
            count = head[1] >> 4
            assert count <= 4096
            values = [self.node(head[3]) for _ in range(max(1, count))]
            out[name] = values if count > 1 else values[0]
        self.align()
        assert self.pos <= start + length <= self.end
        self.pos = start + length
        return out

    def node(self, kind):
        if kind == 13:
            return self.obj()
        if kind == 15:
            return bool(self.take('<B'))
        if kind == 19:
            self.take('<B')
            return None
        if kind == 10:
            length = self.take('<I')
            self.take('<I')
            self.take('<Q')
            value = self.data[self.pos:self.pos + length].decode()
            self.pos += length
            self.take('<B')
            self.align()
            return value
        return self.take({0: '<B', 1: '<H', 2: '<I', 3: '<Q', 4: '<b',
                          5: '<h', 6: '<i', 7: '<q', 8: '<f', 9: '<d',
                          17: '<Q'}[kind])


EXACT = {'CurrentLevel', 'CurrentCheckpoint', 'CurrentCheckpointId',
         'CurrentLightingMode', 'CurrentLightingModeValid', 'PlaythroughSegmentId',
         'PlayerLevel', 'GamePercent', 'NewGamePlus', 'NewGamePlusNewGame',
         'NewGamePlusUnlocked', 'ActiveMissionHash', 'LocationHash', 'LastSaveTime',
         'SlotDifficulty', 'LowestDifficultyEverSet', 'TotalPlayTime'}


def select(value, prefix=''):
    found = {}
    if isinstance(value, dict):
        for name, child in value.items():
            path = prefix + name
            if name in EXACT or 'position' in name.lower() or 'perch' in name.lower():
                found[path] = child
            elif isinstance(child, (dict, list)):
                found.update(select(child, path + '.'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                found.update(select(child, prefix + str(index) + '.'))
    return found


def snapshot(path):
    data = path.read_bytes()
    magic, version, size, count = struct.unpack_from('<4I', data)
    assert magic == 0x44415431 and size == len(data)
    sections = [struct.unpack_from('<3I', data, 16 + index * 12)
                for index in range(count)]
    assert all(start + length <= len(data) for tag, start, length in sections)
    roots, errors = [], 0
    marker = bytes.fromhex('0000000044001503')
    for tag, start, length in sections:
        pos = start
        while True:
            pos = data.find(marker, pos, start + length)
            if pos < 0:
                break
            try:
                fields = select(Parser(data, pos, start + length).obj())
                if fields:
                    roots.append({'section_tag': hex(tag), 'file_offset': hex(pos),
                                  'fields': fields})
            except (AssertionError, ValueError, KeyError, UnicodeError, struct.error):
                errors += 1
            pos += 8
    return {'path': str(path), 'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'mtime_utc': datetime.datetime.fromtimestamp(path.stat().st_mtime,
                         datetime.timezone.utc).isoformat(),
            'DAT1_version': version, 'DAT1_sections': count,
            'matching_objects': roots, 'unparsed_marker_candidates': errors}


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('output_name')
    cli.add_argument('saves', nargs='+')
    args = cli.parse_args()
    output = (Path(__file__).parent / args.output_name).resolve()
    assert output.parent == Path(__file__).resolve().parent and output.suffix == '.json'
    payload = {'snapshot_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'files': [snapshot(Path(name)) for name in args.saves]}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    output.write_text(rendered, encoding='utf-8')
    print(rendered)
    print('Diagnostic JSON: ' + str(output))
