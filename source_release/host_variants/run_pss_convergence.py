import os
from pathlib import Path
import re
import subprocess

project=Path('@PROJECT_ROOT@')
os.chdir(str(project))
seed=(project/'netlists/vco_noise_smoke.scs').read_text()
seed='\n'.join(line for line in seed.splitlines() if not line.startswith('pnoise '))
seed=seed.replace('harmonicbalance=no','harmonicbalance=no maxstep=0.5p tstabmethod=gear2only method=gear2only')
path=project/'netlists/vco_pss_convergence.scs'
path.write_text(seed+'\n')
with open(project/'logs/vco_pss_convergence.stdout','w') as handle:
    rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw','results/vco_pss_convergence','+log','logs/vco_pss_convergence.log'],stdout=handle,stderr=subprocess.STDOUT)
print('SPECTRE_RC={}'.format(rc))
print((project/'logs/vco_pss_convergence.log').read_text()[-2500:])
