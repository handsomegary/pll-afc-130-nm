#!/usr/bin/env bash
set -euo pipefail
cd @PROJECT_ROOT@
python3 - <<'PY'
import json,shutil,time
from pathlib import Path
import run_background_phase3 as helper
project=Path.cwd().resolve()
records=json.loads((project/'results/biasopt/biasopt_v3_cases.json').read_text())
record=next(r for r in records if r['case_id'].startswith('dc_cal_area8_') and r['state']=='completed')
source=helper.contained(project,Path(record['netlist_path']))
tag='resume_dc_probe_20261007_'+str(int(time.time()))
netlist=project/'netlists'/(tag+'.scs'); netlist.write_text(source.read_text())
raw=project/'results'/(tag+'.raw'); log=project/'logs'/(tag+'.log')
rc=helper.run_process([shutil.which('spectre'),str(netlist),'-format','psfascii',
                      '-raw',str(raw),'+log',str(log)],project/'logs'/(tag+'.stdout'),
                     project,time.monotonic()+30)
result={'tag':tag,'rc':rc,'waveform_present':(raw/'dcBias.dc').is_file(),
        'log_summary':helper.spectral_log_summary(log),'source_netlist':str(source)}
helper.atomic_json(project/'results/resume_dc_probe_20261007.json',result)
print(json.dumps(result))
if rc or not result['waveform_present']: raise SystemExit(1)
PY
