"""Eight bounded, resumable startup diagnostics; no GUI, upload or auto-launch.

Run beside run_background_phase3.py in the reviewed VM project. This is an
externally ramped ideal-reference test, not physical/noise startup signoff.
Only this driver's live Spectre process group can be terminated by its timeout.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import time

import run_background_phase3 as helper

VERSION = 'startup-late-v1'
SCOPE = ('TT/1.2V/25C selected ordinary and mixed-RF VCOs; ideal passives and '
         'externally matched 5ns VDD/control/code/10uA-reference ramp; no IC, '
         '250ns deterministic transient. Not unforced physical/noise startup, '
         'PVT, all-band, loaded or complete-PLL proof.')
SEEDS = {'ordinary': 'phase2_target_l5_b11_i5.scs',
         'rf': 'rfrefine_d0_c26_v835938_target5.scs'}
MODES = [('early_1u', 7, '1u'), ('late_1u', 200, '1u'),
         ('late_100u', 200, '100u'), ('no_kick', None, None)]
WINDOWS = {'before_late_kick': (170e-9, 190e-9), 'final': (220e-9, 245e-9)}


def tail_names(model):
    devices = ['MTAILMAIN:d', 'MTAILREGEN:d'] if model == 'ordinary' else [
        'XTAILMAIN.main:d', 'XTAILREGEN.main:d']
    return ['XOSC.XSTAGE{}.{}'.format(stage, device)
            for stage in (0, 1) for device in devices]


def render(source, model, delay_ns, kick_current):
    """Replace only explicit characterization controls/analyses; keep circuitry."""
    if ('n12_ckt_rf' in source) != (model == 'rf'):
        raise ValueError('Seed model does not match requested model: ' + model)
    vdd = float(helper.assignment(source, 'VDDVAL'))
    ctrl = float(helper.assignment(source, 'VCTRLVAL'))
    code = sum(int(float(helper.assignment(source, 'CODE' + str(i)))) << i
               for i in range(5))
    if abs(vdd - 1.2) > 1e-9 or not 0 <= code <= 31:
        raise ValueError('Expected reviewed 1.2V/five-bit seed.')
    if not re.search(r'(?m)^simulatorOptions\s+options[^\n]*\btemp=25(?:\s|$)', source):
        raise ValueError('Expected reviewed TT/25C seed options.')
    if not re.search(r'ms013_io33_v2p6_7p_spe\.lib"\s+section=tt(?:\s|$)', source):
        raise ValueError('Expected TT ordinary-model include.')
    if model == 'rf' and not re.search(r'ms013_io33_rf_v1p9_spe\.lib"\s+section=mos_tt(?:\s|$)', source):
        raise ValueError('Expected mos_tt RF-model include.')
    # Refuse continuation on removed analysis cards rather than accidentally
    # retaining orphan options. Supplied selected seeds have single-line cards.
    lines = []
    analysis = re.compile(r'^\w+\s+(?:\([^)]*\)\s+)?(?:tran|pss|pnoise|dc|ac|xf|sp|noise|info)\b')
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith('//') and (analysis.match(stripped) or
                re.match(r'^(ic|nodeset|save)\s', stripped)):
            if stripped.endswith('\\'):
                raise ValueError('Unsupported continued old characterization card.')
            continue
        lines.append(line)
    text = '\n'.join(lines) + '\n'
    replacements = [
        (r'^VDD\s+\(vdd 0\)\s+vsource\s+dc=VDDVAL\s*$',
         'VDD (vdd 0) vsource type=pwl wave=[0 0 5n VDDVAL]', 'VDD source'),
        (r'^VCTRL\s+\(ctrl 0\)\s+vsource\s+dc=VCTRLVAL\s*$',
         'VCTRL (ctrl 0) vsource type=pwl wave=[0 0 5n VCTRLVAL]', 'control source'),
        (r'^\s*IREF\s+\(vdd bn\)\s+isource\s+dc=IREFVAL\s*$',
         '    IREF (vdd bn) isource type=pwl wave=[0 0 5n IREFVAL]', 'ideal reference')]
    for pattern, replacement, label in replacements:
        text = helper.replace_line(text, pattern, replacement, label)
    for bit in range(5):
        text = helper.replace_line(text,
            r'^VS{0}\s+\(s{0} 0\)\s+vsource\s+dc=VDDVAL\*CODE{0}\s*$'.format(bit),
            'VS{0} (s{0} 0) vsource type=pwl wave=[0 0 5n {1:.12g}]'.format(
                bit, vdd * ((code >> bit) & 1)), 'code source ' + str(bit))
    if re.search(r'(?mi)^\s*(ic|nodeset|IKICK)\b', text):
        raise ValueError('Unexpected residual IC/nodeset/kick in selected seed.')
    saves = ['vdd', 'ctrl', 'bn', 'bp', 'out0', 'out180', 'out90', 'out270', 'VDD:p']
    saves += tail_names(model)
    saves += ['XOSC.XSTAGE{}.{}'.format(stage, node)
              for stage in (0, 1) for node in ['cs1', 'cs2']]
    saves += ['XREF.MNREF:d', 'XREF.MNPMIRROR:d', 'XREF.MPREF:d']
    text += '\n// Startup diagnosis: externally ramped ideal bias; no initial conditions.\n'
    for start in range(0, len(saves), 8):
        text += 'save ' + ' '.join(saves[start:start + 8]) + '\n'
    if delay_ns is not None:
        text += ('// Single pulse only; 1us repeat lies outside 250ns analysis.\n'
                 'IKICK (out0 out180) isource type=pulse val0=0 val1={} '
                 'delay={}n rise=0.5p fall=0.5p width=50p period=1u\n').format(
                     kick_current, delay_ns)
    text += 'tran tran stop=250n maxstep=2p errpreset=conservative skipdc=yes\n'
    return text, {'model': model, 'vdd_V': vdd, 'vctrl_V': ctrl, 'code': code,
                  'temperature_C': 25, 'ramp_ns': 5, 'kick_delay_ns': delay_ns,
                  'kick_current': kick_current, 'kick_width_ps': 50 if delay_ns else None}


def window(data, begin, end):
    """Use shared ASCII/integral/crossing helpers; amplitude-gate all frequencies."""
    all_t = data.get('time', [])
    ids = [i for i, t in enumerate(all_t) if begin <= t <= end]
    if len(ids) < 3:
        raise ValueError('Measurement window has insufficient samples.')
    t = [all_t[i] for i in ids]
    series = {name: [y[i] for i in ids] for name, y in data.items()
              if name != 'time' and len(y) == len(all_t)}
    for name in ['vdd', 'bn', 'bp', 'VDD:p', 'out0', 'out180', 'out90', 'out270']:
        if name not in series:
            raise ValueError('Missing required saved waveform: ' + name)
    stats = {name: {'mean': helper.time_mean(t, y), 'min': min(y), 'max': max(y),
                    'first': y[0], 'last': y[-1], 'last_minus_first': y[-1] - y[0]}
             for name, y in series.items()}
    diff = [a - b for a, b in zip(series['out0'], series['out180'])]
    qdiff = [a - b for a, b in zip(series['out90'], series['out270'])]
    ivpp, qvpp = max(diff) - min(diff), max(qdiff) - min(qdiff)
    amplitude_ok = ivpp >= .05 and qvpp >= .05
    frequency = qfrequency = angle = drift = None
    parts = [None, None]
    periods_cv = None
    cr = qr = []
    if amplitude_ok:
        cr, qr = helper.crossings(t, diff), helper.crossings(t, qdiff)
        frequency = (len(cr) - 1) / (cr[-1] - cr[0]) if len(cr) > 2 else None
        qfrequency = (len(qr) - 1) / (qr[-1] - qr[0]) if len(qr) > 2 else None
        if frequency and qfrequency and abs(qfrequency / frequency - 1) < .01:
            angles = [((min(qr, key=lambda q: abs(q - c)) - c) * frequency * 360) % 360
                      for c in cr[1:-1]]
            angle = math.degrees(math.atan2(
                sum(math.sin(math.radians(a)) for a in angles),
                sum(math.cos(math.radians(a)) for a in angles))) % 360 if angles else None
        mid = (t[0] + t[-1]) / 2
        for i, (lo, hi) in enumerate([(t[0], mid), (mid, t[-1])]):
            sub = [c for c in cr if lo <= c <= hi]
            parts[i] = (len(sub) - 1) / (sub[-1] - sub[0]) if len(sub) > 2 else None
        drift = abs(parts[1] / parts[0] - 1) if all(parts) else None
    power = helper.time_mean(t, [-v * i for v, i in zip(series['vdd'], series['VDD:p'])])
    return {'window_start_s': t[0], 'window_end_s': t[-1], 'samples': len(t),
            'waveform_stats': stats, 'differential_vpp_V': ivpp,
            'q_differential_vpp_V': qvpp, 'amplitude_above_50mV_both_IQ': amplitude_ok,
            'frequency_Hz': frequency, 'q_frequency_Hz': qfrequency,
            'q_rising_phase_deg': angle, 'half_window_frequencies_Hz': parts,
            'half_window_relative_drift': drift, 'supply_power_W': power,
            'frequency_discard_reason': None if amplitude_ok else 'I or Q swing below 50mV; numerical crossings discarded.',
            'valid_screen': bool(amplitude_ok and frequency and qfrequency and
                abs(qfrequency / frequency - 1) < .01 and angle is not None and
                helper.phase_distance(angle, 90) <= 10 and drift is not None and
                drift < .01 and power > 0),
            'screen_limits': {'IQ_vpp_min_V': .05, 'IQ_frequency_agreement_relative': .01,
                              'phase90_tolerance_deg': 10, 'half_frequency_drift_max': .01}}


def reference_bias(project, model, spec):
    """Read available prior selected PSS bias; never invent a steady RF voltage."""
    summary = project / 'results' / ('phase3/phase3_noise_summary.json' if model == 'ordinary'
                                    else 'rfnoise/rfnoise_completion_summary.json')
    if not summary.exists():
        return {'available': False, 'reason': 'Prior selected PSS summary is absent.'}
    try:
        records = json.loads(summary.read_text()).get('records' if model == 'ordinary' else 'cases', [])
        for record in reversed(records):
            if record.get('state') != 'completed':
                continue
            point = record.get('specification', {}) if model == 'ordinary' else record.get('selected', {}).get('best_measured', {})
            if point.get('code') != spec['code'] or abs(point.get('vctrl_V', -1) - spec['vctrl_V']) > 1e-9:
                continue
            path = helper.contained(project, Path(record['measurement']['waveform_path']))
            _, data = helper.read_psf(path)
            t = data.get('time', [])
            wanted = ['bn', 'bp'] + tail_names(model)
            means = {name: helper.time_mean(t, data[name]) for name in wanted
                     if len(data.get(name, [])) == len(t) and len(t) > 1}
            if 'bn' in means:
                return {'available': True, 'kind': 'Prior selected periodic PSS bias, not a new DC analysis.',
                        'waveform_path': str(path), 'waveform_sha256': file_hash(path), 'means': means}
        return {'available': False, 'reason': 'Matching selected PSS with saved BN not found.'}
    except (ValueError, OSError, KeyError, TypeError) as error:
        return {'available': False, 'reason': 'Cannot read matching selected PSS: ' + str(error)}


def diagnose(data, spec, reference):
    model = spec['model']
    required = tail_names(model)
    if any(len(data.get(name, [])) != len(data.get('time', [])) or not data.get(name) for name in required):
        raise ValueError('Both stages actual MOS tail currents were not saved.')
    windows = {}
    for name, (lo, hi) in WINDOWS.items():
        full = window(data, lo, hi)
        mid = (lo + hi) / 2
        halves = [window(data, lo, mid), window(data, mid, hi)]
        names = ['bn', 'bp'] + required
        full['bias_and_tail'] = {}
        reference_means = reference.get('means', {})
        for node in names:
            s = full['waveform_stats'][node]
            target = reference_means.get(node)
            movement = halves[1]['waveform_stats'][node]['mean'] - halves[0]['waveform_stats'][node]['mean']
            full['bias_and_tail'][node] = {
                'mean': s['mean'], 'peak_to_peak': s['max'] - s['min'],
                'last_minus_first': s['last_minus_first'], 'half_mean_movement': movement,
                'prior_PSS_mean': target,
                'mean_minus_prior_PSS': s['mean'] - target if target is not None else None,
                'relative_mean_error_vs_prior_PSS': (s['mean'] / target - 1) if target else None}
        full['half_window_differential_vpp_V'] = [m['differential_vpp_V'] for m in halves]
        full['half_window_q_differential_vpp_V'] = [m['q_differential_vpp_V'] for m in halves]
        full['bias_ready_screen'] = None
        if reference.get('available'):
            bn = full['bias_and_tail']['bn']
            bp = full['bias_and_tail']['bp']
            full['bias_ready_screen'] = bool(abs(bn['relative_mean_error_vs_prior_PSS']) <= .01 and
                abs(bn['half_mean_movement']) <= .001 and abs(bp['half_mean_movement']) <= .001)
        full['bias_ready_limits'] = {'BN_mean_relative_to_prior_PSS_max': .01,
                                    'BN_BP_half_mean_movement_max_V': .001}
        windows[name] = full
    final = windows['final']
    before = windows['before_late_kick']
    probes = {}
    if spec['kick_delay_ns'] is not None:
        kick = spec['kick_delay_ns'] * 1e-9
        for label, offsets in [('just_after_kick', (.1e-9, 2e-9)), ('after_5ns', (5e-9, 10e-9))]:
            m = window(data, kick + offsets[0], kick + offsets[1])
            probes[label] = {k: m[k] for k in ['differential_vpp_V', 'q_differential_vpp_V',
                                             'frequency_Hz', 'valid_screen']}
    silent = max(final['differential_vpp_V'], final['q_differential_vpp_V']) < 1e-9
    gain = None
    if probes:
        initial = probes['just_after_kick']['differential_vpp_V']
        gain = final['differential_vpp_V'] / initial if initial > 1e-12 else None
    if final['valid_screen']:
        if spec['kick_delay_ns'] == 200 and before['valid_screen']:
            outcome = 'Already oscillating before the late kick; final differential oscillation sustained.'
        elif spec['kick_delay_ns'] is None:
            outcome = 'Deterministic no-explicit-kick run oscillates; physical noise startup remains unverified.'
        elif gain is not None and gain > 1.2:
            outcome = 'Explicit kick grows and final differential oscillation passes screening.'
        else:
            outcome = 'Final differential oscillation passes screening after explicit kick.'
    elif silent:
        outcome = 'Final differential signal is numerically silent (<1nVpp); no oscillator frequency reported.'
    else:
        outcome = 'Residual/transient differential signal fails final oscillation screening.'
    return {'windows': windows, 'kick_response_windows': probes,
            'final_to_first_postkick_I_vpp_ratio': gain,
            'final_numerically_silent': silent, 'final_valid_screen': final['valid_screen'],
            'late_kick_bias_ready_screen': before['bias_ready_screen'] if spec['kick_delay_ns'] == 200 else None,
            'outcome': outcome, 'scope': SCOPE}


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Driver:
    def __init__(self, args):
        self.args = args
        self.project = Path(args.project).resolve()
        self.root = helper.contained(self.project, self.project / 'results/startup_late')
        self.netlists = helper.contained(self.project, self.project / 'netlists/startup_late')
        self.logs = helper.contained(self.project, self.project / 'logs/startup_late')
        for directory in (self.root, self.netlists, self.logs):
            directory.mkdir(parents=True, exist_ok=True)
        self.status = self.project / 'results/startup_late_status.json'
        self.started = time.time()
        self.results = []
        self.spectre = shutil.which(args.spectre)
        if not self.spectre:
            raise ValueError('Spectre unavailable; set --spectre executable.')
        self.helper_hash = file_hash(Path(helper.__file__))

    def update(self, stage, **extra):
        data = {'version': VERSION, 'stage': stage, 'pid': os.getpid(), 'scope': SCOPE,
                'started_unix': self.started, 'updated_unix': time.time(),
                'max_spectre_workers': 1, 'scheduled_cases': 8, 'cases_recorded': len(self.results)}
        data.update(extra)
        helper.atomic_json(self.status, data)
        print(json.dumps({'stage': stage, 'cases': len(self.results), **extra}), flush=True)

    def case(self, model, mode, delay, current):
        source_path = helper.contained(self.project, self.project / 'netlists' / SEEDS[model])
        source = source_path.read_text()
        text, spec = render(source, model, delay, current)
        spec['mode'] = mode
        reference = reference_bias(self.project, model, spec)
        identity = {'version': VERSION, 'source_sha256': file_hash(source_path),
                    'shared_helper_sha256': self.helper_hash, 'specification': spec,
                    'netlist': text, 'prior_bias_reference': reference}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        case_id = 'startup_late_{}_{}_{}'.format(model, mode, digest[:12])
        cache = self.root / (case_id + '.json')
        if cache.exists() and not self.args.force:
            try:
                prior = json.loads(cache.read_text())
                if prior.get('identity_sha256') == digest and prior.get('state') == 'completed' and all(
                        Path(p).is_file() for p in prior.get('required_artifacts', [])):
                    prior['resumed'] = True
                    return prior
            except (OSError, ValueError):
                pass
        attempt = 1
        while (self.netlists / ('{}_a{:03d}.scs'.format(case_id, attempt))).exists():
            attempt += 1
        tag = '{}_a{:03d}'.format(case_id, attempt)
        netlist, raw = self.netlists / (tag + '.scs'), self.root / (tag + '.raw')
        log, stdout = self.logs / (tag + '.log'), self.logs / (tag + '.stdout')
        netlist.write_text(text)
        record = {'case_id': case_id, 'identity_sha256': digest, 'source_sha256': identity['source_sha256'],
                  'source_path': str(source_path), 'attempt': attempt, 'specification': spec,
                  'state': 'running', 'scope': SCOPE, 'prior_bias_reference': reference,
                  'netlist_path': str(netlist), 'raw_path': str(raw), 'log_path': str(log), 'resumed': False}
        manifest = self.root / (tag + '.manifest.json')
        helper.atomic_json(manifest, record)
        self.update('running', current_case=case_id, current_manifest=str(manifest))
        started = time.monotonic()
        try:
            rc = helper.run_process([self.spectre, str(netlist), '-format', 'psfascii', '-raw', str(raw),
                                     '+log', str(log)], stdout, self.project, started + self.args.timeout)
            record['spectre_rc'] = rc
            record['spectre_log_summary'] = helper.spectral_log_summary(log)
            if rc != 0 or record['spectre_log_summary']['errors'] not in (None, 0):
                raise RuntimeError('Spectre failed or reported errors.')
            waveform = raw / 'tran.tran.tran'
            _, data = helper.read_psf(waveform)
            record['measurement'] = diagnose(data, spec, reference)
            record['required_artifacts'] = [str(netlist), str(log), str(waveform)]
            record['state'] = 'completed'
        except Exception as error:
            record['state'] = 'failed'
            record['failure'] = repr(error)
        except BaseException:
            record['state'] = 'interrupted'
            helper.atomic_json(manifest, record)
            raise
        record['elapsed_s'] = time.monotonic() - started
        record['finished_unix'] = time.time()
        helper.atomic_json(manifest, record)
        helper.atomic_json(cache, record)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=helper.DEFAULT_PROJECT)
    parser.add_argument('--spectre', default='spectre')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive.')
    helper.STOP.clear()
    driver = None
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        driver = Driver(args)
        driver.update('starting')
        for model in SEEDS:
            for mode, delay, current in MODES:
                record = driver.case(model, mode, delay, current)
                driver.results.append(record)
                helper.atomic_json(driver.root / 'startup_late_all_cases.json', driver.results)
                driver.update('running', last_case=record['case_id'], last_state=record['state'])
        failures = [r['case_id'] for r in driver.results if r['state'] != 'completed']
        summary = {'scope': SCOPE, 'records': driver.results, 'process_or_parse_failed_case_ids': failures,
                   'final_screen_passed': sum(r.get('measurement', {}).get('final_valid_screen', False) for r in driver.results),
                   'final_screen_invalid_case_ids': [r['case_id'] for r in driver.results if
                       r['state'] == 'completed' and not r['measurement']['final_valid_screen']],
                   'conclusion': 'Analysis completion and explicit-kick response only; no guaranteed unforced/noise startup claim.'}
        helper.atomic_json(driver.root / 'startup_late_completion_summary.json', summary)
        driver.update('complete_with_process_failures' if failures else 'complete_analyses',
                      process_or_parse_failed_case_ids=failures, final_screen_passed=summary['final_screen_passed'])
        return 1 if failures else 0
    except BaseException as error:
        helper.STOP.set()
        with helper.ACTIVE_LOCK:
            active = list(helper.ACTIVE.values())
        for process in active:
            helper.stop_process_group(process)
        if driver:
            driver.update('interrupted' if isinstance(error, KeyboardInterrupt) else 'failed', error=repr(error))
        else:
            print(json.dumps({'stage': 'setup_failed', 'error': repr(error)}), flush=True)
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == '__main__':
    raise SystemExit(main())
