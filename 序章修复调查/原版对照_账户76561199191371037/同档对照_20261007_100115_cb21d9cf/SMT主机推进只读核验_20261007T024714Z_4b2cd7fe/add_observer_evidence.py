"""Read observer log and update only this diagnostic report with matching raw state."""
from pathlib import Path
import datetime, json
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
report=HERE/'审计.json'
payload=json.loads(report.read_text(encoding='utf-8'))
capture_cutoff=datetime.datetime.fromisoformat(payload['captured_utc'])
log=ROOT/'记录'/'20261007T024320_772534Z.jsonl'
records=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
matches=[(r.get('utc'),m) for r in records if datetime.datetime.fromisoformat(r['utc'])<=capture_cutoff for m in r.get('data',{}).get('missions',[]) if m.get('mission_name_raw')=='GP_A1_FISK']
utc,mission=matches[-1]
table=payload['slot3_comparison']['after_MSFX']['objective_tables'][0]
disk=[(row['runtime_name'],row['words_raw'][1]) for row in table['rows']]
observed=[(row['name_raw'],row['state_raw']) for row in mission['objectives']]
payload['observer_comparison']={'source':str(log),'last_fisk_utc':utc,
 'all29_names_and_raw_states_match':disk==observed,
 'mission':mission}
payload['checkpoint_validation_limit']='Checkpoint/ID are still the values obtained at SECURITY_COUNTDOWN. No newer scene checkpoint was captured at POP_UP_TUT; cannot infer reload will locate this later phase.'
report.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('observer match',disk==observed,utc)
