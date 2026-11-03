"""Stop one identity-checked diagnostic, preserving all other work."""
import json, os, signal, time
from pathlib import Path
project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
status=project/'results/fullpll_stage1_pll_stage1_fixed26_ctrl835938_status.json'
state=json.loads(status.read_text())
pid=state['pid']; proc=Path('/proc')/str(pid)
expected=['run_pll_full_units_20261007.py','--group','stage1','--only','pll_stage1_fixed26_ctrl835938']
assert state['stage']=='running'
argv=[a.decode() for a in (proc/'cmdline').read_bytes().split(b'\0') if a]
assert argv[1:]==expected and os.readlink(str(proc/'cwd'))==str(project)
assert proc.stat().st_uid==os.getuid()
ticks=(proc/'stat').read_text().rsplit(')',1)[1].split()[19]
assert (proc/'stat').read_text().rsplit(')',1)[1].split()[19]==ticks
os.kill(pid,signal.SIGTERM)
report=dict(time_unix=time.time(),pid=pid,start_ticks=ticks,argv=argv,signal='SIGTERM',
            reason='Resource-bounded acquisition diagnostic; preserve original 1ps source and partial raw. This is not a circuit lock failure.',
            other_sessions_signaled=False)
(project/'results/stage1_compute_revision_20261007.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
