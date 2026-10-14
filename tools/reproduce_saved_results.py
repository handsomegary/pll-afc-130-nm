"""Export hash-verified historical PLL ledgers and compact traces, without a simulator."""
import argparse
import csv
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outdir', type=Path, default=ROOT / 'runs' / 'saved-results')
    args = parser.parse_args()
    verified = subprocess.run([sys.executable, str(ROOT / 'tools' / 'verify_repository.py')],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
    if verified.returncode:
        raise SystemExit(verified.stderr or verified.stdout)
    summary = json.loads((ROOT / 'results' / 'nominal_tt.json').read_text(encoding='utf-8'))
    traces = {}
    for name in ('afc_on', 'afc_off'):
        arrays = json.loads((ROOT / 'results' / (name + '_trace.json')).read_text(encoding='utf-8'))['arrays']
        size = len(arrays['time_us'])
        if size < 2 or any(len(values) != size for values in arrays.values()):
            raise SystemExit('Inconsistent compact trace: ' + name)
        if not all((value is None and name == 'frequency_GHz') or
                   (isinstance(value, (int, float)) and math.isfinite(value))
                   for name, values in arrays.items() for value in values):
            raise SystemExit('Nonfinite compact trace: ' + name)
        if any(b <= a for a, b in zip(arrays['time_us'], arrays['time_us'][1:])):
            raise SystemExit('Unordered compact trace: ' + name)
        traces[name] = arrays
    target = args.outdir.resolve()
    # Preserve publication sources even when an output path was mistyped.
    relative = None
    try:
        relative = target.relative_to(ROOT)
    except ValueError:
        pass
    if relative is not None and (not relative.parts or relative.parts[0] != 'runs'):
        parser.error('Outputs inside the repository must be under the ignored runs/ directory.')
    target.mkdir(parents=True, exist_ok=True)
    for name, arrays in traces.items():
        with (target / (name + '_compact_trace.csv')).open('w', encoding='ascii', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(arrays)
            writer.writerows(zip(*arrays.values()))
    result = {'status': 'verified_historical_evidence_export',
              'simulator_started': False, 'new_transistor_simulation': False,
              'compact_trace_rows': {name: len(arrays['time_us']) for name, arrays in traces.items()},
              'missing_frequency_samples': {name: arrays['frequency_GHz'].count(None) for name, arrays in traces.items()},
              'recorded_results': summary,
              'scope': 'Original measurement ledgers and downsampled traces, not a remeasurement from full raw waveforms. Missing frequency samples remain empty CSV cells.'}
    (target / 'summary.json').write_text(json.dumps(result, indent=2) + '\n', encoding='ascii')
    print(json.dumps({'status': result['status'], 'compact_trace_rows': result['compact_trace_rows'],
                      'selected_code': summary['afc_on']['code'],
                      'recorded_final_frequency_Hz': summary['afc_on']['tail_frequency_Hz'],
                      'simulator_started': False}, indent=2))


if __name__ == '__main__':
    main()
