"""Run only the owned AFC2009 benches, one at a time; Python 3.6+."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import time

PROJECT = Path('@PROJECT_ROOT@')
ROOT = PROJECT / 'afc2009_20261007'
PDK = Path('@TECH_ROOT@')
assert Path.cwd().resolve() == PROJECT
sys.path.insert(0, str(PROJECT))
import run_background_phase3 as helper


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dependencies(bench):
    own, models = {}, {}

    def visit(path):
        path = path.resolve()
        try:
            path.relative_to(PDK.resolve())
            selected = models
        except ValueError:
            path.relative_to(PROJECT.resolve())
            if not (str(path).startswith(str(ROOT.resolve())+'/') or
                    str(path).startswith(str((PROJECT/'pll_full').resolve())+'/')):
                raise ValueError('Unexpected own dependency: '+str(path))
            selected = own
        key = str(path)
        if key in selected:
            return
        content = path.read_bytes()
        selected[key] = dict(sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
        for include in re.findall(r'(?m)^\s*(?:include|ahdl_include)\s+"([^"]+)"',
                                  content.decode('utf-8', errors='replace')):
            candidate = Path(include)
            visit(candidate if candidate.is_absolute() else path.parent/candidate)
    visit(bench)
    return own, models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--only', action='append', default=[])
    parser.add_argument('--deadline', type=int, default=900)
    parser.add_argument('--engine', choices=['aps', 'apsplus', 'classic'], default='aps')
    args = parser.parse_args()
    if not 60 <= args.deadline <= 3600:
        parser.error('Per-case deadline must be 60..3600 seconds.')
    manifest = Path(args.manifest).resolve()
    manifest.relative_to(ROOT.resolve())
    cases = json.loads(manifest.read_text())
    if isinstance(cases, dict):
        cases = cases['cases']
    if args.only:
        cases = [c for c in cases if c['name'] in args.only]
    if not cases or len({c['name'] for c in cases}) != len(cases):
        raise ValueError('Need a nonempty list of uniquely named cases.')
    result_root = PROJECT/'results/afc2009_20261007'
    result_root.mkdir(parents=True, exist_ok=True)
    runner_lock = (result_root/'runner.lock').open('a+')
    fcntl.flock(runner_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    runner_lock.seek(0); runner_lock.truncate(); runner_lock.write(str(os.getpid())+'\n')
    runner_lock.flush()
    records = []
    status_path = result_root/'status.json'

    def status(stage, **extra):
        data = dict(stage=stage, pid=os.getpid(), project=str(PROJECT),
                    new_scope=str(ROOT), manifest=str(manifest),
                    manifest_sha256=sha(manifest), time_unix=time.time(),
                    scheduled=[c['name'] for c in cases], records=records)
        data.update(extra)
        helper.atomic_json(status_path, data)

    def interrupted(signum, frame):
        raise KeyboardInterrupt('Requested signal '+str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    status('starting')
    current = None
    try:
        for case in cases:
            bench = Path(case['path']).resolve()
            bench.relative_to(ROOT.resolve())
            if bench.suffix != '.scs':
                raise ValueError('Only owned Spectre benches allowed.')
            own, models = dependencies(bench)
            signature = hashlib.sha256(json.dumps(dict(own=own, models=models),
                                       sort_keys=True).encode()).hexdigest()
            name = case['name']
            tag_base = name+'_'+signature[:12]+'_'+args.engine
            cache = result_root/(tag_base+'.json')
            if cache.exists():
                saved = json.loads(cache.read_text())
                if saved.get('state') == 'completed' and Path(saved['raw']).exists():
                    saved['resumed_cache'] = True
                    records.append(saved)
                    status('running', last_case=name, cache_reused=True)
                    continue
            attempt = 1
            while (result_root/(tag_base+'_a'+str(attempt)+'.log')).exists():
                attempt += 1
            tag = tag_base+'_a'+str(attempt)
            raw = result_root/(tag+'.raw')
            log = result_root/(tag+'.log')
            stdout = result_root/(tag+'.stdout')
            command = ['@SPECTRE_ROOT@/bin/spectre', str(bench),
                       '-format', 'psfascii', '-raw', str(raw), '+log', str(log)]
            if args.engine in ['aps', 'apsplus']:
                command += ['++aps' if args.engine=='apsplus' else '+aps', '+mt=2']
            current = dict(name=name, state='running', bench=str(bench),
                bench_sha256=sha(bench), source_model_signature_sha256=signature,
                own_dependencies=own, model_dependencies=models, raw=str(raw),
                log=str(log), stdout=str(stdout), attempt=attempt,
                simulator_command=command, simulator_threads_requested=2 if args.engine in ['aps','apsplus'] else 1,
                runner_source_sha256=sha(Path(__file__).resolve()),
                engine=args.engine,
                started_unix=time.time(), deadline_seconds=args.deadline,
                specification=case)
            helper.atomic_json(cache, current)
            status('running', current_case=name)
            try:
                rc = helper.run_process(command, stdout, bench.parent,
                                        time.monotonic()+args.deadline)
                current['spectre_rc'] = rc
                if rc:
                    raise RuntimeError('Spectre returned '+str(rc))
                if not raw.exists() or not list(raw.iterdir()):
                    raise RuntimeError('No raw analysis evidence.')
                current['state'] = 'completed'
            except Exception as error:
                current.update(state='failed', error=repr(error))
            finally:
                current['finished_unix'] = time.time()
                current['source_models_unchanged_at_completion'] = all(
                    Path(p).is_file() and sha(p)==info['sha256']
                    for p, info in list(own.items())+list(models.items()))
                current['spectre_log_summary'] = helper.spectral_log_summary(log)
                if not current['source_models_unchanged_at_completion']:
                    current.update(state='failed', error='Referenced circuit/model changed during run.')
            helper.atomic_json(cache, current)
            records.append(current)
            status('running', last_case=name, last_state=current['state'])
            print(json.dumps(dict(name=name, state=current['state'],
                                  rc=current.get('spectre_rc'), error=current.get('error'))), flush=True)
        status('complete_analyses', failed=[r['name'] for r in records if r['state']!='completed'],
               electrical_verification_pending=True)
    except KeyboardInterrupt:
        helper.STOP.set()
        with helper.ACTIVE_LOCK:
            owned = list(helper.ACTIVE.values())
        for process in owned:
            helper.stop_process_group(process)
        if current and current.get('state') == 'running':
            current.update(state='interrupted', finished_unix=time.time())
            helper.atomic_json(cache, current)
            records.append(current)
        status('interrupted', no_foreign_process_signal=True)
    finally:
        fcntl.flock(runner_lock.fileno(), fcntl.LOCK_UN)
        runner_lock.close()


if __name__ == '__main__':
    main()
