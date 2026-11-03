"""Software-only metadata guard fixtures; no analog vectors, raw or MOS PASS.

Tests the exact missing-stop/restart/saved-spacing counterexamples found by
the independent reviewer, plus completed execution/source/model/cache guards.
"""
import copy
import importlib.util
import json
from pathlib import Path


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,str(path));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def main():
    here=Path(__file__).resolve().parent;reader=load(here/'read_counter9_exercise_v2.py','reader_v2');wrapper=load(here/'measure_completed_counter9_v2.py','wrapper_v2')
    manifest=json.loads((here/'counter9_manifest.json').read_text(encoding='utf-8'))
    policy_path=here/'counter9_completion_policy_v2.json';policy=json.loads(policy_path.read_text(encoding='utf-8'))
    base={'saved_begin_s':0.,'saved_end_s':5.7e-6,'maximum_saved_spacing_s':100e-12,'raw_END_marker_present':True,'reset_release_count':2,'initial_reset_preset_sampled':True,'second_reset_preset_sampled':True,'epoch2_active_CLK_edges':27,'epoch2_stable_REF_samples':28,'epoch2_last_sampled_CLK_ordinal':27}
    rows=[]
    coverage_fixtures=[
        ('complete_summary_guard_only',{},None),
        ('truncated_after_second_assert_5p408us',{'saved_end_s':5.408e-6,'reset_release_count':1,'epoch2_active_CLK_edges':0,'epoch2_stable_REF_samples':0,'epoch2_last_sampled_CLK_ordinal':0},'declared_stop_not_covered'),
        ('tenfold_sparse_1ns',{'maximum_saved_spacing_s':1e-9},'declared_strobe_spacing_exceeded'),
        ('no_second_release_at_declared_stop',{'reset_release_count':1,'epoch2_active_CLK_edges':0,'epoch2_stable_REF_samples':0,'epoch2_last_sampled_CLK_ordinal':0},'second_reset_release_not_covered'),
        ('restart_CLK19',{'epoch2_active_CLK_edges':19},'epoch2_restart_less_than_20_CLK_edges'),
        ('restart_REF19',{'epoch2_stable_REF_samples':19},'epoch2_restart_less_than_20_verified_REF_samples'),
        ('sampled_CLKordinal19',{'epoch2_last_sampled_CLK_ordinal':19},'epoch2_sampled_CLK_ordinal_less_than_20'),
        ('END_missing',{'raw_END_marker_present':False},'raw_END_marker_missing'),
        ('reset2_preset_not_sampled',{'second_reset_preset_sampled':False},'second_reset_preset_not_sampled'),
        ('exact_spacing_tolerance',{'maximum_saved_spacing_s':manifest['strobeperiod_s']*1.05},None),
        ('spacing_just_over_tolerance',{'maximum_saved_spacing_s':manifest['strobeperiod_s']*1.05001},'declared_strobe_spacing_exceeded'),
        ('stop_short_by2fs',{'saved_end_s':manifest['stop_s']-2e-15},'declared_stop_not_covered')]
    for name,changes,expected in coverage_fixtures:
        fixture=dict(base);fixture.update(changes);errors=reader.coverage_errors(fixture,manifest)
        kinds=[item['type'] for item in errors]
        assert (not errors if expected is None else expected in kinds),(name,errors)
        if name=='truncated_after_second_assert_5p408us':assert 'second_reset_release_not_covered' in kinds and 'epoch2_restart_less_than_20_CLK_edges' in kinds
        rows.append({'name':name,'kind':'software_coverage_summary_fixture','guard_expectation_satisfied':True,'rejected':bool(errors),'error_types':kinds,'is_electrical_PASS_evidence':False})
    cases=json.loads((here/'counter9_runner_cases_v2.json').read_text(encoding='utf-8'));case=cases[0]
    signature=wrapper.dependency_signature(policy['expected_own_dependencies'],policy['allowed_model_dependencies'])
    rawdir='/software-fixture-only/counter9.raw';cache_name=case['name']+'_'+signature[:12]+'_apsplus.json'
    execution={'name':case['name'],'state':'completed','spectre_rc':0,'source_models_unchanged_at_completion':True,'spectre_log_summary':{'errors':0},'bench':policy['expected_bench'],'bench_sha256':policy['expected_bench_sha256'],'own_dependencies':policy['expected_own_dependencies'],'model_dependencies':policy['allowed_model_dependencies'],'source_model_signature_sha256':signature,'runner_source_sha256':policy['allowed_runner_source_sha256'][0],'engine':'apsplus','raw':rawdir,'simulator_command':[policy['expected_simulator_binary'],policy['expected_bench'],'-raw',rawdir,'-format','psfascii','++aps'],'specification':case,'started_unix':1.,'finished_unix':2.}
    def check(name,record,expected=None,raw=rawdir+'/tran.tran',cache=cache_name):
        errors=wrapper.execution_errors(record,policy,wrapper.sha(here/'counter9_manifest.json'),wrapper.sha(policy_path),cache,raw)
        assert (not errors if expected is None else expected in errors),(name,errors)
        rows.append({'name':name,'kind':'software_execution_metadata_fixture','guard_expectation_satisfied':True,'rejected':bool(errors),'error_types':errors,'is_electrical_PASS_evidence':False})
    check('complete_binding_metadata_guard_only',execution)
    for field,value,error in [('state','running','execution_not_completed'),('spectre_rc',1,'spectre_rc_not_zero'),('source_models_unchanged_at_completion',False,'source_models_changed_or_unknown_at_completion'),('source_model_signature_sha256','wrong','source_model_signature_mismatch'),('runner_source_sha256','wrong','runner_source_sha256_not_allowed'),('finished_unix',None,'completed_execution_timestamps_invalid')]:
        record=copy.deepcopy(execution);record[field]=value;check(field+'_rejection',record,error)
    record=copy.deepcopy(execution);key=next(iter(record['model_dependencies']));record['model_dependencies'][key]['sha256']='0'*64;check('wrong_allowed_model_SHA',record,'model_dependency_allowlist_mismatch')
    record=copy.deepcopy(execution);key=next(iter(record['own_dependencies']));record['own_dependencies'][key]['sha256']='0'*64;check('wrong_allowed_own_SHA',record,'own_dependency_allowlist_mismatch')
    record=copy.deepcopy(execution);record['specification']['counter9_manifest_sha256']='wrong';check('manifest_binding_rejection',record,'manifest_sha256_binding_mismatch')
    record=copy.deepcopy(execution);record['specification']['counter9_completion_policy_sha256']='wrong';check('policy_binding_rejection',record,'completion_policy_sha256_binding_mismatch')
    check('wrong_cache_filename',execution,'cache_filename_signature_mismatch',cache='wrong.json')
    check('raw_outside_execution_directory',execution,'raw_not_inside_execution_raw_directory',raw='/software-fixture-only/other.raw/tran.tran')
    record=copy.deepcopy(execution);record['simulator_command'][0]='/software-fixture-only/wrong_binary';check('simulator_binary_not_allowed',record,'simulator_binary_path_not_allowed')
    record=copy.deepcopy(execution);record['engine']='classic';check('simulator_engine_flag_mismatch',record,'simulator_command_engine_mismatch')
    result={'status':'software_guard_fixture_checks_passed','fixtures':rows,'fixture_count':len(rows),'analog_vectors_created':False,'PSF_files_created':False,'simulator_started':False,'physical_subset_unit_pass':None,'is_electrical_PASS_evidence':False,'reader_v2_sha256':wrapper.sha(here/'read_counter9_exercise_v2.py'),'completed_wrapper_sha256':wrapper.sha(here/'measure_completed_counter9_v2.py'),'frozen_reader_v1_sha256':wrapper.sha(here/'read_counter9_exercise.py'),'counter_source_sha256':wrapper.sha(here/'counter9_gray_cdc_mos.scs'),'bench_sha256':wrapper.sha(here/'counter9_gray_cdc_tb.scs'),'scope':'Pure metadata coverage and execution-binding tests. No waveform generation, circuit simulation or MOS PASS evidence.'}
    (here/'reader_v2_software_guard_fixtures.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('status','fixture_count','analog_vectors_created','PSF_files_created','physical_subset_unit_pass')},indent=2))


if __name__=='__main__':main()
