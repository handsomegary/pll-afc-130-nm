"""Read-only cross-check of v3 phase routine against independent v2 ledger audit."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'verification'/'monitor_v3_first_edge'/'measure_afc2009.py'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
before=sha(SOURCE)
spec=importlib.util.spec_from_file_location('readonly_monitor_v3_phase',SOURCE)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
old=json.loads((ROOT/'verification'/'r1_remaining_units_independent_review_v2.json').read_text(encoding='utf-8'))
config=json.loads((ROOT/'verification'/'monitor_v3_first_edge'/'physical_portmap_r1.json').read_text(encoding='utf-8'))
rows=[]
for unit in old['records']:
    d=json.loads(Path(unit['measurement_path']).read_text(encoding='utf-8'))
    stop=1.8e-6 if 'no_feedback' not in d['name'] else 640e-9
    for r,ind in zip(d['round_edge_audit']['rounds'],unit['rounds']):
        out=module.audit_first_div_bracket(d['digital_transition_ledgers'],config,r['arm_time_s'],r['decision_time_s'] or stop,ind['counter_reset_release_s'],r['epoch_ack_time_s'])
        same=(out['first_div_time_s']==ind['first_active_gated_Div_s'])
        if ind['first_active_gated_Div_s'] is None:
            phaseok=out['bracket_proof'] is None
        else:
            phaseok=(out['bracket_proof']==ind['first_edge_phase_bracket_supported'] and out['captured_phase']==ind['phase'])
        credit=out.get('reference_counter_credit_diagnostics',{}).get('initial_native_counter_credit_proof')
        rows.append(dict(name=d['name'],trial=r['trial_index'],first_edge_matches_independent_reset_anchor=same,phase_matches_independent_original_REF_pair=phaseok,native_credit_remains_unknown=credit is None,v3_output=out))
assert all(r['first_edge_matches_independent_reset_anchor'] and r['phase_matches_independent_original_REF_pair'] and r['native_credit_remains_unknown'] for r in rows)
result=dict(version='independent-v3-phase-monitor-crosscheck-v1',simulator_started=False,electrical_sources_modified=False,rows=rows,rounds=len(rows),all_crosschecks_passed=True,source_sha256_before=before,source_sha256_after=sha(SOURCE),source_unchanged=before==sha(SOURCE),native_counter_credit_proven=False,raw_reread_performed=False,PLL_capture_proven=False,CDC_MTBF_proven=False)
target=Path(__file__).with_name('r1_v3_phase_monitor_crosscheck.json')
assert not target.exists()
target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(path=target.as_posix(),rounds=len(rows),all_crosschecks_passed=True,source_unchanged=result['source_unchanged'])))
