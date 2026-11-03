"""Add a bounded4p acquisition-only copy; keeps the original 1ps bench.
Relaxed accuracy is labelled in the filename/manifest, never used for jitter.
"""
import hashlib
import json
from pathlib import Path
import re


def main():
    root=Path(__file__).resolve().parent
    src=root/'benches/pll_afc_stage1_initial16.scs'
    text=src.read_text()
    text,n=re.subn(r'(simulatorOptions options temp=25 )reltol=1e-5 vabstol=1e-7 iabstol=1e-12',
                   r'\1reltol=1e-4 vabstol=1e-6 iabstol=1e-12',text)
    if n!=1:raise ValueError('Expected one source global tolerance line')
    text,n=re.subn(r'maxstep=1p errpreset=conservative',
                   'maxstep=4p errpreset=moderate',text)
    if n!=1:raise ValueError('Expected one transient accuracy line')
    text='// Bounded 4ps/moderate acquisition check only; not noise/jitter/signoff.\n'+text
    path=root/'benches/pll_afc_stage1_initial16_bounded4p.scs';path.write_text(text)
    data={'name':path.stem,'path':str(path),'bench_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
          'original_1ps_bench':str(src),'original_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
          'initial_code':16,'duration_s':3e-6,'maxstep_s':4e-12,'errpreset':'moderate',
          'reltol':1e-4,'vabstol_V':1e-6,'scope':'AFC+fine-loop acquisition only; relaxed deterministic solver accuracy, no noise or jitter evidence'}
    (root/'benches/afc_bounded_manifest.json').write_text(json.dumps(data,indent=2)+'\n')
    print('Prepared bounded4p AFC copy, original retained; no simulation launch.')


if __name__=='__main__':main()
