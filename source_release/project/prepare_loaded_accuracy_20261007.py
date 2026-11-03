"""Preserve the measured circuit and vary only reviewed integration maxstep."""
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
digital=root/'pll_full/digital/benches'
source=digital/'tb_loaded_interface_code28_ctrl835938.scs'
result=json.loads((root/'resume_20261007/loaded_interface_measurements.json').read_text())
record=[r for r in result['cases'] if r['name']==source.stem][0]
assert record['interface_valid']
assert hashlib.sha256(source.read_bytes()).hexdigest()==record['bench_sha256']
text=source.read_text()
assert text.count('maxstep=4p')==1
cases=[]
for step in [2,1]:
    name='tb_loaded_accuracy_code28_step{}p'.format(step)
    path=digital/(name+'.scs')
    revised=text.replace('maxstep=4p','maxstep={}p'.format(step))
    assert revised.replace('maxstep={}p'.format(step),'maxstep=4p')==text
    path.write_text(revised)
    cases.append(dict(name=name,maxstep_s=step*1e-12,bench_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
       original_bench_sha256=record['bench_sha256'],change='analysis maxstep only; circuit/tolerances/strobe/duration identical'))
(digital/'loaded_accuracy_manifest.json').write_text(json.dumps(cases,indent=2))
print(json.dumps(cases))
