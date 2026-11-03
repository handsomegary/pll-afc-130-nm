"""Read only the own physical-noise log tail and current suite state."""
import collections,json
from pathlib import Path
project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
status=json.loads((project/'results/driven_pll_noise_status_20261007.json').read_text())
print(json.dumps({'stage':status['stage'],'case_names':[r['name'] for r in status['cases']],
                  'case_states':[r['state'] for r in status['cases']],'reason':status.get('reason')}))
folder=project/'results/fullpll/noise'
logs=sorted(folder.glob('*.log'),key=lambda p:p.stat().st_mtime)
if logs:
    print('OWN LATEST LOG '+str(logs[-1]))
    with logs[-1].open(errors='replace') as f:
        tail=collections.deque(f,maxlen=28)
    print(''.join(tail))
