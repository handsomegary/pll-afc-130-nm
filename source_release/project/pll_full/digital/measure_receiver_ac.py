"""Read-only nominal three-case AC receiver electrical and power selection."""
import argparse
import json
from pathlib import Path

import measure_digital_units as unit
from measure_receiver_sweep import clock_margin


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cases',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();manifest=Path(args.cases).resolve()
    latest={c['name']:c for c in json.loads(manifest.read_text()) if c.get('name','').startswith('tb_receiverac_')}
    results=[]
    for name,c in latest.items():
        r={'name':name,'case_id':c.get('case_id'),'spectre_rc':c.get('spectre_rc'),
           'analysis_state':c.get('state'),'bench_sha256':c.get('bench_sha256'),
           'source_set_sha256':c.get('source_set_sha256'),'valid':False}
        if c.get('state')!='completed' or c.get('spectre_rc')!=0:
            r['reason']='Simulator did not complete successfully';results.append(r);continue
        try:
            raw=[Path(a) for a in c.get('artifacts',[]) if a.endswith('.raw')]
            if len(raw)!=1:raise ValueError('Expected one raw directory')
            p=raw[0].resolve();p.relative_to(manifest.parent)
            waveform=p/'tran.tran.tran'
            if waveform.stat().st_size>512*1024*1024:raise ValueError('Oversized unit raw >512MiB')
            data=unit.read_psf(waveform,20e-9,95e-9)
            r.update(unit.measure(data,'receiver',20e-9,95e-9));r.update(clock_margin(data))
            r['valid']=bool(r['valid'] and r['clk_rail_dwell_valid'] and r['clk_rail_margin_V']>=0)
            r['raw_sha256']=unit.file_sha256(waveform);r['raw_file']=str(waveform)
        except Exception as error:r['reason']=repr(error)
        results.append(r)
    passed=[r for r in results if r['valid']];selected=None
    if passed and len(results)==3:
        best=max(r['clk_rail_margin_V'] for r in passed)
        near=[r for r in passed if r['clk_rail_margin_V']>=best-0.005]
        selected=min(near,key=lambda r:r.get('total_supply_power_W',float('inf')))
    result={'scope':'Nominal AC/selfbias receiver + physical divider; ideal incoming clock and no actual VCO loading/PVT/noise/PEX validation',
            'case_count':len(results),'passed':len(passed),'all_three_present':len(results)==3,
            'selected_candidate':selected['name'] if selected else None,
            'selected_rail_margin_V':selected['clk_rail_margin_V'] if selected else None,
            'selected_total_supply_power_W':selected['total_supply_power_W'] if selected else None,
            'selection_rule':'Frequency+rail+period screens and >=20% high/low clock rail dwell; maximize time-weighted clock rail margin, lowest power within 5mV margin tolerance.',
            'cases':results}
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['case_count','passed','selected_candidate','selected_rail_margin_V','selected_total_supply_power_W']}))
    return 0 if selected else 2


if __name__=='__main__':raise SystemExit(main())
