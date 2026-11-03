"""Headless sampled RF VCO validation, using the chosen bias revision."""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import time

import run_background_phase3 as helper

PROJECT = '@PROJECT_ROOT@'
SCOPE = ('Mixed RF core/tails; ordinary reference/fine/bank; assumed stress '
         'geometry, ideal passives/reference source, unloaded VCO domain. '
         'TT endpoints/interior samples and sampled PVT only, no PEX or PLL signoff.')


def choose_source(project, wait):
    dependency = None
    if wait:
        deadline = time.monotonic()+3600
        while True:
            status = project/'results/biasopt_status.json'
            data = json.loads(status.read_text()) if status.exists() else {}
            if data.get('stage') == 'complete':
                dependency = data
                break
            if data.get('stage') in ['needs_design_review', 'failed', 'stopped', 'interrupted', 'complete_with_failures']:
                raise RuntimeError('Bias optimization did not complete: '+str(data.get('stage')))
            if time.monotonic() > deadline:
                raise RuntimeError('Bias optimization wait exceeded one hour.')
            time.sleep(10)
    candidate = project/'results/biasopt_selected.json'
    data = json.loads(candidate.read_text()) if candidate.exists() else None
    if wait:
        if not isinstance(data, dict) or data.get('verified') is not True:
            raise ValueError('Completed bias run lacks an explicitly verified selection; RF fallback refused.')
        for key in ['version', 'source_sha256']:
            if not isinstance(dependency.get(key), str) or not dependency[key] or data.get(key) != dependency[key]:
                raise ValueError('Bias status/selection '+key+' disagree or are missing.')
    if isinstance(data, dict) and data.get('verified') is True:
        if not isinstance(data.get('netlist_path'), str) or not data['netlist_path'].endswith('.scs'):
            raise ValueError('Verified bias selection has no netlist path.')
        source = Path(data['netlist_path'])
        if not source.is_absolute(): source = project/source
        source = helper.contained(project, source)
        text = source.read_text()
        bits = [float(helper.assignment(text, 'CODE'+str(i))) for i in range(5)]
        if any(bit not in [0, 1] for bit in bits):
            raise ValueError('Selected CODE parameters must each be exactly 0 or 1.')
        actual_code = sum(int(bit) << i for i, bit in enumerate(bits))
        actual_ctrl = float(helper.assignment(text, 'VCTRLVAL'))
        try:
            meta_code, meta_ctrl = float(data['code']), float(data['vctrl_V'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('Bias selection lacks numeric code/control metadata.')
        if meta_code != actual_code or not math.isfinite(actual_ctrl) or not math.isfinite(meta_ctrl) or abs(meta_ctrl-actual_ctrl)>1e-9:
            raise ValueError('Selected code/control metadata disagree with actual netlist.')
        return source, dict(data, selection_kind='biasopt_selected', selection_version=data.get('version'))
    if wait:
        raise ValueError('Verified bias selection unavailable; RF fallback refused.')
    prior = json.loads((project/'results/rfrefine_selected.json').read_text())
    return project/'netlists'/('rfrefine_'+prior['best_measured']['label']+'.scs'), dict(
        prior, selection_kind='rfrefine_selected', selection_version=prior.get('version'))


def prepare_source(text):
    if 'n12_ckt_rf' not in text:
        raise ValueError('RF source required.')
    lines = [line for line in text.splitlines()
             if not re.match(r'^\s*\S+\s+(?:\([^)]*\)\s+)?(?:dc|tran|pss|pnoise|info)\b', line)
             and not re.match(r'^\s*save\s', line)]
    lines.append('save vdd ctrl bn bp out0 out180 out90 out270 VDD:p')
    for stage in ['XSTAGE0', 'XSTAGE1']:
        prefix = 'XOSC.'+stage+'.'
        lines.append('save '+prefix+'cs1 '+prefix+'cs2 '+prefix+'XTAILMAIN.main:d '+prefix+'XTAILREGEN.main:d')
    return '\n'.join(lines)+'\n'


def render(base, spec):
    text = base
    text = helper.change_parameter(text, 'VDDVAL', spec['vdd_V'])
    text = helper.change_parameter(text, 'VCTRLVAL', spec['vctrl_V'])
    for bit in range(5):
        text = helper.change_parameter(text, 'CODE'+str(bit), (spec['code'] >> bit) & 1)
    text = helper.change_temperature(text, spec['temperature_C'])
    for pattern, replacement in [
            (r'(ms013_io33_v2p6_7p_spe\.lib"\s+section=)\w+', spec['corner']),
            (r'(ms013_io33_rf_v1p9_spe\.lib"\s+section=)mos_\w+', 'mos_'+spec['corner'])]:
        text, count = re.subn(pattern, lambda m: m.group(1)+replacement, text)
        if count != 1:
            raise ValueError('Unexpected paired-corner mapping count.')
    if spec['kind'] == 'gain':
        for stage in ['XSTAGE0', 'XSTAGE1']:
            for device in ['XTAILMAIN', 'XTAILREGEN', 'XMAIN1', 'XREGEN1']:
                node = 'XOSC.'+stage+'.'+device+'.main'
                text += 'save '+node+':vds '+node+':vdsat '+node+':vgs\n'
    text += 'tran tran stop=70n maxstep=1p errpreset=conservative skipdc=no\n'
    return text


class Batch:
    def __init__(self, args, source, selection):
        self.args = args
        self.project = Path(args.project).resolve()
        self.source = source.resolve()
        self.source.relative_to(self.project)
        self.base = prepare_source(source.read_text())
        self.source_hash = hashlib.sha256(self.base.encode()).hexdigest()
        self.selection = selection
        self.code = sum(int(float(helper.assignment(self.base, 'CODE'+str(i)))) << i for i in range(5))
        self.ctrl = float(helper.assignment(self.base, 'VCTRLVAL'))
        self.root = self.project/'results/rfvalidation'
        self.root.mkdir(exist_ok=True)
        self.results = []
        self.started = time.time()

    def update(self, stage, **fields):
        data = {'stage': stage, 'pid': os.getpid(), 'started_unix': self.started,
                'updated_unix': time.time(), 'cases_completed_or_resumed': len(self.results),
                'source_netlist': str(self.source), 'source_sha256': self.source_hash,
                'selection_kind': self.selection.get('selection_kind'),
                'selection_version': self.selection.get('selection_version'),
                'scope': SCOPE, 'max_workers': self.args.max_workers}
        data.update(fields)
        helper.atomic_json(self.project/'results/rfvalidation_status.json', data)
        print(json.dumps(data), flush=True)

    def case(self, spec):
        text = render(self.base, spec)
        digest = hashlib.sha256(text.encode()).hexdigest()[:14]
        case_id = '{}_c{}_u{}_{}_{}'.format(spec['kind'], spec['code'], round(spec['vctrl_V']*1e6), spec['condition'], digest)
        cached = self.root/(case_id+'.json')
        if cached.exists():
            data = json.loads(cached.read_text())
            if data.get('state') == 'completed' and Path(data['raw_waveform']).exists():
                data['resumed'] = True
                return data
        attempt = 1
        while (self.project/'netlists'/('rfvalidation_'+case_id+'_a{}.scs'.format(attempt))).exists():
            attempt += 1
        tag = 'rfvalidation_'+case_id+'_a{}'.format(attempt)
        netlist = self.project/'netlists'/(tag+'.scs')
        raw = self.root/(tag+'.raw')
        log = self.project/'logs'/(tag+'.log')
        netlist.write_text(text)
        result = {'case_id': case_id, 'specification': spec, 'state': 'running',
                  'netlist_path': str(netlist), 'source_sha256': self.source_hash, 'scope': SCOPE}
        try:
            rc = helper.run_process(['spectre', str(netlist), '-format', 'psfascii', '-raw', str(raw), '+log', str(log)],
                                    self.project/'logs'/(tag+'.stdout'), self.project, time.monotonic()+300)
            result['spectre_rc'] = rc
            result['spectre_log_summary'] = helper.spectral_log_summary(log)
            if rc:
                raise RuntimeError('Spectre rc {}'.format(rc))
            waveform = raw/'tran.tran.tran'
            late = helper.measure_transient(waveform, 55e-9, 68e-9)
            early = helper.measure_transient(waveform, 40e-9, 53e-9)
            for measurement in [early, late]:
                if min(measurement['differential_vpp_V'], measurement['q_differential_vpp_V']) < .05:
                    measurement['numerical_crossing_frequency_Hz'] = measurement['frequency_Hz']
                    measurement['frequency_Hz'] = None
            result['measurement'] = late
            result['earlier_measurement'] = early
            f0, f1 = early['frequency_Hz'], late['frequency_Hz']
            a0, a1 = early['differential_vpp_V'], late['differential_vpp_V']
            bias_keys = ['bn']+[key for key in late['waveform_stats'] if key.endswith('.main:d')]
            drift = {key: abs(late['waveform_stats'][key]['mean']/early['waveform_stats'][key]['mean']-1)
                     for key in bias_keys if early['waveform_stats'][key]['mean']}
            result['bias_tail_relative_drift'] = drift
            result['valid_sustained_screen'] = bool(early['valid_screen'] and late['valid_screen'] and f0 and f1
                and min(a0, a1, early['q_differential_vpp_V'], late['q_differential_vpp_V']) > .1
                and abs(f1/f0-1)<.01 and abs(a1/a0-1)<.1 and all(value<.01 for value in drift.values()))
            headroom = {}
            for name, stats in late['waveform_stats'].items():
                if name.endswith(':vds'):
                    sat = name[:-4]+':vdsat'
                    if sat in late['waveform_stats']:
                        headroom[name] = {'VDS_min_V': stats['min'], 'VDSAT_max_V': late['waveform_stats'][sat]['max'],
                                         'conservative_margin_V': stats['min']-late['waveform_stats'][sat]['max']}
            result['intrinsic_headroom_screen'] = headroom
            result['raw_waveform'] = str(waveform)
            result['state'] = 'completed'
        except Exception as error:
            result['state'] = 'failed'
            result['error'] = repr(error)
        helper.atomic_json(cached, result)
        return result

    def batch(self, specs, stage):
        self.update(stage, scheduled_cases=len(specs))
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.args.max_workers)
        collected = []
        try:
            futures = [pool.submit(self.case, spec) for spec in specs]
            for future in concurrent.futures.as_completed(futures):
                value = future.result()
                collected.append(value)
                self.results.append(value)
                helper.atomic_json(self.root/'all_cases.json', self.results)
                self.update(stage, scheduled_cases=len(specs), stage_completed=len(collected))
        except BaseException:
            helper.STOP.set()
            with helper.ACTIVE_LOCK:
                owned = list(helper.ACTIVE.values())
            for process in owned:
                helper.stop_process_group(process)
            raise
        finally:
            pool.shutdown(wait=True)
        return collected


def summarize_bands(records):
    by_point = {(r['specification']['code'], r['specification']['vctrl_V']): r for r in records}
    bands = []
    for code in range(32):
        lo, hi = by_point.get((code, .3)), by_point.get((code, 1.0))
        valid = bool(lo and hi and lo.get('valid_sustained_screen') and hi.get('valid_sustained_screen'))
        f0 = lo.get('measurement', {}).get('frequency_Hz') if lo else None
        f1 = hi.get('measurement', {}).get('frequency_Hz') if hi else None
        bands.append({'code': code, 'valid_endpoints': valid, 'f_low_Hz': f0, 'f_high_Hz': f1})
    overlap = [{'code_pair': [i, i+1], 'overlap_Hz': bands[i]['f_high_Hz']-bands[i+1]['f_low_Hz']
                if bands[i]['valid_endpoints'] and bands[i+1]['valid_endpoints'] else None} for i in range(31)]
    return {'bands': bands, 'adjacent_endpoint_overlaps': overlap,
            'scope': 'Endpoint/interior samples only; no continuous fine sweep, mismatch or PEX proof.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default=PROJECT)
    parser.add_argument('--wait-bias-opt', action='store_true')
    parser.add_argument('--max-workers', type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Signal '+str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    runner = None
    try:
        helper.atomic_json(project/'results/rfvalidation_status.json', {'stage': 'waiting_for_bias' if args.wait_bias_opt else 'starting', 'pid': os.getpid(), 'scope': SCOPE})
        source, selected = choose_source(project, args.wait_bias_opt)
        runner = Batch(args, source, selected)
        base = {'corner': 'tt', 'vdd_V': 1.2, 'temperature_C': 25, 'condition': 'tt_1200_25'}
        gain = runner.batch([dict(base, kind='gain', code=runner.code, vctrl_V=runner.ctrl+delta)
                             for delta in [-.02, -.01, .01, .02]], 'local_gain_headroom')
        good = sorted([r for r in gain if r.get('valid_sustained_screen')], key=lambda r: r['specification']['vctrl_V'])
        derivatives = []
        for low, high in [(0, 3), (1, 2)]:
            if len(good) == 4:
                derivatives.append((good[high]['measurement']['frequency_Hz']-good[low]['measurement']['frequency_Hz']) /
                                   (good[high]['specification']['vctrl_V']-good[low]['specification']['vctrl_V']))
        helper.atomic_json(runner.root/'local_gain_summary.json', {'cases': gain, 'Kvco_Hz_per_V_outer_inner': derivatives, 'scope': SCOPE})
        endpoints = runner.batch([dict(base, kind='band', code=code, vctrl_V=ctrl)
                                  for code in range(32) for ctrl in [.3, 1.0]], 'all32_tt_endpoints')
        interior_codes = sorted(set([7, 8, 15, 16, 23, 24, runner.code, min(31, runner.code+1)]))
        middle = runner.batch([dict(base, kind='interior', code=code, vctrl_V=.65) for code in interior_codes], 'critical_interior_samples')
        helper.atomic_json(runner.root/'tt_bands_summary.json', dict(summarize_bands(endpoints), interior_cases=middle, source_selection=selected))
        pvt = []
        for corner in ['ss', 'ff', 'fnsp', 'snfp']:
            for code in sorted(set([0, runner.code, 31])):
                for ctrl in [.3, 1.0]:
                    pvt.append({'kind': 'pvt', 'corner': corner, 'vdd_V': 1.2, 'temperature_C': 25,
                                'condition': corner+'_1200_25', 'code': code, 'vctrl_V': ctrl})
        for voltage, temperature in [(1.08, 25), (1.2, -40), (1.2, 85)]:
            for code in [7, 8, 15, 16, 23, 24]:
                for ctrl in [.3, 1.0]:
                    pvt.append({'kind': 'pvt', 'corner': 'tt', 'vdd_V': voltage, 'temperature_C': temperature,
                                'condition': 'tt_{}_{}'.format(round(voltage*1000), temperature), 'code': code, 'vctrl_V': ctrl})
        corners = runner.batch(pvt, 'sampled_pvt')
        helper.atomic_json(runner.root/'pvt_summary.json', {'cases': corners, 'scope': SCOPE})
        runner.update('complete_sampled_checks', invalid_screen_case_ids=[r['case_id'] for r in runner.results if not r.get('valid_sustained_screen')],
                      remaining='All32 PVT, full fine monotonicity, mismatch, startup, actual receiver/divider/PLL and PEX remain separate checks.')
    except KeyboardInterrupt:
        helper.STOP.set()
        with helper.ACTIVE_LOCK:
            owned = list(helper.ACTIVE.values())
        for process in owned:
            helper.stop_process_group(process)
        if runner:
            runner.update('stopped', completed_results_retained=True)
        else:
            helper.atomic_json(project/'results/rfvalidation_status.json', {'stage': 'stopped', 'pid': os.getpid(), 'scope': SCOPE})
        return 130
    except Exception as error:
        helper.atomic_json(project/'results/rfvalidation_status.json', {'stage': 'failed', 'pid': os.getpid(), 'error': repr(error), 'scope': SCOPE})
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
