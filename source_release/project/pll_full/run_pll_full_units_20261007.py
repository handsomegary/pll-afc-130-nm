"""Identity-scoped, one-at-a-time PLL unit bench runner. Python 3.6+."""
import argparse
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
    parser.add_argument('--group', choices=['units','receiver','cpfast','stage0','stage1','stage2','stage3','afc'], default='units')
    parser.add_argument('--only', default=None)
    args = parser.parse_args()
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
    elif args.group == 'cpfast':
        cases = [('analog',p.stem) for p in sorted((root/'analog/benches').glob('cp_pulse_*x.scs'))]
    elif args.group == 'afc':
        cases = [('digital',p.stem) for p in sorted((root/'digital/benches').glob('pll_afc_stage1*.scs'))]
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
    status_path = project/'results'/('fullpll_'+status_suffix+'_status.json')
    records = []
    def status(stage, **extra):
        data = dict(stage=stage, pid=os.getpid(), group=args.group,
                    cases_recorded=len(records), source_set_sha256=signature,
                    project=str(project), current_time_unix=time.time())
        data.update(extra)
        helper.atomic_json(status_path, data)
        helper.atomic_json(dest/('all_cases_'+args.only+'.json' if args.only else 'all_cases.json'), records)
    status('starting', scheduled=len(cases))
    try:
        for folder, name in cases:
            bench = root/folder/'benches'/(name+'.scs')
            dependencies = {}
            def record_dependency(path):
                path = path.resolve()
                if not str(path).startswith(str(root.resolve())+'/'):
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
            case_id = '{}_{}_{}'.format(folder, name, signature[:10]+content_hash[:6])
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
                          started_unix=time.time(),
                          artifacts=[str(bench), str(log), str(raw)])
            if name == 'tb_afc_va':
                fixture = bench.parent/'afc_test_source.va'
                result['afc_fixture_sha256'] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            helper.atomic_json(cache, result)
            status('running', current_case=case_id)
            try:
                deadline = 1200 if args.group in ['stage1','stage2','stage3','afc'] else 240
                rc = helper.run_process(['@SPECTRE_ROOT@/bin/spectre', str(bench),
                           '-format', 'psfascii', '-raw', str(raw), '+log', str(log)],
                           output, bench.parent, time.monotonic()+deadline)
                result.update(spectre_rc=rc, spectre_log_summary=helper.spectral_log_summary(log))
                if rc:
                    raise RuntimeError('Spectre returned '+str(rc))
                if not list(raw.glob('*')):
                    raise RuntimeError('No raw analysis evidence')
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
        status('stopped', completed_results_retained=True)
        return 130
    return 0

if __name__ == '__main__':
    sys.exit(main())
