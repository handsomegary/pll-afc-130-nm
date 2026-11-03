import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess

project = Path('@PROJECT_ROOT@')
os.chdir(str(project))
seed = (project/'netlists/vco_cmos130_seed.scs').read_text()
seed = re.sub(r'\bdelay\b', 'tg_delay', seed)
seed = seed.replace(' gmin=1e-12','')
seed = '\n'.join(line for line in seed.splitlines()
                 if not line.startswith('save ') and ' info ' not in line)
seed = re.sub(r'tran tran stop=.*',
              'save vdd out0 out180 out90 out270 VDD:p bn\ntran tran stop=50n maxstep=1p errpreset=conservative skipdc=yes',seed)

def run_case(case):
    label, code, ctrl, scale, corner, maxstep, sign = case
    netlist = seed
    bits = ' '.join('CODE{}={}'.format(i,(code>>i)&1) for i in range(5))
    netlist = re.sub(r'parameters CODE0=.*', 'parameters '+bits, netlist)
    netlist = netlist.replace('VCTRLVAL=0.6','VCTRLVAL={}'.format(ctrl))
    netlist = netlist.replace('WMAIN=18u WREGEN=8u','WMAIN={}u WREGEN={}u'.format(18*scale,8*scale))
    netlist = netlist.replace('section=tt','section='+corner)
    netlist = netlist.replace('maxstep=1p','maxstep={}p'.format(maxstep))
    if sign<0:
        netlist = netlist.replace('out0=0.901 out180=0.899','out0=0.899 out180=0.901')
    path = project/'netlists'/('vco_'+label+'.scs')
    path.write_text(netlist+'\n')
    raw = project/'results'/('vco_'+label)
    log = project/'logs'/('vco_'+label+'.log')
    with open(project/'logs'/('vco_'+label+'.stdout'),'w') as handle:
        rc = subprocess.call(['spectre',str(path),'-format','psfascii','-raw',str(raw),'+log',str(log)],stdout=handle,stderr=subprocess.STDOUT)
    result = {'label':label,'code':code,'vctrl_V':ctrl,'width_scale':scale,'corner':corner,'maxstep_ps':maxstep,'ic_sign':sign,'spectre_rc':rc}
    if rc==0 and (raw/'tran.tran.tran').exists():
        measured = subprocess.check_output(['python3','measure_psf.py',str(raw/'tran.tran.tran'),'20e-9','45e-9']).decode()
        detail = json.loads(measured)
        (project/'results'/('vco_'+label+'_measure.json')).write_text(measured)
        result.update({key:detail.get(key) for key in ['frequency_Hz','differential_vpp_V','supply_power_W','q_rising_phase_deg']})
        result['out_min_V'] = min(detail[n]['min'] for n in ['out0','out90','out180','out270'])
        result['out_max_V'] = max(detail[n]['max'] for n in ['out0','out90','out180','out270'])
    print(json.dumps(result),flush=True)
    return result

if __name__=='__main__':
    cases=[('code{}'.format(c),c,0.6,1,'tt',1,1) for c in [0,8,16,24,31]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run_case,cases))
    (project/'results/first_code_scan.json').write_text(json.dumps(results,indent=2))

