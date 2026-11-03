"""Read real Spectre PSF ASCII vectors for the prepared R2 counter subset.

Uses actual saved CLK/REF/reset edges and independent modulo512 edge ordinals.
No simulator launch; no synthesized waveform or behavioral circuit decisions.
"""
import argparse
from array import array
import bisect
import hashlib
import json
import math
from pathlib import Path
import re

LINE=re.compile(r'^"([^\"]+)"\s+(?:"[^\"]+"\s+)?([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)(?:\s|$)')
MAX_RAW_BYTES=512*1024*1024


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def read_vectors(path,selected,memory_mib=192):
    path=Path(path).resolve()
    if not path.is_file() or path.stat().st_size>MAX_RAW_BYTES:raise ValueError('Missing raw or raw exceeds 512MiB guard.')
    before=sha(path);data={name:array('d') for name in ['time']+sorted(selected)}
    block={};reading=False
    def commit():
        if 'time' not in block:return
        if data['time'] and block['time']<=data['time'][-1]:raise ValueError('Saved time not strictly increasing.')
        missing=[name for name in data if name not in block]
        if missing:raise ValueError('Missing required saved scalars: '+', '.join(missing))
        for name in data:data[name].append(block[name])
        if len(data)*len(data['time'])*8*1.2>memory_mib*1024*1024:raise ValueError('Selected-vector memory guard exceeded.')
    with path.open(encoding='utf-8',errors='replace') as stream:
        for raw in stream:
            line=raw.strip()
            if line=='VALUE':reading=True;continue
            if line=='END':commit();block={};break
            if not reading:continue
            match=LINE.match(line)
            if not match:continue
            name=match.group(1)
            if name not in data:continue
            value=float(match.group(2))
            if not math.isfinite(value):raise ValueError('Nonfinite saved scalar: '+name)
            if name=='time':commit();block={'time':value}
            else:block[name]=value
    if block:commit()
    if len(data['time'])<20:raise ValueError('Insufficient transient samples.')
    after=sha(path)
    if before!=after:raise ValueError('Raw changed during read-only extraction.')
    return data,{'raw_file':str(path),'raw_sha256':before,'raw_bytes':path.stat().st_size,'saved_samples':len(data['time']),'raw_unchanged_during_read':True,'raw_guard_bytes':MAX_RAW_BYTES,'selected_vector_memory_guard_MiB':memory_mib}


def transitions(t,y,threshold):
    rows=[]
    for i in range(len(t)-1):
        state0=int(y[i]>threshold);state1=int(y[i+1]>threshold)
        if state0!=state1:
            when=t[i]+(threshold-y[i])*(t[i+1]-t[i])/(y[i+1]-y[i])
            rows.append((when,state1))
    return rows


def at(t,y,point):
    j=bisect.bisect_left(t,point)
    if j==0:return y[0]
    if j>=len(t):raise ValueError('Sample outside saved waveform.')
    fraction=(point-t[j-1])/(t[j]-t[j-1])
    return y[j-1]+fraction*(y[j]-y[j-1])


def word_at(data,names,point,threshold):
    return sum(int(at(data['time'],data[name],point)>threshold)<<i for i,name in enumerate(names))


def gray(binary):return binary^(binary>>1)


