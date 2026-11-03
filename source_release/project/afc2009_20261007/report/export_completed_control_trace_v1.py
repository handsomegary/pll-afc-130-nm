"""Immutable completed-only AFC-off trace export; Python3.6+, stdlib.

Read completed-control-v2 JSON, exact execution/raw/bench/map/dependency hashes.
Never run Spectre, write a guest circuit, or invent AFC Done/FineEnable signals.
Use the byte-frozen control reader and unchanged measured-VCO frequency helper.
The only write is a NEW UTF-8 trace artifact; existing outputs are refused.
"""
from __future__ import print_function
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

READER_SHA = 'b2898c42d28918f00b095e763427f4bacae7cb08e2b6c4ac4d551b328c214d10'
MAP_SHA = 'ea29260e5ec535556ee95c58e6d688878bff49bc831928ac30b0a8145b9abe87'
COMPLETED_V2_SHA = '00a210dea69f2df94e39ec9aedc25c27330d5d24c5c6019a97b54fb0abb7359c'
FREQUENCY_HELPER_SHA = '67b44f4db3dab81703a245be8e48cca0961a47abab2286c4a28447c669e74429'
CONTROL_NAME = 'pll_afc_off_code16_ctrl600_ref10000_4p_6500n_v1'
CONTROL_BENCH_SHA = '508ff6a196f23da3c2f5a9f7f6cec2127b42bce8ac52cf42e44d42e8ffb13f0f'
CONTROL_MANIFEST_SHA = '9594c75d3c6d72f0ae7a1aa28766deddb2fa572c343c82c9616f7f262b35ab36'
RAW_LIMIT_BYTES = 512 * 1024 * 1024


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def load_algorithms(control_dir, helper_path):
    reader_path = control_dir / 'frozen_reader_v1.py'
    if sha(reader_path) != READER_SHA or sha(helper_path) != FREQUENCY_HELPER_SHA:
        raise ValueError('Frozen reader/frequency-helper SHA mismatch')
    reader = module(reader_path, 'control_trace_frozen_reader_v1')
    # The unchanged helper imports this reader under its original module name.
    # Bind it during module import, then restore the caller environment; the
    # returned helper retains the exact frozen reader object in its own globals.
    old = sys.modules.get('measure_afc2009')
    sys.modules['measure_afc2009'] = reader
    try:
        helper = module(helper_path, 'control_trace_frequency_helper_v1')
    finally:
        if old is None:
            sys.modules.pop('measure_afc2009', None)
        else:
            sys.modules['measure_afc2009'] = old
    if helper.m is not reader:
        raise ValueError('Frequency helper is not bound to frozen control reader')
    return reader, helper


def monitor_hash(measurement, basename):
    matches = [value for path, value in (measurement.get('monitor_source_evidence') or {}).items()
               if str(path).replace('\\', '/').rsplit('/', 1)[-1] == basename]
    if len(matches) != 1:
        raise ValueError('Missing/ambiguous immutable monitor binding: ' + basename)
    return matches[0]


def verify_dependencies(execution):
    result = []
    for kind in ['own_dependencies', 'model_dependencies']:
        dependencies = execution.get(kind)
        if not isinstance(dependencies, dict) or not dependencies:
            raise ValueError('Missing execution dependency inventory: ' + kind)
        for path, record in dependencies.items():
            expected = record.get('sha256')
            if not expected or not Path(path).is_file() or sha(path) != expected:
                raise ValueError('Changed/missing execution dependency: ' + path)
            result.append({'kind': kind, 'path': path, 'sha256': expected})
    return result


