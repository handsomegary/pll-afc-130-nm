"""Compact read-only ownership/resource/progress snapshot."""
import json, os, re, time
from pathlib import Path
project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
report={'time_unix':time.time(),'jobs':{},'own_live':[]}
for path in sorted((project/'results').glob('fullpll_*status.json')):
    data=json.loads(path.read_text())
    report['jobs'][path.name]={k:data[k] for k in ['stage','pid','cases_recorded','current_case','failed'] if k in data}
for path in Path('/proc').iterdir():
    if not path.name.isdigit(): continue
    try:
        cwd=os.readlink(str(path/'cwd'))
        if cwd!=str(project) and not cwd.startswith(str(project)+'/pll_full/'):continue
        comm=(path/'comm').read_text().strip()
        if comm not in ['spectre','python3','virtuoso','ocean']:continue
        argv=(path/'cmdline').read_bytes().decode(errors='replace').split('\0')
        report['own_live'].append(dict(pid=int(path.name),comm=comm,cwd=cwd,argv=[a for a in argv if a]))
    except OSError:pass
for raw in (project/'results/fullpll').glob('*/*.raw/tran.tran.tran'):
    if time.time()-raw.stat().st_mtime>30:continue
    with raw.open('rb') as handle:
        handle.seek(max(0,raw.stat().st_size-65536))
        times=re.findall(r'"time"\s+([0-9.eE+-]+)\r?\n',handle.read().decode())
    report.setdefault('active_waveforms',[]).append(dict(path=str(raw),bytes=raw.stat().st_size,
        last_time_s=float(times[-1]) if times else None))
print(json.dumps(report))
