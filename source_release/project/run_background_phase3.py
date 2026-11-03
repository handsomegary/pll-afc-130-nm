"""Bounded, resumable phase-3 ordinary-MOS VCO checks; no GUI or plotting.

Run in the VM after review. This file does not upload or start itself.
Results are sampled VCO checks, never full-PVT/full-PLL or noise-startup proof.
Python 3.6+; no imports from earlier scripts with execution side effects.
"""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import statistics
import subprocess
import threading
import time
import uuid

VERSION = 'phase3-v1'
DEFAULT_PROJECT = '@PROJECT_ROOT@'
SOURCE_NAME = 'phase2_target_l5_b11_i5.scs'
SCOPE = ('Ordinary n12/p12 pre-layout VCO + bias + static band logic; ideal '
         'reference/passives, no buffer/divider/PFD/CP/filter/AFC, no PEX. '
         'Sampled PVT endpoints and externally-ramped-bias test-withkick only.')
STOP = threading.Event()
ACTIVE = {}
ACTIVE_LOCK = threading.Lock()


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('w') as handle:
        json.dump(data, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(temporary), str(path))


def contained(project, path):
    resolved = path.resolve()
    resolved.relative_to(project)
    return resolved


def change_parameter(text, name, value):
    pattern = r'(?m)(^parameters\b[^\n]*?\b' + re.escape(name) + r'=)[^\s]+'
    changed, count = re.subn(pattern, lambda m: m.group(1) + str(value), text)
    if count != 1:
        raise ValueError('Expected exactly one parameter assignment: ' + name)
    return changed


def change_temperature(text, temperature):
    pattern = r'(?m)(^simulatorOptions\s+options[^\n]*?\btemp=)[^\s]+'
    changed, count = re.subn(pattern, lambda m: m.group(1) + str(temperature), text)
    if count != 1:
        raise ValueError('Expected one simulatorOptions temp assignment.')
    return changed


def change_corner(text, corner):
    pattern = r'(ms013_io33_v2p6_7p_spe\.lib"\s+section=)\w+'
    changed, count = re.subn(pattern, lambda m: m.group(1) + corner, text)
    if count != 1:
        raise ValueError('Expected one standard-model include; RF is separate work.')
    return changed


def assignment(text, name):
    match = re.search(r'(?m)^parameters\b[^\n]*?\b' + re.escape(name) + r'=([^\s]+)', text)
    if not match:
        raise ValueError('Missing source parameter: ' + name)
    return match.group(1)


def replace_line(text, pattern, replacement, description):
    changed, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise ValueError('Expected one ' + description + '; found ' + str(count))
    return changed


def base_netlist(source):
    if 'n12_ckt_rf' in source:
        raise ValueError('Phase 3 is ordinary MOS; refusing an RF source netlist.')
    required = ['LFINE', 'WBANK', 'WMAIN_TAIL', 'VCTRLVAL', 'VDDVAL']
    for name in required:
        assignment(source, name)
    # Remove old analyses/info, preserving the reviewed circuit and its IC.
    lines = []
    saved = []
    for line in source.splitlines():
        stripped = line.strip()
        if re.match(r'^(tran|pss|pnoise)\s', stripped) or ' info ' in line:
            continue
        if re.match(r'^save\s', stripped):
            saved.extend(stripped.split()[1:])
            continue
        lines.append(line)
    required_saves = ['vdd', 'ctrl', 'bn', 'bp', 'out0', 'out180', 'out90', 'out270', 'VDD:p']
    for stage in ['XSTAGE0', 'XSTAGE1']:
        prefix = 'XOSC.' + stage + '.'
        required_saves.extend([prefix + 'cs1', prefix + 'cs2'])
        for device in ['MTAILMAIN', 'MTAILREGEN', 'MFINE', 'MSUP0', 'MSUP1', 'MSUP2']:
            required_saves.append(prefix + device + ':d')
    unique = list(dict.fromkeys(saved + required_saves))
    lines.append('// Phase3: selected voltages and physical tail/fine branch currents.')
    for start in range(0, len(unique), 10):
        lines.append('save ' + ' '.join(unique[start:start + 10]))
    return '\n'.join(lines) + '\n'