def time_grid(t, codes, digital, frequency, max_points):
    """Same bounded landmark/uniform grid strategy, using real enable/reset."""
    start, end = t[0], t[-1]
    saved_step = max(b - a for a, b in zip(t, t[1:]))
    delta = max(saved_step, 1e-12)
    landmarks = {start, end}
    for time, value in codes:
        for shift in [-delta, 0, delta]:
            if start <= time + shift <= end:
                landmarks.add(time + shift)
    for key in ['enable', 'pfd_reset']:
        for time, value in digital[key]['levels']:
            for shift in [-delta, 0, delta]:
                if start <= time + shift <= end:
                    landmarks.add(time + shift)
    for window in frequency.get('windows', []):
        landmarks.add(window['center_us'] * 1e-6)
    if len(landmarks) > max_points:
        raise ValueError('Observed control/window landmarks exceed report cap')
    remaining = max_points - len(landmarks)
    points = sorted(landmarks | {start + (end - start) * (i + 1) / (remaining + 1)
                               for i in range(remaining)})
    if len(points) > max_points:
        raise AssertionError('Bounded trace grid exceeded cap')
    return points, {'maximum_saved_sample_spacing_s': saved_step,
                    'landmark_count': len(landmarks), 'selected_report_points': len(points),
                    'max_report_points': max_points,
                    'selection': 'Actual enable/reset/code landmarks and measured frequency-window centers; '
                                 'remaining points uniformly fill saved coverage. Analog interpolation only.'}


