"""Read fixed snapshots only; write audit to the present investigation directory."""
from pathlib import Path
import datetime, hashlib, json, sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import diff_native_progress_153117 as parser

PATHS={
 'current': HERE/'当前SMT_Save_只读快照'/'slot3-s.save',
 'pre_doorstep_020010': ROOT/'穿门安装前备份_20261007_020010_6b9342aa'/'SMT_Save'/'slot3-s.save',
 'pre_elevator_011528': ROOT/'电梯场景对照_20261007_011528_00a33d52'/'主机存档_测试前'/'slot3-s.save',
 'MOD_second_reload': ROOT/'联机NG对照_20261006_155424_9e9669ed'/'MOD二次载入后_已暂停'/'slot3-s.save',
}
expected={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in PATHS.values()}
assert expected[PATHS['current']]=='f0307d2cd827723e76b16414a0257ba7b86d7ecbee3280073a86371ed3d421d8'
assert expected[PATHS['pre_doorstep_020010']]=='911843b9f0214fa0814c5933b66ee7a4010a44eaa1a1f6b3e1078f6819cd5569'
assert expected[PATHS['pre_elevator_011528']]=='9607535f92798647037c24a8c030d2c29a5c417b6e581023ae65215ba81f12fd'
assert expected[PATHS['MOD_second_reload']]=='e80e50fd9758604584be33fd22c7c08e1eff82e9b9ae4f84c3f26aab8f8eee3d'
parser.decoder.EXPECTED=expected
labels=parser.runtime_labels()
items={}
for key,path in PATHS.items():
 d,data=parser.decoder.decode(path)
 m=parser.MSFX(d,data,labels)
 m.pop('raw_hex')
 segments=d['sections']['0x1cea6ceb']['objects']
 items[key]={'decoded':d,'metadata':parser.metadata(d),'MSFX':m,'segments':segments}
 m['tables_duplicate_consistent']=(len(m['objective_tables'])==2 and
  [x['words_raw'][:5] for x in m['objective_tables'][0]['rows']]==
  [x['words_raw'][:5] for x in m['objective_tables'][1]['rows']])
comparisons={}
for name in list(PATHS)[1:]:
 a,b=items[name],items['current']
 ts=[]
 for old,new in zip(a['MSFX']['objective_tables'],b['MSFX']['objective_tables']):
  ts.append({'before_header':old['header_offset'],'after_header':new['header_offset'],
   'stride':old['stride'],'mission_name':old['runtime_name'],
   'changes':[{'index':i,'runtime_name':x['runtime_name'],'before_raw':x['words_raw'],'after_raw':y['words_raw']}
    for i,(x,y) in enumerate(zip(old['rows'],new['rows'])) if x['words_raw']!=y['words_raw']]})
 comparisons[name]={'metadata_diff':parser.decoder.diff(a['metadata'],b['metadata']),
 'section_comparison':parser.comparison(a['decoded'],b['decoded']),
 'mission_state_diff':parser.decoder.diff(a['MSFX']['global_mission_states'],b['MSFX']['global_mission_states']),
 'objective_changes':ts,'segments_diff':parser.decoder.diff(a['segments'],b['segments'])}
payload={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Read-only fixed save comparisons; no runtime/UI or save writes',
 'state_note':'Raw enum values are reported without inferred semantic mapping',
 'runtime_label_source':str(parser.RUNTIME_LOG),'items':items,'comparisons':comparisons}
output=HERE/'存档固定快照比较_只读.json'
output.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
for name,item in items.items():
 print(name,item['decoded']['sha256'],item['decoded']['size'])
 print('metadata',json.dumps(item['metadata'],ensure_ascii=False))
 print('missions',[x for x in item['MSFX']['global_mission_states'] if 'runtime_name' in x])
 print('consistent',item['MSFX']['tables_duplicate_consistent'])
 for t in item['MSFX']['objective_tables']:
  print('table',t['header_offset'],t['stride'],t['runtime_name'],[(x['runtime_name'],x['words_raw'][1:]) for x in t['rows']])
 print('segments',json.dumps(item['segments'],ensure_ascii=False))
for name,cmp in comparisons.items():
 print('COMPARE',name)
 print('metadata',json.dumps(cmp['metadata_diff'],ensure_ascii=False))
 print('objectives',json.dumps(cmp['objective_changes'],ensure_ascii=False))
 print('segments',json.dumps(cmp['segments_diff'],ensure_ascii=False))
print('OUTPUT',output)
