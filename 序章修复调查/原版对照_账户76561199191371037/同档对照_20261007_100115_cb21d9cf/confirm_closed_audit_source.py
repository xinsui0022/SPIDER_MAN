"""Add parent-confirmed provenance to this diagnostic report only."""
from pathlib import Path
import json
HERE=Path(__file__).resolve().parent
report=HERE/'原版关闭后只读核验_20261007T021234Z_82837912.json'
p=json.loads(report.read_text(encoding='utf-8'))
assert p['sha256']=='e6194198d2aaa7b65a556cf145beecae15d32c349882711809e7dd907eb1e0d1'
p['source_identity_confirmation']={
 'source':'Root task explicitly confirmed no native replacement or native file edits through this capture',
 'game_exit_time_hong_kong':'2026-10-07 10:11:35',
 'operation':'Normal AltF4 close after user checkpoint reload test',
 'candidate_replacement_had_occurred':False,
 'write_trigger_limit':'Cannot distinguish checkpoint reload save from normal-exit save using these two fixed files alone'}
p['classification']='Confirmed native checkpoint-reload/normal-exit test save, before any candidate replacement; task tables and checkpoint unchanged.'
report.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
print('Updated diagnostic source confirmation',report)