def analyze(data,manifest,sample_delay):
    times=data['time'];threshold=manifest['threshold_V'];modulus=manifest['modulus'];violations=[]
    if sample_delay<=0:raise ValueError('Stable sampling delay must be positive.')
    ledgers={name:transitions(times,data[name],threshold) for name in ('clk','ref','rst')}
    reset=int(data['rst'][0]>threshold);epoch=0;ordinal=0
    state={label:{'native':words['initial_native'],'sync1':0,'sync2':0} for label,words in manifest['words'].items()}
    events=sorted([(when,0,'rst',level) for when,level in ledgers['rst']]+[(when,1,'clk',level) for when,level in ledgers['clk'] if level]+[(when,2,'ref',level) for when,level in ledgers['ref'] if level])
    sample_rows=[];epoch_ordinals={};clock_rises=[when for when,level in ledgers['clk'] if level];ref_rises=[when for when,level in ledgers['ref'] if level]
    for when,_,kind,level in events:
        if kind=='rst':
            reset=level
            if reset:
                for label,words in manifest['words'].items():state[label]={'native':words['initial_native'],'sync1':0,'sync2':0}
            else:epoch+=1;ordinal=0
            closest=min([abs(edge-when) for edge in clock_rises+ref_rises] or [float('inf')])
            if closest<.5e-9:violations.append({'type':'reset_edge_inside_declared_aperture_guard','time_s':when,'nearest_CLK_or_REF_s':closest})
        elif kind=='clk':
            if not reset:
                ordinal+=1;epoch_ordinals[epoch]=ordinal
                for item in state.values():item['native']=(item['native']+1)%modulus
        else:
            if reset:
                for label,words in manifest['words'].items():state[label]={'native':words['initial_native'],'sync1':0,'sync2':0}
            else:
                for item in state.values():item['sync2']=item['sync1'];item['sync1']=item['native']
            point=when+sample_delay
            if point>times[-1]:continue
            intervening_clock=[edge for edge in clock_rises if when<edge<=point]
            intervening_reset=[edge for edge,_ in ledgers['rst'] if when<edge<=point]
            if intervening_clock or intervening_reset:
                violations.append({'type':'sample_crosses_CLK_or_reset_event','ref_edge_s':when,'sample_s':point});continue
            row={'REF_edge_s':when,'sample_s':point,'reset':reset,'reset_epoch':epoch,'active_CLK_edge_ordinal':ordinal,'words':{}}
            for label,words in manifest['words'].items():
                expected={'native_binary':state[label]['native'],'native_gray':gray(state[label]['native']),'sync1_gray':gray(state[label]['sync1']),'sync2_gray':gray(state[label]['sync2']),'sync2_binary':state[label]['sync2']}
                actual={name:word_at(data,names,point,threshold) for name,names in words.items() if isinstance(names,list)}
                row['words'][label]={'expected':expected,'actual':actual}
                mismatch={name:{'expected':value,'actual':actual[name]} for name,value in expected.items() if actual[name]!=value}
                if mismatch:violations.append({'type':'word_mismatch','REF_edge_s':when,'sample_s':point,'reset_epoch':epoch,'CLK_ordinal':ordinal,'counter':label,'fields':mismatch})
            sample_rows.append(row)
    boundary_rows={name:[] for name in ('255_to_256','511_to_0')}
    for prior,current in zip(sample_rows,sample_rows[1:]):
        if prior['reset'] or current['reset'] or prior['reset_epoch']!=current['reset_epoch']:continue
        if current['active_CLK_edge_ordinal']!=prior['active_CLK_edge_ordinal']+1:continue
        for label in manifest['words']:
            a=prior['words'][label]['expected']['native_binary'];b=current['words'][label]['expected']['native_binary']
            key='255_to_256' if (a,b)==(255,256) else '511_to_0' if (a,b)==(511,0) else None
            if key:boundary_rows[key].append({'counter':label,'prior':prior,'current':current,'actual_observed_native_pair':[prior['words'][label]['actual']['native_binary'],current['words'][label]['actual']['native_binary']]})
    if epoch_ordinals.get(1,0)<512:violations.append({'type':'first_active_epoch_has_less_than_512_CLK_edges','active_edges':epoch_ordinals.get(1,0)})
    for key,rows in boundary_rows.items():
        if len({row['counter'] for row in rows})<len(manifest['words']):violations.append({'type':'required_boundary_not_covered','boundary':key})
    reset_rows=[row for row in sample_rows if row['reset']]
    if not any(row['reset_epoch']==0 for row in reset_rows):violations.append({'type':'initial_reset_preset_not_sampled'})
    if not any(row['reset_epoch']==1 for row in reset_rows):violations.append({'type':'second_reset_preset_not_sampled'})
    spacing=max(b-a for a,b in zip(times,times[1:]))
    phase_offsets=[]
    for edge in ref_rises:
        index=bisect.bisect_right(clock_rises,edge)-1
        if index>=0:phase_offsets.append(edge-clock_rises[index])
    period_ranges={}
    for name,rises,hz in [('CLK',clock_rises,manifest['native_clock_Hz']),('REF',ref_rises,manifest['reference_Hz'])]:
        periods=[b-a for a,b in zip(rises,rises[1:])]
        period_ranges[name]=[min(periods),max(periods)] if periods else None
        if not periods or any(abs(period-1/hz)>.2e-9 for period in periods):violations.append({'type':'external_clock_period_outside_declared_contract','clock':name,'period_range_s':period_ranges[name],'expected_Hz':hz})
    if not phase_offsets or any(abs(offset-manifest['REF_rising_after_CLK_rising_s'])>.2e-9 for offset in phase_offsets):violations.append({'type':'external_CLK_REF_phase_outside_declared_contract','offset_range_s':[min(phase_offsets),max(phase_offsets)] if phase_offsets else None})
    return {'status':'measured_checks_passed' if not violations else 'measured_checks_failed','violations':violations,'stable_REF_samples_checked':len(sample_rows),'active_CLK_edges_by_reset_epoch':epoch_ordinals,'sample_delay_after_actual_REF_s':sample_delay,'actual_CLK_to_REF_offset_range_s':[min(phase_offsets),max(phase_offsets)] if phase_offsets else None,'actual_clock_period_ranges_s':period_ranges,'external_clock_contract_tolerance_s':.2e-9,'maximum_saved_spacing_s':spacing,'required_native_boundary_examples':boundary_rows,'initial_reset_sample':next((r for r in reset_rows if r['reset_epoch']==0),None),'second_reset_sample':next((r for r in reset_rows if r['reset_epoch']==1),None),'rows_near_reset_release':[row for row in sample_rows if row['active_CLK_edge_ordinal']<=3],'CLK_REF_reset_transition_ledgers':ledgers,'model':'Independent actual CLK-edge ordinal modulo512 and two previous REF-captured Gray words; preset native0/1, both CDC stages reset0. Circuit waveform never synthesized by reader.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True)
    ap.add_argument('--subset-source',type=Path,required=True);ap.add_argument('--bench',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--sample-delay-ns',type=float,default=2.5)
    args=ap.parse_args();manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    if sha(args.subset_source)!=manifest['subset_source_sha256']:raise ValueError('Subset source hash does not match manifest.')
    if sha(args.bench)!=manifest['bench_sha256']:raise ValueError('Bench hash does not match manifest.')
    selected={'clk','ref','rst'}|{name for item in manifest['words'].values() for names in item.values() if isinstance(names,list) for name in names}
    data,evidence=read_vectors(args.raw,selected)
    result=analyze(data,manifest,args.sample_delay_ns*1e-9)
    result.update({'source_evidence':evidence,'manifest_sha256':sha(args.manifest),'subset_source_sha256':sha(args.subset_source),'bench_sha256':sha(args.bench),'fixed_R2_AFC_source_sha256':manifest['fixed_R2_AFC_source_sha256'],'R2_builder_sha256':manifest['R2_builder_sha256'],'simulator_started_by_reader':False,'scope':'Measured saved-word correctness for this lightly loaded counter/CDC subset only. 100ps saved sampling may miss narrower events; not full-AFC fanout/CDC, metastability, setup/hold or all-PVT signoff.'})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('status','stable_REF_samples_checked','active_CLK_edges_by_reset_epoch','maximum_saved_spacing_s')},indent=2))
    print('violations='+str(len(result['violations'])))
    if result['violations']:raise SystemExit(1)


if __name__=='__main__':main()
