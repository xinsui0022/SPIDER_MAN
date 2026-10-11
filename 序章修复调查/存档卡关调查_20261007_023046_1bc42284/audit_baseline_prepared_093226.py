"""Read-only verification of the newly prepared native control; write only here."""
from pathlib import Path
import datetime, hashlib, json, sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_native_progress_153117 as parser

SESSION=ROOT/'同档对照_20261007_093226_58209a8b'
state,paths=baseline.load_session(baseline.ENV,SESSION)
events=baseline.read_events(SESSION)
assert state['source_kind']=='smt'
source_manifest=state['source_manifest']
frozen_manifest=json.loads((SESSION/'frozen_manifest.json').read_text(encoding='utf-8'))
original=HERE/'当前SMT_Save_只读快照'/'slot3-s.save'
frozen=paths['freeze']/'slot3-s.save'
parser.decoder.EXPECTED={
 original:'f0307d2cd827723e76b16414a0257ba7b86d7ecbee3280073a86371ed3d421d8',
 frozen:'7c69f619ae0271012c287ccee5a76703fc2cd22e5731bdd98f891b35bcdde475',
}
items={}
labels=parser.runtime_labels()
for label,path in [('investigation_023046',original),('exit_then_frozen_093226',frozen)]:
 d,data=parser.decoder.decode(path)
 msfx=parser.MSFX(d,data,labels)
 msfx.pop('raw_hex')
 items[label]={'decoded':d,'metadata':parser.metadata(d),'MSFX':msfx,
 'segments':d['sections']['0x1cea6ceb']['objects']}
a,b=items.values()
comparisons={
 'metadata':parser.decoder.diff(a['metadata'],b['metadata']),
 'global_missions':parser.decoder.diff(a['MSFX']['global_mission_states'],b['MSFX']['global_mission_states']),
 'objectives':parser.decoder.diff(a['MSFX']['objective_tables'],b['MSFX']['objective_tables']),
 'segments':parser.decoder.diff(a['segments'],b['segments']),
 'sections':parser.comparison(a['decoded'],b['decoded']),
}
actual={}
for label,path in [('frozen',paths['freeze']),('current_smt',Path(state['source_path'])),
 ('native_test_copy',paths['native']),('native_original_preserved',paths['original'])]:
 actual[label]={'path':str(path),'manifest':baseline.manifest(path)}
 actual[label]['matches_recorded']=(actual[label]['manifest']==
  (state['native_original_manifest'] if label=='native_original_preserved' else source_manifest))
actual['winmm']={'canonical_absent':not baseline.ENV.winmm.exists(),
 'preserved_path':str(paths['disabled']),
 'preserved_sha256':baseline.sha256(paths['disabled'])}
actual['winmm']['preserved_matches']=(actual['winmm']['preserved_sha256']==state['known_hashes']['winmm'])
payload={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Reads only; no native/SMT/session-state/runtime/UI changes',
 'session':str(SESSION),'state':state,'journal':events,
 'frozen_manifest_equals_recorded':frozen_manifest==source_manifest,
 'actual_verification':actual,'items':items,'comparisons':comparisons,
 'running_processes_at_end':baseline.processes()}
out=HERE/'原版对照准备_093226_只读核验.json'
assert not out.exists()
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('events',[e['event'] for e in events])
print('counts_matches',[(k,len(v['manifest']['files']),v['matches_recorded']) for k,v in actual.items() if 'manifest' in v])
print('metadata_diff',comparisons['metadata'])
print('global_mission_changes',comparisons['global_missions'])
print('objective_changes',comparisons['objectives'])
print('segment_change_count',len(comparisons['segments']))
print('segment_changes',comparisons['segments'])
print('section_changes',[(x['tag'],x['before_size'],x['after_size'],len(x['object_changes'])) for x in comparisons['sections'] if not x['bytes_equal']])
print('winmm',actual['winmm'])
print('processes',payload['running_processes_at_end'])
