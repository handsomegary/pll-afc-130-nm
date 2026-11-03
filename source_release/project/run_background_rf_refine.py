"""Bounded mixed-RF VCO redesign. Headless, resumable, no PDK edits."""
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time

project = Path('@PROJECT_ROOT@')
os.chdir(str(project))
selected = json.loads((project/'results/phase2_selected_design.json').read_text())
seed = (project/'netlists'/('phase2_'+selected['target']['case']+'.scs')).read_text()
seed = seed.replace('stop=40n', 'stop=50n')
prefix = 'rfrefine'
cases_path = project/'results/rfrefine_cases.json'
status_path = project/'results/rfrefine_status.json'
results = json.loads(cases_path.read_text()) if cases_path.exists() else []
started = time.time()
active = None
scope = ('Mixed RF main/regen/tails, ordinary fine/bank/reference MOS; '
         'TT/1.2V/25C; assumed stress geometry; ideal R and 10uA reference; '
         'not extracted layout, full PLL, or noise signoff.')


def write_json(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def update(stage, **fields):
    value = {'stage': stage, 'pid': os.getpid(), 'started_unix': started,
             'updated_unix': time.time(), 'cases_completed': len(results),
             'scope': scope}
    value.update(fields)
    write_json(status_path, value)
    print(json.dumps(value), flush=True)


def stop_process(proc):
    if proc is None or proc.poll() is not None:
        return
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def interrupted(signum, frame):
    stop_process(active)
    update('stopped', signal=signum)
    raise SystemExit(128+signum)


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)


