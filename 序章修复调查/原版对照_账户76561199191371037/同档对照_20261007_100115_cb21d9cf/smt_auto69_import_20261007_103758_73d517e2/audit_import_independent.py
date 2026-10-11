"""Independent read-only verification of import and preserved test save."""
from pathlib import Path
import datetime, hashlib, json, sys
RUN=Path(__file__).resolve().parent
SESSION=RUN.parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_native_progress_153117 as parser
state_file=SESSION/'state.json'
state_data=state_file.read_bytes();state=json.loads(state_data)
plan_file=RUN/'plan.json'
plan_data=plan_file.read_bytes();plan=json.loads(plan_data)
before=state['source_manifest']
paths=plan['paths']
current=baseline.manifest(Path(paths['Save']))
original=baseline.manifest(Path(paths['original']))
freeze=baseline.manifest(Path(paths['frozen_full']))
native=baseline.manifest(Path(state['paths']['native']))
preserved=baseline.manifest(SESSION/'native_test_save')
current2=baseline.manifest(Path(paths['Save']))
file_changes=[name for name in sorted(current['files'].keys()|before['files'].keys()) if current['files'].get(name)!=before['files'].get(name)]
source_auto=Path(plan['source_auto'])
auto69=source_auto.read_bytes()
assert hashlib.sha256(auto69).hexdigest()=='69d891dd71de75a97028d59de930656960f3b8268159921e7b490d8ee79b9747'
source=source_auto
after=SESSION/'native_test_save'/'slot3-s.save'
afterdata=after.read_bytes();afterdata2=after.read_bytes()
assert afterdata==afterdata2,'Preserved test save changed during read'
parser.decoder.EXPECTED={source:hashlib.sha256(auto69).hexdigest(),after:hashlib.sha256(afterdata).hexdigest()}
a,ad=parser.decoder.decode(source);b,bd=parser.decoder.decode(after)
labels=parser.runtime_labels();am,bm=parser.MSFX(a,ad,labels),parser.MSFX(b,bd,labels)
msfx_changes={
 'global_missions':parser.decoder.diff(am['global_mission_states'],bm['global_mission_states']),
 'objective_tables':parser.decoder.diff(am['objective_tables'],bm['objective_tables'])}
comparison={'before':a,'after':b,'before_metadata':parser.metadata(a),'after_metadata':parser.metadata(b),
 'metadata_diff':parser.decoder.diff(parser.metadata(a),parser.metadata(b)),
 'MSFX_changes':msfx_changes,
 'segments_root_diff':parser.decoder.diff(a['sections']['0x1cea6ceb']['objects'][0]['object'],b['sections']['0x1cea6ceb']['objects'][0]['object']),
 'section_comparison':parser.comparison(a,b)}
result={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Read only; no native/SMT/game/session-state modifications',
 'current_smt_manifest':current,'current_smt_stable_during_audit':current==current2,
 'current_smt_count':len(current['files']),'changed_files_vs_original_state':file_changes,
 'current_matches_import_after_manifest':current==plan['after_manifest'],
 'all_other22_match_state':len(current['files'])==23 and file_changes==['slot3-s.save'],
 'd_original_manifest':original,'d_original_all23_match_state':original==before,
 'c_full_freeze_manifest':freeze,'c_full_freeze_all23_match_state':freeze==before,
 'native_manifest':native,'native_restored_all3_match_state':native==state['native_original_manifest'],
 'source_auto69_sha256':hashlib.sha256(auto69).hexdigest(),
 'current_slot3_equals_entire_source_auto69':(Path(paths['Save'])/'slot3-s.save').read_bytes()==auto69,
 'preserved_native_manifest':preserved,'preserved_auto_comparison':comparison,
 'binaries':baseline.binaries(baseline.ENV),
 'processes':baseline.processes(),
 'state_unchanged':state_file.read_bytes()==state_data,'plan_unchanged':plan_file.read_bytes()==plan_data,
 'session_journal':baseline.read_events(SESSION),'import_journal':baseline.read_events(RUN),
 'validation_limit':'This verifies import files and rollback preservation; it is not an SMT gameplay/reload test.'}
out=RUN/'独立只读核验.json'
assert not out.exists()
out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('checks',{k:v for k,v in result.items() if isinstance(v,bool) or k in ['current_smt_count','changed_files_vs_original_state','processes']})
print('preserved',b['sha256'],b['size'])
print('metadata_diff',comparison['metadata_diff'])
print('MSFX',msfx_changes)
print('segment_changes',comparison['segments_root_diff'])
print('binaries',{k:{x:y for x,y in v.items() if x in ['sha256','matches']} for k,v in result['binaries'].items()})