def export(measurement_json, execution_json, control_dir, frequency_helper,
           raw=None, bench=None, manifest=None, max_points=1000):
    if not 100 <= max_points <= 1000:
        raise ValueError('Report point cap must be100..1000')
    measurement_json = Path(measurement_json).resolve()
    execution_json = Path(execution_json).resolve()
    control_dir = Path(control_dir).resolve()
    frequency_helper = Path(frequency_helper).resolve()
    manifest = Path(manifest).resolve() if manifest else control_dir / 'benches/control_manifest_v1.json'
    inputs = [measurement_json, execution_json, manifest,
              control_dir / 'frozen_reader_v1.py', control_dir / 'signal_map_v1.json',
              control_dir / 'postprocess_completed_control_v2.py', frequency_helper]
    before = {str(path): sha(path) for path in inputs}
    if before[str(manifest)] != CONTROL_MANIFEST_SHA:
        raise ValueError('Exact immutable control manifest SHA required')
    measurement, execution = read(measurement_json), read(execution_json)
    records = read(manifest)
    if len(records) != 1 or records[0].get('name') != CONTROL_NAME:
        raise ValueError('Exactly one immutable fixed-code16 AFC-off manifest required')
    record = records[0]
    if execution.get('state') != 'completed' or execution.get('spectre_rc') != 0:
        raise ValueError('Completed rc0 execution required; partial/failed cache refused')
    if execution.get('source_models_unchanged_at_completion') is not True:
        raise ValueError('Execution circuit/model preservation unproven')
    if measurement.get('name') != CONTROL_NAME or execution.get('name') != CONTROL_NAME:
        raise ValueError('Exact control name binding required')
    if measurement.get('status') != 'measured' or measurement.get('violations'):
        raise ValueError('Missing/inconsistent completed control measurement')
    if (measurement.get('scope') or {}).get('afc_present') is not False:
        raise ValueError('Expected typed AFC-off measurement, not AFC-on result')
    execution_evidence = measurement.get('execution_evidence') or {}
    if (execution_evidence.get('sha256') != before[str(execution_json)] or
            any(execution_evidence.get(key) is not True for key in
                ['numerical_completion', 'bench_matches', 'source_models_unchanged_at_completion',
                 'all_dependency_hashes_match_at_extraction']) or execution_evidence.get('spectre_rc') != 0):
        raise ValueError('Exact completed-control-v2 execution binding required')
    fixed = [(control_dir / 'frozen_reader_v1.py', READER_SHA),
             (control_dir / 'signal_map_v1.json', MAP_SHA),
             (control_dir / 'postprocess_completed_control_v2.py', COMPLETED_V2_SHA)]
    for path, expected in fixed:
        if sha(path) != expected or monitor_hash(measurement, path.name) != expected:
            raise ValueError('Reader/map/completed-v2 monitor binding changed: ' + path.name)
    if measurement.get('frozen_reader_sha256') != READER_SHA or record.get('frozen_reader_sha256') != READER_SHA:
        raise ValueError('Exact frozen control-reader identity required')
    if monitor_hash(measurement, manifest.name) != before[str(manifest)]:
        raise ValueError('Manifest differs from completed measurement source capsule')
    bench = Path(bench).resolve() if bench else Path(execution['bench']).resolve()
    bench_sha = sha(bench)
    if not (bench_sha == CONTROL_BENCH_SHA == record.get('bench_sha256') == measurement.get('bench_sha256') == execution.get('bench_sha256')):
        raise ValueError('Exact measured/executed/manifest/local bench SHA binding required')
    if record.get('fixed_code') != 16:
        raise ValueError('Only the immutable fixed-code16 control is supported')
    before[str(bench)] = bench_sha
    dependencies = verify_dependencies(execution)
    provenance = measurement.get('provenance') or {}
    expected_raw = provenance.get('raw_file')
    raw_sha = provenance.get('raw_sha256')
    if not expected_raw or not raw_sha:
        raise ValueError('Measurement lacks exact saved raw evidence')
    original_parent = expected_raw.replace('\\', '/').rsplit('/', 1)[0]
    if str(execution.get('raw', '')).replace('\\', '/') != original_parent:
        raise ValueError('Execution raw artifact differs from measured waveform parent')
    raw = Path(raw).resolve() if raw else Path(expected_raw).resolve()
    if not raw.is_file() or raw.stat().st_size > RAW_LIMIT_BYTES:
        raise ValueError('Missing raw or raw exceeds512MiB guard')
    if sha(raw) != raw_sha or raw.stat().st_size != provenance.get('raw_bytes'):
        raise ValueError('Saved raw SHA/bytes differ from completed measurement')
    reader, helper = load_algorithms(control_dir, frequency_helper)
    config = copy.deepcopy(read(control_dir / 'signal_map_v1.json'))
    config['analogs'] = {key: config['analogs'][key] for key in ['out0', 'out180', 'ctrl']}
    # The off bench's real "enable" marker is not an AFC FineEnable output.
    config['digitals'] = {'enable': config['digitals']['fine_enable'],
                          'pfd_reset': config['digitals']['pfd_reset']}
    config['words'] = {'code': config['words']['code']}
    data, digital, words, evidence = reader.read_saved_vectors(raw, config, 256)
    t, code = data['time'], words.get('code') or []
    if evidence['raw_sha256'] != raw_sha or evidence['saved_samples'] != provenance.get('saved_samples'):
        raise ValueError('Extracted raw SHA/sample count differs from completed measurement')
    if any(key not in data for key in ['out0', 'out180', 'ctrl']):
        raise ValueError('Missing actual VCO or Vctrl waveform')
    if not code or any(value != 16 for time, value in code):
        raise ValueError('Saved fixed code is not continuously16')
    if code != measurement.get('code_word_ledger'):
        raise ValueError('Actual code ledger differs from completed measurement')
    interval = measurement.get('observation_interval_s') or []
    if len(interval) != 2 or abs(t[0] - interval[0]) > 1e-15 or abs(t[-1] - interval[-1]) > 1e-15:
        raise ValueError('Saved observation interval differs from completed measurement')
    if abs(t[-1] - record['duration_s']) > 1e-10:
        raise ValueError('Actual control raw does not reach declared completed stop')
    if not digital['enable']['rising'] or not digital['pfd_reset']['falling']:
        raise ValueError('Actual enable/reset-release edge missing')
    if (abs(digital['enable']['rising'][0] - measurement['fine_enable_time_s']) > 1e-15 or
            abs(digital['pfd_reset']['falling'][0] - measurement['pfd_reset_release_time_s']) > 1e-15):
        raise ValueError('Actual enable/reset event differs from completed measurement')
    frequency = helper.actual_frequency_windows(data)
    points, selection = time_grid(t, code, digital, frequency, max_points)
    arrays = {'time_us': [point * 1e6 for point in points],
              'code': [reader.event_value(code, point) for point in points],
              'ctrl_V': [reader.interpolate(t, data['ctrl'], point) for point in points],
              'frequency_GHz': [helper.plot_frequency(frequency, point * 1e6) for point in points]}
    for key in ['enable', 'pfd_reset']:
        arrays[key] = [reader.event_value(digital[key]['levels'], point) for point in points]
    for path, expected in before.items():
        if sha(path) != expected:
            raise ValueError('Input/source changed during export: ' + path)
    verify_dependencies(execution)
    return {'version': 'completed-control-trace-v1', 'name': CONTROL_NAME,
            'comparison_role': 'AFC-off fixed-code16 actual saved trace',
            'arrays': arrays, 'panels': [
                {'title': 'code16', 'key': 'code', 'lo': 0, 'hi': 31, 'step': True},
                {'title': 'Vctrl V', 'key': 'ctrl_V'},
                {'title': 'VCO GHz (100ns)', 'key': 'frequency_GHz'},
                {'title': 'enable / PFD reset', 'key': 'enable', 'overlay': 'pfd_reset',
                 'legend': 'blue enable; orange PFD reset', 'lo': 0, 'hi': 1.15, 'step': True}],
            'frequency_windows': frequency, 'plot_selection': selection,
            'observed_code_transitions': code,
            'source_evidence': dict(evidence, measurement_json=str(measurement_json),
                measurement_sha256=before[str(measurement_json)],
                execution_json=str(execution_json), execution_sha256=before[str(execution_json)],
                bench_json=str(bench), bench_sha256=bench_sha,
                portmap_json=str(control_dir / 'signal_map_v1.json'), portmap_sha256=MAP_SHA,
                exporter_sha256=sha(Path(__file__)), frozen_reader_sha256=READER_SHA,
                frequency_helper_sha256=FREQUENCY_HELPER_SHA,
                completed_control_v2_sha256=COMPLETED_V2_SHA,
                input_hashes_verified_before_and_after=True),
            'completed_execution_evidence': {'state': 'completed', 'spectre_rc': 0,
                'source_models_unchanged_at_completion': True,
                'dependency_hashes_verified_before_and_after': dependencies},
            'execution_completion_proven_in_this_export': True,
            'simulator_started': False, 'physical_noise_jitter_s': None,
            'scope': 'AFC-off saved code 16, Vctrl, differential VCO edge frequency and enable/reset. '
                     'The bench has no AFC DONE or FineEnable. Frequency uses 100 ns windows at 50 ns intervals. '
                     'Interpolation between window centers is for plotting only. '
                     'AFC-on and AFC-off loading differ.'}


