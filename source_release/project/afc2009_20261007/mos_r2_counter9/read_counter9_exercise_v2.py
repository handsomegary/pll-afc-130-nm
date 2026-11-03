"""New counter9 reader with required stop, restart and saved-spacing coverage.

Preserves frozen v1. Completed simulation/model/cache binding is provided by
measure_completed_counter9_v2.py, not by this waveform reader alone.
"""
import argparse
import bisect
import importlib.util
import json
from pathlib import Path

FROZEN_V1_SHA='1fa72a1552676fe839d51da5654e1f6c75b9a957fa1114daff032b09303e548e'


def load_v1():
    path=Path(__file__).with_name('read_counter9_exercise.py')
    spec=importlib.util.spec_from_file_location('frozen_counter9_reader_v1',str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if module.sha(path)!=FROZEN_V1_SHA:raise ValueError('Frozen original reader digest changed.')
    return module


def coverage_errors(summary,manifest):
    """Pure metadata guard used on actual extraction and software-only fixtures."""
    errors=[];stop=manifest['stop_s'];spacing_limit=manifest['strobeperiod_s']*1.05
    stop_tolerance=1e-15
    if summary['saved_begin_s']>spacing_limit:errors.append({'type':'initial_saved_coverage_missing'})
    if summary['saved_end_s']<stop-stop_tolerance:errors.append({'type':'declared_stop_not_covered','declared_stop_s':stop,'saved_end_s':summary['saved_end_s'],'tolerance_s':stop_tolerance})
    if summary['maximum_saved_spacing_s']>spacing_limit:errors.append({'type':'declared_strobe_spacing_exceeded','maximum_saved_spacing_s':summary['maximum_saved_spacing_s'],'limit_s':spacing_limit})
    if not summary['raw_END_marker_present']:errors.append({'type':'raw_END_marker_missing'})
    if summary['reset_release_count']<2:errors.append({'type':'second_reset_release_not_covered','release_count':summary['reset_release_count']})
    if not summary['initial_reset_preset_sampled']:errors.append({'type':'initial_reset_preset_not_sampled'})
    if not summary['second_reset_preset_sampled']:errors.append({'type':'second_reset_preset_not_sampled'})
    if summary['epoch2_active_CLK_edges']<20:errors.append({'type':'epoch2_restart_less_than_20_CLK_edges','edges':summary['epoch2_active_CLK_edges']})
    if summary['epoch2_stable_REF_samples']<20:errors.append({'type':'epoch2_restart_less_than_20_verified_REF_samples','samples':summary['epoch2_stable_REF_samples']})
    if summary['epoch2_last_sampled_CLK_ordinal']<20:errors.append({'type':'epoch2_sampled_CLK_ordinal_less_than_20','ordinal':summary['epoch2_last_sampled_CLK_ordinal']})
    return errors


def summarize_coverage(data,result,sample_delay,end_marker):
    ledgers=result['CLK_REF_reset_transition_ledgers'];times=data['time']
    rises={name:[when for when,level in ledgers[name] if level] for name in ('clk','ref')}
    releases=[when for when,level in ledgers['rst'] if not level]
    assertions=[when for when,level in ledgers['rst'] if level]
    stable=[];clocks=[];last_ordinal=0
    if len(releases)>=2:
        begin=releases[1];end=next((when for when in assertions if when>begin),times[-1]+1e-15)
        clocks=[when for when in rises['clk'] if begin<when<=min(end,times[-1])]
        for when in rises['ref']:
            point=when+sample_delay
            if not begin<when<end or point>times[-1] or point>=end:continue
            if any(when<edge<=point for edge in rises['clk']):continue
            if any(when<edge<=point for edge,_ in ledgers['rst']):continue
            stable.append(point)
            last_ordinal=bisect.bisect_right(clocks,when)
    return {'saved_begin_s':times[0],'saved_end_s':times[-1],
        'maximum_saved_spacing_s':max(b-a for a,b in zip(times,times[1:])),
        'raw_END_marker_present':end_marker,'reset_release_count':len(releases),
        'actual_reset_release_times_s':releases,
        'initial_reset_preset_sampled':result['initial_reset_sample'] is not None,
        'second_reset_preset_sampled':result['second_reset_sample'] is not None,
        'epoch2_active_CLK_edges':len(clocks),'epoch2_stable_REF_samples':len(stable),
        'epoch2_last_sampled_CLK_ordinal':last_ordinal,
        'epoch2_first_stable_sample_s':stable[0] if stable else None,
        'epoch2_last_stable_sample_s':stable[-1] if stable else None,
        'sampling_requirement':'At least 20 eligible second-epoch REF+2.5ns samples, actual native CLK edges and sampled CLK ordinal. Word correctness at every eligible REF sample is checked by the frozen v1 gate-independent ordinal model.'}


def measure(raw,manifest_path,subset_source,bench,sample_delay=2.5e-9):
    v1=load_v1();manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if v1.sha(subset_source)!=manifest['subset_source_sha256']:raise ValueError('Subset source digest mismatch.')
    if v1.sha(bench)!=manifest['bench_sha256']:raise ValueError('Bench digest mismatch.')
    selected={'clk','ref','rst'}|{name for item in manifest['words'].values() for names in item.values() if isinstance(names,list) for name in names}
    data,evidence=v1.read_vectors(raw,selected);result=v1.analyze(data,manifest,sample_delay)
    with Path(raw).open('rb') as stream:
        stream.seek(max(0,Path(raw).stat().st_size-4096));tail=stream.read()
    nonempty=[line.strip() for line in tail.splitlines() if line.strip()]
    end_marker=bool(nonempty and nonempty[-1]==b'END')
    summary=summarize_coverage(data,result,sample_delay,end_marker)
    word_errors=list(result['violations']);extra=coverage_errors(summary,manifest)
    result['violations']=word_errors+extra
    result['waveform_word_checks_passed']=not word_errors
    result['required_coverage_checks_passed']=not extra
    result['status']='saved_word_and_coverage_checks_passed' if not result['violations'] else 'saved_word_or_coverage_checks_failed'
    result['coverage']=summary;result['coverage_errors']=extra
    result.update({'reader_version':'counter9-waveform-reader-v2','source_evidence':evidence,
        'manifest_sha256':v1.sha(manifest_path),'subset_source_sha256':v1.sha(subset_source),
        'bench_sha256':v1.sha(bench),'frozen_v1_sha256':FROZEN_V1_SHA,
        'fixed_R2_AFC_source_sha256':manifest['fixed_R2_AFC_source_sha256'],
        'R2_builder_sha256':manifest['R2_builder_sha256'],'simulator_started_by_reader':False,
        'completed_simulator_execution_bound':False,'physical_subset_unit_pass':None,
        'scope':'Saved-word and required coverage checks only. Complete rc0, cache/raw/source/model identity must also pass the completed execution wrapper. Light-load subset is not full-AFC CDC/fanout, timing, metastability or all-PVT signoff.'})
    if v1.sha(raw)!=evidence['raw_sha256']:raise ValueError('Raw changed during coverage extraction.')
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('raw','manifest','subset-source','bench','output'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--sample-delay-ns',type=float,default=2.5);args=ap.parse_args()
    result=measure(args.raw,args.manifest,args.subset_source,args.bench,args.sample_delay_ns*1e-9)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'coverage':result['coverage'],'violations':len(result['violations']),'physical_subset_unit_pass':None},indent=2))
    if result['violations']:raise SystemExit(1)


if __name__=='__main__':main()
