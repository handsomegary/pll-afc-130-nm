import concurrent.futures
import json
from run_vco_scan import project, run_case

cases=[('scale{}'.format(s),16,0.6,s,'tt',1,1) for s in [2,3,4]]
cases.append(('code0_ctrl03',0,0.3,1,'tt',1,1))
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(run_case,cases))
(project/'results/first_sizing_scan.json').write_text(json.dumps(results,indent=2))
