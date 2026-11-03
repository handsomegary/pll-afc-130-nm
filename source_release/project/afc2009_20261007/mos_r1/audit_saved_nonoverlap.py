"""Pure-read bounded PSF-ASCII audit of saved physical clock control phases.

Python3.6+ stdlib. No simulator/session control or netlist/manifest mutation.
Checks sample-visible overlap and linearly interpolated guard intervals only.
It cannot rule out sub-strobe overlap, transient hold races, metastability/PVT.
"""
from __future__ import print_function
import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import re

LINE=re.compile(r'^"([^\"]+)"\s+(?:"[^\"]+"\s+)?([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)(?:\s|$)')
MAX_RAW=512*1024*1024


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def read(path,names):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>MAX_RAW:raise ValueError('Missing or excessive raw')
    before=sha(path);values={name:array('d') for name in ['time']+names};block={};reading=False
    def commit():
        if not block:return
        if set(block)!=set(values):raise ValueError('Missing selected scalar at saved sample: '+str(set(values)-set(block)))
        if values['time'] and block['time']<=values['time'][-1]:raise ValueError('Nonmonotonic saved time')
        for key,v in block.items():values[key].append(v)
        if sum(len(a)*a.itemsize for a in values.values())>32*1024*1024:raise ValueError('32MiB selected-vector guard exceeded')
    with path.open(encoding='utf-8',errors='replace') as f:
        for line in f:
            line=line.strip()
            if line=='VALUE':reading=True;continue
            if not reading:continue
            if line=='END':commit();block={};break
            match=LINE.match(line)
            if not match:continue
            name=match.group(1)
            if name not in values:continue
            value=float(match.group(2))
            if not math.isfinite(value):raise ValueError('Nonfinite selected scalar')
            if name=='time':commit();block={'time':value}
            else:block[name]=value
    if block:commit()
    if before!=sha(path):raise ValueError('Raw changed during read-only extraction')
    if len(values['time'])<20:raise ValueError('Insufficient saved samples')
    return values,before


def events(t,y,threshold=.6,inverted=False):
    result=[];state=int(y[0]<=threshold) if inverted else int(y[0]>threshold);result.append((t[0],state))
    for i in range(1,len(t)):
        new=int(y[i]<=threshold) if inverted else int(y[i]>threshold)
        if new!=state:
            crossing=t[i-1]+(threshold-y[i-1])*(t[i]-t[i-1])/(y[i]-y[i-1]);result.append((crossing,new));state=new
    return result


def union_events(*ledgers):
    current=[ledger[0][1] for ledger in ledgers];merged=[]
    for index,ledger in enumerate(ledgers):merged.extend((time,index,state) for time,state in ledger[1:])
    merged.sort();result=[(min(ledger[0][0] for ledger in ledgers),int(any(current)))]
    for time,index,state in merged:
        current[index]=state;state=int(any(current))
        if state!=result[-1][1]:result.append((time,state))
    return result