def render_case(base, case):
    text = change_corner(base, case['corner'])
    text = change_temperature(text, case['temperature_C'])
    text = change_parameter(text, 'VDDVAL', case['vdd_V'])
    text = change_parameter(text, 'VCTRLVAL', case['vctrl_V'])
    for bit in range(5):
        text = change_parameter(text, 'CODE' + str(bit), (case['code'] >> bit) & 1)
    if case['kind'] == 'noise':
        text += ('pss (out0 out180) pss fund=3.2G tstab=40n harms=30 '
                 'errpreset=conservative harmonicbalance=no maxstep=0.5p '
                 'tstabmethod=gear2only method=gear2only\n'
                 'pnoise (out0 out180) pnoise start=10k stop=100M dec=30 '
                 'sweeptype=relative relharmnum=1 maxsideband=30 noiseout=[pm] '
                 'noisetype=timeaverage\n')
    elif case['kind'] == 'ramp':
        text = re.sub(r'(?m)^\s*ic\s+[^\n]*\n?', '', text)
        ramp = case['ramp_ns'] * 1e-9
        # External testbench sources track supply. The ideal reference is also
        # externally ramped; this is NOT autonomous reference/noise startup.
        replacements = [
            (r'^VDD\s+\(vdd 0\)\s+vsource\s+dc=VDDVAL\s*$',
             'VDD (vdd 0) vsource type=pwl wave=[0 0 {:.12g} {:.12g}]'.format(ramp, case['vdd_V']), 'VDD source'),
            (r'^VCTRL\s+\(ctrl 0\)\s+vsource\s+dc=VCTRLVAL\s*$',
             'VCTRL (ctrl 0) vsource type=pwl wave=[0 0 {:.12g} {:.12g}]'.format(ramp, case['vctrl_V']), 'VCTRL source'),
            (r'^\s*IREF\s+\(vdd bn\)\s+isource\s+dc=IREFVAL\s*$',
             '    IREF (vdd bn) isource type=pwl wave=[0 0 {:.12g} IREFVAL]'.format(ramp), 'ideal IREF source')]
        for pattern, replacement, description in replacements:
            text = replace_line(text, pattern, replacement, description)
        for bit in range(5):
            level = case['vdd_V'] * ((case['code'] >> bit) & 1)
            pattern = r'^VS{0}\s+\(s{0} 0\)\s+vsource\s+dc=VDDVAL\*CODE{0}\s*$'.format(bit)
            replacement = 'VS{0} (s{0} 0) vsource type=pwl wave=[0 0 {1:.12g} {2:.12g}]'.format(bit, ramp, level)
            text = replace_line(text, pattern, replacement, 'band source ' + str(bit))
        text += ('// TEST-WITHKICK: one 1uA / 50ps differential pulse after ramp.\n'
                 '// 1us repeat interval is outside this 80ns test; no IC.\n'
                 'IKICK (out0 out180) isource type=pulse val0=0 val1=1u '
                 'delay={:.12g} rise=0.5p fall=0.5p width=50p period=1u\n'.format(ramp + 2e-9))
        text += 'tran tran stop=80n maxstep=1p errpreset=conservative skipdc=yes\n'
    else:
        text += 'tran tran stop=50n maxstep=1p errpreset=conservative skipdc=no\n'
    return text