def launch(args, output, timeout):
    global active
    with open(str(output), 'w') as handle:
        active = subprocess.Popen(args, stdout=handle, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        try:
            code = active.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_process(active)
            code = 124
        finally:
            active = None
    return code


def model_text(design, code, ctrl):
    text = re.sub(r'VCTRLVAL=\S+', 'VCTRLVAL={}'.format(ctrl), seed, count=1)
    text = re.sub(r'parameters CODE0=.*', 'parameters '+' '.join(
        'CODE{}={}'.format(i, (code >> i) & 1) for i in range(5)), text)
    text = text.replace('RLOAD=620', 'RLOAD={}'.format(design['rload']))
    lib = '@TECH_ROOT@/models/spectre/ms013_io33_rf_v1p9_spe.lib'
    text = text.replace('section=tt', 'section=tt\ninclude "'+lib+'" section=mos_tt', 1)
    mapping = [('MMAIN1', 'XMAIN1', 'LCORE', design['main_nf']),
               ('MMAIN2', 'XMAIN2', 'LCORE', design['main_nf']),
               ('MREGEN1', 'XREGEN1', 'LCORE', design['regen_nf']),
               ('MREGEN2', 'XREGEN2', 'LCORE', design['regen_nf']),
               ('MTAILMAIN', 'XTAILMAIN', 'LTAIL', design['main_tail_nf']),
               ('MTAILREGEN', 'XTAILREGEN', 'LTAIL', design['regen_tail_nf'])]
    for old, new, length, nf in mapping:
        pattern = r'\b'+old+r' (\([^\n]+\)) n12 w=\w+ l=\w+'
        replacement = new+r' \1 n12_ckt_rf lr='+length+' wr=3u nf='+str(nf)+' sar=0.4u sbr=0.4u mr=1 mismod=0'
        text, count = re.subn(pattern, replacement, text)
        if count != 1:
            raise ValueError('Unexpected mapping count: '+old)
    text = '\n'.join(line for line in text.splitlines()
                     if not line.startswith('save XOSC.XSTAGE0.MTAIL'))
    text += '\nsave XOSC.XSTAGE0.XTAILMAIN.main:d XOSC.XSTAGE0.XTAILREGEN.main:d\n'
    text += 'save XOSC.XSTAGE0.MFINE:d\n'
    text = text.replace('tran tran ', 'rfBiasDC dc\nrfDCOP info what=oppoint where=rawfile\ntran tran ', 1)
    return text+'\n'


def measure(raw, label, begin, end):
    output = project/'results'/(prefix+'_'+label+'_measure_{}.json'.format(int(begin*1e9)))
    code = launch(['python3', 'measure_psf.py', str(raw/'tran.tran.tran'),
                   str(begin), str(end)], output, 120)
    if code != 0:
        raise ValueError('Measurement failed with rc {}'.format(code))
    return json.loads(output.read_text())


def run(design, code, ctrl, suffix=None):
    label = design['name']+'_c{}_v{}'.format(code, round(ctrl*1e6))
    if suffix:
        label += '_'+suffix
    prior = next((r for r in results if r['label'] == label), None)
    if prior is not None:
        return prior
    path = project/'netlists'/(prefix+'_'+label+'.scs')
    path.write_text(model_text(design, code, ctrl))
    raw = project/'results'/(prefix+'_'+label)
    log = project/'logs'/(prefix+'_'+label+'.log')
    update('running', current_case=label)
    rc = launch(['spectre', str(path), '-format', 'psfascii', '-raw', str(raw),
                 '+log', str(log)], project/'logs'/(prefix+'_'+label+'.stdout'), 300)
    result = {'label': label, 'design': design, 'code': code, 'vctrl_V': ctrl,
              'rc': rc, 'valid': False, 'swing_above_100mV': False, 'scope': scope}
    if rc == 0 and (raw/'tran.tran.tran').exists():
        early = measure(raw, label, 25e-9, 33e-9)
        late = measure(raw, label, 40e-9, 48e-9)
        result.update({k: late.get(k) for k in ['frequency_Hz', 'differential_vpp_V',
                       'supply_power_W', 'q_rising_phase_deg']})
        f1, f2 = early.get('frequency_Hz'), late.get('frequency_Hz')
        a1, a2 = early.get('differential_vpp_V'), late.get('differential_vpp_V')
        phase = late.get('q_rising_phase_deg')
        result['early_frequency_Hz'] = f1
        result['early_differential_vpp_V'] = a1
        result['amplitude_ratio_late_over_early'] = a2/a1 if a1 else None
        phase_ok = phase is not None and min(abs(phase-90), abs(phase-270)) < 10
        result['valid'] = bool(f1 and f2 and a1 and a2 > .05 and phase_ok
                               and abs(f2/f1-1) < .01 and .9 < a2/a1 < 1.1)
        result['swing_above_100mV'] = bool(result['valid'] and a2 > .1)
        result['node_mean_V'] = {k: late[k]['mean'] for k in ['out0', 'out180', 'bn']}
        result['rising_crossings_per_window'] = [early.get('rising_crossings'), late.get('rising_crossings')]
        result['actual_tail_mean_A'] = {k: late[k]['mean'] for k in late
                                      if k.endswith('.main:d')}
        result['bias_and_tail_stability'] = {k: abs(late[k]['mean']/early[k]['mean']-1)
                                            for k in ['bn']+list(result['actual_tail_mean_A'])
                                            if k in early and early[k]['mean']}
        if any(value >= .01 for value in result['bias_and_tail_stability'].values()):
            result['valid'] = False
            result['swing_above_100mV'] = False
    else:
        result['diagnostic_tail'] = log.read_text()[-1800:] if log.exists() else 'No log'
    results.append(result)
    write_json(cases_path, results)
    print(json.dumps(result), flush=True)
    return result


try:
    designs = []
    for index, (main, regen, resistance) in enumerate([
            (12, 8, 620), (12, 12, 620), (12, 12, 750), (12, 12, 820),
            (10, 12, 620), (10, 12, 750), (14, 12, 620), (14, 16, 620)]):
        designs.append({'name': 'd{}'.format(index), 'main_nf': main, 'regen_nf': regen,
                        'rload': resistance, 'main_tail_nf': 12,
                        'regen_tail_nf': 20 if index == 7 else 16,
                        'wr_um': 3, 'pair_lr_um': .13, 'tail_lr_um': .39})
    screening = []
    for design in designs:
        group = [run(design, code, ctrl) for code, ctrl in
                 [(0, .3), (20, selected['target']['vctrl_V']), (31, 1.0)]]
        screening.append({'design': design, 'cases': group})
    write_json(project/'results/rfrefine_screen.json', screening)
    candidates = [g for g in screening if all(r['swing_above_100mV'] for r in g['cases'])
                  and g['cases'][0]['frequency_Hz'] < 3.2e9 < g['cases'][2]['frequency_Hz']]
    candidates.sort(key=lambda g: abs(g['cases'][1]['frequency_Hz']-3.2e9))
    chosen = None
    # At most two candidates, up to 12 endpoint cases plus 6 target cases each.
    # Binary band search avoids missing a narrow fine band between sampled codes.
    for candidate in candidates[:2]:
        design = candidate['design']
        target_bands = []
        code_low, code_high, code = 0, 31, 20
        for band_step in range(6):
            pair = [run(design, code, v) for v in [.3, 1.0]]
            if all(r['swing_above_100mV'] for r in pair):
                lo, hi = pair[0]['frequency_Hz'], pair[1]['frequency_Hz']
                if lo <= 3.2e9 <= hi:
                    target_bands.append((code, pair))
                    break
                if hi < 3.2e9:
                    code_low = code+1
                elif lo > 3.2e9:
                    code_high = code-1
                else:
                    break
            else:
                break
            if code_low > code_high:
                break
            code = (code_low+code_high)//2
        if not target_bands:
            continue
        code, pair = min(target_bands, key=lambda item: abs(item[0]-20))
        low, high = .3, 1.0
        refinement = []
        for step in range(6):
            ctrl = (low+high)/2
            value = run(design, code, ctrl, 'target{}'.format(step))
            refinement.append(value)
            if not value['swing_above_100mV']:
                break
            if value['frequency_Hz'] < 3.2e9:
                low = ctrl
            else:
                high = ctrl
        good = [r for r in refinement if r['swing_above_100mV']]
        if good:
            best = min(good, key=lambda r: abs(r['frequency_Hz']-3.2e9))
            chosen = {'design': design, 'code': code, 'band_endpoints': pair,
                      'best_measured': best, 'scope': scope,
                      'target_error_Hz': best['frequency_Hz']-3.2e9}
            write_json(project/'results/rfrefine_selected.json', chosen)
            break
    update('complete' if chosen else 'needs_design_review', selected=chosen,
           remaining='All-code continuity, PVT, startup, RF noise, loaded divider and full PLL unverified.')
except Exception as error:
    update('failed', error=repr(error))
    raise
