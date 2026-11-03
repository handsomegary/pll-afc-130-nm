import concurrent.futures
import json
import subprocess
from run_vco_scan import project, seed

def run(label, ctrl, cap, skipdc):
    netlist=seed.replace('VCTRLVAL=0.6','VCTRLVAL={}'.format(ctrl))
    netlist=netlist.replace('WMAIN=18u WREGEN=8u','WMAIN=54u WREGEN=24u')
    netlist=netlist.replace('maxstep=1p','maxstep=0.5p')
    netlist=netlist.replace('skipdc=yes','skipdc='+skipdc)
    netlist=netlist.replace('save vdd out0', 'save vdd out0')
    if cap:
        netlist=netlist.replace('XREF (vdd 0 bn bp) current_ref','XREF (vdd 0 bn bp) current_ref\nCBIAS (bn 0) capacitor c={}p'.format(cap))
    path=project/'netlists'/('vco_'+label+'.scs')
    path.write_text(netlist+'\n')
    raw=project/'results'/('vco_'+label)
    with open(project/'logs'/('vco_'+label+'.stdout'),'w') as handle:
        rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw',str(raw),'+log',str(project/'logs'/('vco_'+label+'.log'))],stdout=handle,stderr=subprocess.STDOUT)
    result={'label':label,'vctrl_V':ctrl,'bias_cap_pF':cap,'skipdc':skipdc,'spectre_rc':rc}
    if rc==0:
        measured=subprocess.check_output(['python3','measure_psf.py',str(raw/'tran.tran.tran'),'20e-9','45e-9']).decode()
        detail=json.loads(measured)
        (project/'results'/('vco_'+label+'_measure.json')).write_text(measured)
        result.update({k:detail.get(k) for k in ['frequency_Hz','differential_vpp_V','supply_power_W','q_rising_phase_deg']})
        result['bn']=detail['bn']
    print(json.dumps(result),flush=True)
    return result

cases=[('dcinit',0.6,0,'no'),('bias1p_v6',0.6,1,'no'),('bias1p_v9',0.9,1,'no')]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results=list(pool.map(lambda c:run(*c),cases))
(project/'results/bias_check.json').write_text(json.dumps(results,indent=2))

