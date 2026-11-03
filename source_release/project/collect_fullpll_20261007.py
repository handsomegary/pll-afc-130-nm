"""Read-only waveform measurement and manifests; no simulator launches."""
import json
import sys
from pathlib import Path
project = Path('@PROJECT_ROOT@')
assert Path.cwd().resolve() == project
units = project/'results/fullpll/units'
records = []
for path in sorted(units.glob('all_cases*.json')):
    records += json.loads(path.read_text())
(units/'merged_cases.json').write_text(json.dumps(records, indent=2))
sys.path.insert(0,str(project/'pll_full/digital'))
import measure_all_digital_units
sys.argv = ['measure_all_digital_units.py','--cases',str(units/'merged_cases.json'),
            '--output',str(units/'digital_electrical_measurements.json')]
measure_all_digital_units.main()
sys.path.insert(0,str(project/'pll_full/analog'))
import measure_pll
import measure_afc_pll
results = []
for group in ['stage0','stage1','stage2','stage3','afc']:
    folder = project/'results/fullpll'/group
    for manifest in sorted(folder.glob('all_cases*.json')):
        for record in json.loads(manifest.read_text()):
            item = dict(name=record['name'],stage=group,
                        simulator_state=record['state'],case_id=record['case_id'],
                        source_set_sha256=record.get('source_set_sha256'),
                        bench_sha256=record.get('bench_sha256'),
                        own_dependency_sha256=record.get('own_dependency_sha256'),
                        dependencies=record.get('dependencies'),
                        external_model_dependencies=record.get('external_model_dependencies'),
                        external_model_set_sha256=record.get('external_model_set_sha256'),
                        source_files_unchanged_at_completion=record.get('source_files_unchanged_at_completion'),
                        simulator_engine=record.get('simulator_engine','classic'),
                        simulator_threads=record.get('simulator_threads',1),
                        simulator_command=record.get('simulator_command'),
                        started_unix=record.get('started_unix'),finished_unix=record.get('finished_unix'))
            if record['state']=='completed' and record.get('spectre_rc')==0:
                try:
                    raw = [Path(p) for p in record['artifacts'] if p.endswith('.raw')][0]
                    waveform = raw/'tran.tran.tran'
                    values = measure_pll.read_psf(waveform)
                    if group == 'afc':
                        item.update(measure_afc_pll.measure(values))
                    else:
                        item.update(measure_pll.measure_lock(values,
                                    enable_s=100e-9 if group=='stage0' else 300e-9))
                    item['raw_file'] = str(waveform)
                except Exception as error:
                    item['measurement_error'] = repr(error)
            else:
                item['analysis_error']=record.get('error')
            results.append(item)
(project/'results/fullpll/fullpll_measurements.json').write_text(json.dumps(results,indent=2,allow_nan=False))
for r in results:
    print(json.dumps({k:r[k] for k in ['name','simulator_state','locked','lock_after_enable_s',
                     'final_frequency_Hz','final_power_W','measurement_error'] if k in r}))
