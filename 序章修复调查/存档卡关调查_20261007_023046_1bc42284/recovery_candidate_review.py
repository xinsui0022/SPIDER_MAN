"""Read only complete DAT1 recovery candidate comparison, no game/save mutations."""
from pathlib import Path
import sys, json, hashlib, datetime

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import diff_native_progress_153117 as p

CANDIDATES={
    'current_snapshot': HERE/'当前SMT_Save_只读快照'/'slot3-s.save',
    'before_helper_020010': ROOT/'穿门安装前备份_20261007_020010_6b9342aa'/'SMT_Save'/'slot3-s.save',
    'before_elevator_011528': ROOT/'电梯场景对照_20261007_011528_00a33d52'/'主机存档_测试前'/'slot3-s.save',
    'MOD_reload_verified_e80': ROOT/'联机NG对照_20261006_155424_9e9669ed'/'MOD二次载入后_已暂停'/'slot3-s.save',
    'native_reload_verified_a836': ROOT/'联机NG对照_20261006_155424_9e9669ed'/'frozen_slot3-s.save',
}
p.decoder.EXPECTED={f:hashlib.sha256(f.read_bytes()).hexdigest() for f in CANDIDATES.values()}
labels=p.runtime_labels()
items={}
for label,f in CANDIDATES.items():
    decoded,data=p.decoder.decode(f)
    tables=p.MSFX(decoded,data,labels)['objective_tables']
    metadata=p.metadata(decoded)
    segments=decoded['sections']['0x1cea6ceb']['objects'][0]['object']
    items[label]={'path':str(f),'sha256':decoded['sha256'],'size':decoded['size'],
        'metadata':metadata,'objective_tables':tables,'segments':segments,
        'sections':{tag:{'size':s['size'],'sha256':s['sha256']} for tag,s in decoded['sections'].items()}}
    print(label,decoded['sha256'],decoded['size'])
    for m in metadata: print(json.dumps(m['fields'],ensure_ascii=False))
    for t in tables:
        print(t['runtime_name'],t['stride'],[(row['runtime_name'],row['words_raw'][1:3]) for row in t['rows'] if row['words_raw'][1] or row['words_raw'][2]])
out=HERE/'完整存档恢复候选_只读.json'
out.write_text(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'note':'Only fixed diagnostic copies read. No UI/process memory/save writes. Metadata/table equality does not prove trigger state integrity.', 'files':items},ensure_ascii=False,indent=2),encoding='utf-8')
print('Report',out)
