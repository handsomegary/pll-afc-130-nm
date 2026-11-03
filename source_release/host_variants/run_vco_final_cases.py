import concurrent.futures
import json
import re
import subprocess
from run_vco_scan import project, seed

def run(case):
    label, code, ctrl, corner = case
    netlist=seed.replace('VCTRLVAL=0.6','VCTRLVAL={}'.format(ctrl))
    netlist=netlist.replace('WMAIN=18u WREGEN=8u','WMAIN=54u WREGEN=24u')
    bits=' '.join('CODE{}={}'.format(i,(code>>i)&1) for i in range(5))
    netlist=re.sub(r'parameters CODE0=.*','parameters '+bits,netlist)
    netlist=netlist.replace('section=tt','section='+corner)
    netlist=netlist.replace('skipdc=yes','skipdc=no')
    netlist=netlist.replace('XREF (vdd 0 bn bp) current_ref','XREF (vdd 0 bn bp) current_ref\nCBIAS (bn 0) capacitor c=1p')
    path=project/'netlists'/('vco_'+label+'.scs')
    path.write_text(netlist+'\n')
    raw=project/'results'/('vco_'+label)
    with open(project/'logs'/('vco_'+label+'.stdout'),'w') as handle:
        rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw',str(raw),'+log',str(project/'logs'/('vco_'+label+'.log'))],stdout=handle,stderr=subprocess.STDOUT)
    result={'label':label,'code':code,'vctrl_V':ctrl,'corner':corner,'maxstep_ps':1,'bias_cap_pF':1,'skipdc':'no','spectre_rc':rc}
    if rc==0:
        measured=subprocess.check_output(['python3','measure_psf.py',str(raw/'tran.tran.tran'),'30e-9','45e-9']).decode()
        detail=json.loads(measured)
        (project/'results'/('vco_'+label+'_measure.json')).write_text(measured)
        result.update({k:detail.get(k) for k in ['frequency_Hz','differential_vpp_V','supply_power_W','q_rising_phase_deg']})
        result['bn']=detail['bn']
    print(json.dumps(result),flush=True)
    return result

cases=[('{}_c{}'.format(k,c),c,0.6,k) for k in ['ss','ff'] for c in [0,16,31]]
cases += [('final_tt_c0',0,0.6,'tt'),('final_tt_c31',31,0.6,'tt'),('final_target',16,0.895,'tt')]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results=list(pool.map(run,cases))
(project/'results/final_cases.json').write_text(json.dumps(results,indent=2))
