"""Double-read only; refuse classification if native now points to a candidate."""
from pathlib import Path
import datetime, hashlib, json, sys, uuid
SESSION=Path(__file__).resolve().parent
ROOT=SESSION.parents[1]
sys.path.insert(0,str(ROOT))
import diff_native_progress_153117 as parser
import baseline_control as baseline
state=json.loads((SESSION/'state.json').read_text(encoding='utf-8'))
native=Path(state['paths']['native'])/'slot3-s.save'
frozen=Path(state['paths']['freeze'])/'slot3-s.save'
original_hash='7c69f619ae0271012c287ccee5a76703fc2cd22e5731bdd98f891b35bcdde475'
identity=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
out=SESSION/('原版关闭后只读核验_'+identity+'.json')
payload={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'native_path':str(native),'processes_at_begin':baseline.processes(),
 'scope':'Double read only; no native/session state changes',
 'frozen_sha256':hashlib.sha256(frozen.read_bytes()).hexdigest()}
try:
 s0=native.stat();d0=native.read_bytes();s1=native.stat();d1=native.read_bytes();s2=native.stat()
 stats=[{'size':s.st_size,'mtime_ns':s.st_mtime_ns} for s in [s0,s1,s2]]
 stable=(d0==d1 and stats[0]==stats[1]==stats[2])
 h=hashlib.sha256(d1).hexdigest()
 payload.update({'stable':stable,'stats':stats,'sha256':h,'size':len(d1),
 'native_equals_original_frozen':d1==frozen.read_bytes(),
 'source_identity_caveat':'If hash differs, cannot assume this is original failure save while parent replaces native directory.'})
 if stable and h==original_hash:
  payload['classification']='Confirmed original frozen bytes still present after native close; no exit save changes.'
 elif not stable:
  payload['classification']='Changed during read; not classified as original failure save.'
 else:
  payload['classification']='Different stable bytes; could be exit save or candidate replacement, requires parent identity confirmation.'
  # Preserve observed bytes only as diagnostic evidence, not as a named failure save.
  evidence=SESSION/('关闭后未分类读数_'+identity+'.save')
  evidence.write_bytes(d1)
  payload['observed_bytes_snapshot']=str(evidence)
  parser.decoder.EXPECTED={frozen:original_hash,evidence:h}
  a,ad=parser.decoder.decode(frozen);b,bd=parser.decoder.decode(evidence)
  labels=parser.runtime_labels()
  am,bm=parser.MSFX(a,ad,labels),parser.MSFX(b,bd,labels)
  payload['comparison_unclassified']={'metadata':parser.decoder.diff(parser.metadata(a),parser.metadata(b)),
   'objective_tables':parser.decoder.diff(am['objective_tables'],bm['objective_tables']),
   'global_missions':parser.decoder.diff(am['global_mission_states'],bm['global_mission_states']),
   'sections':parser.comparison(a,b)}
except FileNotFoundError as e:
 payload.update({'stable':False,'classification':'Native path missing during parent replacement; no failure-source inference.','error':str(e)})
payload['processes_at_end']=baseline.processes()
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in payload.items() if k!='comparison_unclassified'},ensure_ascii=False))
print('OUTPUT',out)
