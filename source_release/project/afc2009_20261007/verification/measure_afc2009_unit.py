"""Read-only physical AFC unit monitor; ideal clocks, no PLL-lock claim.

PASS means the particular MOS AFC unit fixture behaved as expected. Correct
FAIL of range/watchdog fixtures is a functional PASS; it is not AFC success.
Python 3.6+, bounded selected-vector streaming, no simulator launches.
"""
from __future__ import print_function
import argparse
from array import array
import copy
import json
from pathlib import Path
import re
import sys

import measure_afc2009 as m


CASES = {
    'near100_phase_high': {'code':16,'done':1,'fail':0,'fine':1,'phase':1,'history':[16]},
    'near100_phase_low': {'code':16,'done':1,'fail':0,'fine':1,'phase':0,'history':[16]},
    'fast140': {'code':1,'done':0,'fail':1,'fine':0,'history':[16,8,4,2,1],'direction':'fast'},
    'slow70': {'code':31,'done':0,'fail':1,'fine':0,'history':[16,24,28,30,31],'direction':'slow'},
    'no_feedback': {'code':16,'done':0,'fail':1,'fine':0,'history':[16]},
}


def config(portmap=None):
    out=copy.deepcopy(m.DEFAULT_CONFIG)
    proposed=Path(portmap) if portmap is not None and not isinstance(portmap,dict) else Path(__file__).with_name('physical_portmap_proposed.json')
    out.update(portmap if isinstance(portmap,dict) else json.loads(proposed.read_text(encoding='utf-8')))
    out['analogs']={'ref':'ref','fb':'fb','total_current':'VDD:p'}
    out['digitals'].update(reset='rst',active='afc_active',
        epoch_valid='XAFC.epoch_valid',reference='ref',
        control_clock='XAFC.control_clock',counter_reset='XAFC.count_rst',
        reference_counter_reset='XAFC.reference_count_rst',
        fast_raw='XAFC.fast_raw',slow_raw='XAFC.slow_raw',
        fast_qualified='XAFC.fast_qualified',slow_qualified='XAFC.slow_qualified',
        measure_watchdog='XAFC.measure_watchdog',settle='XAFC.settle',
        arm='XAFC.arm',measure='XAFC.measure',drain='XAFC.drain')
    out['digitals'].pop('up',None)
    out['digitals'].pop('dn',None)
    out['words'].update(sync_lead=['XAFC.cl'+str(i) for i in range(8)],
        sync_lag=['XAFC.cg'+str(i) for i in range(8)],
        sync_div=['XAFC.cd'+str(i) for i in range(8)])
    return out


def settled_history(events,begin,end,guard_s):
    accepted=[]
    glitches=[]
    for index,(time,word) in enumerate(events):
        following=events[index+1][0] if index+1<len(events) else end
        if following<=begin:
            continue
        duration=following-max(time,begin)
        if duration<guard_s:
            glitches.append({'time_s':time,'duration_s':duration,'word':word})
            continue
        if not accepted or word!=accepted[-1]['word']:
            accepted.append({'time_s':max(time,begin),'word':word,'stable_interval_s':duration})
    return accepted,glitches


