"""Freeze vanilla69 natural progression with an open exit; compare same-stage files."""
from pathlib import Path
import datetime, hashlib, json, sys, uuid
SESSION=Path(__file__).resolve().parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_native_progress_153117 as parser
state=json.loads((SESSION/'state.json').read_text(encoding='utf-8'))
stage=SESSION/'native69_comparison_20261007_150938_74a58f95'
plan=json.loads((stage/'plan.json').read_text(encoding='utf-8'))
native=Path(plan['native'])
assert native.name=='76561199191371037'
assert any(p['pid']==25988 for p in baseline.processes()),'Expected vanillaPID25988 absent'
identity=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
RUN=SESSION/('原版69自然推进门开只读核验_'+identity)
RUN.mkdir()
first=baseline.manifest(native)
snapshot=RUN/'native_test_snapshot'
baseline.copy_verified(native,snapshot,first)
last=baseline.manifest(native);copied=baseline.manifest(snapshot)
assert first==last==copied,'Native files changed while copy in progress'
cutoff=datetime.datetime.now(datetime.timezone.utc)
paths={'input69':Path(plan['source_auto']),
 'SMT201_same_goal_closed':Path(state['paths']['freeze'])/'slot3-s.save',
 'vanilla69_natural_open':snapshot/'slot3-s.save'}
pins={paths['input69']:'69d891dd71de75a97028d59de930656960f3b8268159921e7b490d8ee79b9747',
 paths['SMT201_same_goal_closed']:'20196723940a8d1d4e392e2acbd1ef520bdf2be8e4bd4fb69b5b6a31c7884e7a',
 paths['vanilla69_natural_open']:hashlib.sha256(paths['vanilla69_natural_open'].read_bytes()).hexdigest()}
parser.decoder.EXPECTED=pins
labels=parser.runtime_labels();items={};raw_files={}
for name,path in paths.items():
 decoded,data=parser.decoder.decode(path);raw_files[name]=data
 msfx=parser.MSFX(decoded,data,labels);msfx.pop('raw_hex')
 tables=msfx['objective_tables']
 items[name]={'decoded':decoded,'metadata':parser.metadata(decoded),'MSFX':msfx,
 'segments_root':decoded['sections']['0x1cea6ceb']['objects'][0]['object'],
 'two_tables_consistent':len(tables)==2 and [r['words_raw'][:5] for r in tables[0]['rows']]==[r['words_raw'][:5] for r in tables[1]['rows']]}
comparisons={}
for name in ['input69','SMT201_same_goal_closed']:
 a,b=items[name],items['vanilla69_natural_open']
 details=[]
 for tag,x in a['decoded']['sections'].items():
  y=b['decoded']['sections'][tag]
  xb=raw_files[name][x['start']:x['start']+x['size']]
  yb=raw_files['vanilla69_natural_open'][y['start']:y['start']+y['size']]
  row={'tag':tag,'before_size':len(xb),'after_size':len(yb),'bytes_equal':xb==yb}
  if xb!=yb:
   if len(xb)==len(yb):
    ranges=[]
    for i,(v,w) in enumerate(zip(xb,yb)):
     if v!=w:
      if ranges and ranges[-1][1]==i:ranges[-1][1]=i+1
      else:ranges.append([i,i+1])
    row['changed_byte_count']=sum(e-s for s,e in ranges)
    row['changed_ranges']=[{'relative_start':s,'relative_end':e,'before_hex':xb[s:e].hex(),'after_hex':yb[s:e].hex()} for s,e in ranges]
   else:row.update({'before_hex':xb.hex(),'after_hex':yb.hex()})
  details.append(row)
 comparisons[name]={'metadata':parser.decoder.diff(a['metadata'],b['metadata']),
 'global_missions':parser.decoder.diff(a['MSFX']['global_mission_states'],b['MSFX']['global_mission_states']),
 'objective_tables':parser.decoder.diff(a['MSFX']['objective_tables'],b['MSFX']['objective_tables']),
 'segments_root':parser.decoder.diff(a['segments_root'],b['segments_root']),
 'sections':parser.comparison(a['decoded'],b['decoded']),'raw_sections':details}
observer_log=ROOT/'记录'/'20261007T071311_048031Z.jsonl'
records=[json.loads(line) for line in observer_log.read_text(encoding='utf-8').splitlines()]
assert any(r.get('event')=='attached_read_only' and r.get('data',{}).get('pid')==25988 for r in records)
matches=[(r['utc'],m) for r in records if datetime.datetime.fromisoformat(r['utc'])<=cutoff for m in r.get('data',{}).get('missions',[]) if m.get('mission_name_raw')=='GP_A1_FISK']
obs_utc,obs=matches[-1]
current=items['vanilla69_natural_open']
disk=[(r['runtime_name'],r['words_raw'][1]) for r in current['MSFX']['objective_tables'][0]['rows']]
live=[(r['name_raw'],r['state_raw']) for r in obs['objectives']]
payload={'captured_utc':cutoff.isoformat(),
 'scope':'Read/copy diagnostic files only; no native/SMT/proxy/UI/runtime/state mutations',
 'user_confirmed_result':'Vanilla PID25988 naturally progressed from valid69 to FIRST_EXPLOSION/调查爆炸; exit open and user can continue; paused.',
 'separate_case_note':'This natural69 open-door case is different from earlier vanilla loaded201 closed-door recurrence.',
 'stable_three_manifests':True,'source_first':first,'source_last':last,'snapshot_manifest':copied,'file_count':len(copied['files']),
 'native_changes_vs_installed69':parser.decoder.diff(plan['after'],copied),
 'items':items,'comparisons':comparisons,
 'observer':{'source':str(observer_log),'utc':obs_utc,'mission':obs,'all29_raw_names_states_match_disk':disk==live},
 'processes_at_end':baseline.processes(),
 'validation_limit':'Open exit during natural progression and a persisted save do not establish exit/re-entry success.'}
out=RUN/'审计.json'
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('stable_full_copy_count',payload['file_count'],'processes',payload['processes_at_end'])
print('CURRENT',current['decoded']['sha256'],current['decoded']['size'],'tables_consistent',current['two_tables_consistent'])
print('metadata',current['metadata'])
for name,cmp in comparisons.items():
 print('COMPARE',name,'metadata',cmp['metadata'],'global',cmp['global_missions'],'goals',cmp['objective_tables'])
 print('changed_sections',[(s['tag'],s['before_size'],s['after_size'],s.get('changed_byte_count')) for s in cmp['raw_sections'] if not s['bytes_equal']])
print('observer',obs_utc,'match',disk==live)
