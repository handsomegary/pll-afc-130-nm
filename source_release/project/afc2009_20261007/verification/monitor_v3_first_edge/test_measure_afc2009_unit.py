"""Synthetic saved-vector fixtures for the unit monitor; never MOS evidence."""
from array import array
import copy
import json
from pathlib import Path
import measure_afc2009 as m
import measure_afc2009_unit as unit


def event(initial,changes):
    return {'levels':[[0,initial]]+[[t,v] for t,v in changes],
        'rising':[t for t,v in changes if v], 'falling':[t for t,v in changes if not v]}


def fake(name):
    cfg=unit.config()
    digital={key:event(0,[]) for key in cfg['digitals']}
    digital.update(enable=event(0,[(120e-9,1)]),reset=event(1,[(100e-9,0)]),
        hold=event(1,[]),pfd_reset=event(1,[]),counter_reset=event(1,[]))
    times=array('d',(i*20e-9 for i in range(91)))
    data={'time':times,'ref':array('d',(0 for _ in times)),
        'fb':array('d',(0 for _ in times)),
        'total_current':array('d',(-.2e-3/1.2 for _ in times))}
    words={key:[[0,0]] for key in cfg['words']}
    words['code']=[[0,16]]
    if name.startswith('near100'):
        phase=1 if name.endswith('high') else 0
        first=153e-9 if phase else 157e-9
        digital.update(trial_arm=event(0,[(150e-9,1),(200e-9,0)]),
            epoch_ack=event(0,[(first,1)]),phase_select=event(0,[(first,phase)]),
            divcal=event(0,[(first,1),(first+5e-9,0)]),
            decision_valid=event(0,[(1440e-9,1),(1450e-9,0)]),
            decision_near=event(0,[(1450.2e-9,1)]),
            done=event(0,[(1450.2e-9,1)]),fine_enable=event(0,[(1470.2e-9,1)]),
            hold=event(1,[(1470.2e-9,0)]),pfd_reset=event(1,[(1470.2e-9,0)]),
            reference=event(0,[(x*1e-9,int(x%10==0)) for x in range(10,1801,5)]))
        digital.update(counter_reset=event(1,[(151e-9,0),(1451e-9,1)]),
            count_run=event(0,[(151e-9,1),(1451e-9,0)]))
        words.update(n_lead=[[0,0],[1450.2e-9,129]],n_lag=[[0,0],[1450.2e-9,128]],
            n_div=[[0,0],[1450.2e-9,129]])
    elif name=='no_feedback':
        digital.update(trial_arm=event(0,[(150e-9,1),(470e-9,0)]),
            fail=event(0,[(470e-9,1)]),
            counter_reset=event(1,[(151e-9,0),(471e-9,1)]),
            count_run=event(0,[(151e-9,1),(471e-9,0)]))
    else:
        fast=name=='fast140'
        expected=unit.CASES[name]
        arms=[150e-9+i*150e-9 for i in range(5)]
        digital.update(trial_arm=event(0,[(t,v) for arm in arms for t,v in [(arm,1),(arm+50e-9,0)]]),
            epoch_ack=event(0,[(t,v) for arm in arms for t,v in [(arm+3e-9,1),(arm+120e-9,0)]]),
            decision_valid=event(0,[(t,v) for arm in arms for t,v in [(arm+100e-9,1),(arm+110e-9,0)]]),
            fail=event(0,[(arms[-1]+120e-9,1)]),
            decision_fast=event(0,[(arms[0]+110.2e-9,int(fast))]),
            decision_slow=event(0,[(arms[0]+110.2e-9,int(not fast))]),
            divcal=event(0,[(t,v) for arm in arms for t,v in [(arm+3e-9,1),(arm+8e-9,0)]]),
            phase_select=event(0,[(arms[0]+3e-9,1)]),
            reference=event(0,[(x*1e-9,int(x%10==0)) for x in range(10,1801,5)]))
        words['code']=[[0,16]]+[[arms[i]-20e-9,expected['history'][i]] for i in range(1,5)]
        digital['counter_reset']=event(1,[(t,v) for arm in arms for t,v in [(arm+1e-9,0),(arm+120e-9,1)]])
        digital['count_run']=event(0,[(t,v) for arm in arms for t,v in [(arm+1e-9,1),(arm+120e-9,0)]])
        words.update(n_lead=[[0,0],[arms[0]+110.2e-9,10]],
            n_lag=[[0,0],[arms[0]+110.2e-9,10 if fast else 12]],
            n_div=[[0,0],[arms[0]+110.2e-9,12 if fast else 10]])
    return data,digital,words,{'synthetic_fixture':True,'simulator_started':False}


