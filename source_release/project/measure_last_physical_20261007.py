"""Attach nominal physical-tail measurements to exact completed Stage3 case."""
import argparse,json,sys
from pathlib import Path
project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
sys.path.insert(0,str(project/'pll_full/digital'))
from measure_physical_tail import measure,unit
parser=argparse.ArgumentParser()
parser.add_argument('--case-name')
parser.add_argument('--out-name',default='physical_tail_measurements.json')
args=parser.parse_args()
assert Path(args.out_name).name==args.out_name and args.out_name.endswith('.json')
rows=json.loads((project/'results/fullpll/fullpll_measurements.json').read_text())
cases=[r for r in rows if r['stage']=='stage3' and r['simulator_state']=='completed']
if args.case_name:cases=[r for r in cases if r['name']==args.case_name]
assert cases
r=max(cases,key=lambda x:x['finished_unix'])
raw=Path(r['raw_file'])
before=unit.file_sha256(raw)
result=measure(unit.read_psf(raw,1.5e-6,2e-6),1.5e-6,2e-6)
assert unit.file_sha256(raw)==before
result.update(name=r['name'],case_id=r['case_id'],bench_sha256=r['bench_sha256'],
  simulator_engine=r['simulator_engine'],raw_file=str(raw),raw_sha256=before,
  analog_lock_screen_pass=r.get('locked',False),complete_fine_loop_validation=bool(r.get('locked') and result['interface_valid']))
out=project/'results/fullpll/stage3'/args.out_name
out.write_text(json.dumps(result,indent=2,allow_nan=False))
print(json.dumps({k:result.get(k) for k in ['name','complete_fine_loop_validation','interface_valid','actual_vco_frequency_Hz','total_supply_power_W','ctrl_mean_V','filter_mid_mean_V']}))
