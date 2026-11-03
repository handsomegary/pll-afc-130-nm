"""Physical CP evidence from root's all_cases.json; never runs a simulator.

Python 3.6+. Missing/failed cases stay missing, never inferred as passing.
"""
from __future__ import print_function
import argparse
import bisect
import json
import re
from pathlib import Path
from measure_pll import read_psf, integral_mean


def raw_directory(record):
    if record.get('raw_path'):
        return Path(record['raw_path'])
    paths = [Path(p) for p in record.get('artifacts',[]) if str(p).endswith('.raw')]
    if len(paths) != 1:
        raise ValueError('Expected exactly one raw artifact for '+record.get('name','?'))
    return paths[0]


def analysis_path(record, kind):
    raw = raw_directory(record)
    paths = sorted(raw.glob('cpdc.dc' if kind=='dc' else '*tran*'))
    paths = [p for p in paths if p.is_file() and not p.name.endswith('.info')]
    if len(paths) != 1:
        raise ValueError('Expected one {} waveform in {}'.format(kind,raw))
    return paths[0]


def interpolate(t,y,x):
    i = bisect.bisect_left(t,x)
    if i == 0:
        return y[0]
    if i >= len(t):
        return y[-1]
    return y[i-1]+(y[i]-y[i-1])*(x-t[i-1])/(t[i]-t[i-1])


def segment(t,y,begin,end):
    a,b=bisect.bisect_right(t,begin),bisect.bisect_left(t,end)
    return [begin]+t[a:b]+[end], [interpolate(t,y,begin)]+y[a:b]+[interpolate(t,y,end)]


def integrate(t,y,begin,end):
    x,z=segment(t,y,begin,end)
    return integral_mean(x,z)*(end-begin)


def pulse_measure(record,filter_parameters):
    data=read_psf(analysis_path(record,'tran'))
    t=data['time']
    n=len(t)
    pterminal='XCP.MPUSW:d' if 'XCP.MPUSW:d' in data else 'XCP.MPUP:d'
    nterminal='XCP.MNDSW:d' if 'XCP.MNDSW:d' in data else 'XCP.MNDN:d'
    for name in ['ctrl','filter_mid',pterminal,nterminal,'VDD:p']:
        if len(data.get(name,[])) != n:
            raise ValueError('Missing pulse waveform '+name)
    ctrl=data['ctrl']; mid=data['filter_mid']
    # MOS current is positive INTO drain. PMOS source output therefore has
    # negative drain current. Both conduction and displacement are included.
    net=[-a-b for a,b in zip(data[pterminal],data[nterminal])]
    windows=[]
    for name,begin,end in [('up',19.8e-9,22.5e-9),('dn',29.8e-9,32.5e-9),
                           ('both',39.8e-9,40.7e-9)]:
        q=integrate(t,net,begin,end)
        delta_ctrl=interpolate(t,ctrl,end)-interpolate(t,ctrl,begin)
        delta_mid=interpolate(t,mid,end)-interpolate(t,mid,begin)
        stored=(filter_parameters['C_shunt_F']*delta_ctrl+
                filter_parameters['C_series_F']*delta_mid)
        selected=segment(t,ctrl,begin,end)[1]
        windows.append(dict(state=name,window_s=[begin,end],
                            net_CP_terminal_charge_C=q,
                            LPF_stored_charge_change_C=stored,
                            charge_balance_error_C=q-stored,
                            ctrl_delta_V=delta_ctrl,ctrl_min_V=min(selected),
                            ctrl_max_V=max(selected)))
    power=[-1.2*x for x in data['VDD:p']]
    px,py=segment(t,power,10e-9,59e-9)
    q_up=windows[0]['net_CP_terminal_charge_C']
    q_dn=-windows[1]['net_CP_terminal_charge_C']
    q_mean=(q_up+q_dn)/2
    return dict(windows=windows,mean_power_10_to_59ns_W=integral_mean(px,py),
                pulse_charge_asymmetry_fraction=(q_up-q_dn)/q_mean if q_mean>0 else None,
                pulse_UP_charge_over_ideal_40fC=q_up/40e-15,
                pulse_DN_charge_over_ideal_40fC=q_dn/40e-15,
                polarity_pass=(windows[0]['net_CP_terminal_charge_C']>0 and
                               windows[1]['net_CP_terminal_charge_C']<0),
                scope='Pulse deterministic conduction+feedthrough test; '
                      'no transient noise or physical rms jitter.')


