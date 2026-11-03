#!/usr/bin/env bash
set -euo pipefail
project=@PROJECT_ROOT@
test "$(hostname)" = @GUEST_HOST@
cd "$project"
python3 - <<'PY'
import hashlib,json,os,shutil,time
from pathlib import Path
project=Path.cwd().resolve()
expected=Path('@PROJECT_ROOT@')
assert project==expected
summary={'project':str(project),'time_unix':time.time(),'processes':[],
         'scripts':{},'status':{},'artifacts_present':True}
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit(): continue
    try:
        argv=(proc/'cmdline').read_bytes().decode(errors='replace').split('\0')
        cwd=os.readlink(str(proc/'cwd'))
        comm=(proc/'comm').read_text().strip()
    except OSError: continue
    if comm in ['virtuoso','spectre','lmgrd','cdslmd','ocean','cdsMsgServer'] or (
            cwd==str(project) and any('run_background_' in a for a in argv)):
        summary['processes'].append({'pid':int(proc.name),'comm':comm,'cwd':cwd,'argv':argv})
for name in ['run_background_phase3.py','run_background_bias_opt.py',
             'run_background_receiver_load.py','run_background_rf_validation.py',
             'run_background_startup_late.py','run_background_selected_startup.py']:
    p=project/name
    summary['scripts'][name]=hashlib.sha256(p.read_bytes()).hexdigest()
for name in ['biasopt','receiverload','rfvalidation','selectedstartup']:
    p=project/'results'/(name+'_status.json')
    if p.exists(): summary['status'][name]=json.loads(p.read_text())
p=project/'results/biasopt/biasopt_v3_cases.json'
records=json.loads(p.read_text())
summary['bias_completed']=len([r for r in records if r['state']=='completed'])
missing=[p for r in records if r['state']=='completed' for p in r.get('artifacts',[]) if not Path(p).is_file()]
summary['missing_bias_artifacts']=missing
summary['artifacts_present']=not missing
summary['spectre']=shutil.which('spectre')
summary['ocean']=shutil.which('ocean')
summary['license_environment_present']=any(os.environ.get(k) for k in ['CDS_LIC_FILE','LM_LICENSE_FILE'])
dest=project/'results/resume_preflight_20261007.json'
dest.write_text(json.dumps(summary,indent=2))
print(json.dumps(summary))
PY
