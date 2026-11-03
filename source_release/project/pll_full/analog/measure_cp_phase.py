"""Measure CP phase-skew sweep from all_cases.json; no simulator."""
import argparse
import json
import re
from pathlib import Path
from measure_cp_units import analysis_path,integrate
from measure_pll import read_psf


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cases',required=True);ap.add_argument('--out')
    args=ap.parse_args();records=json.loads(Path(args.cases).read_text())
    table=[];fail=[]
    for r in records:
        m=re.match(r'^cp_drain_phase_([mp])(\d+)$',r.get('name',''))
        if not m:continue
        if r.get('state')!='completed':
            fail.append(dict(name=r['name'],error=r.get('error','incomplete')));continue
        try:
            skew=int(m.group(2))*1e-12*(-1 if m.group(1)=='m' else 1)
            d=read_psf(analysis_path(r,'tran'));t=d['time']
            q=integrate(t,d['VCLAMP:p'],19.5e-9,30e-9)
            table.append(dict(phase_skew_s=skew,net_charge_C=q,
                              ideal_net_charge_C=20e-6*skew,case_id=r.get('case_id')))
        except Exception as e:fail.append(dict(name=r['name'],error=repr(e)))
    table.sort(key=lambda x:x['phase_skew_s'])
    slope=offset=nonlinearity=None
    if len(table)>=3:
        mean_x=sum(r['phase_skew_s'] for r in table)/len(table)
        mean_y=sum(r['net_charge_C'] for r in table)/len(table)
        variance=sum((r['phase_skew_s']-mean_x)**2 for r in table)
        if variance>0:
            slope=sum((r['phase_skew_s']-mean_x)*(r['net_charge_C']-mean_y)
                      for r in table)/variance
            offset=mean_y-slope*mean_x
            nonlinearity=max(abs(r['net_charge_C']-(slope*r['phase_skew_s']+offset))
                             for r in table)
    result=dict(points=table,incomplete_or_failed=fail,
                effective_phase_gain_Icp_A=slope,zero_phase_net_charge_C=offset,
                maximum_charge_linearity_residual_C=nonlinearity,
                slope_relative_to_20uA=slope/20e-6 if slope is not None else None,
                scope='Deterministic physical CP charge-vs-time-skew at TT1.2V25C, '
                      'Vctrl clamped .83594V, 200ps common reset, ideal reference '
                      'and pulse controls; not complete PFD/CP noise or loop proof.')
    txt=json.dumps(result,indent=2,allow_nan=False)+'\n'
    if args.out:Path(args.out).write_text(txt,encoding='utf-8')
    print(txt)


if __name__=='__main__':main()
