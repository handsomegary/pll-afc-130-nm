#!/usr/bin/env python3
"""Explicitly run one local PLL testbench; Python 3.8+, standard library only.

The repository does not contain process models. Supply the ignored local model
adapter before running. Each invocation owns one child process and one run
directory. Existing sessions are never inspected or signaled.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid


INCLUDES = re.compile(r'^\s*(?:include|ahdl_include)\s+"([^\"]+)"', re.MULTILINE)
BENCHES = {'on': 'pll_afc_on.scs', 'off': 'pll_afc_off.scs'}


def digest(path):
    state = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            state.update(chunk)
    return state.hexdigest()


def inside(path, directory):
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def dependency_hashes(bench, root, adapter):
    """Resolve the actual include graph and hash every file without copying it."""
    public, private, visited = {}, {}, set()

    def visit(path, local_models=False):
        resolved = path.resolve()
        if resolved in visited:
            return
        if not resolved.is_file():
            raise ValueError('Missing include: ' + str(resolved))
        visited.add(resolved)
        local_models = local_models or resolved == adapter
        if not local_models and not inside(resolved, root):
            raise ValueError('Project include leaves the repository: ' + str(resolved))
        entry = {'sha256': digest(resolved), 'bytes': resolved.stat().st_size}
        if local_models:
            private[str(resolved)] = entry
        else:
            public[resolved.relative_to(root).as_posix()] = entry
        text = resolved.read_text(encoding='utf-8', errors='replace')
        for include in INCLUDES.findall(text):
            target = Path(include)
            if not target.is_absolute():
                target = resolved.parent / target
            visit(target, local_models)

    visit(bench)
    if str(adapter) not in private:
        raise ValueError('The selected bench does not include the local model adapter.')
    return public, private


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--bench', choices=sorted(BENCHES), required=True)
    parser.add_argument('--spectre', default='spectre', help='Spectre executable or absolute path')
    parser.add_argument('--threads', type=int, choices=[1, 2, 4], default=4)
    parser.add_argument('--timeout', type=int, default=7200, help='Child-process deadline, seconds')
    args = parser.parse_args()
    if not 60 <= args.timeout <= 7200:
        parser.error('--timeout must be between 60 and 7200 seconds.')
    root = args.root.resolve()
    bench = root / 'circuits' / 'benches' / BENCHES[args.bench]
    adapter = (root / 'config' / 'process_models.local.scs').resolve()
    if not adapter.is_file():
        parser.error('Create the ignored config/process_models.local.scs adapter first.')
    if not inside(adapter, root / 'config'):
        parser.error('The local adapter must resolve inside config/.')
    if not bench.is_file() or not inside(bench, root / 'circuits' / 'benches'):
        parser.error('The selected repository testbench is missing or resolves outside circuits/benches/.')
    executable = shutil.which(args.spectre)
    if executable is None:
        parser.error('Spectre executable not found: ' + args.spectre)
    runs = (root / 'runs').resolve()
    if not inside(runs, root) or runs == root:
        parser.error('The runs directory must resolve inside the repository.')
    public, private = dependency_hashes(bench, root, adapter)
    runs.mkdir(parents=True, exist_ok=True)
    lock_path = runs / 'exclusive.lock'
    try:
        lock_fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        parser.error('An exclusive run lock exists. Inspect runs/exclusive.lock; this tool never removes another run lock.')
    token = str(uuid.uuid4())
    lock = {'runner_pid': os.getpid(), 'token': token, 'bench': args.bench,
            'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with os.fdopen(lock_fd, 'w', encoding='utf-8') as handle:
        json.dump(lock, handle, sort_keys=True)
        handle.write('\n')
    child = None
    record = None
    record_path = None
    try:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run_dir = runs / (stamp + '_' + args.bench + '_' + token[:8])
        run_dir.mkdir()
        raw_dir = run_dir / 'raw'
        raw_dir.mkdir()
        record_path = run_dir / 'execution.json'
        command = [executable, bench.name, '++aps', '+mt=' + str(args.threads),
                   '-format', 'psfascii', '-raw', str(raw_dir), '-log', str(run_dir / 'spectre.log')]
        record = {'schema_version': 1, 'state': 'prepared', 'bench': args.bench,
                  'bench_path': bench.relative_to(root).as_posix(), 'bench_sha256': digest(bench),
                  'command': command, 'cwd': str(bench.parent), 'runner_pid': os.getpid(),
                  'requested_threads': args.threads, 'timeout_s': args.timeout,
                  'started_utc': lock['started_utc'], 'public_dependencies': public,
                  'private_model_dependencies': private,
                  'local_model_adapter_sha256': private[str(adapter)]['sha256'],
                  'raw_directory': str(raw_dir), 'simulation_was_explicitly_invoked': True}
        atomic_json(record_path, record)
        started = time.monotonic()
        with (run_dir / 'stdout.log').open('wb') as output:
            child = subprocess.Popen(command, cwd=str(bench.parent), stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT, shell=False)
            record.update(state='running', child_pid=child.pid)
            atomic_json(record_path, record)
            try:
                returncode = child.wait(timeout=args.timeout)
                record.update(state='completed' if returncode == 0 else 'simulator_failed',
                              simulator_returncode=returncode)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                record.update(state='timed_out', simulator_returncode=child.returncode,
                              signal_scope='Only the child process created by this invocation.')
            except KeyboardInterrupt:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                record.update(state='interrupted', simulator_returncode=child.returncode,
                              signal_scope='Only the child process created by this invocation.')
        record['elapsed_wall_s'] = time.monotonic() - started
        after_public, after_private = dependency_hashes(bench, root, adapter)
        record['source_models_unchanged_at_completion'] = (after_public == public and after_private == private)
        if not record['source_models_unchanged_at_completion']:
            record['state'] = 'source_changed'
        record['completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record['electrical_pass'] = None
        record['limitations'] = 'Numerical completion is not a PLL capture, timing, noise, or PVT qualification.'
        atomic_json(record_path, record)
        print(json.dumps({'state': record['state'], 'execution': str(record_path),
                          'simulator_returncode': record.get('simulator_returncode')}, indent=2))
        return 0 if record['state'] == 'completed' else 2
    except Exception as error:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if record is not None and record_path is not None:
            record.update(state='runner_failed', error=str(error),
                          completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            atomic_json(record_path, record)
        raise
    finally:
        if lock_path.is_file():
            current = json.loads(lock_path.read_text(encoding='utf-8'))
            if current.get('token') == token:
                lock_path.unlink()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print('Error: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
