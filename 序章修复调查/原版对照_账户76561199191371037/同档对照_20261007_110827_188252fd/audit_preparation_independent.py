"""Independent preparation check; reads only except these diagnosis artifacts."""
from pathlib import Path
import datetime, hashlib, json, re, sys, winreg
SESSION=Path(__file__).resolve().parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_reload_save as decoder
statefile=SESSION/'state.json'
statebytes=statefile.read_bytes();state=json.loads(statebytes)
assert state['session_id']=='20261007_110827_188252fd'
assert state['source_kind']=='smt'
source=Path(state['source_path'])
freeze=Path(state['paths']['freeze'])
native=Path(state['paths']['native'])
original=Path(state['paths']['original'])
disabled=Path(state['paths']['disabled'])
assert source==baseline.ENV.saves
assert native.name=='76561199191371037'
assert freeze==SESSION/'frozen_smt_save'
reference=ROOT/'原版对照_账户76561199191371037'/'同档对照_20261007_100115_cb21d9cf'/'SMT重进出口门故障只读核验_20261007T030311Z_5693881d'/'SMT_Save_snapshot'
ref=baseline.manifest(reference)
processes_first=baseline.processes()
assert not processes_first,'Preparation no longer closed-process state'
actual={}
for name,path in [('source_smt',source),('frozen',freeze),('native_control',native),('native_original_preserved',original)]:
 actual[name]={'path':str(path),'manifest':baseline.manifest(path)}
 actual[name]['matches_recorded_manifest']=(actual[name]['manifest']==
  (state['native_original_manifest'] if name=='native_original_preserved' else state['source_manifest']))
 if name!='native_original_preserved':actual[name]['matches_full_failure_snapshot']=actual[name]['manifest']==ref
source_again=baseline.manifest(source)
with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam\ActiveProcess') as key:
 active_user=winreg.QueryValueEx(key,'ActiveUser')[0]
active_steam64=76561197960265728+int(active_user)
login_path=Path('D:/STEAM__/config/loginusers.vdf')
login_data=login_path.read_text(encoding='utf-8')
autologin_ids=[m.group(1) for m in re.finditer(r'"(765\d+)"\s*\{([^{}]*)\}',login_data,re.S) if re.search(r'"AutoLogin"\s*"1"',m.group(2))]
payload={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Read-only independent verification; no SMT/native/proxy/UI/runtime/state changes',
 'state_source_manifest':state['source_manifest'],'reference_failure_snapshot':str(reference),
 'reference_failure_manifest':ref,'actual':actual,
 'source_stable_during_audit':actual['source_smt']['manifest']==source_again,
 'source_freeze_native_all23_equal_failure_snapshot':all(len(actual[k]['manifest']['files'])==23 and actual[k]['matches_full_failure_snapshot'] for k in ['source_smt','frozen','native_control']),
 'all_other22_retained':all(actual['source_smt']['manifest']['files'].get(k)==v for k,v in ref['files'].items() if k!='slot3-s.save'),
 'native_original_all3_preserved':len(actual['native_original_preserved']['manifest']['files'])==3 and actual['native_original_preserved']['matches_recorded_manifest'],
 'winmm':{'canonical_absent':not baseline.ENV.winmm.exists(),'disabled':str(disabled),
 'disabled_sha256':baseline.sha256(disabled),'expected':state['known_hashes']['winmm']},
 'account':{'prepared_native_account':native.name,'registry_active_user':active_user,
 'registry_steam64':str(active_steam64),'autologin_steam64_ids':autologin_ids,
 'active_matches_prepared_native':str(active_steam64)==native.name and native.name in autologin_ids},
 'journal':baseline.read_events(SESSION),'processes_before':processes_first,'processes_after':baseline.processes(),
 'state_unchanged':statefile.read_bytes()==statebytes,
 'slot3':actual['source_smt']['manifest']['files']['slot3-s.save']}
payload['winmm']['disabled_matches_expected']=payload['winmm']['disabled_sha256']==payload['winmm']['expected']
payload['all_checks_passed']=all([payload['source_stable_during_audit'],payload['source_freeze_native_all23_equal_failure_snapshot'],
 payload['all_other22_retained'],payload['native_original_all3_preserved'],payload['winmm']['canonical_absent'],
 payload['winmm']['disabled_matches_expected'],payload['account']['active_matches_prepared_native'],not payload['processes_after'],payload['state_unchanged']])
out=SESSION/'独立准备只读核验.json'
assert not out.exists()
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('checks',{k:v for k,v in payload.items() if isinstance(v,bool)})
print('counts',[(k,len(v['manifest']['files']),v['matches_recorded_manifest']) for k,v in actual.items()])
print('slot3',payload['slot3'],'account',payload['account'],'winmm',payload['winmm'])
print('journal_last',payload['journal'][-1]['event'],'processes',payload['processes_after'])
