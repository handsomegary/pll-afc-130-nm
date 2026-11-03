"""Measure staged PLL/CP PSF ASCII transient, Python 3.6+ and stdlib only.

The lock definition is explicit; deterministic residuals never become noise
jitter. No simulator is started. Reads only the caller's supplied raw file.
"""
from __future__ import print_function
import argparse
import bisect
import json
import math
import re
import statistics
from pathlib import Path


def read_psf(path):
    values = {}
    reading = False
    with Path(path).open(errors='replace') as h:
        for line in h:
            line = line.strip()
            if line == 'VALUE':
                reading = True
                continue
            if line == 'END':
                break
            if not reading:
                continue
            # DC scalar PSF has a quoted type and optional PROP suffix;
            # transient PSF has just name and numeric value. Parse both.
            m = re.match(r'^"([^\"]+)"\s+(?:"[^\"]+"\s+)?'
                         r'([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)(?:\s|$)', line)
            if not m:
                continue
            try:
                value = float(m.group(2))
            except ValueError:
                continue
            if not math.isfinite(value):
                raise ValueError('Nonfinite waveform: '+m.group(1))
            values.setdefault(m.group(1), []).append(value)
    return values


def integral_mean(t, y):
    if len(t) < 2 or len(t) != len(y) or t[-1] <= t[0]:
        raise ValueError('Invalid time grid for integral.')
    return sum((t[i+1]-t[i])*(y[i+1]+y[i])*0.5
               for i in range(len(t)-1)) / (t[-1]-t[0])


def edge_times(t, y, threshold=0):
    return [t[i]+(threshold-y[i])*(t[i+1]-t[i])/(y[i+1]-y[i])
            for i in range(len(t)-1) if y[i] <= threshold < y[i+1]]


def require_wave(values, name, n):
    wave = values.get(name)
    if wave is None or len(wave) != n:
        raise ValueError('Missing or malformed waveform: '+name)
    return wave


def edge_frequency(edges, begin, end, min_edges=3):
    chosen = edges[bisect.bisect_left(edges, begin):bisect.bisect_right(edges, end)]
    if len(chosen) < min_edges or chosen[-1] <= chosen[0]:
        return None
    return (len(chosen)-1)/(chosen[-1]-chosen[0])


def reference_boundary_snapshot(values,reference_hz=100e6,enable_s=0):
    """Actual saved voltages at the last time-zero-aligned reference period.

    PSS preparation separately checks reference delay is an integer period.
    Interpolation is between saved samples; absent/internal unsaved states are
    not guessed. This snapshot does not assert that the loop has locked.
    """
    t=values.get('time',[])
    if len(t)<2 or reference_hz<=0:return None
    period=1.0/reference_hz
    boundary=math.floor((t[-1]+1e-15)/period)*period
    if boundary<t[0] or boundary<enable_s:return None
    if boundary>t[-1]:boundary=t[-1]
    j=bisect.bisect_left(t,boundary)
    nodes=['out0','out90','out180','out270','bn','bp','clk','rxp','rxn',
           'q1','q2','q3','q4','fb','up','dn','XRX.src','XRX.inv_bias','XRX.clkn',
           'XCP.bncp','XCP.bpcp','XCP.pinternal','XCP.ninternal']
    saved={}
    for name in nodes:
        y=values.get(name,[])
        if len(y)!=len(t):continue
        if j==0:value=y[0]
        elif j==len(t):value=y[-1]
        else:value=y[j-1]+(y[j]-y[j-1])*(boundary-t[j-1])/(t[j]-t[j-1])
        saved[name]=value
    return dict(time_s=boundary,reference_period_s=period,node_voltage_V=saved,
                scope='Actual saved-node voltages at the last time-zero-aligned reference period '
                      'boundary; interpolated only between saved samples. No unsaved FF state '
                      'is assumed. Preparation requires integer-period reference delay and actual lock.')


