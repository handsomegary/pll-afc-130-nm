"""Read-only Stage3 fine-acquisition VDD energy; Python3.6+, no simulator.

Run after root's collector has completed. Source identity and actual raw
artifacts are checked against the existing execution cache. Integrate saved
instantaneous -V(vdd)*I(VDD:p), including interpolated exact endpoints, using
the existing CP integrator. This is a scoped learning metric, not a universal
PLL FoM and not steady-state power multiplied by acquisition time.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile

MAX_RAW_BYTES = 512 * 1024 * 1024
FINE_ENABLE_S = 300.05e-9


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def rows(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ['cases', 'records', 'measurements']:
            if isinstance(value.get(key), list):
                return value[key]
        return [value]
    return []


def load_tools(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root / 'analog'))
    sys.path.insert(0, str(root / 'digital'))
    import measure_cp_units
    import measure_digital_units
    return measure_cp_units, measure_digital_units


def integrate_saved_power(data, begin, end, cp):
    t = data.get('time', [])
    if not (math.isfinite(begin) and math.isfinite(end) and end > begin):
        raise ValueError('Invalid acquisition integration boundaries.')
    if len(t) < 3 or t[0] > begin or t[-1] < end:
        raise ValueError('Clipped saved samples do not bracket both exact endpoints; increase margin.')
    if any(not math.isfinite(x) for x in t) or any(b <= a for a, b in zip(t, t[1:])):
        raise ValueError('Require strictly increasing finite saved times.')
    for signal in ['vdd', 'VDD:p']:
        values = data.get(signal, [])
        if len(values) != len(t) or any(not math.isfinite(x) for x in values):
            raise ValueError('Missing/nonfinite saved waveform ' + signal)
    power = [-v * i for v, i in zip(data['vdd'], data['VDD:p'])]
    energy = cp.integrate(t, power, begin, end)
    if not math.isfinite(energy) or energy <= 0:
        raise ValueError('Acquisition VDD energy is not finite and positive.')
    return dict(energy_J=energy, energy_nJ=energy * 1e9,
                average_acquisition_power_W=energy / (end - begin),
                average_acquisition_power_mW=energy / (end - begin) * 1e3,
                endpoint_power_W=[cp.interpolate(t, power, begin),
                                  cp.interpolate(t, power, end)])


def measure_case(record, project, cp, digital, margin_s, expected_raw):
    if record.get('stage') != 'stage3' or record.get('simulator_state') != 'completed' or record.get('locked') is not True:
        raise ValueError('Require this exact completed, locked physical Stage3 record.')
    case_id = record.get('case_id')
    name = record.get('name')
    if not case_id or not name or not re.fullmatch(r'[A-Za-z0-9_]+', case_id):
        raise ValueError('Missing/invalid exact Stage3 case identity.')
    raw = Path(record.get('raw_file', '')).resolve()
    if not raw.is_file() or raw.name != 'tran.tran.tran':
        raise ValueError('Missing exact collected transient raw file.')
    stage_dir = project / 'results/fullpll/stage3'
    raw.relative_to(stage_dir.resolve())
    cache = stage_dir / (case_id + '.json')
    execution = load(cache)
    if execution.get('case_id') != case_id or execution.get('name') != name:
        raise ValueError('Execution cache differs from selected lock record.')
    if execution.get('state') != 'completed' or execution.get('spectre_rc') != 0:
        raise ValueError('Need actual completed zero-error execution cache.')
    if execution.get('source_files_unchanged_at_completion') is not True or record.get('source_files_unchanged_at_completion') is not True:
        raise ValueError('Missing completion-time source identity verification.')
    artifacts = {Path(x).resolve() for x in execution.get('artifacts', [])}
    if raw.parent not in artifacts or not raw.parent.name.startswith(case_id + '_a'):
        raise ValueError('Raw file does not belong to this exact execution artifact/attempt.')
    bench = Path(execution.get('bench', '')).resolve()
    bench.relative_to((project / 'pll_full').resolve())
    bench_hash = sha(bench)
    if bench not in artifacts or bench_hash != record.get('bench_sha256') or bench_hash != execution.get('bench_sha256'):
        raise ValueError('Current physical bench differs from completed lock source.')
    for key in ['dependencies', 'own_dependency_sha256', 'external_model_dependencies',
                'external_model_set_sha256', 'source_set_sha256']:
        if not record.get(key) or record.get(key) != execution.get(key):
            raise ValueError('Selected lock/execution source identity differs: ' + key)
    dependency_checks = []
    for relative, expected in execution['dependencies'].items():
        path = (project / 'pll_full' / relative).resolve()
        path.relative_to((project / 'pll_full').resolve())
        actual = sha(path)
        if actual != expected:
            raise ValueError('Authored MOS source no longer matches lock record: ' + relative)
        dependency_checks.append(dict(relative_path=relative, sha256=actual))
    # These reviewed Stage3 benches have one 300.0--300.1ns enable ramp.
    active = '\n'.join(line.split('//', 1)[0] for line in bench.read_text(encoding='utf8').splitlines())
    if re.search(r'\bahdl_include\b|\bveriloga\b', active, re.I):
        raise ValueError('Behavioral bench is not the physical fine-loop energy case.')
    if not re.search(r'(?m)^VEN\s+\(enable\s+0\)\s+vsource\s+type=pwl\s+wave=\[0\s+0\s+300n\s+0\s+300\.1n\s+1\.2\]', active):
        raise ValueError('Fine enable source is not the reviewed300.05ns half-rail boundary.')
    end = record.get('lock_time_s')
    if not isinstance(end, (int, float)) or not math.isfinite(end) or end <= FINE_ENABLE_S:
        raise ValueError('Missing valid measured lock time.')
    size = raw.stat().st_size
    if size > MAX_RAW_BYTES:
        raise ValueError('Raw file exceeds512MiB read-only postprocess guard.')
    raw_before = sha(raw)
    expected = expected_raw.get(str(raw)) or record.get('raw_sha256')
    if expected and raw_before != expected:
        raise ValueError('Actual raw SHA256 differs from prior exact-case waveform evidence.')
    # Existing reader streams text and retains only the bounded time slice.
    data = digital.read_psf(raw, FINE_ENABLE_S - margin_s, end + margin_s)
    t = data['time']
    enabled = data.get('enable', [])
    if len(enabled) != len(t) or abs(cp.interpolate(t, enabled, FINE_ENABLE_S) - 0.6) > 1e-5:
        raise ValueError('Saved actual enable waveform does not cross0.6V at300.05ns.')
    metrics = integrate_saved_power(data, FINE_ENABLE_S, end, cp)
    raw_after = sha(raw)
    if raw_before != raw_after or size != raw.stat().st_size:
        raise ValueError('Transient evidence changed during energy extraction.')
    result = dict(name=name, case_id=case_id, state='measured',
        source_measurement_stage='stage3', simulator_state='completed', locked=True,
        bench=str(bench), bench_sha256=bench_hash, execution_cache=str(cache),
        execution_cache_sha256=sha(cache), raw_file=str(raw), raw_sha256=raw_before,
        raw_bytes=size, prior_raw_sha256=expected,
        prior_raw_hash_verified=bool(expected), raw_artifact_link_verified=True,
        raw_files_unchanged_during_extraction=True,
        own_dependency_checks=dependency_checks,
        own_dependency_sha256=record['own_dependency_sha256'],
        external_model_set_sha256=record['external_model_set_sha256'],
        external_model_count=len(record['external_model_dependencies']),
        simulator_engine_requested=record.get('simulator_engine'),
        simulator_threads_requested=record.get('simulator_threads'),
        integration_window_s=[FINE_ENABLE_S, end],
        fine_enable_definition='Saved enable crosses0.6V, halfway through reviewed300.0--300.1ns ramp.',
        measured_lock_time_s=end, acquisition_duration_s=end-FINE_ENABLE_S,
        saved_sample_window_s=[t[0], t[-1]], saved_samples=len(t),
        streaming_clip_margin_s=margin_s, raw_limit_bytes=MAX_RAW_BYTES,
        integration_method='Existing measure_cp_units.integrate on saved instantaneous -V(vdd)*I(VDD:p); trapezoids with interpolated exact endpoints.',
        scope='Fine-enable-to-engineering-lock VDD energy only, fixed coarse code; includes all MOS fine-loop blocks and existing ideal bias-source consumption already drawn from VDD. Excludes pre-enable startup, AFC, external reference-clock generator, physical reference/bias-generator implementation and PEX. Not a universal FoM; no branch powers added twice.',
        saved_waveform_accuracy_limit='Energy is from10ps-strobe saved waveforms, not internal adaptive solver points; endpoint interpolation and matched1ps/2ps comparison do not establish all numerical/physical convergence.')
    result.update(metrics)
    return result


def selftest(tools):
    cp, digital = load_tools(tools)
    # A changing power ramp and both non-grid boundaries exercise streaming
    # clipping and exact interpolation; final/steady power timesdt would differ.
    # Keep this owned temporary fixture inside the writable task workspace.
    fixture_root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='lock-energy-fixture-', dir=str(fixture_root)) as folder:
        raw = Path(folder) / 'fixture.tran'
        lines = ['VALUE']
        for ns, mw in [(0, 1), (5, 1.5), (10, 2), (15, 2.5), (20, 3), (25, 3.5), (30, 4)]:
            lines += ['"time" {:.17g}'.format(ns*1e-9), '"vdd" 1', '"VDD:p" {:.17g}'.format(-mw*1e-3)]
        lines += ['END']
        raw.write_text('\n'.join(lines)+'\n', encoding='utf8')
        data = digital.read_psf(raw, 2.5e-9, 29.5e-9)
        measured = integrate_saved_power(data, 7.5e-9, 24.5e-9, cp)
        if not math.isclose(measured['energy_J'], 44.2e-12, rel_tol=1e-12, abs_tol=1e-25):
            raise AssertionError('Exact-boundary ramp integration differs from analytic44.2pJ.')
        try:
            integrate_saved_power(data, 0, 24.5e-9, cp)
        except ValueError:
            pass
        else:
            raise AssertionError('Missing endpoint bracket was not rejected.')
    return dict(selftest_passed=True, analytic_energy_pJ=44.2,
                measured_energy_pJ=measured['energy_J']*1e12,
                simulator_started=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--measurements-json')
    ap.add_argument('--project-root', type=Path)
    ap.add_argument('--tools-root', type=Path)
    ap.add_argument('--raw-evidence-json', action='append', default=[])
    ap.add_argument('--case-name', action='append', default=[])
    ap.add_argument('--clip-margin-ps', type=int, choices=[5, 10], default=10)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    here = Path(__file__).resolve().parent
    tools = args.tools_root or (here/'pll_full')
    if args.selftest:
        print(json.dumps(selftest(tools), indent=2))
        return 0
    if not args.measurements_json or not args.out:
        ap.error('Need --measurements-json and separate --out, or --selftest.')
    measurement_path = Path(args.measurements_json).resolve()
    measurement_hash = sha(measurement_path)
    all_records = rows(load(measurement_path))
    candidates = [r for r in all_records if r.get('stage')=='stage3' and
                  (not args.case_name or r.get('name') in args.case_name)]
    expected_raw = {}
    for path in args.raw_evidence_json:
        for item in rows(load(path)):
            if item.get('raw_file') and item.get('raw_sha256'):
                key = str(Path(item['raw_file']).resolve())
                if key in expected_raw and expected_raw[key] != item['raw_sha256']:
                    raise ValueError('Conflicting prior raw evidence hashes.')
                expected_raw[key] = item['raw_sha256']
    measured = []
    excluded = []
    seen = set()
    for record in sorted(candidates, key=lambda r:r.get('name','')):
        if record.get('case_id') in seen:
            continue
        seen.add(record.get('case_id'))
        if record.get('simulator_state')!='completed' or record.get('locked') is not True:
            excluded.append(dict(name=record.get('name'), case_id=record.get('case_id'),
                reason='Not completed and locked; no energy value inferred.'))
            continue
        raw = Path(record.get('raw_file','')).resolve()
        project = args.project_root.resolve() if args.project_root else raw.parents[4]
        tools = args.tools_root or (here/'pll_full' if (here/'pll_full').is_dir() else project/'pll_full')
        cp, digital = load_tools(tools)
        try:
            measured.append(measure_case(record, project, cp, digital, args.clip_margin_ps*1e-12, expected_raw))
        except Exception as error:
            excluded.append(dict(name=record.get('name'), case_id=record.get('case_id'), reason=repr(error)))
    if sha(measurement_path) != measurement_hash:
        raise ValueError('Selected completed-lock measurements changed during extraction.')
    out = dict(version='fine-lock-energy-20261007-v1', simulator_started=False,
        source_measurements_json=str(measurement_path), source_measurements_sha256=measurement_hash,
        measured_case_count=len(measured), cases=measured, excluded_or_pending=excluded,
        metric_definition='E_fine_acq=integral[-V(vdd)*I(VDD:p)]dt from300.05ns enable half-rail to exact measured engineering lock_time_s; averageP=E/duration.',
        overall_scope='Read-only acquisition-energy learning metric. Fine-loop2ps/1ps records remain separate; no universalFoM, all-PVT, random-noise or whole-chip energy conclusion.')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, allow_nan=False)+'\n', encoding='utf8')
    print(json.dumps(dict(output=str(args.out.resolve()), measured_cases=len(measured),
                         excluded_or_pending=len(excluded), simulator_started=False)))
    return 0 if measured and not excluded else 2


if __name__=='__main__':
    sys.exit(main())
