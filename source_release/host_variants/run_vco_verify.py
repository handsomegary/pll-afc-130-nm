import concurrent.futures
import json
from run_vco_scan import project, run_case

cases=[('s3_halfstep',16,0.6,3,'tt',0.5,1),
       ('s3_reverse',16,0.6,3,'tt',1,-1),
       ('s3_target',16,0.76,3,'tt',0.5,1)]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(run_case,cases))
(project/'results/verification_scan.json').write_text(json.dumps(results,indent=2))
