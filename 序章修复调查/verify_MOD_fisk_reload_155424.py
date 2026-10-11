"""Read-only independent evidence audit of the successful second MOD load."""
from pathlib import Path
import datetime
import hashlib
import json
import diff_native_progress_153117 as parser

ROOT=Path(__file__).resolve().parent
SESSION=ROOT/'联机NG对照_20261006_155424_9e9669ed'
BEFORE=SESSION/'MOD推进后_退出前'
AFTER=SESSION/'MOD二次载入后_已暂停'
LOG=ROOT/'记录'/'20261006T082944_697016Z.jsonl'
EXPECTED_SAVE='e80e50fd9758604584be33fd22c7c08e1eff82e9b9ae4f84c3f26aab8f8eee3d'
EXPECTED_GAME='e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1'
EXPECTED_MOD='b7ab575100f2346af25180d74bf9641e24ce09bf549ce47446be09c3462606c7'

def manifest(path):
    return {str(p.relative_to(path)).replace('\\','/'):{'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in path.rglob('*') if p.is_file()}

if __name__=='__main__':
    bm,am=manifest(BEFORE),manifest(AFTER)
    assert len(am)==23 and len(bm)==23
    old=(BEFORE/'slot3-s.save').read_bytes();new=(AFTER/'slot3-s.save').read_bytes()
    assert old==new and len(new)==142974 and hashlib.sha256(new).hexdigest()==EXPECTED_SAVE
    attach,mod,states=None,None,[]
    records=[json.loads(line) for line in LOG.read_text(encoding='utf-8').splitlines()]
    for record in records:
        if record['event']=='attached_read_only':attach=record
        elif record['event']=='smt_detected':mod=record
        elif record['event']=='state_change':
            data=record.get('data',{})
            for mission in data.get('missions',[]):
                if mission.get('listed') and mission.get('mission_id_raw','').lower()=='0xd3665ca4' and mission.get('objectives'):
                    objectives=mission['objectives']
                    if len(objectives)==29 and [row['state_raw'] for row in objectives]==[2,2,2,2,1]+[0]*24:
                        assert objectives[4]['name_raw']=='GP_A1_FISK_ELEVATOR_LOBBY'
                        states.append({'utc':record['utc'],'mode_raw':data.get('mode_raw'),
                                       'director_enabled_raw':data.get('director_enabled_raw'),'mission':mission})
    assert attach and attach['data']['pid']==15448 and attach['data']['game_sha256']==EXPECTED_GAME
    assert mod and mod['data']['smt_sha256']==EXPECTED_MOD and states
    parser.decoder.EXPECTED={AFTER/'slot3-s.save':EXPECTED_SAVE}
    decoded,data=parser.decoder.decode(AFTER/'slot3-s.save')
    save_msfx=parser.MSFX(decoded,data,parser.runtime_labels())
    assert len(save_msfx['objective_tables'])==2
    for table in save_msfx['objective_tables']:
        assert table['runtime_name']=='GP_A1_FISK' and [row['words_raw'][1] for row in table['rows']]==[2,2,2,2,1]+[0]*24
    differences=[name for name in bm.keys()|am.keys() if bm.get(name)!=am.get(name)]
    payload={'audit_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'before_snapshot':str(BEFORE),'after_snapshot':str(AFTER),
             'slot3_input_byte_equality':True,'slot3_size':len(new),'slot3_sha256':EXPECTED_SAVE,
             'before_manifest':bm,'after_manifest':am,'whole_snapshot_manifest_equal':bm==am,
             'other_file_differences':differences,'runtime_log':str(LOG),
             'attached':attach,'smt_detected':mod,'matching_runtime_task_snapshots':states,
             'save_metadata':parser.metadata(decoded),'save_MSFX':save_msfx,
             'user_confirmation':{'quote':'任务提示正常，并保留门厅战斗后的目标','source':'User response conveyed by root'},
             'scope':'Successful second load of this specific NG+ Fisk save in MOD host mode; not a test of two-player joining, all missions, cross-computer portability, enemy synchronization, or shared saves/resources.'}
    out=ROOT/'MOD二次载入Fisk证据_20261006_155424.json'
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: identical slot3 input / after reload snapshot',len(new),EXPECTED_SAVE)
    print('Whole 23-file snapshot manifest equality:',bm==am,'differences:',differences)
    print('Verified process:',attach['data']['pid'],'game and SMT hashes match pins')
    for row in states:print('matching runtime state',row['utc'],'mode',row['mode_raw'],'director',row['director_enabled_raw'])
    print('Output:',out)