def measure_unit(raw,name,bench=None,memory_mib=256,portmap=None,diagnostic_only=False):
    name=name.removeprefix('afc_unit_') if hasattr(name,'removeprefix') else name.replace('afc_unit_','',1)
    if name not in CASES:
        raise ValueError('Unknown bounded unit fixture name: '+name)
    expected=CASES[name]
    cfg=config(portmap)
    data,digital,words,evidence=m.read_saved_vectors(raw,cfg,memory_mib)
    end=data['time'][-1]
    def levels(key):
        return digital.get(key,{}).get('levels',[])
    def value(key,time):
        return m.event_value(levels(key),time)
    def rises(key):
        return digital.get(key,{}).get('rising',[])
    en=next(iter(rises('enable')),None)
    done=next((time for time in rises('done') if en is not None and time>=en),None)
    fail=next((time for time in rises('fail') if en is not None and time>=en),None)
    fine=next((time for time in rises('fine_enable') if en is not None and time>=en),None)
    violations=[]
    required=['enable','done','fail','fine_enable','hold','pfd_reset','reset']
    missing=[key for key in required if not levels(key)]
    if missing:
        violations.append('Missing mandatory saved controls: '+','.join(missing))
    if en is None:
        violations.append('No AFC start edge observed.')
    guard=cfg['handoff_guard_s']
    final={key:value(key,end) for key in required}
    for key,want in ([] if diagnostic_only else [('done',expected['done']),('fail',expected['fail']),
                     ('fine_enable',expected['fine']),('hold',1-expected['fine']),
                     ('pfd_reset',1-expected['fine'])]):
        if final[key]!=want:
            violations.append('Final '+key+' does not match fixture expectation.')
    if en is not None:
        boundaries=sorted({time for key in required for time,_ in levels(key) if time>=en})
        for time in boundaries:
            point=min(time+guard,end)
            dn,fl,fi,ho,pr=(value(key,point) for key in ['done','fail','fine_enable','hold','pfd_reset'])
            if dn==1 and fl==1:
                violations.append('Done and Fail are simultaneously asserted.')
            if fi==1 and not (dn==1 and fl==0 and value('enable',point)==1):
                violations.append('Fine-enable does not have success permission.')
            if fl==1 and (fi!=0 or ho!=1 or pr!=1):
                violations.append('Failure did not keep hold/PFD reset on and fine off.')
            if fi==0 and (ho!=1 or pr!=1):
                violations.append('Pre-fine hold/PFD reset contract violated.')
    delay=fine-done if fine is not None and done is not None else None
    if ((expected['fine'] and not diagnostic_only) or fine is not None) and (delay is None or delay<20e-9-guard):
        violations.append('Done->fine release is earlier than two REF periods.')
    history,glitches=settled_history(words.get('code',[]),en+guard if en is not None else 0,end,guard)
    codes=[item['word'] for item in history]
    if codes!=(expected['history'][:len(codes)] if diagnostic_only else expected['history']):
        violations.append('Stable tested code history differs from expected search.')
    if not words.get('code') or (not diagnostic_only and words['code'][-1][1]!=expected['code']):
        violations.append('Final coarse code differs from fixture expectation.')
    if fine is not None:
        after=[item for item in words.get('code',[]) if item[0]>fine+guard]
        if after:
            violations.append('Coarse code changed after fine-enable.')
    round_audit=m.audit_round_edges(digital,words,cfg)
    rounds=round_audit['rounds']
    if round_audit['ARM_reentries_without_new_counter_epoch_s']:
        violations.append('ARM state reentered without a fresh physical counter epoch.')
    for item in rounds:
        proof=item.get('sign_proof')
        if proof is False:
            violations.append('Frozen decision direction lacks guarded count support.')
        snapshot=item.get('observed_counter_snapshot',{})
        if expected.get('direction'):
            sign=expected['direction']
            if snapshot and snapshot.get(sign)!=1:
                violations.append('Decision sign contradicts known ideal-clock frequency.')
    near_records=[]
    decode_sample_offset=cfg.get('counter_decode_sample_offset_s',2.5e-9)
    state_overlaps=[]
    for point in rises('control_clock'):
        sample=point+decode_sample_offset
        if sample>end or en is None or sample<en:
            continue
        state=[key for key in ['settle','arm','measure','drain'] if value(key,sample)==1]
        if len(state)>1:
            state_overlaps.append({'time_s':sample,'states':state})
    if state_overlaps:
        violations.append('Stable controller samples contain overlapping one-hot states.')
    if name.startswith('near100'):
        if len(rounds)!=1:
            violations.append('Equal-frequency fixture did not use exactly one tested round.')
        for item in rounds:
            bracket=item.get('first_edge_bracket',{})
            if bracket.get('captured_phase')!=expected['phase']:
                violations.append('First-FB captured phase differs from expected high/low fixture.')
            if bracket.get('bracket_proof') is False:
                violations.append('First-FB phase bracket violated saved reference timing.')
            snapshot=item.get('observed_counter_snapshot',{})
            if snapshot and (snapshot.get('slow') or snapshot.get('fast')):
                violations.append('Equal frequency falsely latched fast/slow.')
            if snapshot and snapshot.get('n_lag',0)<128:
                violations.append('Near decision precedes specified lag-count window.')
        for point in rises('control_clock'):
            sample=point+decode_sample_offset
            if sample>end or value('epoch_valid',sample)!=1:
                continue
            cl,cg,cd=(m.event_value(words.get(key,[]),sample) for key in ['sync_lead','sync_lag','sync_div'])
            if None in [cl,cg,cd]:
                continue
            gs=cg-cd>=2
            gf=cd-cl>=2
            if gs or gf:
                near_records.append({'time_s':sample,'lead':cl,'lag':cg,'div':cd,
                    'slow_guard':gs,'fast_guard':gf})
        if near_records:
            violations.append('Equal-frequency established CDC samples contain guarded false direction.')
    if name=='no_feedback':
        seen_after=[time for time in rises('epoch_ack') if en is not None and time>=en]
        if seen_after or any(item.get('decision_time_s') is not None for item in rounds):
            violations.append('No-feedback case fabricated an epoch or frequency decision.')
    terminal=done if expected['done'] else fail
    if terminal is not None:
        if levels('count_run') and value('count_run',end)!=0:
            violations.append('Native counter clocks remain enabled after terminal status.')
        if levels('counter_reset') and value('counter_reset',end)!=1:
            violations.append('Native counters are not held reset after terminal status.')
        if fine is not None and any(time>fine+guard for time in rises('control_clock')):
            violations.append('Controller clock restarted after fine-enable.')
    power=None
    bench_evidence=None
    if bench is not None:
        bench=Path(bench).resolve()
        active='\n'.join(line.split('//',1)[0] for line in bench.read_text(encoding='utf-8').splitlines())
        vddmatch=re.search(r'(?m)^VDD\s+\(vdd\s+0\)\s+vsource\s+dc=([0-9.]+)\s*$',active)
        if vddmatch and abs(float(vddmatch.group(1))-cfg['vdd_V'])<1e-12:
            data['vdd']=array('d',(cfg['vdd_V'] for _ in data['time']))
            power={'from_start_to_terminal':m.power_metrics(data,en,terminal),
                   'tail':m.power_metrics(data,max(data['time'][0],end-100e-9),end),
                   'voltage_scope':'Declared ideal DC source from exact supplied unit bench; '
                       'vdd itself not saved in original unit raw. No real supply noise inferred.'}
        bench_evidence={'bench':str(bench),'sha256':m.sha(bench),
                        'declared_ideal_vdd_verified':bool(vddmatch)}
    if diagnostic_only and name.startswith('near100'):
        for key in ['fast_qualified','slow_qualified']:
            if en is not None and any(time>=en for time in rises(key)):
                violations.append('Equal-frequency diagnostic produced a qualified direction.')
        if fail is not None:
            violations.append('Equal-frequency diagnostic reached unexpected FAIL.')
        if not levels('counter_reset') or len(round_audit['physical_counter_reset_releases_s'])!=1:
            violations.append('Near diagnostic has no single observed physical counter epoch.')
        if round_audit['raw_ARM_entry_count']!=1:
            violations.append('Near diagnostic does not have a single ARM entry.')
    return {'version':'afc2009-physical-unit-audit-v2','name':'afc_unit_'+name,
        'unit_functional_pass':None if diagnostic_only else not violations,
        'diagnostic_only':diagnostic_only,'short_diagnostic_pass':not violations if diagnostic_only else None,
        'terminal_status_pending':diagnostic_only and done is None and fail is None,
        'expected':expected,'portmap_sha256':m.sha(portmap) if portmap is not None and not isinstance(portmap,dict) else None,
        'afc_success':None,'PLL_locked':None,
        'source_evidence':evidence,'bench_evidence':bench_evidence,
        'actual_controls_final':final,'start_time_s':en,'done_time_s':done,'fail_time_s':fail,
        'fine_enable_time_s':fine,'done_to_fine_enable_s':delay,
        'start_to_terminal_s':terminal-en if terminal is not None and en is not None else None,
        'settled_code_history':history,'sub_guard_code_glitches':glitches,
        'round_edge_audit':round_audit,'equal_frequency_guarded_false_direction_samples':near_records,
        'stable_state_overlap_samples':state_overlaps,
        'counter_decode_sample_offset_after_control_clock_s':decode_sample_offset,
        'counter_decode_sampling_contract':'Observe synchronized binary decoded words after '
            '2.5ns propagation from physical control-clock rising; check true qualified '
            'decision/frozen snapshots separately. This avoids treating propagation glitches '
            'as stable frequency directions; it does not validate metastability.',
        'power':power,'violations':sorted(set(violations)),
        'digital_transition_ledgers':digital,'word_transition_ledgers':words,
        'simulator_started':False,'physical_noise_jitter_s':None,
        'scope':'Physical MOS AFC unit driven by ideal reference/feedback stimulus. '
            'Expected endpoint/watchdog FAIL may be a functional PASS. Does not establish '
            'physical VCO capture, PLL lock, metastability MTBF, all-PVT or noise jitter.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',required=True,type=Path)
    ap.add_argument('--name',required=True)
    ap.add_argument('--bench',type=Path)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--memory-mib',choices=[256,512],type=int,default=256)
    ap.add_argument('--portmap-json',type=Path)
    ap.add_argument('--diagnostic-only',action='store_true')
    args=ap.parse_args()
    try:
        result=measure_unit(args.raw,args.name,args.bench,args.memory_mib,
            portmap=args.portmap_json,diagnostic_only=args.diagnostic_only)
    except Exception as error:
        result={'unit_functional_pass':False,'name':args.name,
            'measurement_error':repr(error),'circuit_failure_inferred':False,
            'simulator_started':False,'physical_noise_jitter_s':None}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output.resolve()),'name':args.name,
        'unit_functional_pass':result.get('unit_functional_pass'),
        'short_diagnostic_pass':result.get('short_diagnostic_pass'),
        'violations':result.get('violations'),'measurement_error':result.get('measurement_error')}))
    return 0 if result.get('unit_functional_pass') or result.get('short_diagnostic_pass') else 2


if __name__=='__main__':
    sys.exit(main())
