import concurrent.futures
import json
import re
import subprocess
from run_vco_tg_scan import project, seed

target=seed
(project/'netlists/vco_tg_target.scs').write_text(target+'\n')

def corner_case(case):
    k,code=case
    label='tg_{}_c{}'.format(k,code)
    text=target.replace('VCTRLVAL=0.895','VCTRLVAL=0.6').replace('section=tt','section='+k)
    bits=' '.join('CODE{}={}'.format(i,(code>>i)&1) for i in range(5))
    text=re.sub(r'parameters CODE0=.*','parameters '+bits,text)
    path=project/'netlists'/('vco_'+label+'.scs')
    path.write_text(text+'\n')
    raw=project/'results'/('vco_'+label)
    with open(project/'logs'/('vco_'+label+'.stdout'),'w') as handle:
        rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw',str(raw),'+log',str(project/'logs'/('vco_'+label+'.log'))],stdout=handle,stderr=subprocess.STDOUT)
    result={'label':label,'code':code,'vctrl_V':0.6,'corner':k,'fine_switch':'TG','spectre_rc':rc}
    if rc==0:
        measured=subprocess.check_output(['python3','measure_psf.py',str(raw/'tran.tran.tran'),'30e-9','45e-9']).decode()
        detail=json.loads(measured)
        (project/'results'/('vco_'+label+'_measure.json')).write_text(measured)
        result.update({a:detail.get(a) for a in ['frequency_Hz','differential_vpp_V','supply_power_W','q_rising_phase_deg']})
    print(json.dumps(result),flush=True)
    return result

def noise():
    text=re.sub(r'tran tran .*',
        'pss (out0 out180) pss fund=3.2G tstab=40n harms=30 errpreset=conservative harmonicbalance=no maxstep=0.5p tstabmethod=gear2only method=gear2only\n'
        'pnoise (out0 out180) pnoise start=10k stop=100M dec=30 sweeptype=relative relharmnum=1 maxsideband=30 noiseout=[pm] noisetype=timeaverage',target)
    path=project/'netlists/vco_tg_noise.scs'
    path.write_text(text+'\n')
    with open(project/'logs/vco_tg_noise.stdout','w') as handle:
        rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw','results/vco_tg_noise','+log','logs/vco_tg_noise.log'],stdout=handle,stderr=subprocess.STDOUT)
    print('TG_NOISE_RC={}'.format(rc),flush=True)
    print((project/'logs/vco_tg_noise.log').read_text()[-2200:],flush=True)
    return rc

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    nf=pool.submit(noise)
    results=list(pool.map(corner_case,[(k,c) for k in ['tt','ss','ff'] for c in [0,16,31]]))
    (project/'results/tg_final_corners.json').write_text(json.dumps(results,indent=2))
    nf.result()
