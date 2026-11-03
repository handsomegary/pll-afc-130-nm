import os
from pathlib import Path
import re
import subprocess

project=Path('@PROJECT_ROOT@')
os.chdir(str(project))
netlist=(project/'netlists/vco_bias1p_v9.scs').read_text()
netlist=netlist.replace('VCTRLVAL=0.9','VCTRLVAL=0.895')
netlist=re.sub(r'tran tran .*',
    'pss (out0 out180) pss fund=3.2G tstab=50n harms=30 errpreset=conservative harmonicbalance=no maxstep=0.5p tstabmethod=gear2only method=gear2only\n'
    'pnoise (out0 out180) pnoise start=10k stop=100M dec=30 sweeptype=relative relharmnum=1 maxsideband=30 noiseout=[pm] noisetype=timeaverage',netlist)
path=project/'netlists/vco_final_noise.scs'
path.write_text(netlist)
with open(project/'logs/vco_final_noise.stdout','w') as handle:
    rc=subprocess.call(['spectre',str(path),'-format','psfascii','-raw','results/vco_final_noise','+log','logs/vco_final_noise.log'],stdout=handle,stderr=subprocess.STDOUT)
print('SPECTRE_RC={}'.format(rc))
print((project/'logs/vco_final_noise.log').read_text()[-2200:])

