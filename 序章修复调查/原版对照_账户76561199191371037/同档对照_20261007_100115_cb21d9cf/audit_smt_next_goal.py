"""Freeze paused SMT saves again; compare checkpoints with auto69 and prior 9ba."""
from pathlib import Path
import datetime, hashlib, json, sys, uuid
SESSION=Path(__file__).resolve().parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_native_progress_153117 as parser
identity=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
RUN=SESSION/('SMT下一目标只读核验_'+identity)
RUN.mkdir()
plan=json.loads((SESSION/'smt_auto69_import_20261007_103758_73d517e2'/'plan.json').read_text(encoding='utf-8'))
source=Path(plan['paths']['Save'])
assert source==baseline.ENV.saves
first=baseline.manifest(source)
snapshot=RUN/'SMT_Save_snapshot'
baseline.copy_verified(source,snapshot,first)
last=baseline.manifest(source);copied=baseline.manifest(snapshot)
stable=first==last==copied
assert stable,'SMT source changed while snapshot copied'
cutoff=datetime.datetime.now(datetime.timezone.utc)
paths={
 'auto69':Path(plan['source_auto']),
 'previous_9ba':SESSION/'SMT主机推进只读核验_20261007T024714Z_4b2cd7fe'/'SMT_Save_snapshot'/'slot3-s.save',
 'current':snapshot/'slot3-s.save',
}
parser.decoder.EXPECTED={paths['auto69']:'69d891dd71de75a97028d59de930656960f3b8268159921e7b490d8ee79b9747',
 paths['previous_9ba']:'9ba1902b83714d33b5fe1e2e8ab7cd43f32a07f7769b42d668fb9629b39eaff5',
 paths['current']:hashlib.sha256(paths['current'].read_bytes()).hexdigest()}
labels=parser.runtime_labels();items={}
for name,path in paths.items():
 decoded,data=parser.decoder.decode(path)
 msfx=parser.MSFX(decoded,data,labels);msfx.pop('raw_hex')
 tables=msfx['objective_tables']
 consistent=len(tables)==2 and [r['words_raw'][:5] for r in tables[0]['rows']]==[r['words_raw'][:5] for r in tables[1]['rows']]
 items[name]={'decoded':decoded,'metadata':parser.metadata(decoded),'MSFX':msfx,
 'segments_root':decoded['sections']['0x1cea6ceb']['objects'][0]['object'],
 'two_tables_consistent':consistent}
comparisons={}
for name in ['auto69','previous_9ba']:
 a,b=items[name],items['current']
 comparisons[name]={'metadata':parser.decoder.diff(a['metadata'],b['metadata']),
 'global_missions':parser.decoder.diff(a['MSFX']['global_mission_states'],b['MSFX']['global_mission_states']),
 'objective_tables':parser.decoder.diff(a['MSFX']['objective_tables'],b['MSFX']['objective_tables']),
 'segments_root':parser.decoder.diff(a['segments_root'],b['segments_root']),
 'sections':parser.comparison(a['decoded'],b['decoded'])}
observer_log=ROOT/'记录'/'20261007T024320_772534Z.jsonl'
records=[json.loads(line) for line in observer_log.read_text(encoding='utf-8').splitlines()]
matches=[(r['utc'],m) for r in records if datetime.datetime.fromisoformat(r['utc'])<=cutoff for m in r.get('data',{}).get('missions',[]) if m.get('mission_name_raw')=='GP_A1_FISK']
obs_utc,obs=matches[-1]
disk=[(r['runtime_name'],r['words_raw'][1]) for r in items['current']['MSFX']['objective_tables'][0]['rows']]
live=[(r['name_raw'],r['state_raw']) for r in obs['objectives']]
changed=[key for key in sorted(plan['after_manifest']['files'].keys()|copied['files'].keys()) if plan['after_manifest']['files'].get(key)!=copied['files'].get(key)]
payload={'captured_utc':cutoff.isoformat(),'scope':'Read/freeze diagnostic copy only; no source/native/UI/runtime/state changes',
 'user_reported_goal':'调查爆炸 (explicit user correction, not inferred localization)',
 'stable_manifests':stable,'file_count':len(copied['files']),
 'source_first':first,'source_last':last,'snapshot_manifest':copied,
 'changed_files_vs_auto69_import':changed,'items':items,'comparisons':comparisons,
 'observer':{'source':str(observer_log),'last_fisk_utc':obs_utc,
 'all29_raw_names_states_match_saved_table':disk==live,'mission':obs},
 'processes_at_end':baseline.processes(),
 'validation_limit':'Requires a new exit/re-entry check. Do not infer scene reload success from objective advancement alone.'}
out=RUN/'审计.json'
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('snapshot_stable',stable,'count',payload['file_count'],'changed',changed)
print('current',items['current']['decoded']['sha256'],items['current']['decoded']['size'])
print('metadata',items['current']['metadata'])
print('previous_metadata_changes',comparisons['previous_9ba']['metadata'])
print('previous_goals',comparisons['previous_9ba']['objective_tables'])
print('segments',comparisons['previous_9ba']['segments_root'])
print('observer',obs_utc,'match',disk==live,'states',live)
print('processes',payload['processes_at_end'])
