"""Read-only six-point receiver screening and bounded interface selection.
Time-weighted clock rail quantiles avoid selecting an overshoot peak as margin.
Selection is a nominal interface candidate, not a PVT/noise/loaded-VCO proof.
"""
import argparse
import hashlib
import json
from pathlib import Path

import measure_digital_units as unit


def time_quantile(t,y,quantile):
    samples=[]
    for i in range(len(t)):
        left=t[i]-t[i-1] if i else 0
        right=t[i+1]-t[i] if i+1<len(t) else 0
        samples.append((y[i],(left+right)/2))
    samples.sort(key=lambda pair:pair[0])
    limit=quantile*(t[-1]-t[0]);total=0
    for value,weight in samples:
        total+=weight
        if total>=limit:
            return value
    return samples[-1][0]


def clock_margin(data,start=20e-9,end=95e-9,vd=1.2):
    idx=[i for i,x in enumerate(data['time']) if start<=x<=end]
    t=[data['time'][i] for i in idx]
    y=[data['clk'][i] for i in idx]
    low=time_quantile(t,y,0.1);high=time_quantile(t,y,0.9)
    span=t[-1]-t[0]
    high_dt=low_dt=0
    for i in range(len(t)-1):
        mid=(y[i]+y[i+1])/2;dt=t[i+1]-t[i]
        if mid>=0.9*vd:high_dt+=dt
        if mid<=0.1*vd:low_dt+=dt
    return {'time_weighted_clk_10pct_V':low,'time_weighted_clk_90pct_V':high,
            'clk_rail_margin_V':min(0.1*vd-low,high-0.9*vd),
            'clk_high_rail_dwell_fraction':high_dt/span,
            'clk_low_rail_dwell_fraction':low_dt/span,
            'clk_rail_dwell_valid':high_dt/span>=0.20 and low_dt/span>=0.20}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cases',required=True)
    ap.add_argument('--output',required=True)
    args=ap.parse_args()
    manifest=Path(args.cases).resolve()
    cases=json.loads(manifest.read_text())
    latest={}
    for c in cases:
        name=c.get('name','')
        if name.startswith('tb_receiver_r'):
            latest[name]=c
    results=[]
    for name,c in latest.items():
        record={'name':name,'case_id':c.get('case_id'),'analysis_state':c.get('state'),
                'spectre_rc':c.get('spectre_rc'),'valid':False,
                'source_set_sha256':c.get('source_set_sha256'),'bench_sha256':c.get('bench_sha256')}
        if c.get('state')!='completed' or c.get('spectre_rc')!=0:
            record['reason']='Simulator did not complete successfully'
            results.append(record);continue
        try:
            raw=[Path(a) for a in c.get('artifacts',[]) if a.endswith('.raw')]
            if len(raw)!=1:raise ValueError('Expected one raw directory')
            p=raw[0].resolve();p.relative_to(manifest.parent)
            waveform=p/'tran.tran.tran'
            if waveform.stat().st_size>512*1024*1024:raise ValueError('Oversized unit raw >512MiB')
            data=unit.read_psf(waveform,20e-9,95e-9)
            record.update(unit.measure(data,'receiver',20e-9,95e-9))
            record.update(clock_margin(data))
            record['valid']=bool(record['valid'] and record['clk_rail_dwell_valid'] and record['clk_rail_margin_V']>=0)
            record['raw_sha256']=unit.file_sha256(waveform)
            record['raw_file']=str(waveform)
        except Exception as error:record['reason']=repr(error)
        results.append(record)
    valid=[r for r in results if r['valid']]
    selected=None
    if valid and len(results)==6:
        highest=max(r['clk_rail_margin_V'] for r in valid)
        # Clock rail differences <5mV are nominally tiny; use lower total power
        # within this stated margin tolerance. Never select a failing interface.
        near=[r for r in valid if r['clk_rail_margin_V']>=highest-0.005]
        selected=min(near,key=lambda r:r.get('total_supply_power_W',float('inf')))
    result={'scope':'Ideal differential clock into actual RF receiver + actual MOS divide32; nominal only, not actual VCO loading/PVT/noise',
            'cases_manifest':str(manifest),'case_count':len(results),'all_six_present':len(results)==6,
            'passed':len(valid),'selected_candidate':selected['name'] if selected else None,
            'selected_rail_margin_V':selected['clk_rail_margin_V'] if selected else None,
            'selected_total_supply_power_W':selected['total_supply_power_W'] if selected else None,
            'selection_rule':'Pass all stage frequency/rail/period checks and >=20% high/low clock rail dwell; maximize time-weighted clock rail margin, then lowest power within 5mV of best margin.',
            'cases':results}
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['case_count','passed','selected_candidate','selected_rail_margin_V','selected_total_supply_power_W']}))
    return 0 if selected else 2


if __name__=='__main__':raise SystemExit(main())
