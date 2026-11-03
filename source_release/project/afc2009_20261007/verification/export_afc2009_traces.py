"""Read-only, bounded actual AFC/PLL report traces; Python3.6+, stdlib.

Requires raw SHA256 already recorded in completed measurement evidence.
No simulation, guest access, original measurement writes or source mutations.
Use the frozen saved-vector reader, select only trace vectors, retain at most
1000 report points plus actual differential-VCO edge frequency windows.
"""
import argparse
from array import array
import bisect
import copy
import json
import math
from pathlib import Path
import measure_afc2009 as m


def stable_codes(events,end,stability_s=1e-9):
    accepted=[]
    omitted=[]
    for index,(time,code) in enumerate(events):
        following=events[index+1][0] if index+1<len(events) else end
        if following-time<stability_s:
            omitted.append({'time_s':time,'code':code,'duration_s':following-time})
            continue
        if not accepted or accepted[-1][1]!=code:
            accepted.append([time,code])
    return accepted,omitted


def actual_frequency_windows(data,window_s=100e-9,stride_s=50e-9):
    t=data['time']
    if 'out0' not in data or 'out180' not in data:
        return {'available':False,'reason':'No actual saved differential VCO nodes; '
            'ideal unit feedback is not converted into fabricated VCO frequency.',
            'window_ns':window_s*1e9,'stride_ns':stride_s*1e9,'windows':[]}
    diff=array('d',(a-b for a,b in zip(data['out0'],data['out180'])))
    crossings=m.edges(t,diff)
    windows=[]
    begin=t[0]
    index=0
    while begin+window_s<=t[-1]+1e-15:
        end=begin+window_s
        a,b=bisect.bisect_left(t,begin),bisect.bisect_right(t,end)
        span=diff[a:b]
        vpp=max(span)-min(span) if span else None
        f=m.frequency(crossings,begin,end,minimum=10)
        first,last=bisect.bisect_left(crossings,begin),bisect.bisect_right(crossings,end)
        if vpp is None or vpp<.05:
            f=None
        windows.append({'begin_us':begin*1e6,'center_us':(begin+end)*.5e6,
            'end_us':end*1e6,'frequency_Hz':f,'differential_vpp_V':vpp,
            'rising_edges':last-first,
            'first_edge_s':crossings[first] if first<last else None,
            'last_edge_s':crossings[last-1] if first<last else None})
        index+=1
        begin=t[0]+index*stride_s
    return {'available':True,'window_ns':window_s*1e9,'stride_ns':stride_s*1e9,
        'minimum_rising_edges':10,'minimum_differential_vpp_V':.05,
        'method':'(number_of_actual_differential_rising_edges-1)/(last_edge-first_edge) '
            'within100ns windows stepped50ns; crossing time linearly interpolated '
            'between saved differential voltages.',
        'scope':'Actual saved differential VCO edge window averages. No Kvco '
            'frequency estimate, no ideal fb*32 proxy, no instantaneous-frequency '
            'or physical-noise-jitter claim.', 'windows':windows}


def plot_frequency(windows,point_us):
    records=windows.get('windows',[])
    centers=[record['center_us'] for record in records]
    if not centers or point_us<centers[0] or point_us>centers[-1]:
        return None
    index=bisect.bisect_left(centers,point_us)
    if index<len(centers) and abs(centers[index]-point_us)<1e-12:
        f=records[index]['frequency_Hz']
        return f*1e-9 if f is not None else None
    if index==0 or index>=len(centers):
        return None
    a,b=records[index-1],records[index]
    if a['frequency_Hz'] is None or b['frequency_Hz'] is None:
        return None
    fraction=(point_us-a['center_us'])/(b['center_us']-a['center_us'])
    return (a['frequency_Hz']+fraction*(b['frequency_Hz']-a['frequency_Hz']))*1e-9


