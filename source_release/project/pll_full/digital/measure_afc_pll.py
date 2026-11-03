"""Measure MOS-VCO + VA AFC staged PLL, with a mandatory AFC-success gate.
No simulation launch. Reads only PSF ASCII and writes explicitly requested JSON.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'analog'))
import measure_pll


def measure(values):
    t=values.get('time',[])
    n=len(t)
    needed=['afc_enable','afc_done','afc_hold','fine_enable','hold_all','ctrl']
    needed+=['s'+str(i) for i in range(5)]
    for name in needed:
        measure_pll.require_wave(values,name,n)
    if n<20:
        raise ValueError('Insufficient transient samples')
    enable_edges=measure_pll.edge_times(t,values['afc_enable'],0.6)
    done_edges=measure_pll.edge_times(t,values['afc_done'],0.6)
    fine_edges=measure_pll.edge_times(t,values['fine_enable'],0.6)
    e=enable_edges[0] if enable_edges else None
    d=done_edges[0] if done_edges else None
    f=fine_edges[0] if fine_edges else None
    code=sum((1<<i) if values['s'+str(i)][-1]>0.6 else 0 for i in range(5))
    afc_pass=bool(e is not None and d is not None and f is not None
                  and d>=e and f>=d and values['afc_done'][-1]>1.08
                  and values['fine_enable'][-1]>1.08
                  and values['hold_all'][-1]<0.12)
    during=[i for i in range(n) if values['afc_enable'][i]>1.08
            and values['afc_done'][i]<0.12]
    clamp_error=max(abs(values['ctrl'][i]-0.8359375) for i in during) if during else None
    if clamp_error is None or clamp_error>0.03:
        afc_pass=False
    result={'scope':'Actual selected MOS VCO, functional AFC/receiverless-divider/PFD/CP, ideal LPF/reference; no physical digital noise/power/PEX',
            'selected_code':code,'afc_enable_time_s':e,'afc_done_time_s':d,
            'fine_enable_time_s':f,'afc_duration_s':d-e if d is not None and e is not None else None,
            'clamp_max_error_V':clamp_error,'afc_success':afc_pass,
            'locked':False,'valid':False}
    if f is not None:
        loop=measure_pll.measure_lock(values,enable_s=f)
        result['fine_loop']=loop
        result['locked']=bool(afc_pass and loop.get('locked'))
        result['valid']=result['locked']
        result['overall_lock_after_afc_enable_s']=loop.get('lock_time_s')-e if loop.get('lock_time_s') is not None and e is not None else None
    else:
        result['reason']='AFC did not release fine loop; do not accept an apparent steady VCO frequency as PLL lock'
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',required=True)
    ap.add_argument('--output',required=True)
    args=ap.parse_args()
    result=measure(measure_pll.read_psf(args.raw))
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'afc_success':result['afc_success'],'selected_code':result['selected_code'],
                      'locked':result['locked'],'valid':result['valid']}))
    return 0 if result['valid'] else 2


if __name__=='__main__':
    sys.exit(main())
