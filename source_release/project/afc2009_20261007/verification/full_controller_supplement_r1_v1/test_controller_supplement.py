"""Digital-only supplemental monitor fixtures; no physical FULL result."""
from __future__ import print_function
from array import array
import copy
import json
from pathlib import Path
import tempfile
import extract_full_controller as monitor

HERE=Path(__file__).resolve().parent


def event(initial,changes):
    return dict(levels=[[0,initial]]+[[t,v] for t,v in changes],
        rising=[t for t,v in changes if v],falling=[t for t,v in changes if not v])


def fixture():
    cfg=monitor.config()
    digital={key:event(0,[]) for key in cfg['digitals']}
    ref=[(x*1e-9,int(x%10==0)) for x in range(10,221,5)]
    digital.update(reference=event(0,ref),ref_lead=event(0,ref),ref_lag=event(1,[(t,1-v) for t,v in ref]),
        enable=event(0,[(20e-9,1)]),active=event(0,[(30e-9,1),(180.3e-9,0)]),
        settle=event(0,[(30e-9,1),(60e-9,0)]),arm=event(0,[(60e-9,1),(80e-9,0)]),
        trial_arm=event(0,[(60e-9,1),(80e-9,0)]),measure=event(0,[(80e-9,1),(160e-9,0)]),
        drain=event(0,[(160e-9,1),(180e-9,0)]),epoch_valid=event(0,[(79e-9,1),(181e-9,0)]),
        control_clock=event(0,[(t,v) for x in range(10,201,10) for t,v in [(x*1e-9,1),((x+5)*1e-9,0)]]),
        counter_reset=event(1,[(60.5e-9,0),(180.3e-9,1)]),
        reference_counter_reset=event(1,[(71e-9,0),(180.5e-9,1)]),
        count_run=event(0,[(60.5e-9,1),(160.3e-9,0)]),fb_clock_enable=event(0,[(61e-9,1),(160.7e-9,0)]),
        divcal=event(0,[(t,v) for x in range(70,151,10) for t,v in [(x*1e-9,1),((x+5)*1e-9,0)]]),
        epoch_ack=event(0,[(70.3e-9,1),(181e-9,0)]),phase_select=event(0,[(70.4e-9,1),(181e-9,0)]),
        fast_raw=event(0,[(120e-9,1),(181e-9,0)]),fast_prev=event(0,[(130.3e-9,1),(160.3e-9,0)]),
        fast_qualified=event(0,[(130.5e-9,1),(160.5e-9,0)]),
        decision_valid=event(0,[(150e-9,1),(160e-9,0)]),decision_fast=event(0,[(160.3e-9,1)]),
        done=event(0,[(180.3e-9,1)]),fine_enable=event(0,[(200.3e-9,1)]),
        hold=event(1,[(200.3e-9,0)]),pfd_reset=event(1,[(200.3e-9,0)]))
    words={'code':[[0,16]],'n_lead':[[0,0],[160.3e-9,10]],
        'n_lag':[[0,0],[160.3e-9,9]],'n_div':[[0,0],[160.3e-9,12]]}
    data={'time':array('d',(i*1e-9 for i in range(221)))}
    return data,digital,words,cfg,{}


