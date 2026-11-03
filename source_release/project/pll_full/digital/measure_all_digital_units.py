"""Read-only measurements of the coordinated runner's five digital units.
Writes only the explicit output JSON, never starts/modifies/stops simulation.
Python 3.6+, stdlib. --cases results/fullpll/units/all_cases.json --output ...
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import measure_digital_units as measure

SPEC = {
    'tb_div32_va': ('divider_va', 20e-9, 95e-9),
    'tb_afc_va': ('afc_va', 1.8e-6, 2.05e-6),
    'tb_pfd_mos': ('pfd', 20e-9, 95e-9),
    'tb_div32_cmos': ('divider', 20e-9, 95e-9),
    'tb_receiver_div32': ('receiver', 20e-9, 95e-9),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    manifest = Path(args.cases).resolve()
    items = json.loads(manifest.read_text())
    if not isinstance(items, list):
        raise ValueError('Expected a list of runner cases')
    latest = {}
    for item in items:
        name = item.get('name')
        if item.get('folder') == 'digital' and name in SPEC:
            key = (item.get('finished_unix', item.get('started_unix', 0)), item.get('attempt', 0))
            old = latest.get(name)
            old_key = (old.get('finished_unix', old.get('started_unix', 0)), old.get('attempt', 0)) if old else (-1, -1)
            if key >= old_key:
                latest[name] = item
    results = []
    for item in latest.values():
        name = item.get('name')
        if item.get('folder') != 'digital' or name not in SPEC:
            continue
        record = {'name': name, 'case_id': item.get('case_id'),
                  'analysis_state': item.get('state'),
                  'spectre_rc': item.get('spectre_rc'),
                  'source_set_sha256': item.get('source_set_sha256'),
                  'bench_sha256': item.get('bench_sha256'), 'valid': False}
        if item.get('state') != 'completed' or item.get('spectre_rc') != 0:
            record['reason'] = 'Simulator did not complete successfully'
            record['analysis_error'] = item.get('error')
            results.append(record)
            continue
        try:
            candidates = [Path(value) for value in item.get('artifacts', [])
                          if str(value).endswith('.raw')]
            if len(candidates) != 1:
                raise ValueError('Expected one raw directory')
            raw = candidates[0].resolve()
            raw.relative_to(manifest.parent)
            path = raw/'tran.tran.tran'
            if not path.is_file():
                raise ValueError('Missing transient raw file')
            if path.stat().st_size > 128*1024*1024:
                raise ValueError('Refusing oversized unit waveform >128MiB')
            kind, begin, end = SPEC[name]
            result = measure.measure(measure.read_psf(path,begin,end), kind, begin, end)
            record.update(result)
            record.update(raw_file=str(path), raw_sha256=measure.file_sha256(path))
        except Exception as error:
            record['reason'] = repr(error)
        results.append(record)
    observed = {item['name'] for item in results}
    missing = sorted(set(SPEC)-observed)
    result = {'scope': 'Digital unit functional/pre-layout checks only; not full transistor PLL or noise/FoM validation',
              'cases_manifest': str(manifest),
              'cases_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
              'all_five_present': not missing, 'missing_cases': missing,
              'electrical_pass': not missing and all(item['valid'] for item in results),
              'pass_count': sum(bool(item['valid']) for item in results),
              'case_count': len(results), 'cases': results}
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'pass_count': result['pass_count'], 'case_count': len(results),
                      'missing': missing, 'electrical_pass': result['electrical_pass']}))
    return 0 if result['electrical_pass'] else 2


if __name__ == '__main__':
    sys.exit(main())