def report_time_grid(t,codes,digital,max_points,frequency):
    start,end=t[0],t[-1]
    saved_step=max(b-a for a,b in zip(t,t[1:]))
    landmarks={start,end}
    delta=max(saved_step,1e-12)
    for time,code in codes:
        for shift in [-delta,0,delta,1e-9]:
            if start<=time+shift<=end:
                landmarks.add(time+shift)
    for key in ['enable','done','fine_enable']:
        for time,state in digital.get(key,{}).get('levels',[]):
            if time<start or time>end:
                continue
            for shift in [-delta,0,delta]:
                if start<=time+shift<=end:
                    landmarks.add(time+shift)
    for record in frequency.get('windows',[]):
        landmarks.add(record['center_us']*1e-6)
    if len(landmarks)>max_points:
        raise ValueError('Actual transition/window landmarks exceed bounded point budget; '
                         'do not silently discard observed transitions.')
    # Uniform analog coverage fills the remaining budget. Important observed
    # code/handoff points and each frequency-window center stay mandatory.
    remaining=max_points-len(landmarks)
    uniform=[start+(end-start)*(i+1)/(remaining+1) for i in range(remaining)]
    points=sorted(landmarks|set(uniform))
    if len(points)>max_points:
        raise AssertionError('Bounded report grid unexpectedly exceeded cap.')
    return points,{'maximum_saved_sample_spacing_s':saved_step,
        'landmark_count':len(landmarks),'selected_report_points':len(points),
        'max_report_points':max_points,'transition_margin_s':delta,
        'selection':'Keep actual stable-code/handoff landmarks with adjacent saved-step '
            'points and all frequency-window centers; fill remaining positions uniformly. '
            'Analog values interpolate only the actual saved waveform.'}


