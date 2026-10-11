"""Freeze stable native read; compare actual saved progress with e80 and failure input."""
from pathlib import Path
import datetime, hashlib, json, sys, uuid
SESSION=Path(__file__).resolve().parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import diff_native_progress_153117 as parser
import baseline_control as baseline
state=json.loads((SESSION/'state.json').read_text(encoding='utf-8'))
native=Path(state['paths']['native'])/'slot3-s.save'
identity=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
DIAG=SESSION/('e80原版推进只读核验_'+identity)
DIAG.mkdir()
def sha(data):return hashlib.sha256(data).hexdigest()
def stat(path):
 s=path.stat();return {'size':s.st_size,'mtime_ns':s.st_mtime_ns,'mtime_utc':datetime.datetime.fromtimestamp(s.st_mtime,datetime.timezone.utc).isoformat()}
s0=stat(native);d0=native.read_bytes();s1=stat(native);d1=native.read_bytes();s2=stat(native)
stable=d0==d1 and s0==s1==s2
assert stable,'Native file changed during dual read; refuse using partial save'
snap=DIAG/'slot3-s.save'
snap.write_bytes(d1)
assert snap.read_bytes()==d1
paths={
 'e80_input':ROOT/'联机NG对照_20261006_155424_9e9669ed'/'MOD二次载入后_已暂停'/'slot3-s.save',
 'original_failure_7c69':SESSION/'frozen_smt_save'/'slot3-s.save',
 'native_progress':snap,
}
expected={paths['e80_input']:'e80e50fd9758604584be33fd22c7c08e1eff82e9b9ae4f84c3f26aab8f8eee3d',
 paths['original_failure_7c69']:'7c69f619ae0271012c287ccee5a76703fc2cd22e5731bdd98f891b35bcdde475',
 snap:sha(d1)}
parser.decoder.EXPECTED=expected
items={}
labels=parser.runtime_labels()
for name,path in paths.items():
 decoded,data=parser.decoder.decode(path)
 msfx=parser.MSFX(decoded,data,labels);msfx.pop('raw_hex')
 seg=decoded['sections']['0x1cea6ceb']['objects']
 items[name]={'decoded':decoded,'metadata':parser.metadata(decoded),'MSFX':msfx,'segments':seg}
comparisons={}
for before in ['e80_input','original_failure_7c69']:
 a,b=items[before],items['native_progress']
 comparisons[before]={'metadata':parser.decoder.diff(a['metadata'],b['metadata']),
 'global_missions':parser.decoder.diff(a['MSFX']['global_mission_states'],b['MSFX']['global_mission_states']),
 'objective_tables':parser.decoder.diff(a['MSFX']['objective_tables'],b['MSFX']['objective_tables']),
 'segments_root':parser.decoder.diff(a['segments'][0]['object'],b['segments'][0]['object']),
 'sections':parser.comparison(a['decoded'],b['decoded'])}
payload={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Read native only; write evidence snapshot and report only under diagnosis session',
 'stable_dual_read':stable,'native_source':str(native),'native_stats':[s0,s1,s2],
 'native_read_hashes':[sha(d0),sha(d1)],'items':items,'comparisons':comparisons,
 'processes_at_end':baseline.processes(),
 'validation_limit':'Disk progress is not an exit/reload success. Actual exit and re-entry are still required.'}
out=DIAG/'审计.json'
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('CURRENT',sha(d1),len(d1))
print('metadata',items['native_progress']['metadata'])
for name,c in comparisons.items():
 print('COMPARE',name,'metadata',c['metadata'],'global',c['global_missions'])
 print('objective_changes',c['objective_tables'])
 print('segment_changes',c['segments_root'])
 print('section_changes',[(x['tag'],x['before_size'],x['after_size']) for x in c['sections'] if not x['bytes_equal']])
print('processes',payload['processes_at_end'])
