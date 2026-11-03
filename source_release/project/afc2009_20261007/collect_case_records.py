"""Small read-only inventory of this task's cases and exact simulator logs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    results = here.parent/'results/afc2009_20261007'
    records = []
    for path in sorted(results.glob('*.json')):
        record = json.loads(path.read_text())
        if not isinstance(record,dict) or 'own_dependencies' not in record:
            continue
        record = dict(record)
        record['execution_file'] = str(path.resolve())
        record['execution_file_sha256'] = sha(path)
        log = Path(record['log'])
        if log.exists():
            text = log.read_text(errors='replace')
            memory = re.findall(r'Peak resident memory used\s*=\s*([\d.]+)\s*Mbytes',text)
            errors = re.findall(r'spectre completes with (\d+) errors, (\d+) warnings',text)
            threads = re.findall(r'(?i)(?:threads|thread count)\D{0,15}(\d+)',text)
            record['actual_log_evidence'] = dict(path=str(log),sha256=sha(log),
                bytes=log.stat().st_size,
                peak_resident_Mbytes=float(memory[-1]) if memory else None,
                completion_errors=int(errors[-1][0]) if errors else None,
                completion_warnings=int(errors[-1][1]) if errors else None,
                thread_mentions=threads,raw_complete=record.get('state')=='completed')
        records.append(record)
    output = dict(snapshot_unix=time.time(),read_only_collection=True,records=records)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(dict(output=str(args.output),cases=len(records),
        completed=sum(r['state']=='completed' for r in records))))


if __name__ == '__main__':
    main()
