"""Read-only terminal evidence for one exact owned TimeoutExpired R1 case.

No signals, simulator launch, process termination, GUI or VM control.
Python 3.6+, stdlib only. Root executes only after the existing run is terminal.
"""
from __future__ import print_function
import argparse
import hashlib
import json
from pathlib import Path
import time

PROJECT=Path('@PROJECT_ROOT@')
SCOPE=PROJECT/'afc2009_20261007'
RESULT_SCOPE=PROJECT/'results'/'afc2009_20261007'
MODEL_SCOPE=Path('@TECH_ROOT@')
CASE_NAME='pll_afc2009_physical_halfvdd_ref10000_4p_r1_6500n'
EXPECTED_BENCH_SHA='4538b92a7027f82e808d90c40230bf101f54c870c2bb6eca96a67902c9ab9793'
EXPECTED_AFC_SHA='12044e0dc052c06682a3372f17c0b8612d637954af88e0d8662cf1d8c0f8f6b8'
OWN_IDENTITIES=[(79487,3085643),(79506,3085647),(79618,3085664),(79631,3085666)]
MAX_RAW_BYTES=512*1024*1024


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def beneath(path,root):
    path=Path(path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise ValueError('Path escapes exact owned/model scope: '+str(path))
    return path


def check_process(pid,startticks,proc_root=Path('/proc')):
    stat=proc_root/str(pid)/'stat'
    if not stat.exists():
        return dict(pid=pid,expected_startticks=startticks,
            same_identity_present=False,identity_gone=True,reason='PID absent from /proc')
    text=stat.read_text(encoding='utf8',errors='replace')
    tail=text[text.rfind(')')+2:].split()
    if len(tail)<20:
        raise ValueError('Malformed /proc stat; cannot prove process identity.')
    actual_ticks=int(tail[19])
    same=actual_ticks==startticks
    return dict(pid=pid,expected_startticks=startticks,observed_startticks=actual_ticks,
        observed_state=tail[0],same_identity_present=same,identity_gone=not same,
        reason='Exact own PID/startticks still present' if same else 'PID reused; original own identity absent')


def process_checks():
    if not Path('/proc').is_dir():
        raise ValueError('Guest /proc is required for terminal proof; no foreign host fallback.')
    rows=[check_process(pid,ticks) for pid,ticks in OWN_IDENTITIES]
    if not all(row['identity_gone'] for row in rows):
        raise ValueError('At least one exact owned process identity still exists; no partial raw read permitted.')
    return rows


def load_terminal_execution(path):
    path=beneath(path,RESULT_SCOPE)
    before=sha(path)
    execution=json.loads(path.read_text(encoding='utf8'))
    if sha(path)!=before:
        raise ValueError('Execution cache changed during read.')
    if execution.get('name')!=CASE_NAME:
        raise ValueError('Terminal proof is limited to the exact owned R1 full case.')
    if execution.get('state')!='failed' or 'TimeoutExpired' not in execution.get('error',''):
        raise ValueError('Only actual failed TimeoutExpired cache is accepted.')
    if not execution.get('source_models_unchanged_at_completion'):
        raise ValueError('Execution does not establish unchanged source/models at terminal state.')
    if not execution.get('finished_unix') or execution.get('spectre_rc')==0:
        raise ValueError('Timeout case lacks terminal timestamp or misleading successful rc0.')
    bench=beneath(execution['bench'],SCOPE/'integration'/'r1'/'pll_6500n')
    if execution.get('bench_sha256')!=EXPECTED_BENCH_SHA or sha(bench)!=EXPECTED_BENCH_SHA:
        raise ValueError('Exact frozen R1 bench SHA mismatch.')
    raw=beneath(Path(execution['raw'])/'tran.tran.tran',RESULT_SCOPE)
    if not raw.is_file() or raw.stat().st_size>MAX_RAW_BYTES:
        raise ValueError('Partial raw missing or exceeds 512MiB guard.')
    return execution,path,before,bench,raw


def verify_dependencies(execution):
    checked={}
    own=execution.get('own_dependencies',{})
    afc=[]
    for kind,dependencies,allowed in [('own',own,PROJECT),
        ('model',execution.get('model_dependencies',{}),MODEL_SCOPE)]:
        if not dependencies:
            raise ValueError('Execution dependency ledger missing '+kind)
        for path,record in dependencies.items():
            path=beneath(path,allowed)
            actual=sha(path)
            if actual!=record.get('sha256'):
                raise ValueError('Referenced source/model changed: '+str(path))
            checked[str(path)]=dict(kind=kind,expected_sha256=record['sha256'],actual_sha256=actual,unchanged=True)
            if kind=='own' and path.name=='afc2009_mos.scs':
                afc.append(actual)
    if afc!=[EXPECTED_AFC_SHA]:
        raise ValueError('AFC dependency is not the exact R1 MOS source.')
    return checked


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execution',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args()
    output=beneath(args.output,SCOPE)
    if output.exists():
        raise ValueError('Proof output already exists; preserve terminal evidence.')
    execution,path,cache_sha,bench,raw=load_terminal_execution(args.execution)
    processes=process_checks()
    before=verify_dependencies(execution)
    raw_sha=sha(raw)
    after=verify_dependencies(execution)
    if before!=after or sha(path)!=cache_sha or sha(raw)!=raw_sha:
        raise ValueError('Terminal cache/raw/dependencies changed while collecting proof.')
    processes_after=process_checks()
    result={'version':'owned-R1-timeout-terminal-proof-v1','created_unix':time.time(),
        'execution':{'path':str(path),'sha256':cache_sha,'name':execution['name'],
            'state':execution['state'],'error':execution['error'],'finished_unix':execution['finished_unix']},
        'bench':{'path':str(bench),'sha256':EXPECTED_BENCH_SHA},
        'raw':{'path':str(raw),'sha256':raw_sha,'bytes':raw.stat().st_size},
        'owned_process_checks_before':processes,'owned_process_checks_after':processes_after,
        'all_owned_process_identities_gone':True,'sources_verified_unchanged':True,
        'dependency_hashes_before':before,'dependency_hashes_after':after,
        'numerical_completion':False,'full_case_pass':None,
        'read_only':True,'signals_sent':False,'simulator_started':False,
        'scope':'Exact root-supplied own PID/startticks identities only; other sessions and the VM are untouched.'}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'output':str(output),'sha256':sha(output),
        'all_owned_process_identities_gone':True,'numerical_completion':False,'full_case_pass':None}))


if __name__=='__main__':
    main()
