"""Prepare ONE phase-boundary-only PSS retry; never launch any analysis.

Python 3.6+, stdlib. Preserve the original bench/manifest and failed evidence.
The installed Spectre18.1 PSS help explains that shooting start phase matters
near nonlinear switching. Change only tstab200n ->201n, without modifying
models, reset/DC sources, saved ICs, tolerances, integration method or maxstep.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def shift_only_tstab(data):
    text=data.decode('utf8')
    lines=[line for line in text.splitlines() if re.match(r'^pss\s+pss\b',line)]
    if len(lines)!=1 or re.search(r'(?m)^\s*\S+\s+\([^\n]*\)\s+pnoise\b',text):
        raise ValueError('Require the failed PSS-only bench, not a noise or alternate analysis.')
    line=lines[0]
    for token in ['fund=100M','tstab=200n','harms=128','errpreset=conservative',
                  'harmonicbalance=no','maxstep=1p','tstabmethod=gear2only','method=gear2only']:
        if token not in line.split():
            raise ValueError('Unexpected original PSS settings: '+token)
    if text.count('tstab=200n')!=1:
        raise ValueError('Require one unambiguous stabilization literal.')
    revised=text.replace('tstab=200n','tstab=201n').encode('utf8')
    if revised.replace(b'tstab=201n',b'tstab=200n')!=data:
        raise AssertionError('Repair changed bytes beyond shooting-start phase.')
    return revised


def prepare(manifest_path,failure_status_path,outdir):
    manifest=json.loads(Path(manifest_path).read_text(encoding='utf8'))
    failure=json.loads(Path(failure_status_path).read_text(encoding='utf8'))
    original=[case for case in manifest['cases'] if case['kind']=='pss']
    if len(original)!=1:raise ValueError('Select one original PSS-only case.')
    case=original[0]
    failed=[item for item in failure['cases'] if item['name']==case['name']]
    if len(failed)!=1:raise ValueError('Require exact original failed execution.')
    execution=failed[0]['execution']
    if execution.get('spectre_rc')!=1 or execution.get('state')!='failed':
        raise ValueError('This targeted retry applies to actual rc1 convergence failure, not timeout.')
    path=Path(case['path']);data=path.read_bytes();hashed=digest_bytes(data)
    if hashed!=case['bench_sha256'] or hashed!=execution.get('bench_sha256'):
        raise ValueError('Original manifest/execution/bench hashes disagree.')
    logs=[Path(p) for p in execution['artifacts'] if p.endswith('.log')]
    if len(logs)!=1:raise ValueError('Require the exact original bound solver log.')
    log=logs[0];logdata=log.read_bytes();logtext=logdata.decode('utf8',errors='replace')
    if 'ERROR (SPECTRE-16192)' not in logtext or 'start = 210 ns' not in logtext:
        raise ValueError('Expected failure at original210ns shooting boundary not confirmed.')
    revised=shift_only_tstab(data)
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    name=case['name']+'_boundary201n'
    newpath=outdir/(name+'.scs')
    if newpath.exists():raise ValueError('Retry bench already exists; preserve immutable attempts.')
    newpath.write_bytes(revised)
    newcase=copy.deepcopy(case)
    newcase.update(name=name,path=str(newpath),bench_sha256=digest_bytes(revised),
                   tstab_s=201e-9,walltime_limit_s=1200,
                   change='Only tstab200n->201n; shooting start210ns->211ns with unchanged10ns period')
    result=copy.deepcopy(manifest)
    result.update(version='driven-physical-pll-noise-boundary-retry-v1',cases=[newcase],
                  ready_to_launch=False,
                  numerical_boundary_retry=dict(original_case=case['name'],
                      original_bench_path=str(path),original_bench_sha256=hashed,
                      original_execution_case_id=execution['case_id'],
                      original_log_path=str(log),original_log_sha256=digest_bytes(logdata),
                      original_rc=1,original_state='failed',
                      hypothesis='Shooting boundary coincides with100MHz reference switching; '
                                 'shift1ns to test phase sensitivity without changing circuit physics.',
                      evidence='Installed Spectre18.1 pss help: nonlinear shooting-start phase discussion.',
                      retained_limits='Same1ps maxstep, gear2only, conservative and all device/tolerance/IC bytes.',
                      no_new_noise_result=True,
                      on_failure='PLL PSS/Pnoise/jitter/FoM remain unknown; no further generic retries.'))
    result['execution_policy']=dict(max_workers=1,max_total_walltime_s=1200,
                                   max_attempts_per_case=1,order=['single targeted PSS-boundary repair'],
                                   prior_walltime_s=392,combined_suite_ceiling_s=1800,
                                   on_timeout_or_failure='Preserve original/retry evidence; mark PSS/noise unknown.')
    newmanifest=outdir/'driven_noise_boundary201n_manifest.json'
    if newmanifest.exists():raise ValueError('Retry manifest already exists; never overwrite.')
    newmanifest.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    return result,newmanifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--failure-status',required=True)
    parser.add_argument('--out-dir',required=True)
    args=parser.parse_args()
    result,path=prepare(args.manifest,args.failure_status,args.out_dir)
    print(json.dumps(dict(manifest=str(path),case=result['cases'][0]['name'],
                         simulation_started=False,only_change='tstab200n->201n'),indent=2))


if __name__=='__main__':main()
