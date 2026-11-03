"""Read-only compact teaching traces from one completed PSFASCII waveform.

No simulation, SSH, UI, or changes to raw data. Python 3.6+.
Frequency is measured from actual differential edges in 100ns windows,
stepped by50ns, not inferred from Kvco/control voltage or labelled instantaneous.
"""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
from measure_pll import read_psf,edge_times,edge_frequency
from measure_cp_units import interpolate


def waveform_file(path):
    path=Path(path)
    if path.is_file():return path
    files=[p for p in path.glob('*tran*') if p.is_file() and not p.name.endswith('.info')]
    if len(files)!=1:raise ValueError('Expected exactly one transient waveform file.')
    return files[0]


def file_sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while True:
            block=f.read(1024*1024)
            if not block:break
            h.update(block)
    return h.hexdigest()


def export(path,name=None,stage='unspecified',scope=None,power_scope=None):
    raw=waveform_file(path)
    d=read_psf(raw);t=d.get('time',[]);n=len(t)
    if n<20 or t[-1]<=t[0] or any(t[i+1]<=t[i] for i in range(n-1)):
        raise ValueError('Invalid/nonmonotonic waveform time grid.')
    for k in ['ctrl','out0','out180']:
        if len(d.get(k,[]))!=n:raise ValueError('Missing or malformed waveform '+k)
    diff=[a-b for a,b in zip(d['out0'],d['out180'])]
    edges=edge_times(t,diff)
    requested_interval=5e-9
    expected=int(math.floor((t[-1]-t[0])/requested_interval))+1
    stride=max(1,int(math.ceil(expected/1000.0)))
    interval=requested_interval*stride
    count=int(math.floor((t[-1]-t[0])/interval))+1
    sample_time=[t[0]+i*interval for i in range(count)]
    control=[interpolate(t,d['ctrl'],x) for x in sample_time]
    frequency_time=[];frequencies=[];details=[]
    begin=t[0];width=100e-9;step=50e-9
    while begin+width<=t[-1]+1e-15:
        end=min(t[-1],begin+width)
        a,b=bisect.bisect_left(t,begin),bisect.bisect_right(t,end)
        y=diff[a:b];vpp=max(y)-min(y) if y else 0
        f=edge_frequency(edges,begin,end,min_edges=10) if vpp>=.05 else None
        ea,eb=bisect.bisect_left(edges,begin),bisect.bisect_right(edges,end)
        frequency_time.append((begin+end)*.5*1e6)
        frequencies.append(f)
        details.append(dict(begin_s=begin,end_s=end,differential_vpp_V=vpp,
                            rising_edges_count=eb-ea,
                            measured_crossing_span_s=edges[eb-1]-edges[ea] if eb-ea>=2 else None,
                            valid_frequency=f is not None))
        begin+=step
    decimation=1
    if len(frequency_time)>1000:
        decimation=int(math.ceil(len(frequency_time)/1000.0))
        frequency_time=frequency_time[::decimation]
        frequencies=frequencies[::decimation]
        details=details[::decimation]
    optional={}
    for k in ['s0','s1','s2','s3','s4','hold','done','fine_enable','enable','rst',
              'afc_enable','afc_hold','afc_done','hold_all']:
        if len(d.get(k,[]))==n:
            optional[k]=[interpolate(t,d[k],x) for x in sample_time]
    return dict(name=name or raw.parent.name,stage=stage,
                time_us=[x*1e6 for x in sample_time],ctrl_V=control,
                frequency_time_us=frequency_time,frequency_Hz=frequencies,
                frequency_GHz=[x/1e9 if x is not None else None for x in frequencies],
                frequency_window_width_ns=100,frequency_window_step_ns=50,
                rendered_frequency_point_spacing_ns=50*decimation,
                frequency_time_coordinate='window_center',frequency_window_details=details,
                auxiliary_control_voltage_traces=optional,
                metadata=dict(raw_waveform_path=str(raw.resolve()),raw_waveform_sha256=file_sha256(raw),
                              original_waveform_samples=n,trace_control_points=len(sample_time),
                              trace_frequency_points=len(frequencies),
                              requested_control_sample_interval_s=requested_interval,
                              actual_control_sample_interval_s=interval,
                              original_waveform_begin_s=t[0],original_waveform_end_s=t[-1],
                              scope=scope or 'Staged PLL acquisition; consult bench for physical/VA blocks.',
                              power_scope=power_scope or 'This trace export does not calculate power. '
                                          'Consult the corresponding bench and measured power result '
                                          'for physical and declared Verilog-A contributions.',
                              noise_scope='No physical noise; traces do not prove rms noise jitter.'),
                frequency_definition='(number of differential rising crossings minus1)/(last minusfirst crossing time), '
                                     'inside100ns windows stepped50ns, Vpp>=50mV and at least10edges; '
                                     'frequency points can be null; never instantaneous frequency.')


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('raw')
    ap.add_argument('--out',required=True)
    ap.add_argument('--name')
    ap.add_argument('--stage',default='unspecified')
    ap.add_argument('--scope')
    ap.add_argument('--power-scope')
    args=ap.parse_args()
    result=export(args.raw,name=args.name,stage=args.stage,scope=args.scope,power_scope=args.power_scope)
    Path(args.out).write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(out=args.out,name=result['name'],stage=result['stage'],
                          control_points=len(result['time_us']),
                          frequency_points=len(result['frequency_time_us']),
                          raw_waveform_sha256=result['metadata']['raw_waveform_sha256']),indent=2))
