"""Merge only the completed CP phase manifests, without modifying them."""
import json
from pathlib import Path
project = Path('@PROJECT_ROOT@')
assert Path.cwd().resolve() == project
folder = project/'results/fullpll/cpphase'
records = []
for name in ['all_cases.json','all_cases_cp_drain_phase_m300.json','all_cases_cp_drain_phase_m400.json']:
    records.extend(json.loads((folder/name).read_text()))
assert len(records) == 11 and len(set(r['name'] for r in records)) == 11
assert all(r['state']=='completed' and r['spectre_rc']==0 for r in records)
(folder/'extended_cases.json').write_text(json.dumps(records,indent=2))
print('11 completed independent phase points merged')
