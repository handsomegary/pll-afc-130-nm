"""One owned, bounded201ns PSS-boundary diagnostic; Python3.6+.

Upload/review before invoking in the VM project. No automatic upload/SSH/GUI.
Keep both original failed status/summary paths read-only. This parent launches
only the uniquely named approved case, with existing identity-scoped helpers.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

PROJECT=Path('@PROJECT_ROOT@')
CASE='fullpll_driven_pss_sb128_boundary201n'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def output_paths(project):
    folder=project/'results/fullpll/noise'
    return dict(folder=folder,summary=folder/'retry_summary_boundary201n.json',
                execution=folder/('all_cases_'+CASE+'_aps2.json'),
                measurement=folder/(CASE+'_measurement.json'),
                runner_stdout=folder/(CASE+'_runner.stdout'),
                measure_stdout=folder/(CASE+'_measure.stdout'),
                original_status=project/'results/driven_pll_noise_status_20261007.json',
                original_summary=folder/'driven_noise_summary.json')


def review_inputs(project,manifest_path):
    manifest_path=Path(manifest_path).resolve()
    manifest_path.relative_to((project/'pll_full/analog/benches').resolve())
    manifest=json.loads(manifest_path.read_text())
    if len(manifest['cases'])!=1:raise ValueError('Exactly one approved boundary retry, no noise suite.')
    case=manifest['cases'][0]
    if case.get('name')!=CASE or case.get('kind')!='pss' or case.get('tstab_s')!=201e-9:
        raise ValueError('Wrong case, kind or approved tstab.')
    bench=Path(case['path']).resolve()
    bench.relative_to((project/'pll_full/analog/benches').resolve())
    if digest(bench)!=case['bench_sha256']:raise ValueError('New bench differs from manifest.')
    retry=manifest['numerical_boundary_retry']
    original=Path(retry['original_bench_path']).resolve()
    original.relative_to((project/'pll_full/analog/benches').resolve())
    if digest(original)!=retry['original_bench_sha256']:raise ValueError('Original bench changed.')
    from prepare_pss_boundary_retry import shift_only_tstab
    if shift_only_tstab(original.read_bytes())!=bench.read_bytes():
        raise ValueError('New bench changes circuit/tolerances beyond approved tstab literal.')
    log=Path(retry['original_log_path']).resolve()
    log.relative_to(project.resolve())
    if digest(log)!=retry['original_log_sha256']:raise ValueError('Original failed log changed.')
    if retry.get('original_rc')!=1:raise ValueError('Require original failed rc1 provenance.')
    paths=output_paths(project)
    for key in ['summary','execution','measurement']:
        if paths[key].exists():raise ValueError('This unique diagnostic already has evidence; no generic retry: '+key)
    preserved={str(paths[key]):digest(paths[key]) for key in ['original_status','original_summary']}
    return manifest,case,bench,paths,preserved


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    args=parser.parse_args()
    project=PROJECT.resolve()
    if Path.cwd().resolve()!=project:raise ValueError('Run only in the owned PLL project.')
    sys.path.insert(0,str(project))
    sys.path.insert(0,str(project/'pll_full/analog'))
    import run_background_phase3 as helper
    manifest,case,bench,paths,preserved=review_inputs(project,args.manifest)
    paths['folder'].mkdir(parents=True,exist_ok=True)
    lock=(paths['folder']/'suite.lock').open('a+')
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    lock.seek(0);lock.truncate();lock.write(str(os.getpid())+'\n');lock.flush()
    started=time.time();deadline=time.monotonic()+1200
    summary=dict(stage='starting',name=CASE,pid=os.getpid(),own_only=True,max_workers=1,
                 parent_walltime_limit_s=1200,units_timeout_s=1185,max_attempts=1,
                 started_unix=started,manifest=str(Path(args.manifest).resolve()),
                 bench=str(bench),bench_sha256=case['bench_sha256'],
                 scope=manifest['scope'],original_file_sha256_before=preserved,
                 original_failed_attempt=manifest['numerical_boundary_retry'],
                 noise_calculation_available=False,PLL_phase_noise_dBc_Hz=None,
                 PLL_noise_jitter_rms_s=None,PLL_noise_FoM_dB=None,
                 unmeasured_values='unknown')

    def save(stage,**extra):
        summary.update(stage=stage,updated_unix=time.time(),elapsed_walltime_s=time.time()-started,**extra)
        helper.atomic_json(paths['summary'],summary)
        print(json.dumps(dict(stage=stage,name=CASE,noise_calculation_available=False)),flush=True)

    def interrupted(signum,frame):
        raise KeyboardInterrupt('Requested signal '+str(signum))

    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    save('running_single_targeted_PSS')
    try:
        command=[sys.executable,str(project/'run_pll_full_units_20261007.py'),
                 '--group','noise','--only',CASE,'--engine','aps','--timeout-seconds','1185']
        rc=helper.run_process(command,paths['runner_stdout'],project,deadline)
        summary['units_runner_rc']=rc
        if not paths['execution'].is_file():raise RuntimeError('No exact new execution record; PSS unknown.')
        records=json.loads(paths['execution'].read_text())
        matches=[record for record in records if record.get('name')==CASE]
        if len(matches)!=1:raise RuntimeError('Expected one exact new execution record.')
        record=matches[0]
        summary.update(execution_record_path=str(paths['execution']),execution=record)
        if rc or record.get('state')!='completed' or record.get('spectre_rc')!=0:
            raise RuntimeError('Bounded physical PSS unavailable: '+str(record.get('error',rc)))
        artifacts=[Path(p) for p in record['artifacts']]
        raw=[p for p in artifacts if p.suffix=='.raw'];log=[p for p in artifacts if p.suffix=='.log']
        if len(raw)!=1 or len(log)!=1 or bench not in [p.resolve() for p in artifacts]:
            raise RuntimeError('Execution artifact identity incomplete.')
        measure=[sys.executable,str(project/'pll_full/analog/measure_driven_pll_noise.py'),
                 '--raw',str(raw[0]),'--spectre-log',str(log[0]),'--spectre-rc','0',
                 '--kind','pss','--out',str(paths['measurement']),
                 '--manifest',str(Path(args.manifest).resolve()),'--case-name',CASE,
                 '--bench',str(bench),'--execution-record-json',str(paths['execution'])]
        measure_rc=helper.run_process(measure,paths['measure_stdout'],project,deadline)
        summary['measurement_rc']=measure_rc
        if measure_rc or not paths['measurement'].is_file():
            raise RuntimeError('Read-only periodic evidence unavailable; see exact measurement stdout.')
        measurement=json.loads(paths['measurement'].read_text())
        summary.update(measurement_path=str(paths['measurement']),measurement=measurement)
        if measurement.get('periodic_screen_pass') is not True:
            raise RuntimeError('Periodic32cycles/feedback/rails/closure evidence screen failed.')
        save('complete_PSS_screen_pass',PSS_periodic_evidence_available=True,
             limitation='PSS-only success; no PM noise database or jitter/FoM measured by this retry.')
    except KeyboardInterrupt as error:
        helper.STOP.set()
        with helper.ACTIVE_LOCK:owned=list(helper.ACTIVE.values())
        for process in owned:helper.stop_process_group(process)
        save('interrupted_owned_diagnostic',reason=str(error),PSS_periodic_evidence_available=False,
             no_more_retries=True)
    except Exception as error:
        save('complete_bounded_evaluation_unknown',reason=repr(error),PSS_periodic_evidence_available=False,
             no_more_retries=True)
    finally:
        after={name:digest(Path(name)) if Path(name).is_file() else None for name in preserved}
        unchanged=after==preserved
        save(summary['stage'],original_file_sha256_after=after,original_status_summary_unchanged=unchanged,
             finished_unix=time.time())
        if not unchanged:raise RuntimeError('Original failed evidence changed externally; review identity.')
        lock.close()
    return 0


if __name__=='__main__':sys.exit(main())
