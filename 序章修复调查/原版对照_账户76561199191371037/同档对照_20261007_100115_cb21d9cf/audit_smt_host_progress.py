"""Read/copy all SMT files to diagnostics, verify both manifests, inspect progress."""
from pathlib import Path
import datetime, hashlib, json, sys, uuid
SESSION=Path(__file__).resolve().parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_native_progress_153117 as parser
identity=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
RUN=SESSION/('SMT主机推进只读核验_'+identity)
RUN.mkdir()
state=json.loads((SESSION/'state.json').read_text(encoding='utf-8'))
import_run=SESSION/'smt_auto69_import_20261007_103758_73d517e2'
plan=json.loads((import_run/'plan.json').read_text(encoding='utf-8'))
source=Path(plan['paths']['Save'])
assert source==baseline.ENV.saves
manifest_first=baseline.manifest(source)
snapshot=RUN/'SMT_Save_snapshot'
baseline.copy_verified(source,snapshot,manifest_first)
manifest_last=baseline.manifest(source)
manifest_copy=baseline.manifest(snapshot)
stable=manifest_first==manifest_last==manifest_copy
assert stable,'Source/copy manifest instability, refuse using mixed save snapshot'
before=plan['after_manifest']
changed=[key for key in sorted(before['files'].keys()|manifest_copy['files'].keys()) if before['files'].get(key)!=manifest_copy['files'].get(key)]
auto69=Path(plan['source_auto'])
current=snapshot/'slot3-s.save'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
parser.decoder.EXPECTED={auto69:'69d891dd71de75a97028d59de930656960f3b8268159921e7b490d8ee79b9747',current:sha(current)}
a,ad=parser.decoder.decode(auto69);b,bd=parser.decoder.decode(current)
labels=parser.runtime_labels()
am,bm=parser.MSFX(a,ad,labels),parser.MSFX(b,bd,labels)
am.pop('raw_hex');bm.pop('raw_hex')
tables=bm['objective_tables']
consistent=len(tables)==2 and [r['words_raw'][:5] for r in tables[0]['rows']]==[r['words_raw'][:5] for r in tables[1]['rows']]
comparison={'before':a,'after':b,'before_metadata':parser.metadata(a),'after_metadata':parser.metadata(b),
 'before_MSFX':am,'after_MSFX':bm,'current_two_tables_consistent':consistent,
 'metadata_diff':parser.decoder.diff(parser.metadata(a),parser.metadata(b)),
 'global_diff':parser.decoder.diff(am['global_mission_states'],bm['global_mission_states']),
 'objective_tables_diff':parser.decoder.diff(am['objective_tables'],bm['objective_tables']),
 'segments_diff':parser.decoder.diff(a['sections']['0x1cea6ceb']['objects'][0]['object'],b['sections']['0x1cea6ceb']['objects'][0]['object']),
 'section_comparison':parser.comparison(a,b)}
other={}
for key in changed:
 if key=='slot3-s.save':continue
 path=snapshot/key
 item={'before':before['files'].get(key),'after':manifest_copy['files'].get(key)}
 if path.suffix=='.save':
  try:
   parser.decoder.EXPECTED[path]=sha(path)
   decoded,_=parser.decoder.decode(path)
   item['decoded_reflection']=decoded
  except Exception as e:item['decode_error']=str(e)
 other[key]=item
payload={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Read/copy diagnostics only; no SMT/native or UI/runtime/state mutations',
 'source':str(source),'snapshot':str(snapshot),'stable_manifests':stable,
 'source_first':manifest_first,'source_last':manifest_last,'snapshot_manifest':manifest_copy,
 'copy_count':len(manifest_copy['files']),'changes_since_auto69_import':changed,
 'other22_changed':other,'slot3_comparison':comparison,
 'processes_at_end':baseline.processes(),
 'interpretation_limit':'This verifies in-session host progress saved to disk. It is not an SMT exit/re-entry test.'}
out=RUN/'审计.json'
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('snapshot',snapshot,'count',payload['copy_count'],'stable',stable)
print('current_sha',b['sha256'],'size',b['size'],'two_tables_consistent',consistent)
print('changed',changed,'other22',list(other))
print('metadata',comparison['metadata_diff'])
print('global',comparison['global_diff'])
print('objectives',comparison['objective_tables_diff'])
print('segments',comparison['segments_diff'])
print('processes',payload['processes_at_end'])
