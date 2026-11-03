"""Provisional saved-prefix diagnosis for an actually terminated TimeoutExpired R1.

Never converts timeout data into numerical completion or a full-case PASS.
Requires exact process-gone terminal proof; rereads cache/source/raw fingerprints.
"""
from __future__ import print_function
import argparse
import json
import math
from pathlib import Path
import tempfile
import measure_afc2009 as m
import collect_terminal_partial_proof as proof_tool

HERE=Path(__file__).resolve().parent


def complete_prefix(raw,destination,config,max_stop_s=None):
    """Stream only blocks closed by a next time record or real END marker.

    An unclosed last block at EOF is discarded even if its selected fields look
    complete. Every accepted block must contain exactly the original first
    complete block's scalar names, not merely the selected analysis ports.
    The temporary derivative adds a parser END; it is never a simulator END.
    """
    raw=Path(raw)
    if raw.stat().st_size>m.MAX_RAW_BYTES:
        raise ValueError('Raw exceeds 512MiB prefix guard.')
    if max_stop_s is not None and (not math.isfinite(max_stop_s) or max_stop_s<=0):
        raise ValueError('max_stop_s must be positive and finite.')
    selected=set(config['analogs'].values())|set(config['digitals'].values())
    selected.update(name for names in config['words'].values() for name in names)
    count=0
    observed_stop=None
    last_accepted_time=None
    expected_names=None
    reading=False
    original_end=False
    max_stop_reached=False
    pending_time=None
    pending_names=set()
    pending_selected=[]
    discarded_eof_time=None
    with destination.open('w',encoding='utf8') as output:
        output.write('HEADER\nVALUE\n')
        def accept_pending():
            nonlocal count,observed_stop,last_accepted_time,expected_names,max_stop_reached
            if pending_time is None:
                return True
            if max_stop_s is not None and pending_time-max_stop_s>1e-18:
                max_stop_reached=True
                return False
            if expected_names is None:
                expected_names=set(pending_names)
                if 'time' not in expected_names:
                    raise ValueError('Complete prefix block has no time scalar.')
            elif pending_names!=expected_names:
                raise ValueError('Closed PSF block has changed/missing scalar fields; cannot certify complete prefix.')
            if last_accepted_time is not None and pending_time<=last_accepted_time:
                raise ValueError('Closed PSF prefix times are not strictly increasing.')
            output.writelines(pending_selected)
            count+=1
            observed_stop=pending_time
            last_accepted_time=pending_time
            return True
        with raw.open(encoding='utf8',errors='strict') as handle:
            for raw_line in handle:
                line=raw_line.strip()
                if line=='VALUE':
                    reading=True
                    continue
                if not reading:
                    continue
                if line=='END':
                    original_end=True
                    accept_pending()
                    pending_time=None
                    break
                match=m.LINE.match(line)
                if match is None:
                    continue
                name=match.group(1)
                number=float(match.group(2))
                if not math.isfinite(number):
                    raise ValueError('Nonfinite original scalar in partial PSF.')
                if name=='time':
                    if not accept_pending():
                        pending_time=None
                        break
                    pending_time=number
                    pending_names=set(['time'])
                    pending_selected=[line+'\n']
                elif pending_time is not None:
                    if name in pending_names:
                        raise ValueError('Duplicate scalar in partial PSF block.')
                    pending_names.add(name)
                    if name in selected:
                        pending_selected.append(line+'\n')
            else:
                # No next time or genuine END closed this block. Never credit it.
                discarded_eof_time=pending_time
        output.write('END\n')
    if count<20 or observed_stop is None:
        raise ValueError('Fewer than 20 actually closed PSF blocks; no useful prefix diagnostic.')
    return {'accepted_complete_blocks':count,'observed_stop_s':observed_stop,
        'requested_max_stop_s':max_stop_s,'max_stop_reached':max_stop_reached,
        'max_stop_numeric_boundary_tolerance_s':1e-18,
        'original_PSF_END_seen':original_end,'discarded_unclosed_EOF_block_time_s':discarded_eof_time,
        'original_scalar_names_per_complete_block':len(expected_names),
        'derivative_adds_parser_END_only':True,
        'scope':'Selected unmodified scalar rows from original blocks closed by next time or actual END. '
            'Temporary parser END does not mean simulator/numerical completion.'}


