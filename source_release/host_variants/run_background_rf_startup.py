"""Bounded RF startup search, detached and without UI."""
import json
import os
from pathlib import Path
import re
import subprocess
import time

project=Path('@PROJECT_ROOT@')
os.chdir(str(project))
seed=(project/'netlists/phase2_rf_v600.scs').read_text()
started=time.time(); results=[]
status=project/'results/rf_startup_status.json'

def update(stage,**fields):
    payload={'stage':stage,'pid':os.getpid(),'started_unix':started,'updated_unix':time.time(),'cases_completed':len(results)}
    payload.update(fields)
    status.write_text(json.dumps(payload,indent=2))
    print(json.dumps(payload),flush=True)

def run(label,rload,regen_nf,tail_nf,code=16,ctrl=.6):
    text=seed.replace('RLOAD=620','RLOAD={}'.format(rload))
    text=text.replace('VCTRLVAL=0.6','VCTRLVAL={}'.format(ctrl))
    text=re.sub(r'parameters CODE0=.*','parameters '+' '.join('CODE{}={}'.format(i,(code>>i)&1) for i in range(5)),text)
    text=re.sub(r'(XREGEN[12] \([^\n]+\) n12_ckt_rf [^\n]*nf=)8\b',lambda m:m[1]+str(regen_nf),text)
    text=re.sub(r'(XTAILREGEN \([^\n]+\) n12_ckt_rf [^\n]*nf=)10\b',lambda m:m[1]+str(tail_nf),text)
    text+='\nrfFinalOP info what=oppoint where=rawfile\n'
    path=project/'netlists'/('rfstartup_'+label+'.scs')
    path.write_text(text)
    raw=project/'results'/('rfstartup_'+label)
    log=project/'logs'/('rfstartup_'+label+'.log')
    with open(project/'logs'/('rfstartup_'+label+'.stdout'),'w') as handle:
        try:
            rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw',str(raw),'+log',str(log)],stdout=handle,stderr=subprocess.STDOUT,timeout=300)
        except subprocess.TimeoutExpired: rc=124
    result={'label':label,'rload_ohm':rload,'regen_total_W_um':3*regen_nf,'regen_tail_total_W_um':3*tail_nf,'code':code,'vctrl_V':ctrl,'rc':rc,
            'scope':'mixed RF sensitivity; fixed assumed stress geometry; not layout/PEX verification'}
    if rc==0:
        measured=subprocess.check_output(['python3','measure_psf.py',str(raw/'tran.tran.tran'),'25e-9','38e-9'],timeout=120).decode()
        d=json.loads(measured)
        (project/'results'/('rfstartup_'+label+'_measure.json')).write_text(measured)
        result.update({k:d.get(k) for k in ['frequency_Hz','differential_vpp_V','supply_power_W','q_rising_phase_deg']})
        result['valid']=bool(result['frequency_Hz'] and result['differential_vpp_V']>.05 and result['q_rising_phase_deg'] is not None)
    else:
        result['valid']=False
        result['diagnostic_tail']=log.read_text()[-1200:] if log.exists() else 'No log'
    results.append(result)
    (project/'results/rf_startup_cases.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(result),flush=True)
    return result

try:
    update('searching')
    chosen=None
    for r,nf,tnf in [(820,8,10),(1000,8,10),(620,12,10),(820,12,10),(820,16,10),(620,16,16)]:
        name='r{}_g{}_t{}'.format(r,nf,tnf)
        result=run(name,r,nf,tnf)
        update('searching',last_case=result)
        if result['valid']:
            chosen=(r,nf,tnf)
            break
    if chosen:
        r,nf,tnf=chosen
        update('range_check',chosen={'rload':r,'regen_nf':nf,'tail_nf':tnf})
        extra=[run('chosen_c16_v895',r,nf,tnf,16,.895),
               run('chosen_c0_v600',r,nf,tnf,0,.6),
               run('chosen_c31_v600',r,nf,tnf,31,.6)]
        update('complete',chosen={'rload':r,'regen_nf':nf,'tail_nf':tnf},range_cases=extra,
               remaining='Noise, stable startup/ramp, refined model reference, all codes/PVT/loaded PLL remain.')
    else:
        update('needs_design_review',reason='None of six RF startup candidates met frequency/swing/I-Q criteria.')
except Exception as e:
    update('failed',error=repr(e))
    raise
