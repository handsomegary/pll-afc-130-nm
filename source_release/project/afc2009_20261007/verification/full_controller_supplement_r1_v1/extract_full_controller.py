"""Source-bound read-only supplemental R1 FULL-controller saved-vector audit.

Accepts completed rc0 cases only. No simulations, live raw, circuit changes or
relaxation of the original bound measurement's clamp/PLL PASS criteria.
"""
from __future__ import print_function
import argparse
import bisect
import json
from pathlib import Path
import measure_afc2009 as m

HERE=Path(__file__).resolve().parent
EXPECTED_R1_SHA='12044e0dc052c06682a3372f17c0b8612d637954af88e0d8662cf1d8c0f8f6b8'
EXTRA_DIGITALS={
    'control_clock':'XAFC.control_clock','settle':'XAFC.settle','arm':'XAFC.arm',
    'measure':'XAFC.measure','drain':'XAFC.drain','epoch_valid':'XAFC.epoch_valid',
    'count_run':'XAFC.count_run','counter_reset':'XAFC.count_rst',
    'reference_counter_reset':'XAFC.reference_count_rst',
    'fast_raw':'XAFC.fast_raw','slow_raw':'XAFC.slow_raw',
    'fast_prev':'XAFC.fast_prev','slow_prev':'XAFC.slow_prev',
    'fast_qualified':'XAFC.fast_qualified','slow_qualified':'XAFC.slow_qualified',
    'afc_reset':'afc_rst','active':'afc_active',
    'measure_watchdog':'XAFC.measure_watchdog','fb_clock_enable':'XAFC.fb_clock_enable'}
STATES=['settle','arm','measure','drain']
STABLE_SAMPLE_OFFSET_S=2.5e-9
SIGNAL_STABLE_BEFORE_S=1e-9
SIGNAL_STABLE_AFTER_S=200e-12


def config():
    cfg=json.loads(json.dumps(m.DEFAULT_CONFIG))
    cfg.update(json.loads((HERE/'physical_portmap_r1.json').read_text(encoding='utf8')))
    cfg['analogs']={}
    cfg['digitals'].update(EXTRA_DIGITALS)
    return cfg


def level(digital,key,point):
    return m.event_value(digital.get(key,{}).get('levels',[]),point)


def rises(digital,key):
    return digital.get(key,{}).get('rising',[])


def stable_value(digital,key,point,begin,end):
    events=digital.get(key,{}).get('levels',[])
    if not events or point<begin or point>end:
        return {'value':None,'stable':False,'reason':'Outside observed interval or signal missing.'}
    times=[row[0] for row in events]
    index=bisect.bisect_right(times,point)-1
    prior=times[index]
    following=times[index+1] if index+1<len(times) else end
    stable=point-prior>=SIGNAL_STABLE_BEFORE_S and following-point>=SIGNAL_STABLE_AFTER_S
    return {'value':events[index][1],'stable':stable,'preceding_transition_s':prior,
        'following_transition_s':following if index+1<len(times) else None,
        'lookback_s':SIGNAL_STABLE_BEFORE_S,'lookahead_s':SIGNAL_STABLE_AFTER_S}


