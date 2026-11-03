"""Export only completed stage/AFC waveforms to compact teaching JSON."""
import json
import sys
from pathlib import Path
project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
sys.path.insert(0,str(project/'pll_full/analog'))
from export_loop_traces import export
rows=json.loads((project/'results/fullpll/fullpll_measurements.json').read_text())
traces=[]
for r in rows:
    if r.get('simulator_state')!='completed' or not r.get('raw_file'):continue
    stage=r['stage']
    power_scope={
      'stage0':'Declared behavioral VCO/CP current estimate; no physical PLL power.',
      'stage1':'Physical VCO plus declared behavioral CP currents; ideal VA divider/PFD omit real digital power.',
      'stage2':'Physical MOS VCO/PFD/CP; VA divider omits real receiver/divider power.',
      'stage3':'Physical MOS VCO/PFD/CP/receiver/divider; ideal reference/IREF/passives and no AFC digital power.',
      'afc':r.get('scope','Consult AFC source for exact physical/behavioral blocks.')
    }[stage]
    traces.append(export(r['raw_file'],name=r['name'],stage=stage,
                         scope=r.get('scope'),power_scope=power_scope))
out=project/'results/fullpll/lock_trace_series.json'
out.write_text(json.dumps(traces,indent=2,allow_nan=False))
print(json.dumps({'exported_completed_traces':len(traces),'output':str(out)}))
