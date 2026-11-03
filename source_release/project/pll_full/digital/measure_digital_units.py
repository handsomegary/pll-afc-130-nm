"""Offline Spectre PSF-ASCII unit measurements; stdlib, Python 3.6+, no simulation.

Usage: python3 measure_digital_units.py --kind divider --raw .../tran.tran.tran
       --start 20e-9 --end 95e-9 --output measurement.json
For PFD, --phase-ns +1 means reference leads feedback by 1ns. This script's
checks are functional/pre-layout screens, not jitter or PVT signoff.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(4*1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def read_psf(path, begin=None, end=None):
    data, reading = {}, False
    keep = begin is None
    with Path(path).open(errors='replace') as handle:
        for line in handle:
            item = line.strip()
            if item == 'VALUE':
                reading = True
                continue
            if item == 'END':
                break
            if not reading:
                continue
            match = re.match(r'^"([^"]+)"\s+([-+0-9.eE]+)\s*$', item)
            if match:
                value = float(match.group(2))
                if not math.isfinite(value):
                    raise ValueError('Nonfinite PSF sample')
                name=match.group(1)
                if name=='time':
                    if end is not None and value>end:
                        break
                    keep=(begin is None or value>=begin) and (end is None or value<=end)
                if keep:
                    data.setdefault(name, []).append(value)
    count = len(data.get('time', []))
    if count < 3:
        raise ValueError('No usable time waveform')
    if any(len(values) != count for values in data.values()):
        raise ValueError('Saved waveform lengths differ')
    return data


def mean(t, y):
    return sum((t[i+1]-t[i])*(y[i]+y[i+1])/2 for i in range(len(t)-1))/(t[-1]-t[0])


def rising(t, y, threshold):
    return [t[i]+(threshold-y[i])*(t[i+1]-t[i])/(y[i+1]-y[i])
            for i in range(len(t)-1) if y[i] <= threshold < y[i+1]]


def waveform(t, y, threshold):
    edge = rising(t, y, threshold)
    periods = [b-a for a, b in zip(edge, edge[1:])]
    frequency = (len(edge)-1)/(edge[-1]-edge[0]) if len(edge) >= 3 else None
    return {'min_V': min(y), 'max_V': max(y), 'mean_V': mean(t, y),
            'rising_edges': len(edge), 'frequency_Hz': frequency,
            'period_min_s': min(periods) if periods else None,
            'period_max_s': max(periods) if periods else None,
            'period_cv_deterministic': statistics.pstdev(periods)/statistics.mean(periods)
                if len(periods) > 2 else None}


def measure(data, kind, start, end, fin=3.2e9, vd=1.2, phase_ns=1.0,
            ref_hz=100e6, fb_hz=100e6):
    idx = [i for i, x in enumerate(data['time']) if start <= x <= end]
    if len(idx) < 3:
        raise ValueError('Insufficient samples in requested window')
    t = [data['time'][i] for i in idx]
    y = {name: [vals[i] for i in idx] for name, vals in data.items() if name != 'time'}
    result = {'kind': kind, 'window_start_s': t[0], 'window_end_s': t[-1],
              'samples': len(t), 'valid': False,
              'scope': 'Functional/pre-layout deterministic unit check; no physical jitter/FoM signoff'}
    result['waveforms'] = {name: waveform(t, value, .5*vd) for name, value in y.items()
                           if ':' not in name}
    result['current_time_mean_A'] = {name: mean(t, value) for name, value in y.items()
                                     if ':' in name}
    if 'VDD:p' in y and 'vdd' in y:
        result['total_supply_power_W'] = mean(t, [-v*i for v, i in zip(y['vdd'], y['VDD:p'])])
    if kind in ('divider', 'receiver'):
        required = ['q1', 'q2', 'q3', 'q4', 'q5']
        if not all(name in y for name in required):
            raise ValueError('Missing divider nodes')
        checks = {}
        for index, name in enumerate(required):
            w = result['waveforms'][name]
            target = fin/(2**(index+1))
            checks[name] = {'target_frequency_Hz': target,
                            'frequency_ok': bool(w['frequency_Hz'] and abs(w['frequency_Hz']/target-1) < .01),
                            'rail_ok': w['min_V'] <= .1*vd and w['max_V'] >= .9*vd,
                            'period_uniform': bool(w['period_min_s'] and
                                abs(w['period_min_s']*target-1) < .02 and
                                abs(w['period_max_s']*target-1) < .02)}
        if kind == 'receiver':
            c = result['waveforms'].get('clk', {})
            checks['receiver_clk'] = {'frequency_ok': bool(c.get('frequency_Hz') and abs(c['frequency_Hz']/fin-1) < .01),
                                      'rail_ok': bool(c and c['min_V'] <= .1*vd and c['max_V'] >= .9*vd)}
            result['receiver_diff_vpp_V'] = max(a-b for a,b in zip(y['rxp'],y['rxn']))-min(a-b for a,b in zip(y['rxp'],y['rxn']))
            result['receiver_common_mode_V'] = mean(t, [(a+b)/2 for a,b in zip(y['rxp'],y['rxn'])])
        result['checks'] = checks
        result['valid'] = all(all(value.values()) if name == 'receiver_clk'
                              else value['frequency_ok'] and value['rail_ok'] and value['period_uniform']
                              for name, value in checks.items())
    elif kind == 'divider_va':
        f = result['waveforms'].get('fb', {}).get('frequency_Hz')
        result['target_frequency_Hz'] = fin/32
        result['valid'] = bool(f and abs(f/(fin/32)-1) < .001)
        result['scope'] = 'Ideal behavioral divide-by-32 contract only; zero default input load, no power/jitter'
    elif kind in ('pfd', 'pfd_frequency'):
        for name in ('ref', 'fb', 'up', 'dn'):
            if name not in y:
                raise ValueError('Missing PFD node: '+name)
        fref = result['waveforms']['ref']['frequency_Hz']
        ffb = result['waveforms']['fb']['frequency_Hz']
        net = mean(t, [(u-d)/vd for u,d in zip(y['up'],y['dn'])])
        estimated_phase = net/fref if fref else None
        expected_phase = phase_ns*1e-9
        clocks_ok = bool(fref and ffb and abs(fref/ref_hz-1) < .001 and abs(ffb/fb_hz-1) < .001)
        outputs_ok = all(result['waveforms'][name]['rising_edges']>=3 and
                         result['waveforms'][name]['min_V']<=.1*vd and
                         result['waveforms'][name]['max_V']>=.9*vd for name in ('up','dn'))
        result['net_up_minus_dn_duty'] = net
        result['equivalent_phase_error_s'] = estimated_phase
        result['expected_phase_error_s'] = expected_phase
        result['clocks_ok'] = clocks_ok
        result['outputs_pulse_valid'] = outputs_ok
        if kind == 'pfd':
            result['valid'] = bool(clocks_ok and outputs_ok and estimated_phase is not None and
                                   abs(estimated_phase-expected_phase) < .2e-9)
        else:
            result['expected_reference_Hz']=ref_hz
            result['expected_feedback_Hz']=fb_hz
            result['expected_net_sign']='positive' if ref_hz>fb_hz else 'negative'
            result['equivalent_phase_error_s']=None
            result['expected_phase_error_s']=None
            direction_ok=net>.02 if ref_hz>fb_hz else net<-.02
            result['valid']=bool(clocks_ok and outputs_ok and direction_ok)
    elif kind == 'afc_va':
        required = ['s0','s1','s2','s3','s4','hold','done']
        if not all(name in y for name in required):
            raise ValueError('Missing AFC output')
        codes = [sum((1<<bit) if y['s'+str(bit)][i]>.5*vd else 0 for bit in range(5))
                 for i in range(len(t))]
        result['selected_code'] = codes[-1]
        result['code_stable'] = len(set(codes)) == 1
        result['hold_released'] = max(y['hold']) < .1*vd
        result['done_asserted'] = min(y['done']) > .9*vd
        result['valid'] = result['selected_code'] == 26 and result['code_stable'] and result['hold_released'] and result['done_asserted']
        result['scope'] = 'AFC algorithm tested with artificial known monotonic frequency fixture, not transistor VCO'
    else:
        raise ValueError('Unknown measurement kind')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', required=True)
    parser.add_argument('--kind', choices=['divider','receiver','divider_va','pfd','pfd_frequency','afc_va'], required=True)
    parser.add_argument('--start', type=float, required=True)
    parser.add_argument('--end', type=float, required=True)
    parser.add_argument('--fin', type=float, default=3.2e9)
    parser.add_argument('--vd', type=float, default=1.2)
    parser.add_argument('--phase-ns', type=float, default=1.0)
    parser.add_argument('--ref-hz', type=float, default=100e6)
    parser.add_argument('--fb-hz', type=float, default=100e6)
    parser.add_argument('--output')
    args = parser.parse_args()
    record = measure(read_psf(args.raw,args.start,args.end), args.kind, args.start, args.end, args.fin, args.vd, args.phase_ns,args.ref_hz,args.fb_hz)
    text = json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False)+'\n'
    if args.output:
        Path(args.output).write_text(text, encoding='utf-8')
    print(text)
    return 0 if record['valid'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