def measure_all(records,filter_parameters,candidate='baseline'):
    groups={}; failures=[]; pulse=None
    for record in records:
        name=record.get('name','')
        if candidate=='drain':
            if not name.startswith('cp_drain_'):
                continue
            name=name.replace('cp_drain_','cp_',1)
        elif candidate.startswith('gate'):
            if name != 'cp_{}_pulse'.format(candidate):
                continue
            name='cp_pulse'
        elif name.startswith('cp_drain_') or re.match(r'^cp_gate\d+_',name):
            continue
        if not name.startswith('cp_'):
            continue
        if record.get('state') != 'completed':
            failures.append(dict(name=name,reason=record.get('error','Analysis incomplete.')))
            continue
        try:
            if name=='cp_pulse':
                pulse=pulse_measure(record,filter_parameters)
                pulse['case_id']=record.get('case_id')
                continue
            match=re.match(r'^cp_dc_v(\d+)_(up|dn|both|off)$',name)
            if not match:
                continue
            v=int(match.group(1))*1e-6; state=match.group(2)
            values=read_psf(analysis_path(record,'dc'))
            flat={k:z[-1] for k,z in values.items() if z}
            pterminal='XCP.MPUSW:d' if 'XCP.MPUSW:d' in flat else 'XCP.MPUP:d'
            nterminal='XCP.MNDSW:d' if 'XCP.MNDSW:d' in flat else 'XCP.MNDN:d'
            required=['VCLAMP:p','VDD:p',pterminal,nterminal]
            if any(k not in flat for k in required):
                raise ValueError('Missing required CP DC signals: '+','.join(required))
            groups.setdefault(v,{})[state]=dict(
                case_id=record.get('case_id'),
                actual_ctrl_V=flat.get('ctrl'),
                net_ctrl_current_A=flat['VCLAMP:p'],
                UP_device_sourcing_A=-flat[pterminal],
                DN_device_sinking_A=flat[nterminal],
                supply_power_W=-1.2*flat['VDD:p'],
                bncp_V=flat.get('XCP.bncp'),bpcp_V=flat.get('XCP.bpcp'),
                gate_up_V=flat.get('XCP.gp'),gate_dn_V=flat.get('XCP.gn'))
        except Exception as error:
            failures.append(dict(name=name,reason=repr(error)))
    table=[]
    for voltage,g in sorted(groups.items()):
        measured=next((state['actual_ctrl_V'] for state in g.values()
                       if state.get('actual_ctrl_V') is not None),None)
        row=dict(ctrl_V=measured if measured is not None else voltage,
                 case_label_rounded_ctrl_V=voltage,states=g,
                 complete=all(k in g for k in ['up','dn','both','off']))
        if row['complete']:
            up=g['up']['net_ctrl_current_A']; dn=-g['dn']['net_ctrl_current_A']
            mean=(up+dn)/2
            mismatch=(up-dn)/mean if mean>0 else None
            row.update(Iup_A=up,Idn_A=dn,mismatch_fraction=mismatch,
                       mismatch_percent=100*mismatch if mismatch is not None else None,
                       off_leakage_A=g['off']['net_ctrl_current_A'],
                       both_net_current_A=g['both']['net_ctrl_current_A'],
                       signed_current_polarity_pass=up>0 and dn>0,
                       compliance_screen_pass=bool(
                           up>0 and dn>0 and abs(up/20e-6-1)<=0.05 and
                           abs(dn/20e-6-1)<=0.05 and mismatch is not None and
                           abs(mismatch)<=0.05 and abs(g['off']['net_ctrl_current_A'])<=1e-9))
        table.append(row)
    target=next((r for r in table if abs(r['ctrl_V']-.835938)<1e-6),None)
    good=[r['ctrl_V'] for r in table if r.get('compliance_screen_pass')]
    return dict(version='cp-units-v2',candidate=candidate,
                dc_voltage_points=table,target_point=target,
                tested_voltage_points_passing=good,
                continuous_compliance_range_proven=False,
                pulse=pulse,incomplete_or_failed=failures,
                scope='Authored TT1.2V25C {} physical MOS CP with '.format(candidate)+
                      'ideal20u reference; five discrete compliance points, '
                      'no PVT/PEX/random matching/noise.',
                acceptance_definition=dict(independent_Iup_Idn_relative_target_error_max=0.05,
                                           current_matching_fraction_max=0.05,
                                           off_leakage_absolute_A_max=1e-9,
                                           nominal_current_A=20e-6))


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--cases',required=True)
    ap.add_argument('--filter',default=str(Path(__file__).resolve().parent/'loop_design.json'))
    ap.add_argument('--out')
    ap.add_argument('--candidate',choices=['baseline','gate4','gate8','drain'],default='baseline')
    args=ap.parse_args()
    records=json.loads(Path(args.cases).read_text())
    parameters=json.loads(Path(args.filter).read_text())
    result=measure_all(records,parameters,candidate=args.candidate)
    text=json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    if args.out:
        Path(args.out).write_text(text,encoding='utf-8')
    print(text)
