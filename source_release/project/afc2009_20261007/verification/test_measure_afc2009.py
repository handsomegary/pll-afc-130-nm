"""Meaningful postprocessor fixtures only; no electrical-result claim."""
from array import array
import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('measure_afc2009',str(HERE/'measure_afc2009.py'))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def event(initial,changes):
    levels=[[0.0,initial]]+[[t,value] for t,value in changes]
    return dict(levels=levels,rising=[t for t,value in changes if value],
                falling=[t for t,value in changes if not value])


def fixture():
    config=copy.deepcopy(m.DEFAULT_CONFIG)
    times=array('d',(i*50e-12 for i in range(40001)))
    def clock(t,hz,offset=0):
        phase=(t-offset)*hz%1
        # Exact reference grid and a finite slew with threshold at period start.
        return .6+min(.6,max(-.6,math.sin(2*math.pi*phase)*3))
    data={'time':times,'out0':array('d',(.934+.08*math.sin(2*math.pi*3.2e9*t) for t in times)),
          'out180':array('d',(.934-.08*math.sin(2*math.pi*3.2e9*t) for t in times)),
          'ref':array('d',(clock(t,100e6) for t in times)),
          'fb':array('d',(clock(t,100e6,-.3e-9) for t in times)),
          'ctrl':array('d',(.6 for _ in times)),
          'filter_mid':array('d',(.6 for _ in times)),
          'vdd':array('d',(1.2 for _ in times)),
          'total_current':array('d',(-4e-3/1.2 for _ in times)),
          'afc_current':array('d',(-.2e-3/1.2 for _ in times))}
    digital={key:event(0,[]) for key in config['digitals']}
    digital.update(enable=event(0,[(100e-9,1)]),done=event(0,[(300e-9,1)]),
        fine_enable=event(0,[(320e-9,1)]),hold=event(1,[(320e-9,0)]),
        fail=event(0,[]))
    words={'code':[[0,16],[180e-9,24],[240e-9,28],[280e-9,29]]}
    return data,digital,words,config


