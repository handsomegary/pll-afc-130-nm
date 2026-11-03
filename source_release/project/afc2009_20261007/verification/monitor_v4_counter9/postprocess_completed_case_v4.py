"""Read-only source-bound extraction for exactly one completed owned case."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


REVISION_MAP={
    'r0':('physical_portmap_proposed.json','4b0874902106b01e21f2498b28336dcd5f01bfa88c8de0f41f57354bbd761dde'),
    'r1':('physical_portmap_r1.json','12044e0dc052c06682a3372f17c0b8612d637954af88e0d8662cf1d8c0f8f6b8'),
    'r2':('physical_portmap_r2.json','45654975e7b53873559fd157955c1d8a922f40550fea81687dfd675fe9de4cc0'),
}


def select_revision(execution):
    specification=execution.get('specification',{})
    revision=specification.get('revision')
    afc_dependencies=[(path,row) for path,row in execution.get('own_dependencies',{}).items()
        if Path(path).name=='afc2009_mos.scs']
    if len(afc_dependencies)!=1:
        raise ValueError('Execution must bind exactly one owned AFC MOS source.')
    afc_path,afc_record=afc_dependencies[0]
    actual_sha=afc_record.get('sha256')
    resolution='explicit_execution_revision'
    if revision is None:
        candidates=[key for key,(_map,source) in REVISION_MAP.items() if source==actual_sha]
        if len(candidates)!=1:
            raise ValueError('Legacy execution has no uniquely recognized AFC source SHA.')
        revision=candidates[0]
        resolution='legacy_revision_inferred_from_exact_owned_AFC_source_SHA'
    if revision not in REVISION_MAP:
        raise ValueError('Unsupported explicit revision; allowed r0/r1/r2 only.')
    map_name,expected_sha=REVISION_MAP[revision]
    if actual_sha!=expected_sha:
        raise ValueError('Revision and owned AFC source SHA disagree.')
    declared_sha=specification.get('mos_source_sha256')
    if declared_sha is not None and declared_sha!=expected_sha:
        raise ValueError('Specification AFC source SHA disagrees with revision.')
    if sha(afc_path)!=expected_sha:
        raise ValueError('AFC source changed since completed execution.')
    return revision,map_name,dict(revision=revision,resolution=resolution,
        source_path=afc_path,source_sha256=expected_sha,source_unchanged_after_completion=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--kind', choices=['unit','diagnostic','pll'], required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('OutputExists: preserve original measurements and select a new v4 output filename')
    here = Path(__file__).resolve().parent
    verification = here
    sys.path.insert(0,str(verification))
    import measure_afc2009 as m
    execution_sha_before=sha(args.execution)
    execution = json.loads(args.execution.read_text())
    if sha(args.execution)!=execution_sha_before:
        raise ValueError('Execution cache changed during initial read.')
    if execution['state'] != 'completed' or execution['spectre_rc'] != 0:
        raise ValueError('Casehasnotcompleted')
    if not execution['source_models_unchanged_at_completion']:
        raise ValueError('Circuit/modelchanged')
    bench = Path(execution['bench'])
    if sha(bench) != execution['bench_sha256']:
        raise ValueError('Benchchangedafterrun')
    raw = Path(execution['raw'])/'tran.tran.tran'
    revision,map_name,revision_evidence=select_revision(execution)
    portmap=verification/map_name
    if args.kind in ['unit','diagnostic']:
        import measure_afc2009_unit as u
        fixture = execution['specification'].get('fixture_name') or ('afc_unit_near100_phase_high' if args.kind=='diagnostic' else execution['name'])
        result = u.measure_unit(raw,fixture,bench,portmap=portmap,diagnostic_only=args.kind=='diagnostic')
        result['fixture_name'] = result['name']
        result['name'] = execution['name']
        result['simulator_electrical_pass'] = result.get('short_diagnostic_pass') if args.kind=='diagnostic' else result['unit_functional_pass']
    else:
        config = json.loads(json.dumps(m.DEFAULT_CONFIG))
        config.update(json.loads(portmap.read_text()))
        # Additional saved debug signal used only for separate counter-credit
        # diagnostics; immutable portmap and circuit/bench files stay unchanged.
        if revision in ['r1','r2']:
            config['digitals']['reference_counter_reset']='XAFC.reference_count_rst'
        result = m.measure(raw,config,256)
        result['name'] = execution['name']
        result['bench_evidence'] = dict(bench=str(bench),sha256=sha(bench))
        result['simulator_electrical_pass'] = result['afc_success']
    if sha(args.execution)!=execution_sha_before:
        raise ValueError('Execution cache changed during raw extraction.')
    if sha(bench)!=execution['bench_sha256']:
        raise ValueError('Bench changed during raw extraction.')
    if sha(revision_evidence['source_path'])!=revision_evidence['source_sha256']:
        raise ValueError('Owned AFC source changed during raw extraction.')
    result['execution_evidence'] = dict(path=str(args.execution.resolve()),sha256=execution_sha_before,
        bench_matches=True,source_models_unchanged_at_completion=True)
    result['monitor_revision_binding']=revision_evidence
    result['monitor_source_evidence'] = {str(path):sha(path) for path in
        [verification/'measure_afc2009.py',verification/'measure_afc2009_unit.py',
         portmap,Path(__file__).resolve()]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(name=result['name'],output=str(args.output.resolve()),
        electrical_pass=result['simulator_electrical_pass'],
        violations=result.get('violations'),locked=result.get('locked'))))
    return 0 if result['simulator_electrical_pass'] else 2


if __name__ == '__main__':
    sys.exit(main())
