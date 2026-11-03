"""Identity-scoped, one-at-a-time PLL unit bench runner. Python 3.6+."""
import argparse
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import sys
import time

project = Path('@PROJECT_ROOT@')
assert Path.cwd().resolve() == project
sys.path.insert(0, str(project))
import run_background_phase3 as helper

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--group', choices=['units','receiver','receiverac','loaded','pfd','cpfast','cpphase','stage0','stage1','stage2','stage3','afc','noise'], default='units')
    parser.add_argument('--only', default=None)
    parser.add_argument('--engine', choices=['classic','aps'], default='classic')
    parser.add_argument('--timeout-seconds', type=int)
    args = parser.parse_args()
    if args.timeout_seconds is not None and not 60 <= args.timeout_seconds <= 3600:
        parser.error('Explicit per-case deadline must be 60..3600 seconds')
    root = project / 'pll_full'
    dest = project / 'results/fullpll' / args.group
    dest.mkdir(parents=True, exist_ok=True)
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Requested signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if args.group == 'units':
        # Fast functional contracts first, then device circuits and compliance.
        cases = [('digital', n) for n in ['tb_div32_va', 'tb_afc_va', 'tb_pfd_mos',
                   'tb_div32_cmos', 'tb_receiver_div32']]
        cases += [('analog', p.stem) for p in sorted((root/'analog/benches').glob('cp_dc_*.scs'))]
        cases += [('analog', 'cp_pulse')]
    elif args.group == 'receiver':
        cases = [('digital',p.stem) for p in sorted((root/'digital/benches').glob('tb_receiver_r*.scs'))]
    elif args.group == 'receiverac':
        cases = [('digital',p.stem) for p in sorted((root/'digital/benches').glob('tb_receiverac_*.scs'))]
    elif args.group == 'loaded':
        cases = [('digital',p.stem) for p in sorted((root/'digital/benches').glob('tb_loaded_*.scs'))]
    elif args.group == 'pfd':
        cases = [('digital',p.stem) for p in sorted((root/'digital/benches').glob('tb_pfd_*.scs')) if p.stem!='tb_pfd_mos']
    elif args.group == 'cpfast':
        cases = [('analog',p.stem) for p in sorted((root/'analog/benches').glob('cp_gate*_pulse.scs'))]
        cases += [('analog',p.stem) for p in sorted((root/'analog/benches').glob('cp_drain_*.scs')) if not p.stem.startswith('cp_drain_phase')]
    elif args.group == 'cpphase':
        cases = [('analog',p.stem) for p in sorted((root/'analog/benches').glob('cp_drain_phase*.scs'))]
    elif args.group == 'afc':
        cases = [('digital',p.stem) for p in sorted((root/'digital/benches').glob('pll_afc_stage1*.scs'))]
    elif args.group == 'stage3':
        cases = [(folder,p.stem) for folder in ['analog','digital']
                 for p in sorted((root/folder/'benches').glob('pll_stage3*.scs'))]
    elif args.group == 'noise':
        cases = [('analog',p.stem) for p in sorted((root/'analog/benches').glob('fullpll_driven_*.scs'))]
    else:
        cases = [('analog', p.stem) for p in sorted((root/'analog/benches').glob('pll_'+args.group+'*.scs'))]
    if args.only:
        cases = [(folder, name) for folder, name in cases if name == args.only]
    assert cases, 'No bench files for requested group'
    signatures = {}
    for folder in ['analog', 'digital']:
        for p in (root/folder).glob('*'):
            if p.is_file() and p.suffix in ['.scs', '.va']:
                signatures[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    signature = hashlib.sha256(json.dumps(signatures, sort_keys=True).encode()).hexdigest()
    if args.only:
        status_suffix = args.group+'_'+args.only
    else:
        status_suffix = args.group
    result_suffix = args.only if args.only else ''
    if args.engine == 'aps':
        status_suffix += '_aps2'
        result_suffix += '_aps2'
    status_path = project/'results'/('fullpll_'+status_suffix+'_status.json')
    lock_handle = (dest/'runner.lock').open('a+')
    fcntl.flock(lock_handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    lock_handle.seek(0);lock_handle.truncate();lock_handle.write(str(os.getpid())+'\n');lock_handle.flush()
    records = []
    def status(stage, **extra):
        data = dict(stage=stage, pid=os.getpid(), group=args.group,
                    cases_recorded=len(records), source_set_sha256=signature,
                    project=str(project), current_time_unix=time.time())
        data.update(extra)
        helper.atomic_json(status_path, data)
        helper.atomic_json(dest/('all_cases_'+result_suffix+'.json' if result_suffix else 'all_cases.json'), records)
    status('starting', scheduled=len(cases))
    result = None
    cache = None
    try:
        for folder, name in cases:
            bench = root/folder/'benches'/(name+'.scs')
            dependencies = {}
            external_models = {}
            def record_dependency(path):
                path = path.resolve()
                if not str(path).startswith(str(root.resolve())+'/'):
                    pdk = Path('@TECH_ROOT@').resolve()
                    path.relative_to(pdk)
                    key = str(path)
                    if key in external_models:
                        return
                    content = path.read_bytes()
                    external_models[key] = dict(sha256=hashlib.sha256(content).hexdigest(),bytes=len(content))
                    for included in re.findall(r'(?m)^\s*include\s+"([^"]+)"',content.decode('utf-8',errors='replace')):
                        candidate = Path(included)
                        record_dependency(candidate if candidate.is_absolute() else path.parent/candidate)
                    return
                key = str(path.relative_to(root))
                if key in dependencies:
                    return
                content = path.read_bytes()
                dependencies[key] = hashlib.sha256(content).hexdigest()
                for included in re.findall(r'(?m)^\s*(?:ahdl_include|include)\s+"([^"]+)"', content.decode('utf-8')):
                    candidate = Path(included)
                    if not candidate.is_absolute():
                        candidate = path.parent/candidate
                    record_dependency(candidate)
            record_dependency(bench)
            content_hash = hashlib.sha256(json.dumps(dependencies,sort_keys=True).encode()).hexdigest()
            model_hash = hashlib.sha256(json.dumps(external_models,sort_keys=True).encode()).hexdigest()
            case_id = '{}_{}_{}'.format(folder, name, signature[:10]+content_hash[:6])
            if external_models:
                case_id += '_pdk'+model_hash[:8]
            if args.engine == 'aps':
                case_id += '_aps2'
            cache = dest/(case_id+'.json')
            if cache.is_file():
                old = json.loads(cache.read_text())
                if old.get('state') == 'completed' and all(Path(p).exists() for p in old.get('artifacts', [])):
                    old['resumed'] = True
                    records.append(old)
                    status('running', current_case=case_id)
                    continue
            attempt = 1
            while (dest/(case_id+'_a'+str(attempt)+'.log')).exists():
                attempt += 1
            tag = case_id+'_a'+str(attempt)
            raw = dest/(tag+'.raw')
            log = dest/(tag+'.log')
            output = dest/(tag+'.stdout')
            result = dict(case_id=case_id, bench=str(bench), name=name, folder=folder,
                          state='running', attempt=attempt, source_set_sha256=signature,
                          bench_sha256=hashlib.sha256(bench.read_bytes()).hexdigest(),
                          own_dependency_sha256=content_hash, dependencies=dependencies,
                          external_model_dependencies=external_models,
                          external_model_set_sha256=model_hash,
                          simulator_engine=args.engine, simulator_threads=2 if args.engine=='aps' else 1,
                          started_unix=time.time(),
                          artifacts=[str(bench), str(log), str(raw)])
            if name == 'tb_afc_va':
                fixture = bench.parent/'afc_test_source.va'
                result['afc_fixture_sha256'] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            helper.atomic_json(cache, result)
            status('running', current_case=case_id)
            try:
                deadline = 1200 if args.group in ['stage1','stage2','stage3','afc'] else 240
                deadline = args.timeout_seconds or deadline
                command = ['@SPECTRE_ROOT@/bin/spectre', str(bench),
                           '-format', 'psfascii', '-raw', str(raw), '+log', str(log)]
                if args.engine == 'aps':
                    command += ['+aps', '+mt=2']
                result.update(simulator_command=command, deadline_seconds=deadline)
                rc = helper.run_process(command,
                           output, bench.parent, time.monotonic()+deadline)
                result.update(spectre_rc=rc, spectre_log_summary=helper.spectral_log_summary(log))
                if rc:
                    raise RuntimeError('Spectre returned '+str(rc))
                if not list(raw.glob('*')):
                    raise RuntimeError('No raw analysis evidence')
                unchanged = all(hashlib.sha256((root/key).read_bytes()).hexdigest()==value
                                for key,value in dependencies.items())
                unchanged = unchanged and all(hashlib.sha256(Path(key).read_bytes()).hexdigest()==value['sha256']
                                              for key,value in external_models.items())
                result['source_files_unchanged_at_completion'] = unchanged
                if not unchanged:
                    raise RuntimeError('A circuit/model source changed during simulation; retain evidence but reject pass')
                result.update(state='completed', finished_unix=time.time(),
                              analysis_files=[p.name for p in raw.glob('*')])
            except Exception as error:
                result.update(state='failed', error=repr(error), finished_unix=time.time())
            helper.atomic_json(cache, result)
            records.append(result)
            status('running', last_case=name, last_state=result['state'])
            print(json.dumps({'case': name, 'state': result['state'], 'rc': result.get('spectre_rc'),
                              'error': result.get('error')}), flush=True)
        status('complete_analyses', failed=[r['name'] for r in records if r['state'] != 'completed'],
               remaining='Electrical pass/fail requires waveform measurement, not exit code alone.')
    except KeyboardInterrupt:
        helper.STOP.set()
        with helper.ACTIVE_LOCK:
            owned = list(helper.ACTIVE.values())
        for process in owned:
            helper.stop_process_group(process)
        if result and result.get('state') == 'running':
            result.update(state='interrupted',finished_unix=time.time(),
                          error='Own diagnostic stopped; retained partial raw is not an electrical pass/fail.')
            helper.atomic_json(cache,result)
            records.append(result)
        status('stopped', completed_results_retained=True)
        return 130
    return 0

if __name__ == '__main__':
    sys.exit(main())
