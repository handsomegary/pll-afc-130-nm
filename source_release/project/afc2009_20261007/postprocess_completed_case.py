"""Read-only source-bound extraction for exactly one completed owned case."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--kind', choices=['unit','diagnostic','pll'], required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    verification = here/'verification'
    sys.path.insert(0,str(verification))
    import measure_afc2009 as m
    execution = json.loads(args.execution.read_text())
    if execution['state'] != 'completed' or execution['spectre_rc'] != 0:
        raise ValueError('Casehasnotcompleted')
    if not execution['source_models_unchanged_at_completion']:
        raise ValueError('Circuit/modelchanged')
    bench = Path(execution['bench'])
    if sha(bench) != execution['bench_sha256']:
        raise ValueError('Benchchangedafterrun')
    raw = Path(execution['raw'])/'tran.tran.tran'
    revision = execution.get('specification',{}).get('revision')
    portmap = verification/('physical_portmap_r1.json' if revision in ['r1','r2','r3'] else 'physical_portmap_proposed.json')
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
        result = m.measure(raw,config,256)
        result['name'] = execution['name']
        result['bench_evidence'] = dict(bench=str(bench),sha256=sha(bench))
        result['simulator_electrical_pass'] = result['afc_success']
    result['execution_evidence'] = dict(path=str(args.execution.resolve()),sha256=sha(args.execution),
        bench_matches=True,source_models_unchanged_at_completion=True)
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