def main():
    tests=[]
    data,digital,words,config=fixture()
    hand=m.audit_handoff(data,digital,words,config)
    assert hand['success_handoff'] and hand['selected_code']==29
    tests.append('Success-gated handoff with frozen tested code')
    loop=m.engineering_lock(data,hand['fine_enable_time_s'],config)
    assert loop['locked'] and abs(loop['final_frequency_Hz']/3.2e9-1)<.001
    assert loop['physical_noise_jitter_s'] is None
    tests.append('Actual-edge engineering lock with physical noise left unknown')
    power=m.power_metrics(data,100e-9,1.1e-6)
    assert math.isclose(power['branches']['total_current']['energy_J'],4e-9,rel_tol=1e-12)
    assert math.isclose(power['branches']['afc_current']['energy_J'],.2e-9,rel_tol=1e-12)
    tests.append('Total integral retains diagnostic AFC power without double counting')
    changed=copy.deepcopy(words)
    changed['code'].append([1e-6,30])
    assert not m.audit_handoff(data,digital,changed,config)['success_handoff']
    tests.append('Post-fine code mutation rejected')
    early=copy.deepcopy(digital)
    early['fine_enable']=event(0,[(301e-9,1)])
    assert not m.audit_handoff(data,early,words,config)['success_handoff']
    tests.append('Fine-enable before two-REF delay rejected')
    failed=copy.deepcopy(digital)
    failed.update(done=event(0,[]),fine_enable=event(0,[]),hold=event(1,[]),
                  fail=event(0,[(350e-9,1)]))
    fail_check=m.audit_handoff(data,failed,words,config)
    assert fail_check['failure_safe'] and not fail_check['success_handoff']
    tests.append('Watchdog fail keeps CP disabled and control held')
    unsafe=copy.deepcopy(failed)
    unsafe['fine_enable']=event(0,[(500e-9,1)])
    assert not m.audit_handoff(data,unsafe,words,config)['failure_safe']
    tests.append('Failure plus fine-enable rejected')
    pulse=copy.deepcopy(digital)
    pulse['up']=event(0,[(200e-9,1),(202e-9,0)])
    assert not m.audit_handoff(data,pulse,words,config)['success_handoff']
    tests.append('CP pulse while clamped rejected')
    # A cycle slip remains visible in ordinal/unwrapped fb-ref error.
    slipped=dict(data)
    slipped['fb']=array('d',(v if t<1.1e-6 else .6+min(.6,max(-.6,
        math.sin(2*math.pi*100e6*(t+.3e-9-5e-9))*3))
        for t,v in zip(data['time'],data['fb'])))
    check=m.engineering_lock(slipped,1e-6,config)
    assert check['lock_time_s'] is None or check['lock_time_s']>1.1e-6
    tests.append('Phase jump cannot qualify the pre-slip hold window')
    # Missing counter contract keeps sign proof unknown rather than invented.
    assert m.audit_round_edges(digital,words,config)['counter_contract'] is None
    tests.append('Absent CDC snapshot contract never becomes sign proof')
    audit_cfg=copy.deepcopy(config)
    audit_cfg['counter_contract']={'snapshot_anchor':'decision_falling',
        'snapshot_delay_s':1e-9,'decision_guard_counts':2}
    observed=copy.deepcopy(digital)
    observed.update(trial_arm=event(0,[(110e-9,1),(150e-9,0)]),
        epoch_ack=event(0,[(115e-9,1)]),decision_valid=event(0,[(130e-9,1),(140e-9,0)]),
        decision_slow=event(0,[(140.2e-9,1)]),decision_fast=event(0,[]))
    snapshots=dict(words,n_lead=[[0,0],[140.2e-9,11]],
        n_lag=[[0,0],[140.2e-9,10]],n_div=[[0,0],[140.2e-9,8]])
    proof=m.audit_round_edges(observed,snapshots,audit_cfg)['rounds'][0]
    assert proof['sign_proof'] and proof['observed_counter_snapshot']['n_lag']==10
    tests.append('Decision-falling anchor selects newly latched counters; exact guard2 accepted')
    snapshots['n_lag']=[[0,0],[140.2e-9,9]]
    assert not m.audit_round_edges(observed,snapshots,audit_cfg)['rounds'][0]['sign_proof']
    tests.append('One-count snapshot cannot substantiate guarded two-count direction')
    observed['decision_fast']=event(0,[(140.2e-9,1)])
    assert not m.audit_round_edges(observed,snapshots,audit_cfg)['rounds'][0]['sign_proof']
    tests.append('Contradictory fast and slow snapshot rejected')
    # Independent analytic integration with non-grid endpoints.
    t=array('d',(x*1e-9 for x in [0,5,10,15,20,25,30]))
    p=array('d',(x*1e-3 for x in [1,1.5,2,2.5,3,3.5,4]))
    assert math.isclose(m.integrate(t,p,7.5e-9,24.5e-9),44.2e-12,rel_tol=1e-12)
    tests.append('Interpolated exact-boundary integration matches analytic 44.2pJ')
    with tempfile.TemporaryDirectory(prefix='fixture-',dir=str(HERE)) as directory:
        raw=Path(directory)/'fixture.tran'
        text=['HEADER','VALUE']
        for index in range(32):
            text.extend(['"time" '+repr(index*1e-9),'"vdd" 1.2',
                '"ctrl" 0.6','"afc_enable" '+str(1.2 if index>=2 else 0),
                '"s0" 1.2','"s1" 0','"s2" 1.2','"s3" 1.2','"s4" 1.2',
                '"ignored_big_signal" 123'])
        text.append('END')
        raw.write_text('\n'.join(text)+'\n',encoding='utf8')
        got,events,word,evidence=m.read_saved_vectors(raw,config)
        assert len(got['time'])==32 and word['code']==[[0.0,29]]
        assert len(events['enable']['rising'])==1 and evidence['raw_unchanged_during_extraction']
        assert 'ignored_big_signal' not in got
        tests.append('Streaming reader reconstructs coherent code and interpolated digital edge')
        damaged=raw.read_text(encoding='utf8').replace('"ctrl" 0.6\n','',1)
        raw.write_text(damaged,encoding='utf8')
        try:
            m.read_saved_vectors(raw,config)
        except ValueError:
            pass
        else:
            raise AssertionError('Late saved analog did not fail strict reader')
        tests.append('Malformed saved-vector timeline rejected')
    out={'fixtures_passed':len(tests),'checks':tests,'simulator_started':False,
         'scope':'Postprocessor correctness and engineering-criterion fixtures only. '
            'No AFC MOS, CDC metastability, PVT, jitter or silicon verification implied.'}
    (HERE/'postprocessor_fixture_results.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
    print(json.dumps(out,indent=2))


if __name__=='__main__':
    main()