def audit_controller(data,digital,words,cfg,base):
    begin,end=data['time'][0],data['time'][-1]
    required=list(EXTRA_DIGITALS)+['enable','done','fail','fine_enable','hold','pfd_reset','up','dn',
        'divcal','decision_valid','decision_slow','decision_fast','decision_near','trial_arm','epoch_ack',
        'reference','phase_select']
    missing=[key for key in required if not digital.get(key,{}).get('levels')]
    enabled=next(iter(rises(digital,'enable')),None)
    done=next((t for t in rises(digital,'done') if enabled is not None and t>=enabled),None)
    fail=next((t for t in rises(digital,'fail') if enabled is not None and t>=enabled),None)
    fine=next((t for t in rises(digital,'fine_enable') if enabled is not None and t>=enabled),None)
    terminal=done if done is not None else fail
    samples=[]
    overlaps=[]
    uncertified_overlaps=[]
    qualification_samples=[]
    previous=None
    boolean_mismatches=[]
    for clock in rises(digital,'control_clock'):
        point=clock+STABLE_SAMPLE_OFFSET_S
        if point>end or enabled is None or point<enabled:
            continue
        states=[key for key in STATES if level(digital,key,point)==1]
        row={'clock_rising_s':clock,'stable_sample_time_s':point,'asserted_states':states,
            'state_values':{key:level(digital,key,point) for key in STATES},
            'active':level(digital,'active',point),'epoch_valid':level(digital,'epoch_valid',point),
            'count_run':level(digital,'count_run',point),'count_rst':level(digital,'counter_reset',point),
            'code':m.event_value(words.get('code',[]),point)}
        row['state_signal_stability']={key:stable_value(digital,key,point,begin,end) for key in STATES}
        row['stable_state_comparison_eligible']=all(item['stable'] for item in row['state_signal_stability'].values())
        samples.append(row)
        if len(states)>1:
            (overlaps if row['stable_state_comparison_eligible'] else uncertified_overlaps).append(row)
        if row['state_values']['measure']==1 and row['epoch_valid']==1:
            detail={'clock_rising_s':clock,'sample_time_s':point,'code':row['code'],'directions':{}}
            for sign in ['fast','slow']:
                observed={kind:stable_value(digital,sign+'_'+kind,point,begin,end)
                    for kind in ['raw','prev','qualified']}
                eligible=all(item['stable'] and item['value'] in [0,1] for item in observed.values())
                match=(observed['qualified']['value']==(observed['raw']['value']&observed['prev']['value'])) if eligible else None
                prior_stable=(previous['directions'][sign]['observed']['raw']
                    if previous is not None else None)
                prior_clock=previous['clock_rising_s'] if previous is not None else None
                detail['directions'][sign]={
                    'observed':observed,'stable_boolean_comparison_eligible':eligible,
                    'qualified_equals_observed_raw_AND_prev':match,
                    'preceding_observed_MEASURE_clock_s':prior_clock,
                    'preceding_observed_MEASURE_raw_sample':prior_stable,
                    'pre_current_clock_raw_value':level(digital,sign+'_raw',clock-200e-12),
                    'pre_current_clock_raw_sample_time_s':clock-200e-12,
                    'native_CDC_count_words_observed':False,'two_consecutive_native_CDC_observations_proof':None,
                    'scope':'Observable saved raw/prev/qualified levels and their prior saved history only; '
                        'neither native Gray words nor live decoded CDC words are saved in FULL.'}
                if match is False:
                    boolean_mismatches.append({'sample_time_s':point,'direction':sign,'observed':observed})
            qualification_samples.append(detail)
            previous=detail
        else:
            # Do not connect raw history across distinct MEASURE epochs/trials.
            previous=None
    rounds=m.audit_round_edges(digital,words,cfg)
    decision_evidence=[]
    for item in rounds['rounds']:
        decision=item.get('decision_time_s')
        frozen=item.get('observed_counter_snapshot',{})
        point=decision+cfg['decision_settle_s'] if decision is not None else None
        detail={'trial_index':item['trial_index'],'trial_code':item.get('trial_code'),
            'decision_rising_time_s':decision,'decision_observation_time_s':point,
            'frozen_snapshot':frozen,'directions':{}}
        for sign in ['fast','slow']:
            detail['directions'][sign]={
                'qualified_rising_edges_this_trial_s':[edge for edge in rises(digital,sign+'_qualified')
                    if item['arm_time_s']<=edge< (rounds['rounds'][item['trial_index']+1]['arm_time_s']
                    if item['trial_index']+1<len(rounds['rounds']) else end)],
                'raw_at_decision_observation':level(digital,sign+'_raw',point) if point is not None and point<=end else None,
                'prev_at_decision_observation':level(digital,sign+'_prev',point) if point is not None and point<=end else None,
                'qualified_at_decision_observation':level(digital,sign+'_qualified',point) if point is not None and point<=end else None}
        detail['scope']='Actual saved qualifier edge times/levels and frozen direction. '
        detail['scope']+='No native count-credit, exact internal sampling aperture, live CDC-word or metastability proof.'
        decision_evidence.append(detail)
    guard=cfg['handoff_guard_s']
    postfine_controller=[edge for edge in rises(digital,'control_clock') if fine is not None and edge>fine+guard]
    postterminal_fb=[edge for edge in rises(digital,'divcal') if terminal is not None and edge>terminal+guard]
    terminal_controls={key:level(digital,key,end) for key in
        ['done','fail','fine_enable','hold','pfd_reset','count_run','counter_reset','reference_counter_reset','fb_clock_enable']}
    expected_terminal=(terminal_controls['done']==1 and terminal_controls['fail']==0 and
        terminal_controls['fine_enable']==1 and terminal_controls['hold']==0 and terminal_controls['pfd_reset']==0
        if done is not None else terminal_controls['fail']==1 and terminal_controls['done']==0 and
        terminal_controls['fine_enable']==0 and terminal_controls['hold']==1 and terminal_controls['pfd_reset']==1
        if fail is not None else None)
    stop_observables=(terminal_controls['count_run']==0 and terminal_controls['counter_reset']==1
        and terminal_controls['fb_clock_enable']==0 and not postterminal_fb) if terminal is not None else None
    held_cp=[]
    if enabled is not None:
        held_end=fine-guard if fine is not None else end
        for key in ['up','dn']:
            for a,b,state in m.digital_intervals(digital.get(key,{}).get('levels',[]),enabled+guard,held_end):
                if state==1 and b>a:
                    held_cp.append({'signal':key,'begin_s':a,'end_s':b})
    eligible=sum(row['directions'][sign]['stable_boolean_comparison_eligible']
        for row in qualification_samples for sign in ['fast','slow'])
    checks={'mandatory_saved_controls_present':not missing,
        'stable_controller_samples_have_at_most_one_live_state':not overlaps if any(
            row['stable_state_comparison_eligible'] for row in samples) else None,
        'no_ARM_reentry_without_new_counter_epoch':not rounds['ARM_reentries_without_new_counter_epoch_s'],
        'saved_qualifier_AND_observations_supported':not boolean_mismatches if eligible else None,
        'controller_no_rising_after_fine_plus_guard':not postfine_controller if fine is not None else None,
        'native_clock_stop_control_observables_supported':stop_observables,
        'terminal_success_or_safe_fail_control_levels_supported':expected_terminal,
        'gated_CP_controls_off_while_held':not held_cp if enabled is not None else None}
    return {'checks':checks,'all_applicable_observable_checks_supported':all(value is True for value in checks.values()),
        'missing_mandatory_controls':missing,'stable_controller_samples':samples,'stable_state_overlap_samples':overlaps,
        'uncertified_or_transient_state_overlap_samples':uncertified_overlaps,
        'round_edge_audit':rounds,'qualification_stable_sample_history':qualification_samples,
        'qualified_AND_comparisons_eligible':eligible,'qualified_AND_mismatch_samples':boolean_mismatches,
        'decision_qualification_observations':decision_evidence,
        'control_clock_transition_ledger':digital.get('control_clock'),
        'terminal_controls_final':terminal_controls,'terminal_time_s':terminal,'fine_enable_time_s':fine,
        'post_fine_controller_rising_edges_s':postfine_controller,
        'post_terminal_saved_gated_FB_rising_edges_s':postterminal_fb,
        'gated_CP_asserted_while_held_intervals':held_cp,
        'tail_diagnostic_phase_clock_rising_counts':{key:sum(edge>fine+guard for edge in rises(digital,key))
            if fine is not None else None for key in ['ref_lead','ref_lag']},
        'stable_sample_offset_after_control_clock_s':STABLE_SAMPLE_OFFSET_S,
        'native_all_internal_clock_stop_proof':None,'native_initial_count_credit_proof':None,
        'two_consecutive_native_CDC_count_observations_proof':None,'metastability_or_MTBF_proof':None,
        'scope':'Saved FULL-controller observables only; at-most-one stable state, saved gated FB clock '
            'and gate/reset controls, observable comparator/previous/qualified Booleans. Buffered lead/lag '
            'diagnostic phase clocks may still toggle after fine; their native AND clocks are not saved.'}


