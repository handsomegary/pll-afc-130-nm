"""Bounded, detached second-round characterization; no GUI or plotting."""
import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess
import time

project=Path('@PROJECT_ROOT@')
os.chdir(str(project))
seed=(project/'netlists/vco_tg_target.scs').read_text()
seed=seed.replace('stop=50n','stop=40n')
seed=seed.replace('save vdd out0 out180 out90 out270 VDD:p bn',
    'save vdd out0 out180 out90 out270 VDD:p bn\n'
    'save XOSC.XSTAGE0.MTAILMAIN:d XOSC.XSTAGE0.MTAILREGEN:d XOSC.XSTAGE0.MFINE:d\n'
    'save XOSC.XSTAGE0.MSUP0:d XOSC.XSTAGE0.MSUP1:d XOSC.XSTAGE0.MSUP2:d')
status_path=project/'results/phase2_status.json'
results=[]
started=time.time()

def update(stage,**fields):
    payload={'stage':stage,'started_unix':started,'updated_unix':time.time(),
             'cases_completed':len(results),'pid':os.getpid()}
    payload.update(fields)
    status_path.write_text(json.dumps(payload,indent=2))
    print(json.dumps(payload),flush=True)

def run_case(case):
    name,design,code,ctrl=case
    text=seed.replace('VCTRLVAL=0.895','VCTRLVAL={}'.format(ctrl))
    text=re.sub(r'parameters CODE0=.*','parameters '+' '.join('CODE{}={}'.format(i,(code>>i)&1) for i in range(5)),text)
    text=text.replace('LFINE=1.04u','LFINE={}u'.format(design['lfine']))
    text=text.replace('WBANK=1.4u','WBANK={}u'.format(design['wbank']))
    text=text.replace('WMAIN_TAIL=18u','WMAIN_TAIL={}u'.format(design['wmain_tail']))
    ratio=design['wbank']/1.4
    text=text.replace('WEXTRA24=0.6u WEXTRA16=0.3u',
                      'WEXTRA24={}u WEXTRA16={}u'.format(.6*ratio,.3*ratio))
    if design.get('rf'):
        include='include "@TECH_ROOT@/models/spectre/ms013_io33_rf_v1p9_spe.lib" section=mos_tt'
        text=text.replace('section=tt','section=tt\n'+include,1)
        for old,new,length,nf in [
            ('MMAIN1','XMAIN1','LCORE',18),('MMAIN2','XMAIN2','LCORE',18),
            ('MREGEN1','XREGEN1','LCORE',8),('MREGEN2','XREGEN2','LCORE',8),
            ('MTAILMAIN','XTAILMAIN','LTAIL',6),('MTAILREGEN','XTAILREGEN','LTAIL',10)]:
            pattern=r'\b'+old+r' (\([^\n]+\)) n12 w=\w+ l=\w+'
            replacement=new+r' \1 n12_ckt_rf lr='+length+' wr=3u nf={} sar=0.4u sbr=0.4u mr=1 mismod=0'.format(nf)
            text,n=re.subn(pattern,replacement,text)
            if n!=1: raise ValueError('RF mapping failed: '+old)
        text='\n'.join(line for line in text.splitlines() if not line.startswith('save XOSC.XSTAGE0.MTAIL'))
    path=project/'netlists'/('phase2_'+name+'.scs')
    path.write_text(text+'\n')
    raw=project/'results'/('phase2_'+name)
    log=project/'logs'/('phase2_'+name+'.log')
    with open(project/'logs'/('phase2_'+name+'.stdout'),'w') as handle:
        try:
            rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw',str(raw),'+log',str(log)],
                stdout=handle,stderr=subprocess.STDOUT,timeout=300)
        except subprocess.TimeoutExpired:
            rc=124
    result={'case':name,'design':design,'code':code,'vctrl_V':ctrl,'rc':rc}
    if rc==0 and (raw/'tran.tran.tran').exists():
        measured=subprocess.check_output(['python3','measure_psf.py',str(raw/'tran.tran.tran'),'25e-9','38e-9'],timeout=120).decode()
        detail=json.loads(measured)
        (project/'results'/('phase2_'+name+'_measure.json')).write_text(measured)
        result.update({key:detail.get(key) for key in ['frequency_Hz','differential_vpp_V','supply_power_W','q_rising_phase_deg']})
        result['valid']=bool(result['frequency_Hz'] and result['differential_vpp_V']>.05 and result['q_rising_phase_deg'] is not None)
        result['branch_mean_A']={key:value['mean'] for key,value in detail.items() if key.startswith('XOSC.')}
    else:
        result['valid']=False
        result['diagnostic_tail']=log.read_text()[-1200:] if log.exists() else 'No log'
    print(json.dumps(result),flush=True)
    return result

def batch(cases,stage):
    collected=[]
    update(stage,scheduled_cases=len(cases))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(run_case,c) for c in cases]
        for future in concurrent.futures.as_completed(futures):
            result=future.result()
            results.append(result); collected.append(result)
            (project/'results/phase2_all_cases.json').write_text(json.dumps(results,indent=2))
            update(stage,scheduled_cases=len(cases),stage_completed=len(collected))
    return collected

