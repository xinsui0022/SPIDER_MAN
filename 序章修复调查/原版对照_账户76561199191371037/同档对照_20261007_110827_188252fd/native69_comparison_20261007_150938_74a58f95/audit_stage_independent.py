"""Read-only stage/preservation verification; native gameplay writes are permitted."""
from pathlib import Path
import datetime, hashlib, json, sys
RUN=Path(__file__).resolve().parent
SESSION=RUN.parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_reload_save as decoder
statefile=SESSION/'state.json';statebytes=statefile.read_bytes();state=json.loads(statebytes)
planfile=RUN/'plan.json';planbytes=planfile.read_bytes();plan=json.loads(planbytes)
installedfile=RUN/'installed.json';installedbytes=installedfile.read_bytes();installed=json.loads(installedbytes)
assert state['session_id']=='20261007_110827_188252fd'
assert Path(plan['native'])==Path(state['paths']['native'])
assert Path(plan['preserved'])==RUN/'native_before'
preserved=baseline.manifest(Path(plan['preserved']))
source=baseline.manifest(Path(state['source_path']))
source_again=baseline.manifest(Path(state['source_path']))
frozen=baseline.manifest(Path(state['paths']['freeze']))
ordinary=baseline.manifest(Path(state['paths']['original']))
native_now=baseline.manifest(Path(plan['native']))
auto=Path(plan['source_auto']);auto_data=auto.read_bytes()
auto_hash=hashlib.sha256(auto_data).hexdigest()
before,after=plan['before'],plan['after']
changed=[k for k in sorted(before['files'].keys()|after['files'].keys()) if before['files'].get(k)!=after['files'].get(k)]
checks={
 'plan_before_count24':len(before['files'])==24,
 'plan_after_count24':len(after['files'])==24,
 'plan_only_slot3_replaced':changed==['slot3-s.save'],
 'source_auto69_matches_pin':auto_hash=='69d891dd71de75a97028d59de930656960f3b8268159921e7b490d8ee79b9747' and len(auto_data)==142398,
 'after_slot3_is_complete_auto69':after['files']['slot3-s.save']=={'size':len(auto_data),'sha256':auto_hash},
 'installed_after_manifest_equals_plan':installed['native_after']==after,
 'installed_before_manifest_equals_plan':installed['preserved_before']==before,
 'preserved_full24_matches_before':len(preserved['files'])==24 and preserved==before,
 'preserved_original_failure_pin':preserved['files']['slot3-s.save']['sha256']=='d4f8c0f39a39c5357b6c51c272ee248c178a85e654a19d073575685787e8ce79',
 'source_smt_full23_matches201_state':len(source['files'])==23 and source==state['source_manifest'],
 'source_smt_slot3_still201':source['files']['slot3-s.save']['sha256']=='20196723940a8d1d4e392e2acbd1ef520bdf2be8e4bd4fb69b5b6a31c7884e7a',
 'source_smt_stable_during_audit':source==source_again,
 'frozen_smt_full23_matches201_state':len(frozen['files'])==23 and frozen==state['source_manifest'],
 'ordinary_original3_preserved':len(ordinary['files'])==3 and ordinary==state['native_original_manifest'],
 'winmm_canonical_absent':not baseline.ENV.winmm.exists(),
 'disabled_winmm_pin_matches':baseline.sha256(Path(state['paths']['disabled']))==state['known_hashes']['winmm'],
 'state_unchanged':statefile.read_bytes()==statebytes,
 'plan_unchanged':planfile.read_bytes()==planbytes,
 'installed_record_unchanged':installedfile.read_bytes()==installedbytes,
}
payload={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Read only; write this diagnostic report only; no SMT/native/proxy/UI/runtime/session-state changes',
 'checks':checks,'all_preparation_checks_passed':all(checks.values()),
 'plan':plan,'installed':installed,'actual_preserved_before':preserved,
 'actual_smt_source':source,'actual_frozen_source':frozen,'actual_ordinary_original':ordinary,
 'native_current_observation':native_now,'native_current_changes_vs_installed':decoder.diff(after,native_now),
 'native_current_observation_limit':'Game has been started after staging and may autosave. Current native equality to initial69 is not a preparation requirement.',
 'proxy_disabled_path':state['paths']['disabled'],'proxy_pin':state['known_hashes']['winmm'],
 'processes_at_end':baseline.processes(),'journal':baseline.read_events(SESSION),
 'validation_limit':'User must complete the corresponding segment and perform exit/re-entry; preparation is not gameplay success.'}
out=RUN/'独立准备复核.json'
assert not out.exists()
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('all_checks',payload['all_preparation_checks_passed'],'checks',checks)
print('plan_delta',changed,'preserved_slot3',preserved['files']['slot3-s.save'])
print('SMT_slot3',source['files']['slot3-s.save'],'native_current_delta',payload['native_current_changes_vs_installed'])
print('processes',payload['processes_at_end'])
