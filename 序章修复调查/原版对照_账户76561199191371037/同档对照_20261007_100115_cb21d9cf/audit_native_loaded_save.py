"""Read native save twice, freeze diagnostic bytes, and compare with frozen input."""
from pathlib import Path
import datetime, hashlib, json, sys, uuid

SESSION=Path(__file__).resolve().parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import diff_native_progress_153117 as parser
import baseline_control as baseline

state_file=SESSION/'state.json'
state_data=state_file.read_bytes()
state=json.loads(state_data)
assert state['session_id']=='20261007_100115_cb21d9cf'
assert state['source_kind']=='smt'
native=Path(state['paths']['native'])/'slot3-s.save'
assert native==Path("C:/Users/xinsui/Documents/Marvel's Spider-Man Remastered/76561199191371037/slot3-s.save")
frozen=Path(state['paths']['freeze'])/'slot3-s.save'
assert frozen==SESSION/'frozen_smt_save'/'slot3-s.save'
def sha(data):return hashlib.sha256(data).hexdigest()
def stat_summary(path):
 s=path.stat()
 return {'size':s.st_size,'mtime_ns':s.st_mtime_ns,'mtime_utc':datetime.datetime.fromtimestamp(s.st_mtime,datetime.timezone.utc).isoformat()}
s0=stat_summary(native);one=native.read_bytes();s1=stat_summary(native)
two=native.read_bytes();s2=stat_summary(native)
stable=(one==two and s0==s1==s2)
assert stable,'Native save changed during read; refuse diagnostic copy'
ident=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
snapshot_dir=SESSION/('原版加载后只读快照_'+ident)
snapshot_dir.mkdir()
snapshot=snapshot_dir/'slot3-s.save'
snapshot.write_bytes(two)
assert snapshot.read_bytes()==two
frozen_hash=sha(frozen.read_bytes())
assert frozen_hash=='7c69f619ae0271012c287ccee5a76703fc2cd22e5731bdd98f891b35bcdde475'
parser.decoder.EXPECTED={frozen:frozen_hash,snapshot:sha(two)}
labels=parser.runtime_labels()
items={}
for name,path in [('frozen_input',frozen),('native_loaded_snapshot',snapshot)]:
 d,data=parser.decoder.decode(path)
 m=parser.MSFX(d,data,labels)
 m.pop('raw_hex')
 items[name]={'decoded':d,'metadata':parser.metadata(d),'MSFX':m,
  'segments':d['sections']['0x1cea6ceb']['objects']}
a,b=items.values()
comparisons={'metadata':parser.decoder.diff(a['metadata'],b['metadata']),
 'MSFX_global':parser.decoder.diff(a['MSFX']['global_mission_states'],b['MSFX']['global_mission_states']),
 'MSFX_objectives':parser.decoder.diff(a['MSFX']['objective_tables'],b['MSFX']['objective_tables']),
 'segments':parser.decoder.diff(a['segments'],b['segments']),
 'sections':parser.comparison(a['decoded'],b['decoded'])}
native_manifest=baseline.manifest(Path(state['paths']['native']))
frozen_manifest=baseline.manifest(Path(state['paths']['freeze']))
manifest_diff=parser.decoder.diff(frozen_manifest,native_manifest)
payload={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Read native/frozen only; write snapshot and audit only under this diagnosis session',
 'state_file_sha256':sha(state_data),'state_unchanged_during_audit':state_file.read_bytes()==state_data,
 'session':str(SESSION),'native_path':str(native),'native_read_stable':stable,
 'native_stats':[s0,s1,s2],'native_read_hashes':[sha(one),sha(two)],
 'native_disk_equals_frozen_input':two==frozen.read_bytes(),
 'native_file_count':len(native_manifest['files']),'frozen_file_count':len(frozen_manifest['files']),
 'native_manifest':native_manifest,'frozen_manifest':frozen_manifest,'manifest_diff':manifest_diff,
 'running_processes_at_end':baseline.processes(),'items':items,'comparisons':comparisons,
 'interpretation_limit':'Unchanged disk bytes do not establish whether runtime load rebuilt or changed state; observer must answer that.'}
out=SESSION/('原版加载后存档只读核验_'+ident+'.json')
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('stable/equal',stable,payload['native_disk_equals_frozen_input'])
print('hash',sha(two),'size',len(two))
print('metadata',b['metadata'])
print('all_changes',{k:(len(v) if isinstance(v,list) else None) for k,v in comparisons.items()})
print('changed_sections',[v['tag'] for v in comparisons['sections'] if not v['bytes_equal']])
print('manifest_diff',manifest_diff)
print('processes',payload['running_processes_at_end'])
