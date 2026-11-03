"""Resume remaining PLL checks after verifying this project's current identity."""
import hashlib
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import time

project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
sys.path.insert(0,str(project))
import run_background_phase3 as helper

choices=[
 ('receiverload','run_background_receiver_load.py',['--wait-bias-opt','--wait-seconds','3600','--noise']),
 ('rfvalidation','run_background_rf_validation.py',['--wait-bias-opt','--max-workers','1']),
 ('selectedstartup','run_background_selected_startup.py',[]),
]
launch=json.loads((project/'results/resume_launch_20261007.json').read_text())
preflight=json.loads((project/'results/resume_preflight_20261007.json').read_text())
expected=dict(preflight['scripts']);expected.update(launch['reviewed_driver_sha256'])
for name in expected:
    assert hashlib.sha256((project/name).read_bytes()).hexdigest()==expected[name], 'Driver/helper changed: '+name
choice=json.loads((project/'results/biasopt_selected.json').read_text())
bias=json.loads((project/'results/biasopt_status.json').read_text())
assert bias['stage']=='complete' and choice['verified'] is True
assert all(choice.get(k)==bias.get(k) and choice.get(k) for k in ['version','source_sha256'])
source=helper.contained(project,Path(choice['netlist_path']))
assert source.is_file()
records=json.loads((project/'results/biasopt/biasopt_v3_cases.json').read_text())
assert all(Path(p).is_file() for r in records if r['state']=='completed' for p in r.get('artifacts',[]))
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():continue
    try:
        argv=(proc/'cmdline').read_bytes().split(b'\0')
        cwd=os.readlink(str(proc/'cwd'))
    except OSError:continue
    if cwd==str(project) and any(name.encode() in argv for _,name,_ in choices):
        raise RuntimeError('Existing own driver; duplicate launch refused: '+proc.name)
for _,name,_ in choices:py_compile.compile(str(project/name),doraise=True)
stamp=str(int(time.time()))
manifest=project/'results'/('resume_pending_launch_'+stamp+'.json')
report={'project':str(project),'reason':'User requested continuation; previous drivers no longer exist.',
        'selected_name':choice['name'],'bias_completed_retained':len(records),'drivers':[]}
for kind,name,args in choices:
    old=json.loads((project/'results'/(kind+'_status.json')).read_text())
    if old.get('stage') in ['complete_sampled_checks','complete_analyses','complete','complete_with_rejections']:
        report['drivers'].append({'name':name,'skipped_complete_stage':old['stage']})
        continue
    log=project/'logs'/('resume_pending_'+stamp+'_'+kind+'.log')
    with log.open('w') as stream:
        p=subprocess.Popen(['python3','-u',name]+args,cwd=str(project),stdin=subprocess.DEVNULL,
                           stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    row={'name':name,'pid':p.pid,'log':str(log),'argv':['python3','-u',name]+args,
         'process_start_ticks':Path('/proc/{}/stat'.format(p.pid)).read_text().split()[21]}
    report['drivers'].append(row);helper.atomic_json(manifest,report)
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=json.loads((project/'results'/(kind+'_status.json')).read_text())
        if state.get('pid')==p.pid:
            assert state.get('stage') not in ['failed','stopped','interrupted'], state
            row['initial_stage']=state.get('stage');helper.atomic_json(manifest,report)
            print(json.dumps(row),flush=True)
            break
        if p.poll() is not None:raise RuntimeError('Driver exited before new status: '+name)
        time.sleep(.2)
    else:raise RuntimeError('Initial status not written: '+name)
report['launch_completed']=True;helper.atomic_json(manifest,report)
helper.atomic_json(project/'results/resume_pending_launch_latest.json',report)
print(json.dumps({'manifest':str(manifest),'bias_retained':len(records)}),flush=True)
