"""Read-only final job inventory; never signal a process or change shared VM."""
import json
import os
from pathlib import Path
import time

project = Path('@PROJECT_ROOT@')
assert Path.cwd().resolve() == project
names = {'run_background_bias_opt.py', 'run_background_receiver_load.py',
    'run_background_rf_validation.py', 'run_background_selected_startup.py',
    'run_pll_full_units_20261007.py', 'run_driven_pll_noise_20261007.py',
    'run_loaded_pn30_check_20261007.py', 'run_pss_boundary_retry_20261007.py',
    'resume_rf_two_workers_20261007.py'}
owned = []
others = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        stat = (proc/'stat').read_text().rsplit(')', 1)[1].split()
        if stat[0] == 'Z':
            continue
        comm = (proc/'comm').read_text().strip()
        argv = [a.decode(errors='replace') for a in (proc/'cmdline').read_bytes().split(b'\0') if a]
        cwd = os.readlink(str(proc/'cwd'))
        uid = proc.stat().st_uid
    except OSError:
        continue
    in_project = uid == os.getuid() and (cwd == str(project) or cwd.startswith(str(project)+'/pll_full/'))
    driver = in_project and any(Path(a).name in names for a in argv)
    cadence = comm in {'spectre', 'ocean', 'virtuoso', 'cdsMsgServer'}
    if driver or (in_project and cadence):
        owned.append(dict(pid=int(proc.name), comm=comm, cwd=cwd, uid=uid,
                          start_ticks=stat[19], argv=argv))
    elif cadence:
        others.append(dict(pid=int(proc.name), comm=comm, cwd=cwd,
                           signal_sent_by_this_script=False))
result = dict(version='final-owned-job-inventory-v1', timestamp_unix=time.time(),
    project=str(project), read_only=True, signal_sent=False, vm_state_changed=False,
    own_jobs_remaining=owned, own_jobs_finished=not owned, other_cadence_sessions=others,
    note='No VM suspend/cache flush/shared-session cleanup. Completed sources/results/logs retained.')
(project/'results/final_owned_jobs_20261007.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result))
