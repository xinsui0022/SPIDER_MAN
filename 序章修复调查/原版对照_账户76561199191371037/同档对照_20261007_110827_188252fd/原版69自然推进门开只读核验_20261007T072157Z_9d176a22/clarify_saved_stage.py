"""Clarify this diagnosis JSON only; do not re-read or modify the live native save."""
from pathlib import Path
import json
HERE=Path(__file__).resolve().parent
report=HERE/'审计.json'
p=json.loads(report.read_text(encoding='utf-8'))
assert p['items']['vanilla69_natural_open']['decoded']['sha256']=='69d891dd71de75a97028d59de930656960f3b8268159921e7b490d8ee79b9747'
p['user_reported_result']=p.pop('user_confirmed_result')
p['persisted_stage_consistency']={
 'new_FIRST_EXPLOSION_auto_obtained':False,
 'slot3_all28_sections_equal_input69':True,
 'full_native_manifest_equal_installed69':not p['native_changes_vs_installed69'],
 'persisted_objective_segment':'GP_A1_FISK_SECURITY_COUNTDOWN',
 'observer_array_matches_unchanged69':p['observer']['all29_raw_names_states_match_disk'],
 'user_HUD_report_not_overridden':True,
 'same_saved_stage_comparison_with_SMT201_obtained':False,
 'note':'User reports open exit and FIRST_EXPLOSION natural play; disk and observed array remain69. Do not infer the HUD is incorrect or a new-stage auto has been obtained.'}
report.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
print('Clarified diagnosis report',report)
