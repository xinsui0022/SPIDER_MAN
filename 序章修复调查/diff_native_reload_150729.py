"""Read-only pinned comparison of the pre-cancel MOD save and native reload result."""
from pathlib import Path
import datetime
import hashlib
import json
import struct
import diff_reload_save as decoder
from read_save_metadata import select

ROOT = Path(__file__).resolve().parent
SESSION = ROOT / '同档对照_20261006_150729_e523cddc'
BEFORE = SESSION / '用于对照_取消前slot3-s.save'
AFTER = SESSION / '原版退出后slot3-s.save'
decoder.EXPECTED = {
    BEFORE: 'de29a47bfd6d4925069523e9f940eb1ecac0ebb6c9adac9962e9c0f364b7a0b7',
    AFTER: '1c88c230e1900c097f93902946e9ac7e71dab137a6895563336a7b309189fa55',
}
NAMES = ['INTRO', 'UNLOAD_APT', 'START', 'FIRST_STOP', 'FIRST_STOP_INTRO',
         'FIRST_STOP_MELEE', 'FIRST_STOP_DODGE', 'FIRST_STOP_WEBSTRIKE',
         'SECOND_STOP', 'SECOND_STOP_FINISH', 'GET_TO_FISK']
HASHES = [0x96ef1f34, 0xee49fa3b, 0x13938f9b, 0x51d959a5, 0x9c5bd5dc,
          0x49b96b5d, 0x1731da72, 0xad48a1ca, 0xb70583f4, 0xf43e958c,
          0xab721a52]

def table_snapshot(decoded, data):
    section = decoded['sections']['0xeb364589']
    raw = data[section['start']:section['start'] + section['size']]
    signature = struct.pack('<2I', 0x3705d72b, 11)
    at, tables = 0, []
    while True:
        at = raw.find(signature, at)
        if at < 0:
            break
        for stride in (20, 24):
            if at+8+11*stride > len(raw):
                continue
            rows = [list(struct.unpack_from('<'+'I'*(stride//4), raw, at+8+i*stride)) for i in range(11)]
            if [row[0] for row in rows] == HASHES:
                tables.append({'header_relative_offset': hex(at), 'stride': stride,
                               'rows': [{'runtime_label': name, 'objective_hash': hex(row[0]), 'words_raw': row}
                                        for name, row in zip(NAMES, rows)]})
        at += 1
    return {'section_header_hex': raw[:16].hex(), 'tables': tables,
            'raw_hex': raw.hex()}

def metadata(decoded):
    result = []
    for tag, section in decoded['sections'].items():
        for root in section['objects']:
            fields = select(root['object'])
            if fields:
                result.append({'section_tag': tag, 'relative_offset': root['relative_offset'], 'fields': fields})
    return result

def raw_changes(a, ad, b, bd):
    result = {}
    for tag in ('0xeb364589', '0xd0a9df', '0xa806f448'):
        x, y = a['sections'][tag], b['sections'][tag]
        sx = ad[x['start']:x['start']+x['size']]
        sy = bd[y['start']:y['start']+y['size']]
        assert len(sx) == len(sy)
        ranges = []
        for i, (v, w) in enumerate(zip(sx, sy)):
            if v != w:
                if ranges and ranges[-1][1] == i:
                    ranges[-1][1] = i+1
                else:
                    ranges.append([i, i+1])
        result[tag] = {'changed_bytes': sum(end-start for start, end in ranges),
                       'ranges': [{'relative_start': hex(start), 'relative_end': hex(end),
                                   'before_hex': sx[start:end].hex(), 'after_hex': sy[start:end].hex()}
                                  for start, end in ranges]}
    return result

if __name__ == '__main__':
    a, ad = decoder.decode(BEFORE)
    b, bd = decoder.decode(AFTER)
    comparisons = []
    for tag in a['sections']:
        x, y = a['sections'][tag], b['sections'][tag]
        comparisons.append({'tag': tag, 'before_size': x['size'], 'after_size': y['size'],
                            'bytes_equal': x['sha256'] == y['sha256'],
                            'before_objects': len(x['objects']), 'after_objects': len(y['objects']),
                            'object_changes': decoder.diff(x['objects'], y['objects'])})
    payload = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'before': a, 'after': b, 'section_comparison': comparisons,
               'before_metadata': metadata(a), 'after_metadata': metadata(b),
               'before_MSFX': table_snapshot(a, ad), 'after_MSFX': table_snapshot(b, bd),
               'raw_change_details': raw_changes(a, ad, b, bd)}
    out = ROOT / '原版载入取消前档完整差异_20261006_150729.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('BEFORE', a['size'], a['sha256'])
    print('AFTER', b['size'], b['sha256'])
    for item in comparisons:
        if item['bytes_equal']:
            continue
        print('SECTION', item['tag'], item['before_size'], '->', item['after_size'],
              'fieldchanges', len(item['object_changes']))
        for change in item['object_changes'][:70]:
            print(json.dumps(change, ensure_ascii=False)[:600])
    for label in ('before', 'after'):
        print(label, 'metadata')
        for row in payload[label+'_metadata']:
            print(json.dumps(row, ensure_ascii=False))
        print(label, 'MSFX tables')
        for table in payload[label+'_MSFX']['tables']:
            print(table['header_relative_offset'], 'stride', table['stride'], 'states', [row['words_raw'][1] for row in table['rows']])
    print('D0A9DF equal:', a['sections']['0xd0a9df']['sha256'] == b['sections']['0xd0a9df']['sha256'])
    print('Output', out)
