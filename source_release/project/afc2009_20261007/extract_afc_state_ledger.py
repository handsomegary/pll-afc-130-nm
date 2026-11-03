"""Read-only, compact raw state/CDC ledger, no simulation or source changes.

Inputs are an exact completed raw and its existing measurement JSON; clocks
are sampled at several declared offsets to distinguish decode propagation
from stable counter/FSM behavior. Python3.6+, 512MiB raw/256MiB RAM guard.
"""
import argparse
import bisect
import copy
import json
from pathlib import Path
import measure_afc2009 as m
import measure_afc2009_unit as unit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--measurement-json',type=Path)
    args=parser.parse_args()
    cfg=unit.config()
    cfg['analogs']={'ref':'ref','fb':'fb'}
    cfg['digitals'].update(settle='XAFC.settle',arm='XAFC.arm',
        measure='XAFC.measure',drain='XAFC.drain',count_run='XAFC.count_run')
    data,digital,words,evidence=m.read_saved_vectors(args.raw,cfg)
    t=data['time']
    def value(key,point):
        return m.event_value(digital.get(key,{}).get('levels',[]),point)
    def word(key,point):
        return m.event_value(words.get(key,[]),point)
    def sample(point):
        states={key:value(key,point) for key in ['settle','arm','measure','drain']}
        result={'time_s':point,'state':states,'simultaneous_high_states':
            [key for key,val in states.items() if val==1],
            'code':word('code',point),
            'count':{key:word('sync_'+key,point) for key in ['lead','lag','div']},
            'control':{key:value(key,point) for key in ['count_run','counter_reset',
                'reference_counter_reset','epoch_ack','epoch_valid','decision_valid',
                'fast_raw','slow_raw','fast_qualified','slow_qualified',
                'done','fail','fine_enable','hold','pfd_reset','measure_watchdog']}}
        a,b,c=(result['count'][key] for key in ['lead','lag','div'])
        result['deltas']={'lag_minus_div':b-c if None not in [b,c] else None,
                          'div_minus_lead':c-a if None not in [c,a] else None}
        return result
    clocks=digital['control_clock']['rising']
    offsets=[1e-9,2.5e-9,4e-9,7e-9,9e-9]
    cycle_samples=[]
    for clock in clocks:
        if clock<120e-9:
            continue
        rows=[]
        for offset in offsets:
            point=clock+offset
            if point>t[-1]:
                continue
            item=sample(point);item['sample_offset_after_control_rising_s']=offset
            rows.append(item)
        cycle_samples.append({'control_clock_rise_s':clock,'samples':rows})
    transitions={key: value['levels'] for key,value in digital.items()}
    resets=digital.get('counter_reset',{}).get('falling',[])
    ends=digital.get('counter_reset',{}).get('rising',[])
    epochs=[{'counter_reset_release_s':release,
             'counter_reset_assert_s':next((end for end in ends if end>release),None)}
            for release in resets]
    nearby=[]
    for center in [650e-9,1130e-9,1290e-9,1450e-9]:
        nearby.append({'center_s':center,
            'samples':[sample(center+i*.25e-9) for i in range(-2,17)
                       if t[0]<=center+i*.25e-9<=t[-1]]})
    output={'version':'afc2009-readonly-state-ledger-v1','source_evidence':evidence,
        'source_measurement_json':str(args.measurement_json.resolve()) if args.measurement_json else None,
        'source_measurement_sha256':m.sha(args.measurement_json) if args.measurement_json else None,
        'observed_counter_epochs':epochs,'digital_transition_ledgers':transitions,
        'word_transition_ledgers':words,'control_cycle_samples':cycle_samples,
        'selected_decode_aperture_samples':nearby,'simulator_started':False,
        'scope':'Declared multi-offset samples of existing raw only. Does not treat '
            'early decode propagation as a stable frequency sign and does not hide '
            'real FSM state overlap or qualified decision pulses. No noise/MTBF claim.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'output':str(args.output.resolve()),'counter_epochs':len(epochs),
        'arm_rises':len(digital['arm']['rising']),'samples':len(cycle_samples),
        'raw_sha256':evidence['raw_sha256']}))


if __name__=='__main__':
    main()