def dependency_fingerprints(execution):
    rows={}
    afc=[]
    for kind in ['own_dependencies','model_dependencies']:
        if not execution.get(kind):
            raise ValueError('Missing source dependency ledger: '+kind)
        for path,record in execution[kind].items():
            actual=m.sha(path)
            if actual!=record.get('sha256'):
                raise ValueError('Source/model changed since completed run: '+path)
            rows[path]=actual
            if kind=='own_dependencies' and Path(path).name=='afc2009_mos.scs':
                afc.append(actual)
    if afc!=[EXPECTED_R1_SHA]:
        raise ValueError('Supplement supports exact R1 physical AFC source only.')
    return rows


def bound_inputs(execution_path,measurement_path):
    execution_path=execution_path.resolve()
    measurement_path=measurement_path.resolve()
    execution_sha=m.sha(execution_path)
    measurement_sha=m.sha(measurement_path)
    execution=json.loads(execution_path.read_text(encoding='utf8'))
    base=json.loads(measurement_path.read_text(encoding='utf8'))
    if execution.get('state')!='completed' or execution.get('spectre_rc')!=0:
        raise ValueError('Completed rc0 execution required; live/failed/partial raw refused.')
    if not execution.get('source_models_unchanged_at_completion'):
        raise ValueError('Completion source/model integrity guard missing.')
    if execution.get('specification',{}).get('revision')!='r1':
        raise ValueError('Explicit R1 execution required.')
    if base.get('name')!=execution.get('name') or base.get('execution_evidence',{}).get('sha256')!=execution_sha:
        raise ValueError('Existing measurement does not bind exact completed cache/name.')
    if Path(base['execution_evidence']['path']).resolve()!=execution_path:
        raise ValueError('Measurement execution path differs from supplied cache.')
    bench=Path(execution['bench']).resolve()
    if m.sha(bench)!=execution['bench_sha256'] or base.get('bench_evidence',{}).get('sha256')!=execution['bench_sha256']:
        raise ValueError('Bench SHA differs across source/cache/measurement.')
    if abs(base.get('configuration',{}).get('clamp_tolerance_V',-1)-.03)>1e-12:
        raise ValueError('Strict original 30mV clamp contract must remain unchanged.')
    raw=(Path(execution['raw'])/'tran.tran.tran').resolve()
    if Path(base['source_evidence']['raw_file']).resolve()!=raw or raw.stat().st_size!=base['source_evidence']['raw_bytes']:
        raise ValueError('Bound raw path/byte count mismatch.')
    if raw.stat().st_size>m.MAX_RAW_BYTES:
        raise ValueError('Full raw exceeds 512MiB guard.')
    with raw.open('rb') as handle:
        handle.seek(max(0,raw.stat().st_size-65536))
        tail=handle.read().decode('utf8',errors='strict')
    if not tail.splitlines() or tail.strip().splitlines()[-1].strip()!='END':
        raise ValueError('Original full raw has no final genuine END marker; partial EOF refused.')
    return execution,base,bench,raw,execution_sha,measurement_sha


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execution',required=True,type=Path)
    ap.add_argument('--measurement',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args()
    if args.output.exists():
        raise ValueError('Existing supplemental output cannot be overwritten.')
    execution,base,bench,raw,execution_sha,measurement_sha=bound_inputs(args.execution,args.measurement)
    dependencies_before=dependency_fingerprints(execution)
    cfg=config()
    data,digital,words,evidence=m.read_saved_vectors(raw,cfg,256)
    if evidence['raw_sha256']!=base['source_evidence']['raw_sha256'] or evidence['saved_samples']!=base['source_evidence']['saved_samples']:
        raise ValueError('Raw SHA/sample count differs from bound full measurement.')
    requested_stop=execution.get('specification',{}).get('duration_s')
    strobe=execution.get('specification',{}).get('strobeperiod_s',40e-12)
    if requested_stop is None or abs(data['time'][-1]-requested_stop)>strobe+1e-18:
        raise ValueError('Saved FULL interval does not reach requested numerical stop.')
    supplemental=audit_controller(data,digital,words,cfg,base)
    dependencies_after=dependency_fingerprints(execution)
    if dependencies_before!=dependencies_after or m.sha(args.execution)!=execution_sha or m.sha(args.measurement)!=measurement_sha:
        raise ValueError('Source/cache/measurement changed during extraction.')
    result={'version':'R1-FULL-controller-supplement-v1','name':execution['name'],
        'numerical_completion':True,'simulator_started':False,'circuit_or_criteria_modified':False,
        'source_evidence':evidence,'bench_evidence':{'bench':str(bench),'sha256':execution['bench_sha256']},
        'execution_evidence':{'path':str(args.execution.resolve()),'sha256':execution_sha,'completed_rc0':True},
        'bound_measurement_evidence':{'path':str(args.measurement.resolve()),'sha256':measurement_sha},
        'inherited_bound_full_measurement_verdict':{key:base.get(key) for key in ['afc_success','locked','afc_handoff_success']},
        'inherited_strict_clamp_tolerance_V':base['configuration']['clamp_tolerance_V'],
        'inherited_handoff':base['handoff'],'inherited_fine_loop_capture':base['fine_loop'].get('locked'),
        'controller_observable_audit':supplemental,'digital_transition_ledgers':digital,'word_transition_ledgers':words,
        'source_dependencies_before':dependencies_before,'source_dependencies_after':dependencies_after,
        'monitor_source_evidence':{str(path):m.sha(path) for path in
            [HERE/'measure_afc2009.py',HERE/'physical_portmap_r1.json',Path(__file__).resolve()]},
        'physical_noise_jitter_s':None,'scope':'Supplemental FULL saved-controller audit only; '
            'original strict clamp/PLL verdict retained. No native live Gray/CDC counter-credit, '
            'metastability/MTBF, internal clock stop, noise or all-PVT proof.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'output':str(args.output.resolve()),'name':execution['name'],
        'controller_checks':supplemental['checks'],'bound_full_afc_success':base.get('afc_success'),
        'strict_clamp_tolerance_V':base['configuration']['clamp_tolerance_V']}))
    return 0


if __name__=='__main__':
    main()
