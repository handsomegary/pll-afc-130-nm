"""Export compact own-case logs/fingerprints, never model files or raw arrays."""
import hashlib,json,re,shutil
from pathlib import Path
project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
source_root=project/'results/fullpll';dest=project/'results/owned_log_exports_20261007'
dest.mkdir(exist_ok=True);rows=[];seen=set()
for group in ['stage0','stage1','stage2','stage3','afc','loaded','noise']:
    for manifest in sorted((source_root/group).glob('all_cases*.json')):
        for record in json.loads(manifest.read_text()):
            if record.get('case_id') in seen:continue
            seen.add(record.get('case_id'))
            for original in record.get('artifacts',[]):
                path=Path(original)
                if path.suffix!='.log' or not path.is_file():continue
                path.resolve().relative_to(source_root.resolve())
                data=path.read_bytes();text=data.decode(errors='replace')
                target=dest/(group+'_'+path.name)
                if len(data)<=8*1024*1024:
                    shutil.copy2(path,target);complete=True
                else:
                    lines=text.splitlines();target=target.with_suffix('.excerpt.txt')
                    target.write_text('\n'.join(lines[:120]+['EXCERPT: middle omitted']+lines[-160:])+'\n');complete=False
                relevant=[line for line in text.splitlines() if re.search(r'Multithread|\bthreads?\b|\bAPS\b|Spectre.*Version|Version.*Spectre',line,re.I)][:25]
                rows.append(dict(case=record['name'],case_id=record['case_id'],state=record['state'],
                    engine_requested=record.get('simulator_engine','classic'),threads_requested=record.get('simulator_threads',1),
                    log_file=str(path),log_sha256=hashlib.sha256(data).hexdigest(),export_name=target.name,
                    full_log_exported=complete,actual_engine_thread_log_lines=relevant))
(dest/'actual_solver_log_index.json').write_text(json.dumps(rows,indent=2))
print(json.dumps({'own_case_logs':len(rows),'destination':str(dest)}))
