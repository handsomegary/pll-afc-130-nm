"""Read-only metrics of four additional PFD benches, Python 3.6+.
Phase cases check signed phase integral; frequency cases check signed duty.
"""
import argparse
import json
from pathlib import Path

import measure_digital_units as unit

SPEC={'tb_pfd_ref_lag':('pfd',20e-9,95e-9,-1,100e6,100e6),
      'tb_pfd_equal_phase':('pfd',20e-9,95e-9,0,100e6,100e6),
      'tb_pfd_ref99_fb100':('pfd_frequency',50e-9,490e-9,0,99e6,100e6),
      'tb_pfd_ref100_fb99':('pfd_frequency',50e-9,490e-9,0,100e6,99e6)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cases',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();manifest=Path(args.cases).resolve()
    latest={c['name']:c for c in json.loads(manifest.read_text()) if c.get('name') in SPEC}
    results=[]
    for name,c in latest.items():
        r={'name':name,'case_id':c.get('case_id'),'spectre_rc':c.get('spectre_rc'),
           'analysis_state':c.get('state'),'bench_sha256':c.get('bench_sha256'),
           'source_set_sha256':c.get('source_set_sha256'),'valid':False}
        if c.get('state')!='completed' or c.get('spectre_rc')!=0:
            r['reason']='Simulator did not complete successfully';results.append(r);continue
        try:
            raw=[Path(a) for a in c.get('artifacts',[]) if a.endswith('.raw')]
            if len(raw)!=1:raise ValueError('Expected one raw path')
            p=raw[0].resolve();p.relative_to(manifest.parent)
            kind,begin,end,phase,fr,ff=SPEC[name]
            r.update(unit.measure(unit.read_psf(p/'tran.tran.tran',begin,end),kind,begin,end,
                                  phase_ns=phase,ref_hz=fr,fb_hz=ff))
            r['raw_file']=str(p/'tran.tran.tran')
        except Exception as error:r['reason']=repr(error)
        results.append(r)
    result={'scope':'Nominal MOS PFD functional phase and frequency-direction screens, no PVT/noise/CP deadzone validation',
            'case_count':len(results),'all_four_present':len(results)==4,
            'electrical_pass':len(results)==4 and all(r['valid'] for r in results),
            'pass_count':sum(r['valid'] for r in results),'cases':results}
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['case_count','pass_count','electrical_pass']}))
    return 0 if result['electrical_pass'] else 2


if __name__=='__main__':raise SystemExit(main())