def phase_summary(t,master,slave,begin,end):
    boundaries=[];state={'M':master[0][1],'S':slave[0][1]};previous_closed={};deadtime=[];overlap=[]
    for label,ledger in [('M',master),('S',slave)]:boundaries.extend((time,label,value) for time,value in ledger[1:])
    boundaries.sort();overlap_start=None
    for time,label,value in boundaries:
        state[label]=value
        other='S' if label=='M' else 'M'
        if value==0:previous_closed[label]=time
        elif begin<=time<=end and other in previous_closed:
            guard=time-previous_closed[other]
            if guard>=0:deadtime.append({'open':label,'open_time_s':time,'other_close_time_s':previous_closed[other],'interpolated_guard_s':guard})
        now_overlap=bool(state['M'] and state['S'])
        if now_overlap and overlap_start is None:overlap_start=time
        elif not now_overlap and overlap_start is not None:
            if time>=begin and overlap_start<=end:overlap.append({'begin_s':max(begin,overlap_start),'end_s':min(end,time),'duration_s':min(end,time)-max(begin,overlap_start)})
            overlap_start=None
    valid=[d['interpolated_guard_s'] for d in deadtime]
    return {'interpolated_guard_intervals':deadtime,'minimum_interpolated_guard_s':min(valid) if valid else None,
            'maximum_interpolated_guard_s':max(valid) if valid else None,'interpolated_overlap_intervals':overlap}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--raw',required=True);ap.add_argument('--manifest',required=True);ap.add_argument('--source',required=True)
    ap.add_argument('--expected-raw-sha',required=True);ap.add_argument('--out',required=True);ap.add_argument('--prefix',default='XAFC.');ap.add_argument('--begin-s',type=float,default=120e-9);ap.add_argument('--vdd',type=float,default=1.2);args=ap.parse_args()
    manifestpath=Path(args.manifest);manifestsha=sha(manifestpath);manifest=json.loads(manifestpath.read_text(encoding='utf-8'))
    sourcesha=sha(args.source)
    if sourcesha!=manifest['source_sha256']:raise ValueError('Source/manifest hash mismatch')
    hierarchy=manifest['diagnostic_hierarchy'];keys=['controller_master_open','controller_master_openb','controller_slave_open','controller_slave_openb','controller_clock']
    actual={key:args.prefix+hierarchy[key] for key in keys};data,rawsha=read(args.raw,list(actual.values()))
    if rawsha!=args.expected_raw_sha:raise ValueError('Wrong raw digest')
    if sha(args.source)!=sourcesha or sha(manifestpath)!=manifestsha:raise ValueError('Source/manifest changed while reading')
    t=data['time'];y={key:data[name] for key,name in actual.items()};begin=args.begin_s;end=t[-1];threshold=args.vdd*.5
    selected=[i for i,time in enumerate(t) if begin<=time<=end]
    both_logic=[i for i in selected if y['controller_master_open'][i]>threshold and y['controller_slave_open'][i]>threshold]
    both_drive=[i for i in selected if (y['controller_master_open'][i]>threshold or y['controller_master_openb'][i]<=threshold) and (y['controller_slave_open'][i]>threshold or y['controller_slave_openb'][i]<=threshold)]
    both_off=[i for i in selected if y['controller_master_open'][i]<=threshold and y['controller_master_openb'][i]>threshold and y['controller_slave_open'][i]<=threshold and y['controller_slave_openb'][i]>threshold]
    master=events(t,y['controller_master_open'],threshold);slave=events(t,y['controller_slave_open'],threshold)
    masterdrive=union_events(master,events(t,y['controller_master_openb'],threshold,inverted=True));slavedrive=union_events(slave,events(t,y['controller_slave_openb'],threshold,inverted=True))
    steps=[t[i]-t[i-1] for i in range(1,len(t))]
    result={'version':'read-only-nonoverlap-saved-vector-v1','source_sha256':sourcesha,'manifest_sha256':manifestsha,
            'raw_file':args.raw,'raw_sha256':rawsha,'raw_bytes':Path(args.raw).stat().st_size,'raw_unchanged':True,'simulator_started':False,
            'selected_nodes':actual,'saved_samples':len(t),'selected_sample_interval_s':[begin,end],
            'maximum_observed_saved_step_s':max(steps),'minimum_observed_saved_step_s':min(steps),'gate_threshold_V':threshold,
            'sampled_both_logical_open_count':len(both_logic),'sampled_any_TG_device_drive_overlap_count':len(both_drive),'sampled_both_TG_paths_off_count':len(both_off),
            'sampled_overlap_times_s':[t[i] for i in both_drive[:30]],
            'logical_open_interpolation':phase_summary(t,master,slave,begin,end),
            'TG_gate_drive_interpolation':phase_summary(t,masterdrive,slavedrive,begin,end),
            'status':'no_overlap_in_saved_samples' if not both_logic and not both_drive else 'overlap_present_in_saved_samples',
            'limits':['100ps saved samples can miss narrower overlaps or multiple crossings between samples.','Linear interpolation is an estimate, not unsampled waveform reconstruction.','The0.6V gate classification is not a PDK transistor conduction/current criterion.','Only primary controller phases checked; other clock/reset groups, PVT, MC, hold time, charge retention, CDC and metastability not certified.']}
    out=Path(args.out)
    if out.resolve() in {Path(args.raw).resolve(),manifestpath.resolve(),Path(args.source).resolve()}:raise ValueError('Output would overwrite input')
    if out.exists():raise ValueError('Immutable evidence output already exists')
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['status','source_sha256','raw_sha256','saved_samples','sampled_both_logical_open_count','sampled_any_TG_device_drive_overlap_count','sampled_both_TG_paths_off_count']},indent=2))
    print('minimum_interpolated_guard_s='+str(result['TG_gate_drive_interpolation']['minimum_interpolated_guard_s']))


if __name__=='__main__':main()
