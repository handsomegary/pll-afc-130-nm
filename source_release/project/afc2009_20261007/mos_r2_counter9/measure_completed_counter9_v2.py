"""Read-only counter9 complete-execution wrapper; never launches Spectre.

Requires actual completed rc0 cache, exact sources/models, immutable raw, full
waveform coverage and restart correctness before physical_subset_unit_pass.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def dependency_signature(own,models):
    return hashlib.sha256(json.dumps({'own':own,'models':models},sort_keys=True).encode()).hexdigest()


def execution_errors(execution,policy,manifest_sha256,policy_sha256,cache_name,raw_path):
    """Pure metadata checks; software fixtures never invoke waveform PASS path."""
    errors=[]
    if execution.get('state')!='completed':errors.append('execution_not_completed')
    if execution.get('spectre_rc')!=0:errors.append('spectre_rc_not_zero')
    if execution.get('source_models_unchanged_at_completion') is not True:errors.append('source_models_changed_or_unknown_at_completion')
    if execution.get('spectre_log_summary',{}).get('errors')!=0:errors.append('spectre_log_error_count_not_zero')
    if execution.get('name')!=policy['expected_case_name']:errors.append('case_name_mismatch')
    if execution.get('bench')!=policy['expected_bench']:errors.append('bench_path_mismatch')
    if execution.get('bench_sha256')!=policy['expected_bench_sha256']:errors.append('bench_sha256_mismatch')
    own=execution.get('own_dependencies',{});models=execution.get('model_dependencies',{})
    if own!=policy['expected_own_dependencies']:errors.append('own_dependency_allowlist_mismatch')
    if models!=policy['allowed_model_dependencies']:errors.append('model_dependency_allowlist_mismatch')
    signature=dependency_signature(own,models)
    if execution.get('source_model_signature_sha256')!=signature:errors.append('source_model_signature_mismatch')
    if execution.get('runner_source_sha256') not in policy['allowed_runner_source_sha256']:errors.append('runner_source_sha256_not_allowed')
    expected_cache=execution.get('name','')+'_'+signature[:12]+'_'+execution.get('engine','')+'.json'
    if cache_name!=expected_cache:errors.append('cache_filename_signature_mismatch')
    try:
        Path(raw_path).resolve().relative_to(Path(execution['raw']).resolve())
    except (KeyError,ValueError):errors.append('raw_not_inside_execution_raw_directory')
    command=execution.get('simulator_command',[])
    if not command or command[0]!=policy['expected_simulator_binary']:errors.append('simulator_binary_path_not_allowed')
    if len(command)<2 or command[1]!=policy['expected_bench']:errors.append('simulator_command_bench_mismatch')
    if '-raw' not in command or command[command.index('-raw')+1:command.index('-raw')+2]!=[execution.get('raw')]:errors.append('simulator_command_raw_mismatch')
    if '-format' not in command or command[command.index('-format')+1:command.index('-format')+2]!=['psfascii']:errors.append('simulator_command_format_mismatch')
    engine=execution.get('engine')
    if engine not in ('aps','apsplus','classic') or (engine=='aps' and ('+aps' not in command or '++aps' in command)) or (engine=='apsplus' and ('++aps' not in command or '+aps' in command)) or (engine=='classic' and ('+aps' in command or '++aps' in command)):errors.append('simulator_command_engine_mismatch')
    spec=execution.get('specification',{})
    if spec.get('counter9_manifest_sha256')!=manifest_sha256 or manifest_sha256!=policy['counter9_manifest_sha256']:errors.append('manifest_sha256_binding_mismatch')
    if spec.get('counter9_completion_policy_sha256')!=policy_sha256:errors.append('completion_policy_sha256_binding_mismatch')
    if spec.get('sha256')!=policy['expected_bench_sha256'] or spec.get('mos_source_sha256')!=policy['expected_subset_source_sha256']:errors.append('specification_source_sha256_mismatch')
    if spec.get('duration_s')!=policy['required_stop_s'] or spec.get('strobeperiod_s')!=policy['required_strobeperiod_s']:errors.append('specification_stop_or_strobe_mismatch')
    started=execution.get('started_unix');finished=execution.get('finished_unix')
    if not isinstance(started,(int,float)) or not isinstance(finished,(int,float)) or not math.isfinite(started) or not math.isfinite(finished) or finished<started:errors.append('completed_execution_timestamps_invalid')
    return errors


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('raw','manifest','subset-source','bench','policy','execution-cache','output'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--sample-delay-ns',type=float,default=2.5);args=ap.parse_args()
    # Parse and hash the same bytes, then verify again after extraction.
    # Separate parse/hash reads could otherwise bind an old completed record
    # to a newly rewritten running-cache digest.
    policy_bytes=args.policy.read_bytes();cache_bytes=args.execution_cache.read_bytes();manifest_bytes=args.manifest.read_bytes()
    policy=json.loads(policy_bytes.decode('utf-8'));execution=json.loads(cache_bytes.decode('utf-8'));manifest=json.loads(manifest_bytes.decode('utf-8'))
    cache_before=hashlib.sha256(cache_bytes).hexdigest();policy_before=hashlib.sha256(policy_bytes).hexdigest();manifest_before=hashlib.sha256(manifest_bytes).hexdigest()
    errors=execution_errors(execution,policy,manifest_before,policy_before,args.execution_cache.name,args.raw)
    if manifest['fixed_R2_AFC_source_sha256']!=policy['fixed_R2_AFC_source_sha256'] or manifest['R2_builder_sha256']!=policy['R2_builder_sha256']:errors.append('fixed_parent_source_or_builder_binding_mismatch')
    if sha(args.subset_source)!=policy['expected_subset_source_sha256'] or sha(args.bench)!=policy['expected_bench_sha256']:errors.append('actual_source_or_bench_digest_mismatch')
    if str(args.subset_source.resolve()) not in policy['expected_own_dependencies'] or str(args.bench.resolve())!=policy['expected_bench']:errors.append('actual_source_or_bench_path_mismatch')
    # Rehash live own and model dependencies. This runs on the guest where
    # the record's exact paths exist; copied cache metadata alone is insufficient.
    live={}
    for category,dependencies in [('own',policy['expected_own_dependencies']),('models',policy['allowed_model_dependencies'])]:
        live[category]={}
        for name,info in dependencies.items():
            path=Path(name)
            actual={'sha256':sha(path),'bytes':path.stat().st_size} if path.is_file() else None
            live[category][name]=actual
            if actual!=info:errors.append('live_'+category+'_dependency_mismatch:'+name)
    if errors:
        result={'version':'counter9-completed-wrapper-v2','status':'execution_binding_failed','physical_subset_unit_pass':False,'execution_binding_errors':errors,'waveform_analyzed':False,'simulator_started_by_wrapper':False}
    else:
        reader_path=Path(__file__).with_name('read_counter9_exercise_v2.py')
        spec=importlib.util.spec_from_file_location('counter9_reader_v2',str(reader_path));reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
        result=reader.measure(args.raw,args.manifest,args.subset_source,args.bench,args.sample_delay_ns*1e-9)
        unchanged=sha(args.execution_cache)==cache_before and sha(args.policy)==policy_before and sha(args.manifest)==manifest_before
        for dependencies in live.values():
            for name,info in dependencies.items():
                unchanged=unchanged and Path(name).is_file() and sha(name)==info['sha256']
        if not unchanged:result['violations'].append({'type':'bound_inputs_changed_during_measurement'})
        result['version']='counter9-completed-wrapper-v2'
        result['completed_simulator_execution_bound']=unchanged
        result['physical_subset_unit_pass']=unchanged and not result['violations']
        result['status']='completed_lightload_subset_checks_passed' if result['physical_subset_unit_pass'] else 'completed_lightload_subset_checks_failed'
        result['execution_binding_errors']=[] if unchanged else ['inputs_changed_during_read']
        result['waveform_analyzed']=True;result['live_dependency_sizes_and_hashes_checked']=True
        result['reader_v2_sha256']=sha(reader_path)
    result.update({'execution_cache':str(args.execution_cache.resolve()),'execution_cache_sha256':cache_before,'policy_sha256':policy_before,'manifest_sha256':manifest_before,'source_model_signature_sha256':execution.get('source_model_signature_sha256'),'actual_spectre_rc':execution.get('spectre_rc'),'actual_execution_state':execution.get('state'),'simulator_started_by_wrapper':False,'scope':'Completed execution-bound measured word/coverage checks of lightly loaded 9-bit counter/CDC only. Not complete AFC clock/reset loading, metastability, timing, noise, PLL capture or all-PVT signoff.'})
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'physical_subset_unit_pass':result['physical_subset_unit_pass'],'execution_binding_errors':result['execution_binding_errors']},indent=2))
    if not result['physical_subset_unit_pass']:raise SystemExit(1)


if __name__=='__main__':main()