def validate_terminal_proof(path,execution_path,execution_sha,raw):
    path=proof_tool.beneath(path,proof_tool.SCOPE)
    proof_sha=proof_tool.sha(path)
    proof=json.loads(path.read_text(encoding='utf8'))
    if proof_tool.sha(path)!=proof_sha:
        raise ValueError('Terminal proof changed during read.')
    if proof.get('version')!='owned-R1-timeout-terminal-proof-v1':
        raise ValueError('Unrecognized terminal proof version.')
    if proof.get('execution',{}).get('sha256')!=execution_sha or Path(proof['execution']['path']).resolve()!=execution_path:
        raise ValueError('Terminal proof does not bind this exact execution cache.')
    if proof.get('all_owned_process_identities_gone') is not True or proof.get('sources_verified_unchanged') is not True:
        raise ValueError('Proof lacks terminal process-gone/source integrity facts.')
    if proof.get('numerical_completion') is not False or proof.get('full_case_pass') is not None:
        raise ValueError('Terminal proof incorrectly promotes numerical/full-case status.')
    expected=set(proof_tool.OWN_IDENTITIES)
    for key in ['owned_process_checks_before','owned_process_checks_after']:
        rows=proof.get(key,[])
        if {(row['pid'],row['expected_startticks']) for row in rows}!=expected or len(rows)!=len(expected):
            raise ValueError('Proof process whitelist does not match exact own identities.')
        if not all(row.get('identity_gone') is True and row.get('same_identity_present') is False for row in rows):
            raise ValueError('Proof includes a live/ambiguous process identity.')
    if Path(proof['raw']['path']).resolve()!=raw or proof['raw']['sha256']!=proof_tool.sha(raw):
        raise ValueError('Proof raw fingerprint does not match terminal raw.')
    if proof['raw']['bytes']!=raw.stat().st_size:
        raise ValueError('Proof raw byte count mismatch.')
    proof_tool.process_checks()
    return proof,path,proof_sha


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execution',required=True,type=Path)
    ap.add_argument('--terminal-proof',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--max-stop-s',type=float)
    args=ap.parse_args()
    output=proof_tool.beneath(args.output,proof_tool.SCOPE)
    if output.exists():
        raise ValueError('Output exists; preserve previous full/partial evidence.')
    execution,execution_path,execution_sha,bench,raw=proof_tool.load_terminal_execution(args.execution)
    proof,proof_path,proof_sha=validate_terminal_proof(args.terminal_proof,execution_path,execution_sha,raw)
    before=proof_tool.verify_dependencies(execution)
    if proof['dependency_hashes_after']!=before or proof['dependency_hashes_before']!=before:
        raise ValueError('Current dependency hashes differ from terminal proof.')
    raw_sha=proof_tool.sha(raw)
    config=json.loads(json.dumps(m.DEFAULT_CONFIG))
    portmap=HERE/'physical_portmap_r1.json'
    config.update(json.loads(portmap.read_text(encoding='utf8')))
    config['digitals']['reference_counter_reset']='XAFC.reference_count_rst'
    planned_stop=float(execution.get('specification',{}).get('duration_s',6.5e-6))
    bound=min(args.max_stop_s,planned_stop) if args.max_stop_s is not None else planned_stop
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='owned-R1-terminal-prefix-',dir=str(output.parent)) as temp:
        prefix=Path(temp)/'complete-prefix-derived.tran'
        prefix_evidence=complete_prefix(raw,prefix,config,bound)
        diagnosis=m.measure(prefix,config,256)
        derivative_evidence=diagnosis['source_evidence']
    after=proof_tool.verify_dependencies(execution)
    processes_after=proof_tool.process_checks()
    if before!=after or proof_tool.sha(raw)!=raw_sha or proof_tool.sha(execution_path)!=execution_sha:
        raise ValueError('Terminal raw/cache/dependencies changed during bounded extraction.')
    if proof_tool.sha(proof_path)!=proof_sha:
        raise ValueError('Terminal proof changed during bounded extraction.')
    prefix_diagnostics={key:diagnosis[key] for key in
        ['handoff','fine_loop','round_edge_audit','first_edge_audit_valid','first_edge_audit_violations',
         'power','digital_transition_ledgers','word_transition_ledgers']}
    prefix_diagnostics['provisional']=True
    prefix_diagnostics['engineering_lock_observed_within_prefix']=diagnosis['locked']
    prefix_diagnostics['candidate_qualified_by_prefix_capture']=diagnosis['afc_candidate_qualified_by_actual_fine_capture']
    prefix_diagnostics['prefix_observation_scope']='Actual complete terminal PSF prefix only. '
    prefix_diagnostics['prefix_observation_scope']+='Any observed handoff/engineering lock is provisional; later requested simulation duration was not completed.'
    result={'version':'R1-timeout-terminal-partial-diagnostic-v1','name':execution['name'],
        'measurement_state':'terminal_timeout_complete_prefix_diagnostic',
        'numerical_completion':False,'full_case_pass':None,'simulator_electrical_pass':None,
        'afc_success':None,'locked':None,'physical_noise_jitter_s':None,
        'execution_evidence':{'path':str(execution_path),'sha256':execution_sha,
            'state':execution['state'],'error':execution['error'],'numerical_completion':False},
        'terminal_proof_evidence':{'path':str(proof_path),'sha256':proof_sha,
            'process_gone_rechecked':True,'sources_verified_unchanged':True},
        'bench_evidence':{'path':str(bench),'sha256':proof_tool.EXPECTED_BENCH_SHA},
        'source_evidence':{'raw_file':str(raw),'raw_sha256':raw_sha,'raw_bytes':raw.stat().st_size,
            'raw_unchanged_during_extraction':True,'saved_samples':prefix_evidence['accepted_complete_blocks'],
            'observed_stop_s':prefix_evidence['observed_stop_s'],'requested_case_stop_s':planned_stop,
            'numerical_completion':False},
        'prefix_evidence':prefix_evidence,'derived_parser_input_evidence':derivative_evidence,
        'prefix_diagnostics':prefix_diagnostics,'dependency_hashes_before':before,
        'dependency_hashes_after':after,'owned_process_checks_after_extraction':processes_after,
        'monitor_source_evidence':{str(path):proof_tool.sha(path) for path in
            [HERE/'measure_afc2009.py',portmap,HERE/'collect_terminal_partial_proof.py',Path(__file__).resolve()]},
        'simulator_started':False,'signals_sent':False,
        'scope':'Failed TimeoutExpired run remains numerically incomplete. Bounded read-only provisional '
            'prefix observations cannot prove full-case completion/PASS, stochastic jitter, PVT or silicon performance.'}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'output':str(output),'observed_stop_s':prefix_evidence['observed_stop_s'],
        'numerical_completion':False,'full_case_pass':None,
        'prefix_engineering_lock_observed':prefix_diagnostics['engineering_lock_observed_within_prefix']}))
    # This exit code means the diagnostic was extracted, never electrical PASS.
    return 0


if __name__=='__main__':
    main()
