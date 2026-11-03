"""Read-only inventory of owned AFC2009 runs; never signal any process."""
import json
import os
from pathlib import Path
import re
import time

PROJECT = Path('@PROJECT_ROOT@')
RESULTS = PROJECT/'results/afc2009_20261007'
data = dict(timestamp_unix=time.time(), read_only=True, signal_sent=False)
status = RESULTS/'status.json'
if status.exists():
    source = json.loads(status.read_text())
    data['status'] = {key:source.get(key) for key in ['stage','pid','current_case','last_case','last_state','failed']}
records = []
for path in RESULTS.glob('*.json'):
    if path.name == 'status.json':
        continue
    try:
        record = json.loads(path.read_text())
    except Exception:
        continue
    if not isinstance(record, dict) or 'bench' not in record:
        continue
    summary = {key:record.get(key) for key in ['name','state','spectre_rc','error','started_unix','finished_unix','source_models_unchanged_at_completion']}
    summary['cache_path'] = str(path)
    summary['elapsed_wall_seconds'] = (record.get('finished_unix') or time.time())-record['started_unix']
    log = Path(record['log'])
    if log.exists():
        with log.open('rb') as handle:
            handle.seek(max(0, log.stat().st_size-4096))
            tail = handle.read().decode('utf-8', errors='replace')
        summary['log_tail'] = tail[-1600:]
    raw=Path(record['raw'])/'tran.tran.tran'
    if raw.is_file():
        summary['raw_bytes_current']=raw.stat().st_size
        with raw.open('rb') as handle:
            handle.seek(max(0,raw.stat().st_size-32768))
            raw_tail=handle.read().decode('utf-8',errors='replace')
        times=re.findall(r'^\"time\"\s+([-+0-9.eE]+)',raw_tail,re.M)
        summary['saved_time_current_s']=float(times[-1]) if times else None
        summary['progress_scope']='Incomplete saved time only; no electrical pass/lock conclusion.'
    records.append(summary)
data['cases'] = records
memory = Path('/proc/meminfo').read_text()
data['mem_available_kB'] = int(re.search(r'^MemAvailable:\s*(\d+)', memory, re.M).group(1))
processes = []
for path in Path('/proc').glob('[0-9]*'):
    try:
        argv = (path/'cmdline').read_bytes().replace(b'\0', b' ').decode('utf-8', errors='replace')
        if 'afc2009_20261007' not in argv or any(n in argv for n in ['read_progress.py','read_progress_v2.py']) or str(path.name)==str(os.getpid()):
            continue
        if not any(token in argv for token in ['spectre','run_cases.py','run_cases_v2.py']):
            continue
        status_text = (path/'status').read_text()
        resident = re.search(r'^VmRSS:\s*(\d+)', status_text, re.M)
        stat = (path/'stat').read_text().rsplit(')',1)[1].split()
        processes.append(dict(pid=int(path.name),start_ticks=int(stat[19]),
                              rss_kB=int(resident.group(1)) if resident else None,argv=argv))
    except (OSError, ValueError, IndexError):
        pass
data['owned_processes'] = processes
print(json.dumps(data, indent=2))
