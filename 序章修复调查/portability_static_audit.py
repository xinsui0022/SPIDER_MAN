"""Read-only local MOD portability inventory; no personal string values emitted."""
from pathlib import Path
import hashlib
import json
import re
import zipfile
import pefile

GAME = Path(r"D:\STEAM__\steamapps\common\Marvel's Spider-Man Remastered")
PACKAGE = Path(r"C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod\HeiheiSMT0.5.1\HeiheiSMT")
OUT = Path(r"C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod\序章修复调查\可移植性静态核验_20261006.json")
REL = ['winmm.dll','miniupnpc.dll','discord-rpc.dll','cache','SMT-Launcher.exe','SMT/Scripts/smt.dll','SMT/Assets/UI','SMT/UI/Title.gfx','SMT/UI/SystemOverlay_UIv2.gfx','SMT/UI/POIs.gfx','SMT/UI/Overlay.gfx','SMT/UI/HUD.gfx']

def sha(data):
    return hashlib.sha256(data).hexdigest()

def shape(v):
    if isinstance(v, dict):
        return {k: shape(val) for k, val in v.items()}
    if isinstance(v, list):
        return {'type': 'array', 'length': len(v), 'item_shapes': [shape(x) for x in v]}
    if isinstance(v, str):
        return {'type':'string','length':len(v), 'value':'<not emitted>'}
    return v

result = {'files': [], 'configs': {}, 'imports': {}, 'runtime_path_strings': {}, 'absolute_string_counts': {}}
for rel in REL:
    p = GAME / rel
    q = PACKAGE / rel
    d = p.read_bytes()
    result['files'].append({'relative_path':rel,'bytes':len(d),'sha256':sha(d),'package_same':q.is_file() and sha(q.read_bytes()) == sha(d)})
for name in ['Connections.json', 'Preferences.json', 'Multiplayer.json']:
    p = GAME/'SMT'/name
    result['configs'][name] = {'deployed':shape(json.loads(p.read_text(encoding='utf-8-sig'))),'package':shape(json.loads((PACKAGE/'SMT'/name).read_text(encoding='utf-8-sig')))}
for name in ['winmm.dll','SMT/Scripts/smt.dll','miniupnpc.dll','discord-rpc.dll','steam_api64.dll']:
    d = (GAME/name).read_bytes()
    pe = pefile.PE(data=d)
    result['imports'][name] = [{'dll':x.dll.decode(errors='replace'),'functions':[y.name.decode(errors='replace') if y.name else f'ordinal:{y.ordinal}' for y in x.imports]} for x in getattr(pe,'DIRECTORY_ENTRY_IMPORT',[])]
    printable = [m.group().decode('ascii') for m in re.finditer(rb'[ -~]{5,}',d)]
    allow = []
    for s in printable:
        if (s.startswith('SMT/') or s.startswith('./SMT/') or s in ['-mp','-nolauncher','cache'] or s.startswith('\\System32\\') or s.startswith('configs/')):
            allow.append(s)
    result['runtime_path_strings'][name] = allow
    result['absolute_string_counts'][name] = {'absolute_drive_paths':sum(bool(re.match(r'^[A-Za-z]:[\\/]', s)) for s in printable),'pdb_strings':sum('.pdb' in s.lower() for s in printable)}
archive = PACKAGE.parent.parent/'HeiheiSMT0.5.1.zip'
with zipfile.ZipFile(archive) as z:
    result['zip_entries'] = [{'name':x.filename,'bytes':x.file_size} for x in z.infolist()]
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'output':str(OUT),'files':result['files'],'configs':result['configs'],'runtime_path_strings':result['runtime_path_strings'],'absolute_string_counts':result['absolute_string_counts']},ensure_ascii=False,indent=2))