def stop_process_group(process):
    # Only groups launched by this driver, identified by their live Popen handle.
    if process.poll() is not None:
        return
    try:
        if os.getpgid(process.pid) != process.pid:
            return
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def run_process(command, output, cwd, deadline):
    if STOP.is_set():
        raise RuntimeError('Driver stop requested before process launch.')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, 0)
    with output.open('w') as handle:
        process = subprocess.Popen(command, cwd=str(cwd), stdout=handle,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        with ACTIVE_LOCK:
            ACTIVE[process.pid] = process
        try:
            return process.wait(timeout=remaining)
        except BaseException:
            stop_process_group(process)
            raise
        finally:
            with ACTIVE_LOCK:
                ACTIVE.pop(process.pid, None)


def read_psf(path):
    data = {}
    header = {}
    reading = False
    with path.open(errors='replace') as handle:
        for line in handle:
            stripped = line.strip()
            if stripped == 'VALUE':
                reading = True
                continue
            if stripped == 'END':
                break
            match = re.match(r'^"([^\"]+)"\s+([-+0-9.eE]+)\s*$', stripped)
            if not match:
                continue
            try:
                value = float(match.group(2))
            except ValueError:
                continue
            if not math.isfinite(value):
                continue
            if reading:
                data.setdefault(match.group(1), []).append(value)
            else:
                header[match.group(1)] = value
    return header, data


def time_mean(t, y):
    if len(t) < 2 or len(y) != len(t) or t[-1] <= t[0]:
        raise ValueError('Invalid time series for integral mean.')
    return sum((t[i + 1] - t[i]) * (y[i + 1] + y[i]) / 2
               for i in range(len(t) - 1)) / (t[-1] - t[0])


def crossings(t, y):
    return [t[i] - y[i] * (t[i + 1] - t[i]) / (y[i + 1] - y[i])
            for i in range(len(t) - 1) if y[i] <= 0 < y[i + 1]]


def phase_distance(angle, expected):
    return abs((angle - expected + 180) % 360 - 180)


def measure_transient(path, begin, end):
    _, data = read_psf(path)
    all_t = data.get('time', [])
    indices = [i for i, value in enumerate(all_t) if begin <= value <= end]
    if len(indices) < 3:
        raise ValueError('Transient measurement window lacks samples.')
    t = [all_t[i] for i in indices]
    values = {name: [series[i] for i in indices] for name, series in data.items()
              if len(series) == len(all_t) and name != 'time'}
    for required in ['vdd', 'VDD:p', 'bn', 'out0', 'out180', 'out90', 'out270']:
        if required not in values:
            raise ValueError('Missing saved waveform: ' + required)
    result = {'window_start_s': t[0], 'window_end_s': t[-1], 'samples': len(t)}
    result['waveform_stats'] = {name: {'min': min(y), 'max': max(y), 'mean': time_mean(t, y)}
                                for name, y in values.items()}
    result['supply_power_W'] = time_mean(t, [-v * i for v, i in zip(values['vdd'], values['VDD:p'])])
    diff = [a - b for a, b in zip(values['out0'], values['out180'])]
    qdiff = [a - b for a, b in zip(values['out90'], values['out270'])]
    cr = crossings(t, diff)
    qr = crossings(t, qdiff)
    result['differential_vpp_V'] = max(diff) - min(diff)
    result['q_differential_vpp_V'] = max(qdiff) - min(qdiff)
    result['rising_crossings'] = len(cr)
    frequency = (len(cr) - 1) / (cr[-1] - cr[0]) if len(cr) > 2 else None
    qfrequency = (len(qr) - 1) / (qr[-1] - qr[0]) if len(qr) > 2 else None
    result['frequency_Hz'] = frequency
    result['q_frequency_Hz'] = qfrequency
    angle = None
    if frequency and qfrequency and abs(qfrequency / frequency - 1) < .01:
        angles = [((min(qr, key=lambda q: abs(q - c)) - c) * frequency * 360) % 360
                  for c in cr[1:-1]]
        # Circular mean avoids a false 180-degree result at the 0/360 boundary.
        sx = sum(math.cos(math.radians(a)) for a in angles)
        sy = sum(math.sin(math.radians(a)) for a in angles)
        angle = math.degrees(math.atan2(sy, sx)) % 360 if angles else None
    result['q_rising_phase_deg'] = angle
    periods = [cr[i + 1] - cr[i] for i in range(len(cr) - 1)]
    result['period_min_s'] = min(periods) if periods else None
    result['period_max_s'] = max(periods) if periods else None
    result['period_cv'] = statistics.pstdev(periods) / statistics.mean(periods) if len(periods) > 2 else None
    # A second-half comparison detects gross envelope/settling drift. This is
    # screening, NOT a physical jitter metric or startup-margin signoff.
    mid = (t[0] + t[-1]) / 2
    fparts = []
    for start, stop in [(t[0], mid), (mid, t[-1])]:
        subcr = [c for c in cr if start <= c <= stop]
        fparts.append((len(subcr) - 1) / (subcr[-1] - subcr[0]) if len(subcr) > 2 else None)
    result['half_window_frequencies_Hz'] = fparts
    drift = abs(fparts[1] / fparts[0] - 1) if all(fparts) else None
    result['half_window_relative_drift'] = drift
    result['valid_screen'] = bool(frequency and qfrequency and frequency > 0 and
        result['differential_vpp_V'] > .05 and result['q_differential_vpp_V'] > .05 and
        angle is not None and phase_distance(angle, 90) <= 10 and
        drift is not None and drift < .01 and result['supply_power_W'] > 0)
    result['screen_limits'] = {'both_diff_vpp_min_V': .05, 'phase_90_tolerance_deg': 10,
                               'half_window_frequency_drift_max': .01}
    return result


def pss_waveform(raw):
    candidates = [raw / 'pss_td.pss', raw / 'pss_td.pss.pss']
    candidates.extend(p for p in sorted(raw.iterdir()) if p.is_file() and 'pss' in p.name and 'pnoise' not in p.name)
    for path in dict.fromkeys(candidates):
        if not path.is_file():
            continue
        with path.open(errors='replace') as handle:
            head = handle.read(8192)
        if 'td.pss' in head and '"fundamental"' in head:
            return path
    raise ValueError('No ASCII periodic time-domain PSS waveform found.')


def measure_pss(path):
    header, data = read_psf(path)
    frequency = header.get('fundamental')
    period = header.get('period')
    if not frequency or frequency <= 0:
        raise ValueError('No positive actual PSS fundamental in raw header.')
    if period and abs((1 / period) / frequency - 1) > .001:
        raise ValueError('PSS period and fundamental disagree.')
    t = data.get('time', [])
    for required in ['vdd', 'VDD:p', 'out0', 'out180']:
        if len(data.get(required, [])) != len(t):
            raise ValueError('PSS power/output waveform missing: ' + required)
    power = time_mean(t, [-v * i for v, i in zip(data['vdd'], data['VDD:p'])])
    if power <= 0:
        raise ValueError('PSS supply power is not positive.')
    diff = [a - b for a, b in zip(data['out0'], data['out180'])]
    return {'actual_carrier_Hz': frequency, 'period_s': period,
            'pss_supply_power_W': power, 'differential_vpp_V': max(diff) - min(diff),
            'waveform_samples': len(t), 'waveform_path': str(path),
            'target_relative_error': abs(frequency / 3.2e9 - 1)}


def skill_string(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def ocean_script(raw, curve_path, scalar_path):
    return ('openResults({raw})\n'
            'selectResult(\'pnoise_pm)\n'
            'pn=phaseNoise(1 "pss_fd" ?result "pnoise_pm")\n'
            'unless(pn error("phaseNoise returned nil\\n"))\n'
            'ocnPrint(?output {curve} ?numberNotation \'scientific ?precision 12 pn)\n'
            'f=outfile({scalar})\n'
            'fprintf(f "PN1M %.15g\\n" value(pn 1e6))\n'
            'fprintf(f "PN10M %.15g\\n" value(pn 1e7))\n'
            'close(f)\n'
            'exit()\n').format(raw=skill_string(raw), curve=skill_string(curve_path), scalar=skill_string(scalar_path))


def spectral_log_summary(path):
    text = path.read_text(errors='replace') if path.exists() else ''
    matches = re.findall(r'(\d+)\s+errors?\s*[,;]\s*(\d+)\s+warnings?', text, re.I)
    return {'errors': int(matches[-1][0]) if matches else None,
            'warnings': int(matches[-1][1]) if matches else None,
            'tail': text[-1800:] if not matches or int(matches[-1][0]) else ''}


class Driver:
    def __init__(self, args):
        self.args = args
        self.project = Path(args.project).resolve()
        self.source_path = contained(self.project, self.project / 'netlists' / SOURCE_NAME)
        source = self.source_path.read_text()
        self.source_hash = hashlib.sha256(source.encode()).hexdigest()
        self.base = base_netlist(source)
        self.target_ctrl = float(assignment(source, 'VCTRLVAL'))
        self.target_code = sum(int(float(assignment(source, 'CODE' + str(i)))) << i for i in range(5))
        self.spectre = shutil.which(args.spectre)
        if not self.spectre:
            raise ValueError('Spectre not on PATH; set --spectre to its executable.')
        self.ocean = shutil.which(args.ocean)
        self.root = contained(self.project, self.project / 'results' / 'phase3')
        self.netlists = contained(self.project, self.project / 'netlists' / 'phase3')
        self.logs = contained(self.project, self.project / 'logs' / 'phase3')
        for directory in [self.root, self.netlists, self.logs]:
            directory.mkdir(parents=True, exist_ok=True)
        self.started = time.time()
        self.results = []
        self.status = contained(self.project, self.project / 'results' / 'phase3_status.json')

    def update(self, stage, **extra):
        payload = {'version': VERSION, 'stage': stage, 'pid': os.getpid(),
                   'started_unix': self.started, 'updated_unix': time.time(),
                   'cases_completed_or_resumed': len(self.results), 'source_netlist': str(self.source_path),
                   'source_sha256': self.source_hash, 'scope': SCOPE, 'max_workers': self.args.max_workers}
        payload.update(extra)
        atomic_json(self.status, payload)
        print(json.dumps({'stage': stage, 'cases': len(self.results), **extra}), flush=True)

    def case(self, specification):
        text = render_case(self.base, specification)
        identity = {'version': VERSION, 'source_sha256': self.source_hash,
                    'specification': specification, 'netlist': text}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        case_id = specification['label'] + '_' + digest[:12]
        cache = self.root / (case_id + '.json')
        if cache.exists() and not self.args.force:
            prior = json.loads(cache.read_text())
            if prior.get('identity_sha256') == digest and prior.get('state') == 'completed':
                if all(Path(p).exists() for p in prior.get('required_artifacts', [])):
                    prior['resumed'] = True
                    return prior
        # Each attempt has new raw/log/netlist paths; interrupted/stale data is
        # never overwritten or accepted as a fresh simulation result.
        attempt = 1
        while (self.netlists / ('{}_a{:03d}.scs'.format(case_id, attempt))).exists():
            attempt += 1
        tag = '{}_a{:03d}'.format(case_id, attempt)
        netlist = self.netlists / (tag + '.scs')
        raw = self.root / (tag + '.raw')
        log = self.logs / (tag + '.log')
        stdout = self.logs / (tag + '.stdout')
        netlist.write_text(text)
        result = {'case_id': case_id, 'identity_sha256': digest, 'attempt': attempt,
                  'specification': specification, 'netlist_path': str(netlist), 'raw_path': str(raw),
                  'log_path': str(log), 'scope': SCOPE, 'resumed': False, 'state': 'running'}
        atomic_json(self.root / (tag + '.manifest.json'), result)
        deadline = time.monotonic() + self.args.timeout
        try:
            rc = run_process([self.spectre, str(netlist), '-format', 'psfascii', '-raw', str(raw),
                              '+log', str(log)], stdout, self.project, deadline)
            result['spectre_rc'] = rc
            result['spectre_log_summary'] = spectral_log_summary(log)
            if rc != 0 or result['spectre_log_summary']['errors'] not in (None, 0):
                raise RuntimeError('Spectre did not complete without errors.')
            artifacts = [str(netlist), str(log)]
            if specification['kind'] == 'noise':
                if not self.ocean:
                    raise ValueError('Headless OCEAN not on PATH; use --ocean executable.')
                waveform = pss_waveform(raw)
                result['measurement'] = measure_pss(waveform)
                ocean_file = self.netlists / (tag + '.ocn')
                curve = self.root / (tag + '_pn_ssb.txt')
                scalar = self.root / (tag + '_pn_scalars.txt')
                ocean_file.write_text(ocean_script(raw, curve, scalar))
                ocean_rc = run_process([self.ocean, '-nograph', '-restore', str(ocean_file)],
                                       self.logs / (tag + '_ocean.stdout'), self.project, deadline)
                result['ocean_rc'] = ocean_rc
                if ocean_rc != 0 or not scalar.exists() or not curve.exists():
                    raise RuntimeError('OCEAN phaseNoise extraction failed.')
                pn = {}
                for line in scalar.read_text().splitlines():
                    fields = line.split()
                    if len(fields) == 2 and fields[0] in ('PN1M', 'PN10M'):
                        pn[fields[0]] = float(fields[1])
                if not all(name in pn and math.isfinite(pn[name]) for name in ('PN1M', 'PN10M')):
                    raise ValueError('Missing/nonfinite OCEAN phaseNoise scalar.')
                m = result['measurement']
                m['phase_noise_1MHz_dBc_Hz'] = pn['PN1M']
                m['phase_noise_10MHz_dBc_Hz'] = pn['PN10M']
                for offset, value, label in [(1e6, pn['PN1M'], '1MHz'), (1e7, pn['PN10M'], '10MHz')]:
                    m['oscillator_FoM_' + label + '_dB'] = value - 20 * math.log10(m['actual_carrier_Hz'] / offset) + 10 * math.log10(m['pss_supply_power_W'] * 1000)
                result['noise_scope'] = 'Free-running VCO SSB PM noise, 30 harms/sidebands; no sideband convergence or PLL RMS jitter claim.'
                artifacts.extend([str(waveform), str(ocean_file), str(curve), str(scalar)])
            else:
                waveform = raw / 'tran.tran.tran'
                if not waveform.exists():
                    raise ValueError('Expected transient raw waveform is missing.')
                begin, end = (65e-9, 78e-9) if specification['kind'] == 'ramp' else (35e-9, 48e-9)
                result['measurement'] = measure_transient(waveform, begin, end)
                if specification['kind'] == 'ramp':
                    result['startup_scope'] = 'TEST-WITHKICK: supply/control/ideal IREF externally ramped; no IC; single 1uA 50ps kick. Not autonomous reference or noise startup.'
                artifacts.append(str(waveform))
            result['required_artifacts'] = artifacts
            result['state'] = 'completed'
        except subprocess.TimeoutExpired as error:
            result['state'] = 'failed'
            result['failure'] = 'Per-case deadline exceeded; owned process group terminated: ' + str(error)
        except Exception as error:
            result['state'] = 'failed'
            result['failure'] = repr(error)
        result['finished_unix'] = time.time()
        atomic_json(self.root / (tag + '.manifest.json'), result)
        atomic_json(cache, result)
        return result

    def batch(self, cases, stage):
        self.update(stage, scheduled_cases=len(cases))
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.args.max_workers)
        futures = []
        collected = []
        try:
            futures = [executor.submit(self.case, case) for case in cases]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                self.results.append(result)
                collected.append(result)
                atomic_json(self.root / 'phase3_all_cases.json', self.results)
                self.update(stage, scheduled_cases=len(cases), stage_completed=len(collected),
                            last_case=result['case_id'], last_state=result['state'])
        except BaseException:
            STOP.set()
            for future in futures:
                future.cancel()
            with ACTIVE_LOCK:
                active = list(ACTIVE.values())
            for process in active:
                stop_process_group(process)
            raise
        finally:
            executor.shutdown(wait=True)
        return collected


def pvt_summary(records):
    groups = {}
    for record in records:
        spec = record['specification']
        key = '{}_v{}_t{}'.format(spec['corner'], spec['vdd_V'], spec['temperature_C'])
        groups.setdefault(key, []).append(record)
    summaries = {}
    for key, group in groups.items():
        by_point = {(r['specification']['code'], r['specification']['vctrl_V']): r for r in group}
        bands = []
        for code in [0, 15, 16, 20, 31]:
            low = by_point.get((code, .3), {})
            high = by_point.get((code, 1.0), {})
            lo = low.get('measurement', {})
            hi = high.get('measurement', {})
            valid = bool(low.get('state') == 'completed' and high.get('state') == 'completed' and
                         lo.get('valid_screen') and hi.get('valid_screen'))
            f0 = lo.get('frequency_Hz')
            f1 = hi.get('frequency_Hz')
            bands.append({'code': code, 'endpoints_valid': valid, 'f_at_0p3_Hz': f0, 'f_at_1p0_Hz': f1,
                          'positive_endpoint_slope': bool(valid and f1 > f0),
                          'endpoint_average_Kvco_Hz_per_V': (f1 - f0) / .7 if valid else None,
                          'sampled_band_contains_3p2g': bool(valid and min(f0, f1) <= 3.2e9 <= max(f0, f1))})
        b15 = next(b for b in bands if b['code'] == 15)
        b16 = next(b for b in bands if b['code'] == 16)
        overlap = b15['f_at_1p0_Hz'] - b16['f_at_0p3_Hz'] if b15['endpoints_valid'] and b16['endpoints_valid'] else None
        summaries[key] = {'bands': bands, 'code15_to16_endpoint_overlap_Hz': overlap,
                          'scope': 'Five codes/two endpoints only; interior monotonicity, all32 overlap, loaded/cold-start margin remain unverified.'}
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=DEFAULT_PROJECT)
    parser.add_argument('--spectre', default=os.environ.get('PHASE3_SPECTRE', 'spectre'))
    parser.add_argument('--ocean', default=os.environ.get('PHASE3_OCEAN', 'ocean'))
    parser.add_argument('--stages', default='noise,pvt,ramp', help='Comma-separated noise,pvt,ramp, in priority order.')
    parser.add_argument('--max-workers', type=int, choices=[1, 2], default=2)
    parser.add_argument('--timeout', type=int, default=300, help='Combined per-case Spectre/OCEAN deadline in seconds.')
    parser.add_argument('--force', action='store_true', help='New attempts even for completed cache entries; never overwrite old raw/logs.')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive.')
    stages = args.stages.split(',')
    if any(stage not in ['noise', 'pvt', 'ramp'] for stage in stages) or len(set(stages)) != len(stages):
        parser.error('Stages must be unique choices from noise,pvt,ramp.')
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    driver = Driver(args)
    try:
        driver.update('starting', requested_stages=stages)
        groups = {}
        baseline = {'corner': 'tt', 'temperature_C': 25, 'vdd_V': 1.2,
                    'code': driver.target_code, 'vctrl_V': driver.target_ctrl}
        for stage in stages:
            cases = []
            if stage == 'noise':
                cases = [dict(baseline, kind='noise', label='phase3_target_noise')]
            elif stage == 'pvt':
                conditions = [('ss', 1.2, 25), ('ff', 1.2, 25), ('tt', 1.08, 25),
                              ('tt', 1.32, 25), ('tt', 1.2, -40), ('tt', 1.2, 85)]
                for corner, vdd, temperature in conditions:
                    for code in [0, 15, 16, 20, 31]:
                        for ctrl in [.3, 1.0]:
                            label = 'phase3_pvt_{}_v{}_t{}_c{}_u{}'.format(corner, int(round(vdd * 1000)), temperature, code, int(ctrl * 1000))
                            cases.append({'kind': 'pvt', 'label': label, 'corner': corner, 'vdd_V': vdd,
                                          'temperature_C': temperature, 'code': code, 'vctrl_V': ctrl})
            else:
                cases = [dict(baseline, kind='ramp', ramp_ns=ramp,
                              label='phase3_test_withkick_ramp_{}ps'.format(int(ramp * 1000)))
                         for ramp in [.5, 5, 20]]
            groups[stage] = driver.batch(cases, stage)
            summary = {'stage': stage, 'scope': SCOPE, 'records': groups[stage]}
            if stage == 'pvt':
                summary['sampled_conditions'] = pvt_summary(groups[stage])
            atomic_json(driver.root / ('phase3_' + stage + '_summary.json'), summary)
        failures = [r['case_id'] for r in driver.results if r['state'] != 'completed']
        final = {'scope': SCOPE, 'source_sha256': driver.source_hash, 'groups': groups,
                 'failed_case_ids': failures,
                 'remaining': ['Pnoise sideband/accuracy convergence', 'All32 PVT/interior fine monotonicity/overlap margin',
                               'RF/geometry consistency and PEX', 'Unforced physical reference/noise cold start',
                               'Buffer/divider load and complete PLL noise/locking/power/area']}
        atomic_json(driver.root / 'phase3_completion_summary.json', final)
        driver.update('complete_with_failures' if failures else 'complete_sampled_checks',
                      failed_case_ids=failures,
                      conclusion='Analysis completion only; no full-PVT/all-code/locked-PLL success claim.')
    except KeyboardInterrupt:
        STOP.set()
        with ACTIVE_LOCK:
            active = list(ACTIVE.values())
        for process in active:
            stop_process_group(process)
        driver.update('interrupted', conclusion='Completed per-case records retained; rerun resumes only matching completed cases.')
        return 130
    except Exception as error:
        driver.update('failed', error=repr(error))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