def export(raw,measurement_json,portmap_json,max_points=1000,name=None,execution_json=None):
    raw=Path(raw).resolve()
    measurement_json=Path(measurement_json).resolve()
    portmap_json=Path(portmap_json).resolve()
    before_measurement=m.sha(measurement_json)
    before_map=m.sha(portmap_json)
    measurement=json.loads(measurement_json.read_text(encoding='utf-8-sig'))
    expected=measurement.get('source_evidence',{})
    if not expected.get('raw_sha256') or not expected.get('raw_file'):
        raise ValueError('Measurement lacks exact raw identity evidence.')
    # Cross-host archived raw paths can differ; exact bytes must still match.
    if m.sha(raw)!=expected['raw_sha256']:
        raise ValueError('Actual raw bytes differ from selected measurement SHA256.')
    execution_evidence=None
    if execution_json is not None:
        execution_json=Path(execution_json).resolve()
        execution_hash=m.sha(execution_json)
        execution=json.loads(execution_json.read_text(encoding='utf-8-sig'))
        if execution.get('state')!='completed' or execution.get('spectre_rc')!=0:
            raise ValueError('Trace requires completed zero-error execution cache.')
        expected_parent=expected['raw_file'].replace('\\','/').rsplit('/',1)[0]
        if execution.get('raw','').replace('\\','/')!=expected_parent:
            raise ValueError('Execution raw artifact differs from measurement waveform parent.')
        execution_evidence={'path':str(execution_json),'sha256':execution_hash,
            'state':execution['state'],'spectre_rc':execution['spectre_rc'],
            'source_models_unchanged_at_completion':execution.get('source_models_unchanged_at_completion')}
    map_config=json.loads(portmap_json.read_text(encoding='utf-8-sig'))
    cfg=copy.deepcopy(m.DEFAULT_CONFIG)
    cfg.update(map_config)
    cfg['analogs']={key:actual for key,actual in cfg['analogs'].items()
                    if key in ['out0','out180','ctrl']}
    cfg['digitals']={key:actual for key,actual in cfg['digitals'].items()
                     if key in ['enable','done','fine_enable']}
    cfg['words']={'code':cfg['words']['code']}
    data,digital,words,evidence=m.read_saved_vectors(raw,cfg,256)
    if evidence['raw_sha256']!=expected['raw_sha256']:
        raise ValueError('Trace extraction raw differs from measurement evidence.')
    t=data['time']
    code,omitted=stable_codes(words.get('code',[]),t[-1])
    if not code:
        raise ValueError('No coherent, stable actual code word available.')
    frequency=actual_frequency_windows(data)
    points,selection=report_time_grid(t,code,digital,max_points,frequency)
    arrays={'time_us':[point*1e6 for point in points],
        'code':[m.event_value(code,point) for point in points]}
    if 'ctrl' in data:
        arrays['ctrl_V']=[m.interpolate(t,data['ctrl'],point) for point in points]
    for canonical in ['done','fine_enable']:
        levels=digital.get(canonical,{}).get('levels',[])
        if levels:
            arrays[canonical]=[m.event_value(levels,point) for point in points]
    if frequency['available']:
        arrays['frequency_GHz']=[plot_frequency(frequency,point*1e6) for point in points]
    if any(len(values)!=len(points) for values in arrays.values()):
        raise ValueError('Report trace vectors are not equal length.')
    if m.sha(measurement_json)!=before_measurement or m.sha(portmap_json)!=before_map:
        raise ValueError('Measurement or portmap changed during trace export.')
    if execution_json is not None and m.sha(execution_json)!=execution_evidence['sha256']:
        raise ValueError('Execution cache changed during trace export.')
    panels=[{'title':'code','key':'code','lo':0,'hi':31,'step':True},
        {'title':'Vctrl V','key':'ctrl_V'},
        {'title':'done / fine','key':'fine_enable','lo':0,'hi':1.15,
            'overlay':'done','step':True}]
    if frequency['available']:
        panels.insert(2,{'title':'VCO GHz (100ns)','key':'frequency_GHz'})
    return {'name':name or measurement.get('name') or raw.parent.name,
        'arrays':arrays,'panels':panels,'frequency_windows':frequency,
        'stable_code_transitions':code,'omitted_sub_ns_code_words':omitted,
        'code_stability_definition_s':1e-9,'plot_selection':selection,
        'source_evidence':dict(evidence,measurement_json=str(measurement_json),
            measurement_sha256=before_measurement,portmap_json=str(portmap_json),
            portmap_sha256=before_map,
            measurement_raw_hash_verified=True,measurement_unchanged_during_export=True,
            exporter_sha256=m.sha(Path(__file__)),
            frozen_reader_sha256=m.sha(Path(m.__file__))),
        'completed_execution_evidence':execution_evidence,
        'execution_completion_proven_in_this_export':execution_evidence is not None,
        'simulator_started':False,'physical_noise_jitter_s':None,
        'scope':'Actual saved-vector trace only. Code plot retains observed words stable '
            'at least1ns and omits sub-ns binary-carry transition words; the actual MOS '
            'electrical effects remain in Vctrl and differential-VCO edge windows. '
            'Missing analogs remain unavailable. frequency_GHz is plot-only linear '
            'interpolation between explicit100ns window centers; frequency_windows '
            'contains exact measured window estimates. No old VA curve, Kvco estimate, '
            'instantaneous frequency or physical random-jitter claim.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',required=True,type=Path)
    ap.add_argument('--measurement-json',required=True,type=Path)
    ap.add_argument('--portmap-json',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--name')
    ap.add_argument('--execution-json',type=Path)
    ap.add_argument('--max-points',type=int,default=1000)
    args=ap.parse_args()
    if not 100<=args.max_points<=1000:
        raise ValueError('Report point cap must be100..1000.')
    if args.output.resolve() in [args.raw.resolve(),args.measurement_json.resolve(),args.portmap_json.resolve()]:
        raise ValueError('Trace output must be a separate artifact.')
    result=export(args.raw,args.measurement_json,args.portmap_json,args.max_points,args.name,
        args.execution_json)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'output':str(args.output.resolve()),'name':result['name'],
        'points':len(result['arrays']['time_us']),
        'actual_VCO_frequency_available':result['frequency_windows']['available']}))


if __name__=='__main__':
    main()
