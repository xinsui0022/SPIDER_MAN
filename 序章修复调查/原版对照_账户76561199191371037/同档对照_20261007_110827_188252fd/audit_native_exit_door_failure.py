"""Freeze the running vanilla same-save failure for comparison; no source writes."""
from pathlib import Path
import datetime, hashlib, json, sys, uuid
SESSION=Path(__file__).resolve().parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_native_progress_153117 as parser
state=json.loads((SESSION/'state.json').read_text(encoding='utf-8'))
native=Path(state['paths']['native'])
assert native.name=='76561199191371037'
assert any(p['pid']==22880 for p in baseline.processes()),'Expected PID22880 not present'
identity=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
RUN=SESSION/('原版同201出口门故障只读核验_'+identity)
RUN.mkdir()
first=baseline.manifest(native)
snapshot=RUN/'native_test_snapshot'
baseline.copy_verified(native,snapshot,first)
last=baseline.manifest(native);copied=baseline.manifest(snapshot)
stable=first==last==copied
assert stable,'Native files changed during snapshot copy'
cutoff=datetime.datetime.now(datetime.timezone.utc)
source=Path(state['paths']['freeze'])/'slot3-s.save'
current=snapshot/'slot3-s.save'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
parser.decoder.EXPECTED={source:'20196723940a8d1d4e392e2acbd1ef520bdf2be8e4bd4fb69b5b6a31c7884e7a',current:sha(current)}
labels=parser.runtime_labels();items={}
for name,path in [('input_201',source),('vanilla_loaded',current)]:
 decoded,data=parser.decoder.decode(path)
 msfx=parser.MSFX(decoded,data,labels);msfx.pop('raw_hex')
 items[name]={'decoded':decoded,'metadata':parser.metadata(decoded),'MSFX':msfx,
 'segments_root':decoded['sections']['0x1cea6ceb']['objects'][0]['object']}
a,b=items.values()
comparisons={'metadata':parser.decoder.diff(a['metadata'],b['metadata']),
 'global_missions':parser.decoder.diff(a['MSFX']['global_mission_states'],b['MSFX']['global_mission_states']),
 'objective_tables':parser.decoder.diff(a['MSFX']['objective_tables'],b['MSFX']['objective_tables']),
 'segments_root':parser.decoder.diff(a['segments_root'],b['segments_root']),
 'sections':parser.comparison(a['decoded'],b['decoded'])}
observer_log=ROOT/'记录'/'20261007T031253_519554Z.jsonl'
records=[json.loads(line) for line in observer_log.read_text(encoding='utf-8').splitlines()]
assert any(r.get('event')=='attached_read_only' and r.get('data',{}).get('pid')==22880 for r in records)
matches=[(r['utc'],m) for r in records if datetime.datetime.fromisoformat(r['utc'])<=cutoff for m in r.get('data',{}).get('missions',[]) if m.get('mission_name_raw')=='GP_A1_FISK']
obs_utc,obs=matches[-1]
disk=[(r['runtime_name'],r['words_raw'][1]) for r in b['MSFX']['objective_tables'][0]['rows']]
live=[(r['name_raw'],r['state_raw']) for r in obs['objectives']]
reference=baseline.manifest(Path(state['paths']['freeze']))
payload={'captured_utc':cutoff.isoformat(),
 'scope':'Read/freeze running native test directory only; no SMT/native/proxy/UI/runtime/state changes',
 'user_confirmed_result':'Vanilla same complete 201 save still has closed machine-room exit and cannot continue.',
 'source':str(native),'snapshot':str(snapshot),'source_first':first,'source_last':last,'snapshot_manifest':copied,
 'stable_manifests':stable,'copy_count':len(copied['files']),
 'manifest_diff_vs_complete_201_input':parser.decoder.diff(reference,copied),
 'items':items,'comparisons':comparisons,
 'observer':{'source':str(observer_log),'utc':obs_utc,'mission':obs,'all29_raw_states_match_disk':disk==live},
 'process_and_module_evidence':{'verification_method':'Read-only CIM and Get-Process.Modules immediately before this capture',
 'pid':22880,'creation_hk':'2026-10-07T11:12:33.392069+08:00',
 'command_line':'"D:\\steam__\\steamapps\\common\\Marvel\'s Spider-Man Remastered\\Spider-Man.exe" -nolauncher',
 'matching_modules':[{'module':'WINMM.dll','path':'C:\\WINDOWS\\SYSTEM32\\WINMM.dll'}],
 'smt_dll_loaded':False,'DoorStep_dll_loaded':False,'game_directory_winmm_proxy_loaded':False},
 'processes_at_end':baseline.processes(),
 'interpretation_limit':'Vanilla recurrence shows failure follows this complete saved state, not exclusively active SMT runtime. It does not identify corrupted fields or prove 69 repair.'}
out=RUN/'审计.json'
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('stable',stable,'count',payload['copy_count'])
print('slot3',b['decoded']['sha256'],b['decoded']['size'])
print('metadata',comparisons['metadata'],'global',comparisons['global_missions'],'goals',comparisons['objective_tables'])
print('segments',comparisons['segments_root'])
print('manifest_changes',payload['manifest_diff_vs_complete_201_input'])
print('observer',obs_utc,'match',disk==live,'raw_states',live)
print('processes',payload['processes_at_end'])
