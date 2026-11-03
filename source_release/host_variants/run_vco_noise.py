import os
from pathlib import Path
import re
import subprocess

project=Path('@PROJECT_ROOT@')
os.chdir(str(project))
netlist=(project/'netlists/vco_scale3.scs').read_text()
netlist=re.sub(r'tran tran .*',
    'pss (out0 out180) pss fund=3.02G tstab=100n harms=30 errpreset=conservative harmonicbalance=no\n'
    'pnoise (out0 out180) pnoise start=10k stop=100M dec=30 sweeptype=relative relharmnum=1 maxsideband=30 noiseout=[pm] noisetype=timeaverage',netlist)
path=project/'netlists/vco_noise_smoke.scs'
path.write_text(netlist)
with open(project/'logs/vco_noise_smoke.stdout','w') as handle:
    rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw','results/vco_noise_smoke','+log','logs/vco_noise_smoke.log'],stdout=handle,stderr=subprocess.STDOUT)
print('SPECTRE_RC={}'.format(rc))
print((project/'logs/vco_noise_smoke.log').read_text()[-3500:])
