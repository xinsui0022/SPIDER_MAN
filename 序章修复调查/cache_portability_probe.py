"""Read-only structural checks; values are offsets and PE metadata, not identities."""
from pathlib import Path
import collections
import json
import struct

source = Path(r"C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod\HeiheiSMT0.5.1\HeiheiSMT\cache")
game = Path(r"D:\STEAM__\steamapps\common\Marvel's Spider-Man Remastered\Spider-Man.exe")
d = source.read_bytes()
n = struct.unpack_from('<I',d,4)[0]
assert 0 < n < 10000 and len(d) == 8+n*25
rows = [d[8+i*25:8+(i+1)*25] for i in range(n)]
vals = [int.from_bytes(r[12:20],'little') for r in rows]
out = {
    'header_version':struct.unpack_from('<I',d,0)[0],
    'header_count':n,
    'exact_25byte_record_size_match':True,
    'offset8_u32_distribution':dict(collections.Counter(int.from_bytes(r[8:12],'little') for r in rows)),
    'offset12_u64_min':min(vals),
    'offset12_u64_max':max(vals),
    'last_byte_distribution':dict(collections.Counter(r[24] for r in rows)),
    'offset20_u32_distribution':dict(collections.Counter(int.from_bytes(r[20:24],'little') for r in rows)),
}
with game.open('rb') as f:
    f.seek(0x3c)
    pe_offset = int.from_bytes(f.read(4),'little')
    f.seek(pe_offset)
    h = f.read(112)
    assert h[:4] == b'PE\0\0'
    out['game_pe_timestamp'] = int.from_bytes(h[8:12],'little')
    out['game_image_base'] = int.from_bytes(h[48:56],'little')
    out['game_image_size'] = int.from_bytes(h[80:84],'little')
out['all_record_values_below_image_size'] = all(v < out['game_image_size'] for v in vals)
out['all_record_field8_equal_game_timestamp'] = all(int.from_bytes(r[8:12],'little') == out['game_pe_timestamp'] for r in rows)
output = source.parents[2]/'序章修复调查'/'cache可移植性结构_20261006.json'
output.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
