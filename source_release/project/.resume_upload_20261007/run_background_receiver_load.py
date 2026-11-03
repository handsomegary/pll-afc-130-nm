"""Headless, single-worker RF receiver loading and bounded 3.2 GHz retuning.

Run only after upload/review; importing this module never starts a simulation.
Requires the reviewed run_background_phase3.py beside this file, Python 3.6+.
No PDK edits, divider, CMOS-rail claim, GUI, plots, or automatic upload.
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
import subprocess
import time

import run_background_phase3 as helper

VERSION = 'receiver-load-v2'
TARGET = 3.2e9
SCOPE = ('Mixed-RF VCO plus an actual RF NMOS CML receiver; ordinary bias/fine/bank, '
         'ideal reference/passives and assumed stress geometry. Pre-layout loading '
         'sensitivity only; ideal bias-source noise remains provisional. No divider, '
         'CMOS-rail interface, PEX, autonomous cold-start or full PLL/FoM proof.')


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else None


def verified(record):
    if not isinstance(record, dict):
        return False
    if record.get('verified') is True or record.get('valid') is True:
        return True
    return any(verified(record.get(key)) for key in
               ['best_measured', 'measurement', 'target', 'selected', 'best', 'transient'])


def netlist_name(record):
    if not isinstance(record, dict):
        return None
    for key in ['netlist_path', 'netlist', 'source_netlist', 'selected_netlist']:
        if isinstance(record.get(key), str) and record[key].endswith('.scs'):
            return record[key]
    for key in ['best_measured', 'target', 'selected', 'best', 'transient', 'artifacts']:
        child = record.get(key)
        if isinstance(child, dict):
            found = netlist_name(child)
            if found:
                return found
    return None


def prepare_base(source):
    if 'n12_ckt_rf' not in source or 'section=mos_' not in source:
        raise ValueError('A reviewed mixed-RF source netlist is required.')
    if re.search(r'(?m)^\s*(?:XRX|VBUF|VGINP|VGINN)\b', source):
        raise ValueError('Source already contains the receiver/probe names.')
    lines, saves = [], []
    for line in source.splitlines():
        stripped = line.strip()
        if re.match(r'^save\s', stripped):
            saves.extend(stripped.split()[1:])
            continue
        # Remove named analyses, preserving all devices, bias sources and ICs.
        if re.match(r'^\S+\s+(?:\([^)]*\)\s+)?(?:tran|dc|pss|pnoise|info)\b', stripped):
            continue
        lines.append(line)
    saves.extend(['vdd', 'VDD:p', 'bn', 'ctrl', 'out0', 'out180', 'out90', 'out270',
                  'XOSC.XSTAGE0.XTAILMAIN.main:d', 'XOSC.XSTAGE0.XTAILREGEN.main:d'])
    return '\n'.join(lines) + '\n', list(dict.fromkeys(saves))


def render(base, saves, width, code, ctrl, noise=False, sidebands=60):
    text = helper.change_parameter(base, 'VCTRLVAL', '{:.12g}'.format(ctrl))
    for bit in range(5):
        text = helper.change_parameter(text, 'CODE' + str(bit), (code >> bit) & 1)
    names = list(saves)
    if width:
        text += ('\n// Actual RF receiver: input Wtot={width}um; tail Wtot=30um/L=.39um.\n'
                 '// VBUF measures total receiver supply current without a supply drop.\n'
                 'subckt cml_load_receiver (vdd vss inp inn bn op on)\n'
                 'XINP (on inp rxcs vss) n12_ckt_rf lr=.13u wr={finger:.12g}u nf=4 '
                 'sar=.4u sbr=.4u mr=1 mismod=0\n'
                 'XINN (op inn rxcs vss) n12_ckt_rf lr=.13u wr={finger:.12g}u nf=4 '
                 'sar=.4u sbr=.4u mr=1 mismod=0\n'
                 'XTAIL (rxcs bn vss vss) n12_ckt_rf lr=.39u wr=2.5u nf=12 '
                 'sar=.4u sbr=.4u mr=1 mismod=0\n'
                 'RXP (op vdd) resistor r=1k\n'
                 'RXN (on vdd) resistor r=1k\n'
                 'ends cml_load_receiver\n'
                 'VBUF (vdd vddrx) vsource dc=0\n'
                 'VGINP (out0 rxginp) vsource dc=0\n'
                 'VGINN (out180 rxginn) vsource dc=0\n'
                 'XRX (vddrx 0 rxginp rxginn bn rxp rxn) cml_load_receiver\n').format(
                     width=width, finger=width / 4.0)
        names += ['vddrx', 'VBUF:p', 'rxp', 'rxn', 'XRX.rxcs',
                  'XRX.XTAIL.main:d', 'XRX.XINP.main:d', 'XRX.XINN.main:d',
                  'VGINP:p', 'VGINN:p']
    for start in range(0, len(names), 10):
        text += 'save ' + ' '.join(names[start:start + 10]) + '\n'
    if noise:
        text += ('pss (out0 out180) pss fund=3.2G tstab=50n harms={n} '
                 'errpreset=conservative harmonicbalance=no maxstep=.5p '
                 'tstabmethod=gear2only method=gear2only\n'
                 'pnoise (out0 out180) pnoise start=10k stop=100M dec=30 '
                 'sweeptype=relative relharmnum=1 maxsideband={n} '
                 'noiseout=[pm] noisetype=timeaverage\n').format(n=sidebands)
    else:
        text += 'rxDCOP info what=oppoint where=rawfile\n'
        text += 'tran tran stop=50n maxstep=1p errpreset=conservative skipdc=no\n'
    return text


def receiver_measurement(path, begin, end):
    _, data = helper.read_psf(path)
    all_t = data['time']
    idx = [i for i, value in enumerate(all_t) if begin <= value <= end]
    t = [all_t[i] for i in idx]
    names = ['rxp', 'rxn', 'vdd', 'VBUF:p', 'XRX.rxcs', 'XRX.XTAIL.main:d',
             'XRX.XINP.main:d', 'XRX.XINN.main:d', 'out0', 'out180', 'VGINP:p', 'VGINN:p']
    if len(t) < 3 or any(len(data.get(name, [])) != len(all_t) for name in names):
        raise ValueError('Missing receiver saved waveform or measurement samples.')
    waves = {name: [data[name][i] for i in idx] for name in names}
    diff = [p - n for p, n in zip(waves['rxp'], waves['rxn'])]
    mean = helper.time_mean(t, diff)
    edge = helper.crossings(t, [v - mean for v in diff])
    amplitude = max(diff) - min(diff)
    frequency = (len(edge) - 1) / (edge[-1] - edge[0]) if len(edge) >= 20 and amplitude > .01 else None
    input_diff = [p - n for p, n in zip(waves['out0'], waves['out180'])]
    input_vpp = max(input_diff) - min(input_diff)
    return {'differential_vpp_V': amplitude, 'differential_mean_V': mean,
            'frequency_Hz': frequency, 'rising_crossings': len(edge),
            'common_mode_mean_V': helper.time_mean(t, [(p + n) / 2 for p, n in zip(waves['rxp'], waves['rxn'])]),
            'input_common_mode_mean_V': helper.time_mean(t, [(p + n) / 2 for p, n in zip(waves['out0'], waves['out180'])]),
            'large_signal_vpp_gain': amplitude / input_vpp if input_vpp > .001 else None,
            'supply_power_W': helper.time_mean(t, [v * i for v, i in zip(waves['vdd'], waves['VBUF:p'])]),
            'input_loading_current_rms_A': {name: math.sqrt(helper.time_mean(t, [i * i for i in waves[name]]))
                                            for name in ['VGINP:p', 'VGINN:p']},
            'input_loading_mean_power_W': helper.time_mean(t, [vp * ip + vn * inn for vp, ip, vn, inn in
                zip(waves['out0'], waves['VGINP:p'], waves['out180'], waves['VGINN:p'])]),
            'tail_mean_A': helper.time_mean(t, waves['XRX.XTAIL.main:d']),
            'source_mean_V': helper.time_mean(t, waves['XRX.rxcs']),
            'input_branch_mean_A': {name: helper.time_mean(t, waves[name])
                                    for name in ['XRX.XINP.main:d', 'XRX.XINN.main:d']}}


def loading_comparison(baseline, fixed):
    valid = bool(baseline.get('valid') and fixed.get('valid'))
    comparison = {'fixed_code_and_control': True, 'baseline_frequency_Hz': baseline['frequency_Hz'],
                  'loading_comparison_valid': valid,
                  'validity_reason': 'valid unloaded and loaded oscillation/interface screens' if valid else
                  'loaded oscillation/interface screen failed; crossing frequency excluded from loading comparison'}
    if valid:
        comparison['frequency_shift_Hz'] = fixed['frequency_Hz'] - baseline['frequency_Hz']
        comparison['frequency_shift_fraction'] = fixed['frequency_Hz'] / baseline['frequency_Hz'] - 1
    if fixed.get('supply_power_W') is not None:
        comparison['added_total_supply_power_W'] = fixed['supply_power_W'] - baseline['supply_power_W']
        comparison['vco_differential_vpp_ratio'] = fixed['differential_vpp_V'] / baseline['differential_vpp_V']
    return comparison


def pss_receiver_measurement(waveform):
    _, data = helper.read_psf(waveform)
    t = data.get('time', [])
    if len(t) < 2 or any(len(data.get(name, [])) != len(t) for name in ['rxp', 'rxn']):
        raise ValueError('Missing loaded PSS receiver waveforms.')
    diff = [p - n for p, n in zip(data['rxp'], data['rxn'])]
    return {'receiver_differential_vpp_V': max(diff) - min(diff),
            'receiver_common_mode_mean_V': helper.time_mean(t, [(p + n) / 2 for p, n in zip(data['rxp'], data['rxn'])])}


class Driver:
    def __init__(self, args):
        self.args = args
        self.project = Path(args.project).resolve()
        if not self.project.is_dir():
            raise ValueError('Project does not exist.')
        self.root = helper.contained(self.project, self.project / 'results' / 'receiverload')
        self.netlists = helper.contained(self.project, self.project / 'netlists' / 'receiverload')
        self.logs = helper.contained(self.project, self.project / 'logs' / 'receiverload')
        for directory in [self.root, self.netlists, self.logs]:
            directory.mkdir(parents=True, exist_ok=True)
        # A second instance cannot concurrently overwrite this driver's status/cache.
        import fcntl
        self.lock = (self.root / 'driver.lock').open('a+')
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.started = time.time()
        self.status = self.project / 'results' / 'receiverload_status.json'
        self.records = []
        self.spectre = shutil.which(args.spectre)
        self.ocean = shutil.which(args.ocean)
        if not self.spectre or (args.noise and not self.ocean):
            raise ValueError('Required Spectre/OCEAN executable not found.')

    def update(self, stage, **fields):
        value = {'version': VERSION, 'stage': stage, 'pid': os.getpid(),
                 'started_unix': self.started, 'updated_unix': time.time(),
                 'cases_completed_or_resumed': len(self.records), 'max_workers': 1,
                 'scope': SCOPE}
        value.update(fields)
        helper.atomic_json(self.status, value)
        print(json.dumps(value), flush=True)

    def select_source(self):
        chosen_path = self.project / 'results' / 'biasopt_selected.json'
        dependency = self.project / 'results' / 'biasopt_status.json'
        dep = None
        if self.args.wait_bias_opt:
            self.update('waiting_for_bias_opt', maximum_wait_s=self.args.wait_seconds)
            deadline = time.monotonic() + self.args.wait_seconds
            while True:
                dep = read_json(dependency) or {}
                if dep.get('stage') == 'complete':
                    break
                if dep.get('stage') in ['failed', 'stopped', 'interrupted', 'needs_design_review', 'complete_with_failures']:
                    raise ValueError('Bias optimisation ended without verified completion: ' + str(dep.get('stage')))
                if time.monotonic() >= deadline:
                    raise ValueError('Bias optimisation wait expired; no simulations started.')
                if helper.STOP.wait(10):
                    raise KeyboardInterrupt()
        chosen = read_json(chosen_path)
        if self.args.wait_bias_opt:
            if not isinstance(chosen, dict) or chosen.get('verified') is not True:
                raise ValueError('Completed bias run lacks an explicitly verified selection; RF fallback refused.')
            for key in ['version', 'source_sha256']:
                if not isinstance(dep.get(key), str) or not dep[key] or chosen.get(key) != dep[key]:
                    raise ValueError('Bias status/selection {} disagree or are missing.'.format(key))
        if chosen is not None:
            if not verified(chosen):
                raise ValueError('Existing biasopt_selected.json has no explicit verified/valid flag.')
            name = netlist_name(chosen)
            if not name:
                raise ValueError('Verified bias selection has no netlist path.')
            self.selection_kind = 'biasopt_selected'
        else:
            chosen = read_json(self.project / 'results' / 'rfrefine_selected.json')
            if not verified(chosen):
                raise ValueError('No verified RF fallback selection found.')
            name = netlist_name(chosen)
            if not name:
                label = chosen.get('best_measured', {}).get('label')
                if not label or not re.fullmatch(r'[A-Za-z0-9_.-]+', label):
                    raise ValueError('RF fallback label missing or invalid.')
                name = str(self.project / 'netlists' / ('rfrefine_' + label + '.scs'))
            self.selection_kind = 'rfrefine_selected'
        path = Path(name)
        if not path.is_absolute():
            path = self.project / path
        self.source_path = helper.contained(self.project, path)
        source = self.source_path.read_text()
        self.source_hash = hashlib.sha256(source.encode()).hexdigest()
        self.base, self.saves = prepare_base(source)
        bits = [float(helper.assignment(source, 'CODE' + str(i))) for i in range(5)]
        if any(bit not in [0, 1] for bit in bits):
            raise ValueError('Selected CODE parameters must each be exactly 0 or 1.')
        self.code = sum(int(bit) << i for i, bit in enumerate(bits))
        self.ctrl = float(helper.assignment(source, 'VCTRLVAL'))
        if not 0 <= self.code <= 31 or not self.args.ctrl_min <= self.ctrl <= self.args.ctrl_max:
            raise ValueError('Selected operating point outside bounded code/control window.')
        if self.selection_kind == 'biasopt_selected':
            try:
                meta_code, meta_ctrl = float(chosen['code']), float(chosen['vctrl_V'])
            except (KeyError, TypeError, ValueError):
                raise ValueError('Bias selection lacks numeric code/control metadata.')
            if meta_code != self.code or not math.isfinite(meta_ctrl) or abs(meta_ctrl-self.ctrl) > 1e-9:
                raise ValueError('Selected code/control metadata disagree with actual netlist.')
        self.selection = chosen
        self.update('source_selected', source_netlist=str(self.source_path),
                    source_sha256=self.source_hash, selection_kind=self.selection_kind,
                    selection_version=chosen.get('version'),
                    code=self.code, vctrl_V=self.ctrl)

    def run_case(self, width, code, ctrl, noise=False):
        text = render(self.base, self.saves, width, code, ctrl, noise, self.args.sidebands)
        identity = hashlib.sha256((VERSION + text).encode()).hexdigest()[:16]
        stem = 'rx{}_c{}_v{}_{}_{}'.format(width, code, round(ctrl * 1e6), 'pn' if noise else 'tran', identity)
        cache = self.root / (stem + '.json')
        prior = read_json(cache)
        if prior and prior.get('state') == 'completed' and all(Path(p).exists() for p in prior.get('artifacts', [])):
            self.records.append(prior)
            return prior
        attempt = 1
        while (self.netlists / (stem + '_a{}.scs'.format(attempt))).exists():
            attempt += 1
        tag = stem + '_a{}'.format(attempt)
        netlist, raw, log = self.netlists / (tag + '.scs'), self.root / (tag + '.raw'), self.logs / (tag + '.log')
        netlist.write_text(text)
        record = {'state': 'running', 'case_id': stem, 'input_pair_total_width_um': width,
                  'code': code, 'vctrl_V': ctrl, 'source_sha256': self.source_hash,
                  'netlist_path': str(netlist), 'valid': False, 'scope': SCOPE}
        helper.atomic_json(cache, record)
        self.update('noise_running' if noise else 'transient_running', current_case=tag)
        deadline = time.monotonic() + 300
        try:
            rc = helper.run_process([self.spectre, str(netlist), '-format', 'psfascii', '-raw', str(raw), '+log', str(log)],
                                    self.logs / (tag + '.stdout'), self.project, deadline)
            record['rc'] = rc
            record['spectre_log_summary'] = helper.spectral_log_summary(log)
            record['artifacts'] = [str(netlist), str(log)]
            if rc or record['spectre_log_summary']['errors'] not in [None, 0]:
                raise ValueError('Spectre failed: rc={}'.format(rc))
            if noise:
                self.measure_noise(record, raw, tag, deadline)
            else:
                self.measure_transient(record, raw)
            record['state'] = 'completed'
        except (Exception, KeyboardInterrupt) as error:
            record.update(state='failed', error=repr(error))
            helper.atomic_json(cache, record)
            if isinstance(error, KeyboardInterrupt):
                raise
        record['finished_unix'] = time.time()
        helper.atomic_json(cache, record)
        self.records.append(record)
        return record

    def measure_transient(self, record, raw):
        waveform = raw / 'tran.tran.tran'
        early = helper.measure_transient(waveform, 25e-9, 33e-9)
        late = helper.measure_transient(waveform, 40e-9, 48e-9)
        a1, a2 = early['differential_vpp_V'], late['differential_vpp_V']
        f1, f2 = early['frequency_Hz'], late['frequency_Hz']
        stats = late['waveform_stats']
        watched = ['bn', 'XOSC.XSTAGE0.XTAILMAIN.main:d', 'XOSC.XSTAGE0.XTAILREGEN.main:d']
        if any(name not in stats or name not in early['waveform_stats'] for name in watched):
            raise ValueError('Missing actual VCO bias/tail saved waveform.')
        drift = {name: abs(stats[name]['mean'] / early['waveform_stats'][name]['mean'] - 1)
                 if early['waveform_stats'][name]['mean'] else None for name in watched}
        record.update(frequency_Hz=f2, q_frequency_Hz=late['q_frequency_Hz'],
                      differential_vpp_V=a2, q_differential_vpp_V=late['q_differential_vpp_V'],
                      q_rising_phase_deg=late['q_rising_phase_deg'], supply_power_W=late['supply_power_W'],
                      early_frequency_Hz=f1, amplitude_ratio_late_over_early=a2 / a1 if a1 else None,
                      bias_and_tail_relative_drift=drift, node_mean_V={k: stats[k]['mean'] for k in ['out0', 'out180', 'bn']})
        record['valid'] = bool(early['valid_screen'] and late['valid_screen'] and
                               early['rising_crossings'] >= 20 and late['rising_crossings'] >= 20 and
                               f1 and f2 and abs(f2 / f1 - 1) < .01 and a1 and .9 < a2 / a1 < 1.1 and
                               a2 > .1 and late['q_differential_vpp_V'] > .1 and
                               all(value is not None and value < .01 for value in drift.values()))
        if record['input_pair_total_width_um']:
            rxearly = receiver_measurement(waveform, 25e-9, 33e-9)
            rx = receiver_measurement(waveform, 40e-9, 48e-9)
            record['receiver'] = rx
            rxdrift = abs(rx['tail_mean_A'] / rxearly['tail_mean_A'] - 1) if rxearly['tail_mean_A'] else None
            record['receiver_tail_relative_drift'] = rxdrift
            record['receiver_interface_valid'] = bool(rx['frequency_Hz'] and f2 and
                abs(rx['frequency_Hz'] / f2 - 1) < .01 and rx['differential_vpp_V'] > .1 and
                rx['supply_power_W'] > 0 and rx['tail_mean_A'] > 0 and rxdrift is not None and rxdrift < .01)
            record['valid'] = record['valid'] and record['receiver_interface_valid']
        record['artifacts'].append(str(waveform))

    def measure_noise(self, record, raw, tag, deadline):
        waveform = helper.pss_waveform(raw)
        measurement = helper.measure_pss(waveform)
        if measurement['differential_vpp_V'] <= .1 or measurement['target_relative_error'] > .001:
            raise ValueError('Loaded PSS missed frequency or amplitude screen.')
        measurement.update(pss_receiver_measurement(waveform))
        record['measurement'] = measurement
        if measurement['receiver_differential_vpp_V'] <= .1:
            record['validity_reason'] = 'PSS receiver differential swing at or below 100mV'
            raise ValueError('Loaded PSS receiver differential swing must exceed 100mV.')
        ocean_file = self.netlists / (tag + '.ocn')
        curve, scalar = self.root / (tag + '_pn_ssb.txt'), self.root / (tag + '_pn_scalars.txt')
        ocean_file.write_text(helper.ocean_script(raw, curve, scalar))
        rc = helper.run_process([self.ocean, '-nograph', '-restore', str(ocean_file)],
                                self.logs / (tag + '_ocean.stdout'), self.project, deadline)
        if rc or not curve.exists() or not scalar.exists():
            raise ValueError('Loaded OCEAN phaseNoise extraction failed.')
        points = dict(line.split() for line in scalar.read_text().splitlines() if len(line.split()) == 2)
        for key, offset in [('PN1M', 1e6), ('PN10M', 1e7)]:
            value = float(points[key])
            if not math.isfinite(value):
                raise ValueError('Nonfinite loaded SSB phase noise.')
            measurement[key + '_dBc_Hz'] = value
            measurement[key + '_loaded_VCO_plus_receiver_FoM_dB'] = value - 20 * math.log10(
                measurement['actual_carrier_Hz'] / offset) + 10 * math.log10(measurement['pss_supply_power_W'] * 1000)
        record.update(measurement=measurement, valid=True, sidebands=self.args.sidebands,
                      validity_reason='PSS VCO/receiver swings exceed 100mV and carrier target is within 0.1%',
                      noise_band_Hz=[1e4, 1e8], normalization='OCEAN phaseNoise: SSB dBc/Hz, actual PSS carrier; total VDD power')
        record['artifacts'] += [str(p) for p in [waveform, ocean_file, curve, scalar]]

    def retune(self, width, fixed):
        tested, code, bracket = [], self.code, None
        for step in range(self.args.coarse_bands):
            if not 0 <= code <= 31 or code in tested:
                break
            tested.append(code)
            lo = self.run_case(width, code, self.args.ctrl_min)
            hi = self.run_case(width, code, self.args.ctrl_max)
            if not lo['valid'] or not hi['valid']:
                return {'state': 'rejected', 'reason': 'invalid/no-oscillation endpoint', 'tested_codes': tested, 'endpoints': [lo, hi]}
            fl, fh = lo['frequency_Hz'], hi['frequency_Hz']
            if fh <= fl:
                return {'state': 'rejected', 'reason': 'nonincreasing fine endpoints', 'tested_codes': tested, 'endpoints': [lo, hi]}
            if fl <= TARGET <= fh:
                bracket = [lo, hi]
                break
            code += 1 if fh < TARGET else -1
        if not bracket:
            return {'state': 'rejected', 'reason': 'no bracket in bounded adjacent-code window', 'tested_codes': tested}
        low, high = self.args.ctrl_min, self.args.ctrl_max
        candidates = list(bracket)
        if fixed['valid'] and fixed['code'] == code:
            candidates.append(fixed)
        for step in range(6):
            value = self.run_case(width, code, (low + high) / 2)
            if not value['valid']:
                return {'state': 'rejected', 'reason': 'invalid/no-oscillation interior', 'tested_codes': tested, 'endpoints': bracket, 'failed_interior': value}
            if not bracket[0]['frequency_Hz'] <= value['frequency_Hz'] <= bracket[1]['frequency_Hz']:
                return {'state': 'rejected', 'reason': 'interior frequency outside initial bracket', 'tested_codes': tested}
            candidates.append(value)
            if abs(value['frequency_Hz'] - TARGET) <= 1e6:
                break
            if value['frequency_Hz'] < TARGET:
                low = value['vctrl_V']
            else:
                high = value['vctrl_V']
        best = min(candidates, key=lambda item: abs(item['frequency_Hz'] - TARGET))
        acceptable = abs(best['frequency_Hz'] / TARGET - 1) <= .001
        return {'state': 'retuned' if acceptable else 'rejected', 'tested_codes': tested,
                'endpoints': bracket, 'best_measured': best, 'verified': acceptable,
                'target_error_Hz': best['frequency_Hz'] - TARGET,
                'reason': None if acceptable else 'target error exceeds 0.1% after six bisections'}

    def execute(self):
        self.select_source()
        baseline = self.run_case(0, self.code, self.ctrl)
        if not baseline['valid'] or abs(baseline['frequency_Hz'] / TARGET - 1) > .01:
            raise ValueError('Unloaded selected baseline failed or was not within 1% of 3.2 GHz; comparison stopped.')
        groups = []
        for width in [6, 12]:
            fixed = self.run_case(width, self.code, self.ctrl)
            comparison = loading_comparison(baseline, fixed)
            retuned = self.retune(width, fixed)
            groups.append({'input_pair_total_width_um': width, 'fixed_operating_point': fixed,
                           'measured_loading_vs_unloaded': comparison, 'retune': retuned})
            helper.atomic_json(self.root / 'receiverload_progress.json', {'baseline': baseline, 'receivers': groups, 'scope': SCOPE})
        good = [group for group in groups if group['retune'].get('verified')]
        selected = min(good, key=lambda g: g['input_pair_total_width_um']) if good else None
        if selected:
            selected_record = selected['retune']['best_measured']
            selection = {'verified': True, 'netlist_path': selected_record['netlist_path'],
                         'code': selected_record['code'], 'vctrl_V': selected_record['vctrl_V'],
                         'best_measured': selected_record, 'scope': SCOPE}
            helper.atomic_json(self.project / 'results' / 'receiverload_selected.json', selection)
        noise = None
        if selected and self.args.noise:
            best = selected['retune']['best_measured']
            noise = self.run_case(selected['input_pair_total_width_um'], best['code'], best['vctrl_V'], noise=True)
        conclusion = {'scope': SCOPE, 'version': VERSION, 'source_netlist': str(self.source_path),
                      'source_sha256': self.source_hash, 'selection_kind': self.selection_kind,
                      'baseline': baseline, 'receivers': groups, 'selected': selected, 'noise': noise,
                      'remaining': 'Actual CML latch/divider and level conversion; reference-noise model; PVT/loading/startup and layout/PEX; full PLL.',
                      'noise_sideband_convergence_checked': False}
        helper.atomic_json(self.root / 'receiverload_completion_summary.json', conclusion)
        helper.atomic_json(self.project / 'results' / 'receiverload_completion_summary.json', conclusion)
        stage = 'complete' if selected and (not self.args.noise or noise['valid']) else 'needs_design_review'
        self.update(stage, summary_path=str(self.root / 'receiverload_completion_summary.json'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=helper.DEFAULT_PROJECT)
    parser.add_argument('--wait-bias-opt', action='store_true')
    parser.add_argument('--wait-seconds', type=int, default=3600, help='Maximum dependency wait, 1..3600 seconds.')
    parser.add_argument('--ctrl-min', type=float, default=.3)
    parser.add_argument('--ctrl-max', type=float, default=1.0)
    parser.add_argument('--coarse-bands', type=int, default=6, help='At most this many adjacent code bands, 1..8.')
    parser.add_argument('--spectre', default='@SPECTRE_ROOT@/bin/spectre')
    parser.add_argument('--ocean', default='ocean')
    parser.add_argument('--noise', action='store_true', help='One loaded PSS/Pnoise on the smallest passing receiver only.')
    parser.add_argument('--sidebands', type=int, default=60, choices=[30, 60])
    args = parser.parse_args(argv)
    if not 1 <= args.wait_seconds <= 3600 or not 1 <= args.coarse_bands <= 8 or not 0 <= args.ctrl_min < args.ctrl_max <= 1.2:
        parser.error('Dependency wait, code bound or core control voltage out of range.')
    driver = None

    def interrupt(signum, frame):
        helper.STOP.set()
        raise KeyboardInterrupt('Signal {}'.format(signum))

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    try:
        driver = Driver(args)
        driver.execute()
        return 0
    except KeyboardInterrupt:
        helper.STOP.set()
        with helper.ACTIVE_LOCK:
            processes = list(helper.ACTIVE.values())
        for process in processes:
            helper.stop_process_group(process)
        if driver:
            driver.update('stopped', completed_results_retained=True)
        return 130
    except Exception as error:
        if driver:
            driver.update('failed', error=repr(error))
        else:
            print(json.dumps({'stage': 'failed_before_simulation', 'error': repr(error)}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
