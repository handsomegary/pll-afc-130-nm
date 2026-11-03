"""Replace only this PLL's slow classic AFC diagnostic with reviewed APS."""
import json, os, signal, time
from pathlib import Path
project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
status=project/'results/fullpll_afc_pll_afc_stage1_initial16_bounded4p_status.json'
state=json.loads(status.read_text())
pid=state['pid'];proc=Path('/proc')/str(pid)
expected=['run_pll_full_units_20261007.py','--group','afc','--only','pll_afc_stage1_initial16_bounded4p']
assert state['stage']=='running' and pid==23424
argv=[a.decode() for a in (proc/'cmdline').read_bytes().split(b'\0') if a]
assert argv[1:]==expected and os.readlink(str(proc/'cwd'))==str(project)
assert proc.stat().st_uid==os.getuid()
ticks=(proc/'stat').read_text().rsplit(')',1)[1].split()[19]
assert (proc/'stat').read_text().rsplit(')',1)[1].split()[19]==ticks
os.kill(pid,signal.SIGTERM)
report=dict(time_unix=time.time(),pid=pid,start_ticks=ticks,argv=argv,signal='SIGTERM',
  reason='Classic runtime projection exceeds bounded3us diagnostic budget. Exact circuit and tolerances retained; switch to separately identified APS2 solver after actual loaded MOS APS comparison. Partial raw retained; not an electrical failure.',
  other_sessions_signaled=False)
(project/'results/afc_compute_revision_20261007.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
