"""Install reviewed drivers with hash guards and resume only this PLL project."""
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import time

PROJECT=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==PROJECT
sys.path.insert(0,str(PROJECT))
NAMES=['run_background_bias_opt.py','run_background_receiver_load.py',
       'run_background_rf_validation.py','run_background_selected_startup.py']
NEW={
 'run_background_bias_opt.py':'0d3d42a3dcc52b5c43d4b3a035b07e736960693d755b831e3a9ee42418cc99b1',
 'run_background_receiver_load.py':'108fed3523bdc85fb4c8c7154a2ddb01b602fa672f48aa792826667598c20087',
 'run_background_rf_validation.py':'7317f7fd1c833ad5d1542d64dcceac044c0d7fe51ca9bf52b850df31d8d778eb',
}
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit(): continue
    try:
        argv=(proc/'cmdline').read_bytes().split(b'\0')
        cwd=os.readlink(str(proc/'cwd'))
    except OSError: continue
    if cwd==str(PROJECT) and any(n.encode() in argv for n in NAMES):
        raise RuntimeError('Own project worker already active: '+proc.name)
preflight=json.loads((PROJECT/'results/resume_preflight_20261007.json').read_text())
incoming=PROJECT/'.resume_upload_20261007'
for name,wanted in NEW.items():
    assert digest(PROJECT/name) in [preflight['scripts'][name],wanted], 'Driver changed unexpectedly: '+name
    assert digest(incoming/name)==wanted, 'Reviewed upload hash mismatch: '+name
    py_compile.compile(str(incoming/name),doraise=True)
for name in ['run_background_phase3.py','run_background_startup_late.py','run_background_selected_startup.py']:
    assert digest(PROJECT/name)==preflight['scripts'][name], 'Helper changed: '+name
stamp=str(int(time.time()))
archives=[p for p in (PROJECT/'scripts_archive').glob('resume_20261007_*')
          if all((p/name).is_file() and digest(p/name)==preflight['scripts'][name] for name in NEW)]
if archives:
    archive=sorted(archives)[0]
else:
    assert all(digest(PROJECT/name)==preflight['scripts'][name] for name in NEW), 'Original backup missing.'
    archive=PROJECT/'scripts_archive'/('resume_20261007_'+stamp)
    archive.mkdir(parents=True)
    for name in NEW: shutil.copy2(str(PROJECT/name),str(archive/name))
for name,wanted in NEW.items():
    if digest(PROJECT/name)!=wanted: shutil.copy2(str(incoming/name),str(PROJECT/name))
import run_background_phase3 as helper
record={'date_label':'2026-10-07','project':str(PROJECT),'archive':str(archive),
        'reviewed_driver_sha256':NEW,'drivers':[],
        'scope':'Headless bounded continuation; no Virtuoso GUI, PDK edits or other project process changes.'}
manifest=PROJECT/'results/resume_launch_20261007.json'
def launch(name,args,status):
    log=PROJECT/'logs'/('resume_20261007_'+stamp+'_'+name+'.log')
    with log.open('w') as stream:
        p=subprocess.Popen(['python3','-u',name]+args,cwd=str(PROJECT),stdin=subprocess.DEVNULL,
                           stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    identity={'name':name,'pid':p.pid,'argv':['python3','-u',name]+args,'log':str(log),
              'process_start_ticks':Path('/proc/{}/stat'.format(p.pid)).read_text().split()[21]}
    record['drivers'].append(identity)
    helper.atomic_json(manifest,record)
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        data=json.loads(status.read_text()) if status.exists() else {}
        if data.get('pid')==p.pid:
            if data.get('stage') in ['failed','interrupted','stopped','needs_design_review']:
                raise RuntimeError('New driver failed immediately: '+json.dumps(data))
            identity['initial_stage']=data.get('stage')
            helper.atomic_json(manifest,record)
            print(json.dumps(identity),flush=True)
            return p
        if p.poll() is not None: raise RuntimeError('Driver exited before initial status: '+name)
        time.sleep(.2)
    raise RuntimeError('New driver did not write status in ten seconds: '+name)

launch(NAMES[0],[],PROJECT/'results/biasopt_status.json')
launch(NAMES[1],['--wait-bias-opt','--wait-seconds','3600','--noise'],PROJECT/'results/receiverload_status.json')
launch(NAMES[2],['--wait-bias-opt','--max-workers','1'],PROJECT/'results/rfvalidation_status.json')
launch(NAMES[3],[],PROJECT/'results/selectedstartup_status.json')
record['all_launched']=True
helper.atomic_json(manifest,record)
print(json.dumps({'manifest':str(manifest),'drivers':len(record['drivers'])}),flush=True)
