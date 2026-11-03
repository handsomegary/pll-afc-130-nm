"""Sequential read-only extraction of five completed, frozen R1 unit cases."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

PROJECT = Path('@PROJECT_ROOT@')
ROOT = PROJECT/'afc2009_20261007'
MOS_SHA = '12044e0dc052c06682a3372f17c0b8612d637954af88e0d8662cf1d8c0f8f6b8'
CASES = [
    ('near100_high', 'afc_unit_near100_phase_high_r1_100p_788b21b5ae44_aps.json'),
    ('near100_low', 'afc_unit_near100_phase_low_r1_100p_0ebf01748f9b_aps.json'),
    ('fast140', 'afc_unit_fast140_r1_100p_915cf062c6f5_aps.json'),
    ('slow70', 'afc_unit_slow70_r1_100p_2fcae2da9ae4_aps.json'),
    ('no_feedback', 'afc_unit_no_feedback_r1_100p_1a9f1a0f7a90_aps.json'),
]


def main():
    assert Path.cwd().resolve() == PROJECT
    assert hashlib.sha256((ROOT/'mos_r1/afc2009_mos.scs').read_bytes()).hexdigest() == MOS_SHA
    monitor = ROOT/'verification/monitor_v3_first_edge/postprocess_completed_case_v3.py'
    records = []
    for short, name in CASES:
        execution = PROJECT/'results/afc2009_20261007'/name
        record = json.loads(execution.read_text())
        assert record['state']=='completed' and record['spectre_rc']==0
        assert record['source_models_unchanged_at_completion']
        assert record['own_dependencies'][str(ROOT/'mos_r1/afc2009_mos.scs')]['sha256']==MOS_SHA
        output = ROOT/'evidence/r1'/('r1_'+short+'_measurement_v3.json')
        rc = subprocess.call([sys.executable,str(monitor),'--execution',str(execution),
                              '--kind','unit','--output',str(output)])
        records.append(dict(name=record['name'],output=str(output),returncode=rc))
    summary = ROOT/'evidence/r1/r1_units_v3_extraction_summary.json'
    assert not summary.exists()
    summary.write_text(json.dumps(dict(records=records,all_pass=all(r['returncode']==0 for r in records)),indent=2)+'\n')
    return 0 if all(r['returncode']==0 for r in records) else 2


if __name__ == '__main__':
    sys.exit(main())
