"""Prepare strict source/model/cache policy and runner cases, without simulation.

Allowed model metadata comes from an existing completed R1 execution. No PDK
contents are copied. Current model files are independently hashed by wrapper.
"""
import argparse
import hashlib
import json
from pathlib import Path

GUEST_DIR='@PROJECT_ROOT@/afc2009_20261007/mos_r2_counter9'
FIXED_V1_SHA='1fa72a1552676fe839d51da5654e1f6c75b9a957fa1114daff032b09303e548e'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    here=Path(__file__).resolve().parent;root=here.parent
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model-reference-execution',type=Path,default=root/'evidence'/'r1'/'afc_unit_near100_phase_high_r1_diagnostic600n_9c3f3bce9e32_aps.json')
    ap.add_argument('--guest-dir',default=GUEST_DIR);args=ap.parse_args()
    manifest_path=here/'counter9_manifest.json';m=json.loads(manifest_path.read_text(encoding='utf-8'))
    reference=json.loads(args.model_reference_execution.read_text(encoding='utf-8'))
    if reference.get('state')!='completed' or reference.get('spectre_rc')!=0 or reference.get('source_models_unchanged_at_completion') is not True:raise ValueError('Expected completed unchanged R1 model reference.')
    source=here/'counter9_gray_cdc_mos.scs';bench=here/'counter9_gray_cdc_tb.scs'
    if sha(source)!=m['subset_source_sha256'] or sha(bench)!=m['bench_sha256'] or sha(here/'read_counter9_exercise.py')!=FIXED_V1_SHA:raise ValueError('Frozen counter source, bench or v1 reader changed.')
    own={args.guest_dir+'/'+path.name:{'sha256':sha(path),'bytes':path.stat().st_size} for path in (bench,source)}
    runner_sha={path.name:sha(path) for path in (root/'run_cases_v3.py',root/'run_cases_v4.py') if path.exists()}
    policy={'status':'prepared_not_simulated','version':'counter9-completion-policy-v2','expected_case_name':'afc_counter9_gray_cdc_r2_prepared_v2',
        'counter9_manifest_sha256':sha(manifest_path),'frozen_reader_v1_sha256':FIXED_V1_SHA,
        'expected_subset_source_sha256':m['subset_source_sha256'],'expected_bench_sha256':m['bench_sha256'],
        'fixed_R2_AFC_source_sha256':m['fixed_R2_AFC_source_sha256'],'R2_builder_sha256':m['R2_builder_sha256'],
        'expected_bench':args.guest_dir+'/'+bench.name,'expected_own_dependencies':own,
        'allowed_model_dependencies':reference['model_dependencies'],
        'allowed_model_reference_execution':str(args.model_reference_execution.resolve()),
        'allowed_model_reference_execution_sha256':sha(args.model_reference_execution),
        'allowed_runner_source_sha256':sorted(runner_sha.values()),'allowed_runner_files':runner_sha,
        'expected_simulator_binary':reference['simulator_command'][0],
        'required_state':'completed','required_spectre_rc':0,'required_source_models_unchanged_at_completion':True,
        'required_stop_s':m['stop_s'],'required_strobeperiod_s':m['strobeperiod_s'],'required_restart_CLK_edges':20,'required_restart_REF_samples':20,
        'scope':'Prepared execution allowlist, not a new simulation result. Only source/model path,size,hash metadata; PDK contents not distributed.'}
    policy_path=here/'counter9_completion_policy_v2.json';policy_path.write_text(json.dumps(policy,indent=2)+'\n',encoding='utf-8')
    cases=[{'name':policy['expected_case_name'],'path':policy['expected_bench'],'sha256':m['bench_sha256'],
        'duration_s':m['stop_s'],'maxstep_s':m['maxstep_s'],'strobeperiod_s':m['strobeperiod_s'],
        'counter9_manifest_sha256':policy['counter9_manifest_sha256'],'counter9_completion_policy_sha256':sha(policy_path),
        'mos_source_sha256':m['subset_source_sha256'],'fixed_R2_AFC_source_sha256':m['fixed_R2_AFC_source_sha256'],
        'actual_status':'not_run','revision':'counter9-prepared-v2','scope':'Light-load 9-bit counter/CDC exercise only, not complete AFC.'}]
    (here/'counter9_runner_cases_v2.json').write_text(json.dumps(cases,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'prepared_only':True,'models_in_allowlist':len(reference['model_dependencies']),'policy_sha256':sha(policy_path),'runner_cases_sha256':sha(here/'counter9_runner_cases_v2.json')},indent=2))


if __name__=='__main__':main()
