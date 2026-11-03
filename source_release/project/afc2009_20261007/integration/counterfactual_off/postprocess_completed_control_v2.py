"""Bind the unchanged AFC-off reader to one completed owned execution.

No simulator launch or process signal; Python3.6+ and standard library only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('OutputExists: preserve prior evidence')
    here = Path(__file__).resolve().parent
    execution = json.loads(args.execution.read_text())
    if execution.get('state') != 'completed' or execution.get('spectre_rc') != 0:
        raise ValueError('Numerical completion with rc0 required')
    if execution.get('source_models_unchanged_at_completion') is not True:
        raise ValueError('Circuit or model changed during execution')
    for path, record in list(execution['own_dependencies'].items()) + list(execution['model_dependencies'].items()):
        if sha(path) != record['sha256']:
            raise ValueError('Dependency changed after execution: '+path)
    records = json.loads(args.manifest.read_text())
    if len(records) != 1:
        raise ValueError('Exactly one immutable AFC-off control required')
    record = records[0]
    bench = Path(execution['bench'])
    if execution['name'] != record['name'] or execution['bench_sha256'] != record['bench_sha256'] or sha(bench) != record['bench_sha256']:
        raise ValueError('Exact execution and control bench binding required')
    sys.path.insert(0, str(here))
    import measure_counterfactual_v1 as reader
    config = json.loads((here/'signal_map_v1.json').read_text())
    result = reader.measure(Path(execution['raw'])/'tran.tran.tran', bench, record, config, 256, here)
    stop = result['observation_interval_s'][-1]
    if abs(stop-6.5e-6) > 1e-10:
        raise ValueError('Completed control raw does not reach its declared6.5us stop')
    result['execution_evidence'] = {
        'path':str(args.execution.resolve()), 'sha256':sha(args.execution),
        'numerical_completion':True, 'spectre_rc':0, 'bench_matches':True,
        'source_models_unchanged_at_completion':True,
        'all_dependency_hashes_match_at_extraction':True}
    result['monitor_source_evidence'] = {str(p.resolve()):sha(p) for p in
        [Path(__file__), here/'measure_counterfactual_v1.py',
         here/'frozen_reader_v1.py', here/'signal_map_v1.json', args.manifest]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'name':result['name'],'numerical_completion':True,
        'locked':result['loop']['locked'],'final_frequency_Hz':result['loop'].get('final_frequency_Hz'),
        'violations':result['violations'],'output':str(args.output.resolve())}))
    return 0 if not result['violations'] else 2


if __name__ == '__main__':
    sys.exit(main())
