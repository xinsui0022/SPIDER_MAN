"""Freeze the reload failure scene's saves/log/photo without mutating game state."""
from pathlib import Path
import datetime, hashlib, json, shutil, sys, uuid
SESSION=Path(__file__).resolve().parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_native_progress_153117 as parser
identity=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
RUN=SESSION/('SMT重进出口门故障只读核验_'+identity)
RUN.mkdir()
before_processes=baseline.processes()
assert any(p['pid']==22416 and p['name'].casefold()=='spider-man.exe' for p in before_processes),'Expected running PID22416 not present'
source=baseline.ENV.saves
first=baseline.manifest(source)
snapshot=RUN/'SMT_Save_snapshot'
baseline.copy_verified(source,snapshot,first)
last=baseline.manifest(source);copied=baseline.manifest(snapshot)
stable=first==last==copied
assert stable,'Source save changed during snapshot'
cutoff=datetime.datetime.now(datetime.timezone.utc)
paths={
 'before_exit_2019':SESSION/'SMT下一目标只读核验_20261007T024959Z_9cf1fb97'/'SMT_Save_snapshot'/'slot3-s.save',
 'after_reload':snapshot/'slot3-s.save',
}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
parser.decoder.EXPECTED={paths['before_exit_2019']:'20196723940a8d1d4e392e2acbd1ef520bdf2be8e4bd4fb69b5b6a31c7884e7a',
 paths['after_reload']:sha(paths['after_reload'])}
labels=parser.runtime_labels();items={}
for name,path in paths.items():
 decoded,data=parser.decoder.decode(path)
 msfx=parser.MSFX(decoded,data,labels);msfx.pop('raw_hex')
 tables=msfx['objective_tables']
 items[name]={'decoded':decoded,'metadata':parser.metadata(decoded),'MSFX':msfx,
 'segments_root':decoded['sections']['0x1cea6ceb']['objects'][0]['object'],
 'two_tables_consistent':len(tables)==2 and [r['words_raw'][:5] for r in tables[0]['rows']]==[r['words_raw'][:5] for r in tables[1]['rows']]}
a,b=items.values()
comparison={'metadata':parser.decoder.diff(a['metadata'],b['metadata']),
 'global_missions':parser.decoder.diff(a['MSFX']['global_mission_states'],b['MSFX']['global_mission_states']),
 'objective_tables':parser.decoder.diff(a['MSFX']['objective_tables'],b['MSFX']['objective_tables']),
 'segments_root':parser.decoder.diff(a['segments_root'],b['segments_root']),
 'sections':parser.comparison(a['decoded'],b['decoded'])}
prior_manifest=json.loads((SESSION/'SMT下一目标只读核验_20261007T024959Z_9cf1fb97'/'审计.json').read_text(encoding='utf-8'))['snapshot_manifest']
changed=[key for key in sorted(prior_manifest['files'].keys()|copied['files'].keys()) if prior_manifest['files'].get(key)!=copied['files'].get(key)]
observer_log=ROOT/'记录'/'20261007T025726_008540Z.jsonl'
records=[json.loads(line) for line in observer_log.read_text(encoding='utf-8').splitlines()]
assert any(r.get('event')=='attached_read_only' and r.get('data',{}).get('pid')==22416 for r in records),'Observer log does not identify expected process'
matches=[(r['utc'],m) for r in records if datetime.datetime.fromisoformat(r['utc'])<=cutoff for m in r.get('data',{}).get('missions',[]) if m.get('mission_name_raw')=='GP_A1_FISK']
obs_utc,obs=matches[-1]
disk=[(r['runtime_name'],r['words_raw'][1]) for r in b['MSFX']['objective_tables'][0]['rows']]
live=[(r['name_raw'],r['state_raw']) for r in obs['objectives']]
doorlog=baseline.ENV.game_root/'SMT'/'Scripts'/'DoorStep.log'
doorbytes=doorlog.read_bytes();doorbytes2=doorlog.read_bytes()
assert doorbytes==doorbytes2,'DoorStep log changed during read'
(RUN/'DoorStep_现场.log').write_bytes(doorbytes)
creation_hk='2026-10-07T10:56:37.949444+08:00' # Read immediately before capture via CIM for PID22416.
lines=doorbytes.decode('utf-8').splitlines()
current_lines=[line for line in lines if line[:19]>='2026-10-07 10:56:37']
movement_events=[line for line in current_lines if (' ARMED:' in line or 'request queued' in line or ' step applied' in line or 'returned to last step origin' in line)]
photo_source=Path('C:/Users/xinsui/AppData/Local/Temp/codex-clipboard-08ef9faf-c6be-4061-a4eb-240e696eaaf0.png')
photo={'source':str(photo_source),'exists':photo_source.exists()}
if photo_source.exists():
 photo_copy=RUN/'用户现场截图_只读保留.png'
 shutil.copy2(photo_source,photo_copy)
 photo.update({'copied':str(photo_copy),'source_sha256':sha(photo_source),'copied_sha256':sha(photo_copy),'not_edited':True})
payload={'captured_utc':cutoff.isoformat(),
 'scope':'Read/copy diagnostic artifacts only; no source/native/proxy/UI/runtime/state mutations',
 'user_observation':'SMT reload: map objective FIRST_EXPLOSION/调查爆炸 retained; machine-room exit shut; L2+R2 point-launch HELP shown; no bypass requested during this scene.',
 'source_first':first,'source_last':last,'snapshot_manifest':copied,
 'stable_manifests':stable,'file_count':len(copied['files']),'changed_files_since_before_exit':changed,
 'items':items,'comparison':comparison,
 'observer':{'source':str(observer_log),'utc':obs_utc,'mission':obs,'all29_raw_states_match_disk':disk==live},
 'DoorStep':{'source':str(doorlog),'copied':str(RUN/'DoorStep_现场.log'),
 'source_sha256':hashlib.sha256(doorbytes).hexdigest(),'stable_read':True,
 'process_creation_hk_from_CIM':creation_hk,'current_process_log_lines':current_lines,
 'activation_request_warp_return_events':movement_events,
 'log_supports_default_disarmed_no_warp_this_run':bool(current_lines) and not movement_events},
 'photo':photo,'processes_before':before_processes,'processes_at_end':baseline.processes(),
 'validation_limit':'Retained mission objective does not establish scene-object restoration. Same-save vanilla comparison is still needed.'}
out=RUN/'审计.json'
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('stable',stable,'count',payload['file_count'],'changed',changed)
print('current',b['decoded']['sha256'],b['decoded']['size'],'tables_consistent',b['two_tables_consistent'])
print('metadata',comparison['metadata'])
print('global',comparison['global_missions'],'goals',comparison['objective_tables'])
print('segments',comparison['segments_root'])
print('observer',obs_utc,'match',disk==live,'raw_states',live)
print('DoorStep',payload['DoorStep'])
print('photo',photo)
print('processes',payload['processes_at_end'])
