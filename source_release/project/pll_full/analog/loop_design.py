"""Analytic CP-PLL filter design. Python 3.6+, no third-party packages.

The result is a continuous-time SMALL-SIGNAL estimate, not a sampled-PFD,
nonlinear acquisition, silicon, or full-PLL noise measurement.
"""
from __future__ import print_function
import argparse
import cmath
import csv
import json
import math
from pathlib import Path


def impedance(f, r, c_shunt, c_series):
    s = 2j * math.pi * f
    return (1.0 + s * r * c_series) / (
        s * (c_shunt + c_series) *
        (1.0 + s * r * c_shunt * c_series / (c_shunt + c_series)))


def open_loop(f, icp, kvco, divide, r, c_shunt, c_series):
    # Kpd = Icp/(2*pi) A/rad, Kvco(rad/s/V) = 2*pi*Kvco(Hz/V).
    return icp * kvco * impedance(f, r, c_shunt, c_series) / (
        divide * 2j * math.pi * f)


def design(icp=20e-6, kvco=423e6, divide=32, fc=2e6,
           zero_ratio=0.25, pole_ratio=5.0):
    wz = 2.0 * math.pi * fc * zero_ratio
    wp = 2.0 * math.pi * fc * pole_ratio
    wc = 2.0 * math.pi * fc
    ratio = wp / wz
    total = icp * kvco / divide * math.sqrt(1.0 + (wc / wz) ** 2) / (
        wc * wc * math.sqrt(1.0 + (wc / wp) ** 2))
    c_shunt = total / ratio
    c_series = total - c_shunt
    r = 1.0 / (wz * c_series)
    phase_margin = math.degrees(math.atan(wc / wz) - math.atan(wc / wp))
    return dict(Icp_A=icp, Kvco_Hz_per_V=kvco, divide=divide,
                target_unity_gain_Hz=fc, zero_Hz=wz / (2 * math.pi),
                pole_Hz=wp / (2 * math.pi), R_ohm=r,
                C_shunt_F=c_shunt, C_series_F=c_series,
                phase_margin_deg=phase_margin,
                unity_gain_magnitude=abs(open_loop(fc, icp, kvco, divide,
                                                  r, c_shunt, c_series)),
                topology='Vctrl--Cshunt--VSS; Vctrl--R--filter_mid--Cseries--VSS',
                scope='Continuous-time small-signal nominal estimate only; ideal '
                      'passives, constant Kvco and Icp, no sample delay/PEX/noise.')


def crossover(parameters):
    lo, hi = 1e3, 1e9
    p = parameters
    for unused in range(90):
        mid = math.sqrt(lo * hi)
        magnitude = abs(open_loop(mid, p['Icp_A'], p['Kvco_Hz_per_V'],
                                 p['divide'], p['R_ohm'], p['C_shunt_F'],
                                 p['C_series_F']))
        if magnitude > 1:
            lo = mid
        else:
            hi = mid
    fc = math.sqrt(lo * hi)
    l = open_loop(fc, p['Icp_A'], p['Kvco_Hz_per_V'], p['divide'],
                  p['R_ohm'], p['C_shunt_F'], p['C_series_F'])
    phase = math.degrees(cmath.phase(l))
    if phase > 0:
        phase -= 360
    return dict(unity_gain_Hz=fc, phase_margin_deg=180 + phase)


def make_outputs(out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    p = design()
    p['fixed_filter_gain_sensitivity'] = []
    for gain in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
        q = dict(p)
        q['Kvco_Hz_per_V'] = p['Kvco_Hz_per_V'] * gain
        measure = crossover(q)
        measure['Icp_times_Kvco_scale'] = gain
        p['fixed_filter_gain_sensitivity'].append(measure)
    (out_dir / 'loop_design.json').write_text(
        json.dumps(p, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    with (out_dir / 'loop_bode.csv').open('w', newline='', encoding='utf-8') as h:
        w = csv.writer(h)
        w.writerow(['offset_Hz', 'open_loop_gain_dB', 'open_loop_phase_deg',
                    'reference_phase_to_output_gain_dB',
                    'free_vco_phase_to_output_gain_dB'])
        for i in range(401):
            f = 1e3 * 10.0 ** (i / 80.0)
            l = open_loop(f, p['Icp_A'], p['Kvco_Hz_per_V'], p['divide'],
                          p['R_ohm'], p['C_shunt_F'], p['C_series_F'])
            phase = math.degrees(cmath.phase(l))
            if phase > 0:
                phase -= 360
            href = p['divide'] * l / (1 + l)
            hvco = 1.0 / (1 + l)
            w.writerow([f, 20 * math.log10(abs(l)), phase,
                        20 * math.log10(abs(href)), 20 * math.log10(abs(hvco))])
    return p


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(Path(__file__).resolve().parent))
    args = ap.parse_args()
    result = make_outputs(Path(args.out_dir))
    print(json.dumps(result, indent=2, ensure_ascii=False))
