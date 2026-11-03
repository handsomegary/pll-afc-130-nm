"""Export bounded real saved samples around a completed PLL clamp excursion."""
import argparse
import json
from pathlib import Path
import sys


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execution',type=Path,required=True)
    ap.add_argument('--measurement',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--begin-ns',type=float,default=476)
    ap.add_argument('--end-ns',type=float,default=486)
    a=ap.parse_args()
    if a.output.exists():raise ValueError('OutputExists')
    here=Path(__file__).resolve().parent
    sys.path.insert(0,str(here/'monitor_v3_first_edge'))
    import measure_afc2009 as m
    e=json.loads(a.execution.read_text());actual=json.loads(a.measurement.read_text())
    if e.get('state')!='completed' or e.get('spectre_rc')!=0 or e.get('source_models_unchanged_at_completion') is not True:raise ValueError('Completed unchanged source execution required')
    if actual['execution_evidence']['sha256']!=m.sha(a.execution):raise ValueError('Execution measurement binding mismatch')
    for p,r in list(e['own_dependencies'].items())+list(e['model_dependencies'].items()):
        if m.sha(p)!=r['sha256']:raise ValueError('Dependency changed: '+p)
    cfg=json.loads(json.dumps(actual['configuration']))
    cfg['analogs']={k:v for k,v in cfg['analogs'].items() if k in ['ctrl','filter_mid','vhold']}
    cfg['digitals']={};cfg['words']={'code':cfg['words']['code']}
    raw=Path(e['raw'])/'tran.tran.tran'
    data,digitals,words,provenance=m.read_saved_vectors(raw,cfg,256)
    if provenance['raw_sha256']!=actual['source_evidence']['raw_sha256']:raise ValueError('Actual raw identity mismatch')
    lo,hi=a.begin_ns*1e-9,a.end_ns*1e-9
    if not data['time'][0]<=lo<hi<=data['time'][-1]:raise ValueError('Zoom must stay within saved interval')
    idx=[i for i,t in enumerate(data['time']) if lo<=t<=hi]
    if not 20<=len(idx)<=1000:raise ValueError('Zoom must contain20..1000 actual saved samples')
    arrays={'time_us':[data['time'][i]*1e6 for i in idx],
        'ctrl_V':[data['ctrl'][i] for i in idx],
        'vhold_V':[data['vhold'][i] for i in idx],
        'filter_mid_V':[data['filter_mid'][i] for i in idx],
        'code':[m.event_value(words['code'],data['time'][i]) for i in idx]}
    provenance.update(measurement_file=str(a.measurement.resolve()),measurement_sha256=m.sha(a.measurement),
        execution_file=str(a.execution.resolve()),execution_sha256=m.sha(a.execution),
        extractor_file=str(Path(__file__).resolve()),extractor_sha256=m.sha(Path(__file__)),
        common_reader_sha256=m.sha(here/'monitor_v3_first_edge/measure_afc2009.py'))
    result={'name':e['name']+' clamp waveform after first code selection',
        'arrays':arrays,'x_range_us':[a.begin_ns*.001,a.end_ns*.001],'x_tick_decimals':4,
        'panels':[{'title':'Vctrl / half-supply node (V)','key':'ctrl_V','overlay':'vhold_V','legend':'blue: Vctrl, orange: vhold','lo':.55,'hi':.62},
            {'title':'Filter_mid / half-supply node (V)','key':'filter_mid_V','overlay':'vhold_V','legend':'blue: filter_mid, orange: vhold','lo':.585,'hi':.615},
            {'title':'actual bank code','key':'code','lo':14,'hi':26,'step':True}],
        'source_evidence':provenance,'numerically_completed':True,
        'frequency_windows':{'available':False,'reason':'Local clamp zoom; no RF frequency claim.'},
        'scope':'Actual 40 ps saved samples from the initial wrapper. The strict AFC handoff failed. A code update occurs nearby. The cause and continuous pulse width remain unresolved.'}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'name':result['name'],'actual_samples':len(idx),'output':str(a.output.resolve())}))


if __name__=='__main__':main()