def main():
    original=m.read_saved_vectors
    results=[]
    try:
        for name in unit.CASES:
            fixture=fake(name)
            m.read_saved_vectors=lambda *args,**kwargs:fixture
            measured=unit.measure_unit('no-real-raw',name)
            assert measured['unit_functional_pass'],(name,measured['violations'])
            assert measured['afc_success'] is None and measured['PLL_locked'] is None
            results.append({'name':name,'unit_functional_pass':True})
        fixture=list(fake('near100_phase_high'))
        fixture[2]['code'].append([1.6e-6,17])
        m.read_saved_vectors=lambda *args,**kwargs:fixture
        measured=unit.measure_unit('no-real-raw','near100_phase_high')
        assert not measured['unit_functional_pass']
        results.append({'name':'post-fine-code-mutated','rejected':True})
        fixture=list(fake('fast140'))
        fixture[1]['fine_enable']=event(0,[(1e-6,1)])
        m.read_saved_vectors=lambda *args,**kwargs:fixture
        assert not unit.measure_unit('no-real-raw','fast140')['unit_functional_pass']
        results.append({'name':'endpoint-failure-releases-fine','rejected':True})
        fixture=list(fake('near100_phase_high'))
        fixture[1]['counter_reset']=event(1,[(151e-9,0),(1451e-9,1)])
        fixture[1]['trial_arm']=event(0,[(150e-9,1),(200e-9,0),(300e-9,1),(310e-9,0)])
        m.read_saved_vectors=lambda *args,**kwargs:fixture
        measured=unit.measure_unit('no-real-raw','near100_phase_high')
        assert not measured['unit_functional_pass']
        assert len(measured['round_edge_audit']['rounds'])==1
        assert len(measured['round_edge_audit']['ARM_reentries_without_new_counter_epoch_s'])==1
        results.append({'name':'ARM-reentry-is-FSM-error-not-a-second-counter-trial','rejected':True})
        fixture=list(fake('near100_phase_high'))
        fixture[1]['control_clock']=event(0,[(250e-9,1),(255e-9,0)])
        fixture[1]['settle']=event(0,[(120e-9,1)])
        fixture[1]['measure']=event(0,[(210e-9,1)])
        m.read_saved_vectors=lambda *args,**kwargs:fixture
        measured=unit.measure_unit('no-real-raw','near100_phase_high')
        assert not measured['unit_functional_pass'] and measured['stable_state_overlap_samples']
        results.append({'name':'stable-one-hot-state-overlap','rejected':True})
        fixture=list(fake('near100_phase_high'))
        fixture[0]=dict(fixture[0],time=array('d',[0,.6e-6]))
        for key,event_data in list(fixture[1].items()):
            fixture[1][key]={'levels':[row for row in event_data['levels'] if row[0]<=.6e-6],
                'rising':[t for t in event_data['rising'] if t<=.6e-6],
                'falling':[t for t in event_data['falling'] if t<=.6e-6]}
        fixture[1]['counter_reset']=event(1,[(151e-9,0)])
        fixture[2]={key:[row for row in value if row[0]<=.6e-6] for key,value in fixture[2].items()}
        m.read_saved_vectors=lambda *args,**kwargs:fixture
        measured=unit.measure_unit('no-real-raw','near100_phase_high',diagnostic_only=True)
        assert measured['short_diagnostic_pass'] and measured['terminal_status_pending']
        assert measured['unit_functional_pass'] is None
        results.append({'name':'short-near-diagnostic-pending-terminal-not-functional-PASS','checked':True})
    finally:
        m.read_saved_vectors=original
    out={'fixtures_passed':len(results),'cases':results,'simulator_started':False,
        'scope':'Synthetic saved-vector monitor tests only. No physical MOS electrical result.'}
    Path(__file__).with_name('unit_postprocessor_fixture_results.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
    print(json.dumps(out,indent=2))


if __name__=='__main__':
    main()