def main():
    cases=[]
    args=fixture()
    audit=monitor.audit_controller(*args)
    assert audit['all_applicable_observable_checks_supported'],audit['checks']
    assert audit['qualified_AND_comparisons_eligible']>0 and not audit['qualified_AND_mismatch_samples']
    assert audit['native_initial_count_credit_proof'] is None
    assert audit['two_consecutive_native_CDC_count_observations_proof'] is None
    assert audit['metastability_or_MTBF_proof'] is None
    cases.append('Synthetic saved-controller Booleans/one-hot/stop controls supported without native-credit or CDC proof')
    records=[row for row in audit['qualification_stable_sample_history']
        if row['sample_time_s']>132e-9 and row['directions']['fast']['observed']['qualified']['value']==1]
    assert records and records[0]['directions']['fast']['preceding_observed_MEASURE_raw_sample']['value']==1
    assert audit['decision_qualification_observations'][0]['directions']['fast']['qualified_rising_edges_this_trial_s']==[130.5e-9]
    cases.append('Qualifier edge time and preceding saved raw history exported only from observed digital ledgers')
    changed=list(fixture())
    changed[1]['fast_qualified']=event(0,[])
    rejected=monitor.audit_controller(*changed)
    assert rejected['checks']['saved_qualifier_AND_observations_supported'] is False
    cases.append('Stable raw1/prev1/qualified0 mismatch is reported, not guessed from frozen sign')
    changed=list(fixture())
    changed[1]['settle']=event(0,[(30e-9,1),(100e-9,0)])
    rejected=monitor.audit_controller(*changed)
    assert rejected['stable_state_overlap_samples']
    assert rejected['checks']['stable_controller_samples_have_at_most_one_live_state'] is False
    cases.append('Persisting one-hot state overlap fails only from stable observed state samples')
    changed=list(fixture())
    changed[1]['settle']=event(0,[(30e-9,1),(60e-9,0),(92.45e-9,1),(92.55e-9,0)])
    rejected=monitor.audit_controller(*changed)
    assert rejected['uncertified_or_transient_state_overlap_samples']
    assert not rejected['stable_state_overlap_samples']
    cases.append('Short overlap at sampling point is logged as uncertified/transient, without manufacturing stable-state failure')
    changed=list(fixture())
    changed[1]['trial_arm']=event(0,[(60e-9,1),(80e-9,0),(100e-9,1),(105e-9,0)])
    rejected=monitor.audit_controller(*changed)
    assert rejected['checks']['no_ARM_reentry_without_new_counter_epoch'] is False
    cases.append('ARM reentry without new count-reset release remains an actual FSM observable error')
    changed=list(fixture())
    changed[1]['control_clock']=event(0,[(t,v) for x in range(10,211,10) for t,v in [(x*1e-9,1),((x+5)*1e-9,0)]])
    rejected=monitor.audit_controller(*changed)
    assert rejected['checks']['controller_no_rising_after_fine_plus_guard'] is False
    cases.append('Controller restart after fine is rejected from actual saved clock rising')
    changed=list(fixture())
    changed[1]['divcal']['rising'].append(210e-9)
    rejected=monitor.audit_controller(*changed)
    assert rejected['checks']['native_clock_stop_control_observables_supported'] is False
    cases.append('Late saved gated-FB clock violates stop observables without claiming every unsaved internal clock')
    changed=list(fixture())
    changed[1]['up']=event(0,[(110e-9,1),(112e-9,0)])
    rejected=monitor.audit_controller(*changed)
    assert rejected['checks']['gated_CP_controls_off_while_held'] is False
    cases.append('Saved gated CP pulse during hold is reported')
    assert audit['tail_diagnostic_phase_clock_rising_counts']['ref_lead']>0
    assert audit['checks']['native_clock_stop_control_observables_supported'] is True
    cases.append('Buffered REF phase clocks may toggle after fine even with supported native gate-stop controls')
    changed=list(fixture())
    changed[1].pop('slow_prev')
    rejected=monitor.audit_controller(*changed)
    assert rejected['checks']['mandatory_saved_controls_present'] is False
    assert 'slow_prev' in rejected['missing_mandatory_controls']
    cases.append('Missing saved comparator history remains unsupported rather than fabricated from snapshot counts')
    with tempfile.TemporaryDirectory(prefix='controller-bind-fixture-',dir=str(HERE)) as directory:
        directory=Path(directory)
        bench=directory/'synthetic.scs'
        bench.write_text('// Digital-only binding fixture, never simulated.\n',encoding='utf8')
        rawroot=directory/'raw'
        rawroot.mkdir()
        raw=rawroot/'tran.tran.tran'
        raw.write_text('HEADER\nVALUE\nEND\n',encoding='utf8')
        execution_path=directory/'execution.json'
        measurement_path=directory/'measurement.json'
        execution={'state':'completed','spectre_rc':0,'name':'synthetic-binding-only',
            'source_models_unchanged_at_completion':True,'specification':{'revision':'r1'},
            'bench':str(bench),'bench_sha256':monitor.m.sha(bench),'raw':str(rawroot)}
        def write_inputs():
            execution_path.write_text(json.dumps(execution)+'\n',encoding='utf8')
            base={'name':execution['name'],'execution_evidence':{'path':str(execution_path),'sha256':monitor.m.sha(execution_path)},
                'bench_evidence':{'sha256':execution['bench_sha256']},'configuration':{'clamp_tolerance_V':.03},
                'source_evidence':{'raw_file':str(raw),'raw_bytes':raw.stat().st_size}}
            measurement_path.write_text(json.dumps(base)+'\n',encoding='utf8')
        write_inputs()
        monitor.bound_inputs(execution_path,measurement_path)
        execution['state']='failed'
        write_inputs()
        try:
            monitor.bound_inputs(execution_path,measurement_path)
        except ValueError as error:
            assert 'Completed rc0' in str(error)
        else:
            raise AssertionError('Incomplete execution accepted')
        cases.append('Failed/partial cache is refused before controller raw extraction')
        execution['state']='completed'
        write_inputs()
        bad=json.loads(measurement_path.read_text(encoding='utf8'))
        bad['execution_evidence']['sha256']='wrong-cache'
        measurement_path.write_text(json.dumps(bad),encoding='utf8')
        try:
            monitor.bound_inputs(execution_path,measurement_path)
        except ValueError as error:
            assert 'bind exact completed cache' in str(error)
        else:
            raise AssertionError('Different measurement cache accepted')
        cases.append('Supplement cannot mix measurements from different completed executions')
        write_inputs()
        raw.write_text('HEADER\nVALUE\n"time" 0\n',encoding='utf8')
        write_inputs()
        try:
            monitor.bound_inputs(execution_path,measurement_path)
        except ValueError as error:
            assert 'final genuine END' in str(error)
        else:
            raise AssertionError('EOF partial raw accepted')
        cases.append('Partial EOF raw is refused even when a synthetic cache claims completed rc0')
    result={'fixtures_passed':len(cases),'checks':cases,'simulator_started':False,
        'analogue_actual_results_generated':False,'physical_FULL_PASS':None,
        'scope':'Synthetic digital-controller and input-binding parser fixtures only; no physical circuit result.'}
    (HERE/'controller_fixture_results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
