import concurrent.futures
import json
import re
import subprocess
from run_vco_scan import project

seed=(project/'netlists/vco_final_target.scs').read_text()
for i,label in enumerate(['s8up','s16up','s24up']):
    anchor='MSUPCTRL{} (g{}up {}_p ctrl vss) n12 w=WSW l=LCORE'.format(i,[8,16,24][i],label)
    addition='\n    PSUPCTRL{} (g{}up {}_n ctrl vdd) p12 w=1.5u l=LCORE'.format(i,[8,16,24][i],label)
    if anchor not in seed:
        raise ValueError('Missing pass-switch anchor '+anchor)
    seed=seed.replace(anchor,anchor+addition)
seed=seed.replace('// Starting dimensions only: frequency, startup and noise are unverified.',
                  '// Porting revision: complementary TGs pass the fine control voltage without NMOS threshold clipping.')

def run(ctrl):
    label='tg_v{}'.format(int(round(ctrl*1000)))
    netlist=seed.replace('VCTRLVAL=0.895','VCTRLVAL={}'.format(ctrl))
    path=project/'netlists'/('vco_'+label+'.scs')
    path.write_text(netlist+'\n')
    raw=project/'results'/('vco_'+label)
    with open(project/'logs'/('vco_'+label+'.stdout'),'w') as handle:
        rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw',str(raw),'+log',str(project/'logs'/('vco_'+label+'.log'))],stdout=handle,stderr=subprocess.STDOUT)
    result={'label':label,'code':16,'vctrl_V':ctrl,'corner':'tt','maxstep_ps':1,'bias_cap_pF':1,'skipdc':'no','spectre_rc':rc,'fine_switch':'TG'}
    if rc==0:
        measured=subprocess.check_output(['python3','measure_psf.py',str(raw/'tran.tran.tran'),'30e-9','45e-9']).decode()
        detail=json.loads(measured)
        (project/'results'/('vco_'+label+'_measure.json')).write_text(measured)
        result.update({k:detail.get(k) for k in ['frequency_Hz','differential_vpp_V','supply_power_W','q_rising_phase_deg']})
    print(json.dumps(result),flush=True)
    return result

if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(run,[0.75,0.8,0.85]))
    (project/'results/tg_scan.json').write_text(json.dumps(results,indent=2))
