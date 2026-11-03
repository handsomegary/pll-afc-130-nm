"""Read-only two-point actual MOS VCO/receiver/divider loading measurements.
Measures divider against actual carrier, separately tests the 3.2GHz target.
"""
import argparse
import json
from pathlib import Path

import measure_digital_units as unit
from measure_receiver_sweep import clock_margin


def frequency(t,y):
    edges=unit.rising(t,y,0)
    return (len(edges)-1)/(edges[-1]-edges[0]) if len(edges)>=20 else None


def measure(data,begin=40e-9,end=75e-9):
    idx=[i for i,v in enumerate(data['time']) if begin<=v<=end]
    t=[data['time'][i] for i in idx]
    y={n:[wave[i] for i in idx] for n,wave in data.items() if n!='time'}
    diff=[a-b for a,b in zip(y['out0'],y['out180'])]
    fq=frequency(t,diff)
    if not fq:raise ValueError('Missing sustained actual VCO carrier')
    result=unit.measure(data,'receiver',begin,end,fin=fq)
    result.update(clock_margin(data,begin,end))
    result['actual_vco_frequency_Hz']=fq
    result['actual_vco_differential_vpp_V']=max(diff)-min(diff)
    result['target_Hz']=3.2e9
    result['target_relative_error']=fq/3.2e9-1
    result['target_frequency_ok']=abs(result['target_relative_error'])<.001
    result['interface_valid']=bool(result['valid'] and result['clk_rail_dwell_valid'] and result['clk_rail_margin_V']>=0
                                   and result['actual_vco_differential_vpp_V']>.05)
    result['valid']=bool(result['interface_valid'] and result['target_frequency_ok'])
    if 'VDDIG:p' in y and 'vdddig' in y:
        result['digital_supply_power_W']=unit.mean(t,[-v*i for v,i in zip(y['vdddig'],y['VDDIG:p'])])
        result['vco_and_bias_supply_power_W']=result['total_supply_power_W']-result['digital_supply_power_W']
    result['scope']='Actual MOS VCO+RF receiver+AC/selfbias CMOS+physical divide32; nominal open loop only, no PFD/CP/AFC/noise/PEX'
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cases',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();manifest=Path(args.cases).resolve()
    latest={c['name']:c for c in json.loads(manifest.read_text()) if c.get('name','').startswith('tb_loaded_interface_')}
    results=[]
    for name,c in latest.items():
        r={'name':name,'case_id':c.get('case_id'),'analysis_state':c.get('state'),
           'spectre_rc':c.get('spectre_rc'),'bench_sha256':c.get('bench_sha256'),
           'source_set_sha256':c.get('source_set_sha256'),'valid':False,'interface_valid':False}
        if c.get('state')!='completed' or c.get('spectre_rc')!=0:
            r['reason']='Simulator did not complete successfully';results.append(r);continue
        try:
            raw=[Path(a) for a in c.get('artifacts',[]) if a.endswith('.raw')]
            if len(raw)!=1:raise ValueError('Expected one raw directory')
            p=raw[0].resolve();p.relative_to(manifest.parent)
            wave=p/'tran.tran.tran'
            data=unit.read_psf(wave,40e-9,75e-9)
            r.update(measure(data));r['raw_file']=str(wave);r['raw_sha256']=unit.file_sha256(wave)
        except Exception as error:r['reason']=repr(error)
        results.append(r)
    qualified=[r for r in results if r['interface_valid']]
    chosen=min(qualified,key=lambda r:abs(r['target_relative_error'])) if qualified and len(results)==2 else None
    result={'scope':'Two bounded actual loaded VCO/interface operating points; no complete PLL or noise validation',
            'case_count':len(results),'all_two_present':len(results)==2,
            'interface_passed':len(qualified),'target_passed':sum(r['valid'] for r in results),
            'closest_valid_interface_case':chosen['name'] if chosen else None,
            'closest_target_relative_error':chosen['target_relative_error'] if chosen else None,
            'cases':results}
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['case_count','interface_passed','target_passed','closest_valid_interface_case','closest_target_relative_error']}))
    return 0 if result['target_passed'] else 2


if __name__=='__main__':raise SystemExit(main())
