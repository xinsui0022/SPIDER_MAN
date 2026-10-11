"""Read-only full-manifest check after normal host exit."""
from pathlib import Path
import datetime, json, sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
import baseline_control as baseline
import diff_reload_save as decoder
processes_before=baseline.processes()
assert not processes_before,'Game unexpectedly running; refuse closed-process classification'
expected=baseline.manifest(HERE/'SMT_Save_snapshot')
first=baseline.manifest(baseline.ENV.saves)
second=baseline.manifest(baseline.ENV.saves)
processes_after=baseline.processes()
payload={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Read only; writes this diagnostic JSON only, no additional save copies',
 'processes_before':processes_before,'processes_after':processes_after,
 'source_first':first,'source_second':second,'expected_snapshot':expected,
 'stable_double_manifest':first==second,
 'all23_equal_snapshot':len(first['files'])==23 and first==expected==second,
 'changes_vs_snapshot':decoder.diff(expected,first),
 'slot3':first['files'].get('slot3-s.save')}
out=HERE/'退出后只读核验.json'
assert not out.exists()
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('OUTPUT',out)
print('all23_equal',payload['all23_equal_snapshot'],'stable',payload['stable_double_manifest'],
 'closed',not processes_after,'slot3',payload['slot3'],'changes',payload['changes_vs_snapshot'])
