"""Export exact terminal owned logs; numerical failures stay failures."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

PROJECT = Path('@PROJECT_ROOT@')
ROOT = PROJECT/'afc2009_20261007'
RESULTS = PROJECT/'results/afc2009_20261007'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.relative_to((ROOT/'evidence').resolve())
    if output.exists():
        raise ValueError('Preserve previous exports; choose a new output directory.')
    records = []
    for cache in sorted(RESULTS.glob('*.json')):
        record = json.loads(cache.read_text())
        if not isinstance(record,dict) or 'own_dependencies' not in record:
            continue
        if record['state'] == 'running':
            raise ValueError('Final export forbids active analyses: '+record['name'])
        if not record['source_models_unchanged_at_completion']:
            raise ValueError('Source changed: '+record['name'])
        for path, info in record['own_dependencies'].items():
            if sha(path)!=info['sha256']:
                raise ValueError('Owned source bytes differ: '+path)
        log = Path(record['log']).resolve()
        log.relative_to(RESULTS.resolve())
        if log.suffix != '.log' or not log.is_file() or log.stat().st_size>8*1024*1024:
            raise ValueError('Unexpected log source: '+str(log))
        content = log.read_text(errors='replace')
        completion = re.findall(r'spectre completes with (\d+) errors?, (\d+) warnings?',content)
        numerically_completed = bool(record['state']=='completed' and record.get('spectre_rc')==0)
        if numerically_completed and (not completion or int(completion[-1][0])!=0):
            raise ValueError('Missing successful simulator completion log: '+str(log))
        memory = re.findall(r'Peak resident memory used\s*=\s*([\d.]+)\s*Mbytes',content)
        records.append(dict(name=record['name'],export_name=log.name,log_sha256=sha(log),
            log_file=str(log),log_bytes=log.stat().st_size,full_log_exported=True,
            execution_file=str(cache),execution_sha256=sha(cache),
            simulator_engine_requested=record.get('engine') or ('aps' if '+aps' in record['simulator_command'] else 'classic'),
            simulator_command=record['simulator_command'],
            threads_requested=record['simulator_threads_requested'],
            elapsed_wall_seconds=record['finished_unix']-record['started_unix'],
            peak_resident_Mbytes=float(memory[-1]) if memory else None,
            errors=int(completion[-1][0]) if completion else None,
            warnings=int(completion[-1][1]) if completion else None,
            numerical_state=record['state'],spectre_rc=record.get('spectre_rc'),
            numerically_completed=numerically_completed,
            scope='Exact terminal log; failed/timeout analyses remain failed. Electrical audit is separate.'))
    if not records:
        raise ValueError('No completed owned logs.')
    output.mkdir(parents=True)
    for record in records:
        target=output/record['export_name']
        shutil.copyfile(record['log_file'],str(target))
        assert sha(target)==record['log_sha256']
    (output/'actual_solver_log_index.json').write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps(dict(exported=len(records),output=str(output))))


if __name__=='__main__':
    main()
