"""Read a finished bounded solver comparison; do not overwrite selections."""
import argparse,hashlib,json,sys
from pathlib import Path
project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
sys.path.insert(0,str(project/'pll_full/digital'))
import measure_loaded_interface as loaded
ap=argparse.ArgumentParser();ap.add_argument('--cases',required=True);ap.add_argument('--output',required=True)
args=ap.parse_args();rows=[]
for r in json.loads(Path(args.cases).read_text()):
    item={k:r.get(k) for k in ['name','case_id','bench_sha256','state','spectre_rc','simulator_engine','simulator_threads','started_unix','finished_unix']}
    if r['state']=='completed' and r.get('spectre_rc')==0:
        assert hashlib.sha256(Path(r['bench']).read_bytes()).hexdigest()==r['bench_sha256']
        raw=[Path(p) for p in r['artifacts'] if p.endswith('.raw')][0]/'tran.tran.tran'
        item.update(loaded.measure(loaded.unit.read_psf(raw,40e-9,75e-9)))
        item.update(raw_file=str(raw),raw_sha256=loaded.unit.file_sha256(raw))
    rows.append(item)
Path(args.output).write_text(json.dumps(rows,indent=2,allow_nan=False))
print(json.dumps([{k:r.get(k) for k in ['name','interface_valid','actual_vco_frequency_Hz','total_supply_power_W']} for r in rows]))
