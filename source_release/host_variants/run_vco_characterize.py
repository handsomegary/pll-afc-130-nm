import concurrent.futures
import json
from run_vco_scan import project, run_case

cases=[('s3_c{}_v{}'.format(c,int(v*10)),c,v,3,'tt',1,1)
       for c in [0,8,16,24,31] for v in [0.3,0.6,0.9]]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results=list(pool.map(run_case,cases))
(project/'results/sized_vco_grid.json').write_text(json.dumps(results,indent=2))
