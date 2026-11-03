"""Source-bound read-only clamp excursion ledger for a completed owned PLL."""
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execution',type=Path,required=True)
    ap.add_argument('--measurement',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():raise ValueError('OutputExists')
    execution=json.loads(args.execution.read_text()); measurement=json.loads(args.measurement.read_text())
    if execution.get('state')!='completed' or execution.get('spectre_rc')!=0 or execution.get('source_models_unchanged_at_completion') is not True:
        raise ValueError('Completed unchanged source execution required')
    if measurement['execution_evidence']['sha256']!=sha(args.execution):raise ValueError('Measurement/execution mismatch')
    for p,r in list(execution['own_dependencies'].items())+list(execution['model_dependencies'].items()):
        if sha(p)!=r['sha256']:raise ValueError('Dependency changed: '+p)
    here=Path(__file__).resolve().parent
    sys.path.insert(0,str(here/'monitor_v3_first_edge'))
    import measure_afc2009 as m
    config=json.loads(json.dumps(measurement['configuration']))
    config['analogs']={k:v for k,v in config['analogs'].items() if k in ['ctrl','filter_mid','vhold']}
    config['digitals']={k:v for k,v in config['digitals'].items() if k in ['enable','hold','fine_enable']}
    config['words']={'code':config['words']['code']}
    raw=Path(execution['raw'])/'tran.tran.tran'
    data,digital,words,provenance=m.read_saved_vectors(raw,config,256)
    if provenance['raw_sha256']!=measurement['source_evidence']['raw_sha256']:raise ValueError('Raw measurement binding mismatch')
    h=measurement['handoff'];lo=h['afc_enable_time_s']+config['handoff_guard_s'];hi=h['fine_enable_time_s']-config['handoff_guard_s']
    idx=[i for i,t in enumerate(data['time']) if lo<=t<=hi and m.event_value(digital['hold']['levels'],t)==1]
    def point(i):
        return {'time_s':data['time'][i],'ctrl_V':data['ctrl'][i],'filter_mid_V':data['filter_mid'][i],
            'vhold_V':data['vhold'][i],'code':m.event_value(words['code'],data['time'][i]),
            'ctrl_minus_target_V':data['ctrl'][i]-config['clamp_V'],
            'ctrl_minus_vhold_V':data['ctrl'][i]-data['vhold'][i]}
    maximum=max(idx,key=lambda i:abs(data['ctrl'][i]-config['clamp_V']))
    reference=max(idx,key=lambda i:abs(data['ctrl'][i]-data['vhold'][i]))
    tol=config['clamp_tolerance_V'];bad=[i for i in idx if abs(data['ctrl'][i]-config['clamp_V'])>tol]
    groups=[]
    for i in bad:
        if not groups or i!=groups[-1][-1]+1:groups.append([i])
        else:groups[-1].append(i)
    excursions=[{'first_saved_s':data['time'][g[0]],'last_saved_s':data['time'][g[-1]],
        'saved_sample_count':len(g),'peak':point(max(g,key=lambda i:abs(data['ctrl'][i]-config['clamp_V'])))} for g in groups]
    result={'name':execution['name'],'numerically_completed':True,
        'unchanged_acceptance_tolerance_V':tol,'held_audit_interval_s':[lo,hi],
        'maximum_target_error_sample':point(maximum),'maximum_reference_error_sample':point(reference),
        'excursions_above_unchanged_tolerance':excursions,
        'above_tolerance_saved_samples':len(bad),'code_ledger':words['code'],
        'source_evidence':provenance,'execution_evidence':{'path':str(args.execution),'sha256':sha(args.execution)},
        'measurement_evidence':{'path':str(args.measurement),'sha256':sha(args.measurement)},
        'reader_evidence':{str(p):sha(p) for p in [Path(__file__),here/'monitor_v3_first_edge/measure_afc2009.py']},
        'scope':'Actual saved40ps samples only. Excursion spans are first/last violating saved samples, not interpolated continuous-time widths. No pass override or causal conclusion.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'name':result['name'],'maximum_target_error_sample':result['maximum_target_error_sample'],
        'excursion_groups':len(excursions),'above_tolerance_saved_samples':len(bad)}))


if __name__=='__main__':main()