try:
    update('starting')
    baseline={'name':'mixed_rf','lfine':1.04,'wbank':1.4,'wmain_tail':18,'rf':True}
    rf=batch([('rf_v600',baseline,16,.6),('rf_v895',baseline,16,.895)],'mixed_rf_sensitivity')
    (project/'results/phase2_rf_check.json').write_text(json.dumps(rf,indent=2))
    designs=[
        {'name':'l3_b14','lfine':3.12,'wbank':1.4,'wmain_tail':19.83},
        {'name':'l5_b14','lfine':5.2,'wbank':1.4,'wmain_tail':20.20},
        {'name':'l3_b11','lfine':3.12,'wbank':1.1,'wmain_tail':25.03},
        {'name':'l5_b11','lfine':5.2,'wbank':1.1,'wmain_tail':25.40}]
    screen=batch([(d['name']+'_c{}_v{}'.format(c,int(v*1000)),d,c,v)
        for d in designs for c in [0,16,24,31] for v in [.3,1.0]],'low_kvco_screen')
    (project/'results/phase2_screen.json').write_text(json.dumps(screen,indent=2))
    candidates=[]
    for d in designs:
        group=[r for r in screen if r['design']['name']==d['name']]
        if all(r['valid'] for r in group) and min(r['frequency_Hz'] for r in group)<3.2e9<max(r['frequency_Hz'] for r in group):
            candidates.append(d)
    candidates.sort(key=lambda d:(-d['lfine'],d['wbank']))
    selected=None; band_reports=[]
    for d in candidates:
        known={(r['code'],r['vctrl_V']):r for r in screen if r['design']['name']==d['name']}
        cases=[(d['name']+'_c{}_v{}'.format(c,int(v*1000)),d,c,v)
               for c in range(32) for v in [.3,1.0] if (c,v) not in known]
        extra=batch(cases,'all32_'+d['name'])
        for r in extra: known[(r['code'],r['vctrl_V'])]=r
        bands=[]
        for c in range(32):
            lo=known[(c,.3)]; hi=known[(c,1.0)]
            bands.append({'code':c,'fmin_Hz':lo.get('frequency_Hz'),'fmax_Hz':hi.get('frequency_Hz'),
                          'valid':lo['valid'] and hi['valid'],
                          'endpoint_average_Kvco_Hz_per_V':(hi['frequency_Hz']-lo['frequency_Hz'])/.7 if lo['valid'] and hi['valid'] else None})
        overlap=[]
        for c in range(31):
            overlap.append({'code_pair':[c,c+1],'overlap_Hz':bands[c]['fmax_Hz']-bands[c+1]['fmin_Hz']
                if bands[c]['valid'] and bands[c+1]['valid'] else None})
        report={'design':d,'bands':bands,'overlap':overlap,
                'scope':'TT/1.2V/25C ordinary MOS; endpoint-only band check, not complete PVT/monotonic/loaded PLL verification'}
        band_reports.append(report)
        (project/'results/phase2_band_reports.json').write_text(json.dumps(band_reports,indent=2))
        if all(b['valid'] and b['fmax_Hz']>b['fmin_Hz'] for b in bands) and all(o['overlap_Hz']>0 for o in overlap):
            target_bands=[b for b in bands if b['fmin_Hz']<=3.2e9<=b['fmax_Hz']]
            if target_bands:
                chosen=min(target_bands,key=lambda b:abs(b['code']-16))
                selected={'design':d,'code':chosen['code'],'band':chosen}
                break
    if selected:
        d=selected['design']; code=selected['code']; lo=.3; hi=1.0; target_cases=[]
        for i in range(6):
            ctrl=(lo+hi)/2
            r=run_case(('target_'+d['name']+'_i{}'.format(i),d,code,ctrl))
            results.append(r); target_cases.append(r)
            if not r['valid']: break
            if r['frequency_Hz']<3.2e9: lo=ctrl
            else: hi=ctrl
        good=[r for r in target_cases if r['valid']]
        if good:
            best=min(good,key=lambda r:abs(r['frequency_Hz']-3.2e9))
            ctrl=best['vctrl_V']
            derivative=batch([('target_derivative_low',d,code,max(.3,ctrl-.01)),
                              ('target_derivative_high',d,code,min(1.0,ctrl+.01))], 'target_local_gain')
            selected['target']=best; selected['derivative_cases']=derivative
            if all(r['valid'] for r in derivative):
                dr=sorted(derivative,key=lambda r:r['vctrl_V'])
                selected['local_Kvco_Hz_per_V']=(dr[1]['frequency_Hz']-dr[0]['frequency_Hz'])/(dr[1]['vctrl_V']-dr[0]['vctrl_V'])
        (project/'results/phase2_selected_design.json').write_text(json.dumps(selected,indent=2))
        update('complete',selected=selected,
               next_work='Noise, RF consistency, loaded divider, cold-start, full PVT and PLL integration remain.')
    else:
        update('needs_design_review',reason='No screened design passed all32 TT endpoint overlap and target-band criteria.')
except Exception as error:
    update('failed',error=repr(error))
    raise