def measure_lock(values, target_hz=3.2e9, reference_hz=100e6,
                 enable_s=100e-9, frequency_tolerance=0.001,
                 lock_hold_s=500e-9, phase_pp_fraction=0.01):
    t = values.get('time', [])
    if len(t) < 20:
        raise ValueError('Too few transient points.')
    n = len(t)
    pos = require_wave(values, 'out0', n)
    neg = require_wave(values, 'out180', n)
    differential = [a-b for a, b in zip(pos, neg)]
    ref = edge_times(t, require_wave(values, 'ref', n), 0.6)
    fb = edge_times(t, require_wave(values, 'fb', n), 0.6)
    out = edge_times(t, differential)
    period = 1.0/reference_hz
    # Align ordinal edge trains once. Counting/missing a cycle subsequently
    # changes the unwrapped error, unlike rematching every edge to nearest ref.
    fbi = bisect.bisect_left(fb, enable_s)
    if fbi >= len(fb) or not ref:
        return dict(valid_waveform=False, locked=False, lock_time_s=None,
                    reason='No feedback/reference edges after loop enable.')
    ri = bisect.bisect_left(ref, fb[fbi])
    ri = min(max(ri, 0), len(ref)-1)
    if ri > 0 and abs(ref[ri-1]-fb[fbi]) < abs(ref[ri]-fb[fbi]):
        ri -= 1
    pairs = min(len(fb)-fbi, len(ref)-ri)
    pair_times = fb[fbi:fbi+pairs]
    unwrapped_error = [fb[fbi+i]-ref[ri+i] for i in range(pairs)]
    phase_pp_limit = phase_pp_fraction*period
    qualify = []
    for begin in pair_times:
        end = begin+lock_hold_s
        if begin < enable_s or end > t[-1] or end > pair_times[-1]:
            continue
        p0 = bisect.bisect_left(pair_times, begin)
        p1 = bisect.bisect_right(pair_times, end)
        errors = unwrapped_error[p0:p1]
        f = edge_frequency(out, begin, end, min_edges=10)
        sample0, sample1 = bisect.bisect_left(t, begin), bisect.bisect_right(t, end)
        window_diff = differential[sample0:sample1]
        vpp = max(window_diff)-min(window_diff) if window_diff else 0
        # Additionally inspect every 100ns frequency subwindow; a long-window
        # average alone could hide an acquisition oscillation.
        frequencies = []
        local = begin
        while local+100e-9 <= end+1e-15:
            frequencies.append(edge_frequency(out, local, local+100e-9, 10))
            local += 50e-9
        all_f_valid = (f is not None and frequencies and
                       all(q is not None and abs(q/target_hz-1)<=frequency_tolerance
                           for q in frequencies))
        phase_pp = max(errors)-min(errors) if len(errors) >= 10 else None
        valid = (all_f_valid and phase_pp is not None and
                 phase_pp <= phase_pp_limit and vpp >= 0.05)
        qualify.append(dict(begin_s=begin, end_s=end, valid=bool(valid),
                            frequency_Hz=f, differential_vpp_V=vpp,
                            unwrapped_phase_error_pp_s=phase_pp))
    # Require no later complete hold window to fail after the reported lock.
    first = None
    for i, window in enumerate(qualify):
        if window['valid'] and all(q['valid'] for q in qualify[i:]):
            first = window
            break
    tail_begin = max(enable_s, t[-1]-lock_hold_s)
    b0 = bisect.bisect_left(t, tail_begin)
    power = None
    if 'VDD:p' in values and 'vdd' in values:
        current = require_wave(values, 'VDD:p', n)
        vdd = require_wave(values, 'vdd', n)
        p = [-a*b for a,b in zip(current, vdd)]
        power = integral_mean(t[b0:], p[b0:])
    p0 = bisect.bisect_left(pair_times, tail_begin)
    errors = unwrapped_error[p0:]
    residual_rms = None
    phase_mean = None
    principal_phase_mean = None
    if len(errors) >= 2:
        mean = sum(errors)/len(errors)
        phase_mean = mean
        # Report a static phase offset modulo one reference period, but retain
        # the unwrapped mean and use only unwrapped errors for lock/cycle-slip
        # checks. A constant offset is not stochastic jitter.
        principal_phase_mean = (mean+0.5*period)%period-0.5*period
        residual_rms = math.sqrt(sum((x-mean)**2 for x in errors)/len(errors))
    output_tail=out[bisect.bisect_left(out,tail_begin):]
    output_periods=[output_tail[i+1]-output_tail[i] for i in range(len(output_tail)-1)]
    output_deterministic={}
    if len(output_periods)>=10:
        period_mean=sum(output_periods)/len(output_periods)
        period_rms=math.sqrt(sum((x-period_mean)**2 for x in output_periods)/len(output_periods))
        delta=[output_periods[i+1]-output_periods[i] for i in range(len(output_periods)-1)]
        count=len(output_tail)
        index_mean=(count-1)*0.5
        time_mean=sum(output_tail)/count
        denom=sum((i-index_mean)**2 for i in range(count))
        fit_period=sum((i-index_mean)*(x-time_mean) for i,x in enumerate(output_tail))/denom
        tie=[x-(time_mean+fit_period*(i-index_mean)) for i,x in enumerate(output_tail)]
        output_deterministic=dict(
            edges=count,period_mean_s=period_mean,
            period_residual_rms_s=period_rms,
            period_peak_to_peak_s=max(output_periods)-min(output_periods),
            cycle_to_cycle_rms_s=math.sqrt(sum(x*x for x in delta)/len(delta)),
            detrended_TIE_rms_s=math.sqrt(sum(x*x for x in tie)/len(tie)),
            detrended_TIE_peak_to_peak_s=max(tie)-min(tie),
            scope='NO physical noise. Deterministic modulation plus numerical '
                  'and waveform-interpolation residual; not rms noise jitter.')
    return dict(valid_waveform=bool(qualify), locked=first is not None,
                lock_time_s=first['begin_s'] if first else None,
                lock_after_enable_s=first['begin_s']-enable_s if first else None,
                final_frequency_Hz=edge_frequency(out, tail_begin, t[-1], 10),
                final_ctrl_mean_V=integral_mean(t[b0:], require_wave(values,'ctrl',n)[b0:]),
                final_filter_mid_mean_V=integral_mean(t[b0:], values['filter_mid'][b0:])
                    if len(values.get('filter_mid',[]))==n else None,
                final_reference_period_boundary_snapshot=reference_boundary_snapshot(values,reference_hz,enable_s),
                final_power_W=power, power_window_s=[tail_begin,t[-1]],
                final_differential_vpp_V=max(differential[b0:])-min(differential[b0:]),
                deterministic_feedback_phase_residual_rms_s=residual_rms,
                deterministic_feedback_phase_unwrapped_mean_s=phase_mean,
                deterministic_feedback_principal_static_offset_s=principal_phase_mean,
                feedback_phase_sign_convention='feedback rising-edge time minus '
                    'reference rising-edge time; positive means feedback lags. '
                    'Principal static offset is modulo one reference period; '
                    'unwrapped errors alone determine cycle-slip and lock.',
                deterministic_VCO_output_edge_statistics=output_deterministic,
                physical_noise_jitter_s=None,
                lock_definition=dict(frequency_tolerance_fraction=frequency_tolerance,
                                     hold_s=lock_hold_s,
                                     phase_pp_limit_fraction_reference_period=phase_pp_fraction,
                                     phase_pp_limit_s=phase_pp_limit,
                                     differential_vpp_min_V=0.05),
                windows_count=len(qualify), final_window=qualify[-1] if qualify else None,
                scope='Staged mixed-signal acquisition; residual is deterministic '
                      'phase ripple/numerical error, not physical rms noise jitter.')


def measure_dc(values):
    if 'VCLAMP:p' not in values:
        raise ValueError('CP DC current requires VCLAMP:p.')
    flat = {k:v[-1] for k,v in values.items() if v}
    return dict(actual_net_current_into_ctrl_A=flat['VCLAMP:p'],
                supply_power_W=-1.2*flat.get('VDD:p',0),
                waveforms=flat,
                scope='Physical MOS CP with ideal reference at TT1.2V25C; '
                      'net current is not independently UP and DN in both-on.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('raw_file')
    ap.add_argument('--kind', choices=['pll','cp_dc'], default='pll')
    ap.add_argument('--enable-ns', type=float, default=100)
    ap.add_argument('--out')
    args = ap.parse_args()
    values = read_psf(args.raw_file)
    result = measure_dc(values) if args.kind=='cp_dc' else measure_lock(values,enable_s=args.enable_ns*1e-9)
    txt = json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    if args.out:
        Path(args.out).write_text(txt,encoding='utf-8')
    print(txt)


if __name__=='__main__':
    main()