def save_new(output, result):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also closes the existence-check/write race.
    with output.open('xb') as handle:
        handle.write((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def main():
    here = Path(__file__).resolve().parent
    default_control = here if (here / 'frozen_reader_v1.py').exists() else here.parent / 'integration/counterfactual_off'
    default_helper = default_control.parents[1] / 'verification/export_afc2009_traces.py'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measurement-json', required=True, type=Path)
    parser.add_argument('--execution-json', required=True, type=Path)
    parser.add_argument('--control-dir', type=Path, default=default_control)
    parser.add_argument('--frequency-helper', type=Path, default=default_helper)
    parser.add_argument('--raw', type=Path)
    parser.add_argument('--bench', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--max-points', type=int, default=1000)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output exists; immutable trace must use a NEW filename')
    result = export(args.measurement_json, args.execution_json, args.control_dir,
                    args.frequency_helper, args.raw, args.bench, args.manifest, args.max_points)
    save_new(args.output, result)
    print(json.dumps({'output': str(args.output.resolve()), 'name': result['name'],
                      'points': len(result['arrays']['time_us']),
                      'actual_frequency_windows': len(result['frequency_windows']['windows']),
                      'completed_rc0_bound': True, 'no_AFC_signals_created': True,
                      'simulator_started': False}))


if __name__ == '__main__':
    main()
