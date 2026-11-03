"""Generate staged headless PLL transient benches. Does NOT run simulations.

Stage 0 is completely behavioral apart from ideal LPF passives.
Stage 1 uses exact selected MOS VCO but behavioral PFD/CP/divider.
Stage 2 replaces PFD and CP with authored transistor circuits; divider is VA.
No stage is allowed to be labelled a fully transistor/noise-complete PLL.
Python 3.6+.
"""
from __future__ import print_function
import argparse
import hashlib
import json
import re
from pathlib import Path

GUEST_ROOT = '@PROJECT_ROOT@/pll_full'


def retain_vco(source):
    if 'n12_ckt_rf' not in source or 'LREF=3.12u' not in source:
        raise ValueError('Require the exact area8 mixed-RF candidate netlist.')
    removed_control = 0
    output = []
    for line in source.splitlines():
        stripped = line.strip()
        if re.match(r'^VCTRL\s+\(ctrl 0\)\s+vsource\b', stripped):
            removed_control += 1
            continue
        if re.match(r'^(save|ic)\s', stripped):
            continue
        if re.match(r'^saveOptions\s', stripped):
            continue
        if re.match(r'^\S+\s+(?:\([^)]*\)\s+)?(?:tran|dc|pss|pnoise|info)\b', stripped):
            continue
        output.append(line)
    if removed_control != 1:
        raise ValueError('Expected exactly one VCTRL source to replace.')
    return '\n'.join(output) + '\n'


def staged_top(stage, initial, duration, guest_root, p, ref_hz=100e6,
               fixed_code=26, physical_pfd_name='pll130_pfd', cp_mismatch=0):
    tstart = 300e-9 if stage else 100e-9
    text = '\n// Authored staged PLL loop. No physical noise simulation.\n'
    text += 'ahdl_include "{}/analog/pll130_analog.va"\n'.format(guest_root)
    text += 'ahdl_include "{}/digital/pll130_digital_va.va"\n'.format(guest_root)
    if stage == 2:
        text += 'include "{}/analog/pll130_cp_transistor.scs"\n'.format(guest_root)
        text += 'include "{}/digital/pll130_digital_mos.scs"\n'.format(guest_root)
    if not stage:
        text += 'XVCO (vdd 0 ctrl out0 out180) pll130_vco_linear_va\n'
    text += ('VREF (ref 0) vsource type=pulse val0=0 val1=1.2 '
             'delay=10n rise=20p fall=20p width={:.12g} period={:.12g}\n').format(
                 0.5 / ref_hz - 20e-12, 1.0 / ref_hz)
    text += ('VRST (rst 0) vsource type=pwl wave=[0 1.2 {t:.12g} 1.2 '
             '{t2:.12g} 0]\n'
             'VEN (enable 0) vsource type=pwl wave=[0 0 {t:.12g} 0 '
             '{t2:.12g} 1.2]\n'
             'VDIVEN (div_enable 0) vsource dc=1.2\n').format(t=tstart, t2=tstart+100e-12)
    text += 'XDIV (vdd 0 out0 out180 div_enable fb) pll130_div32_va\n'
    if stage == 2:
        text += 'XPFD (vdd 0 ref fb rst up dn) {}\n'.format(physical_pfd_name)
        text += 'XCP (vdd 0 up dn ctrl) pll130_cp_transistor\n'
    else:
        text += 'XPFD (vdd 0 ref fb rst up dn) pll130_pfd_va\n'
        text += ('XCP (vdd 0 up dn enable ctrl) pll130_cp_va '
                 'icp=20u mismatch={:.9g}\n').format(cp_mismatch)
    text += ('CSHUNT (ctrl 0) capacitor c={c1:.12g}\n'
             'RSERIES (ctrl filter_mid) resistor r={r:.12g}\n'
             'CSERIES (filter_mid 0) capacitor c={c2:.12g}\n').format(
                 c1=p['C_shunt_F'], c2=p['C_series_F'], r=p['R_ohm'])
    if stage:
        text += ('// DC-biased initial-condition test; not noise/rail-ramp startup.\n'
                 'ic ctrl={v:.12g} filter_mid={v:.12g} out0=0.935 '
                 'out180=0.933 out90=0.934 out270=0.934\n').format(v=initial)
    else:
        text += 'ic ctrl={v:.12g} filter_mid={v:.12g}\n'.format(v=initial)
    text += ('saveOptions options save=selected\n'
             'save vdd ctrl filter_mid ref fb rst enable up dn out0 out180 VDD:p\n')
    if stage:
        text += 'save bn bp out90 out270\n'
    if stage == 2:
        text += 'save XCP.bncp XCP.bpcp XCP.gp XCP.gn\n'
    # strobeonly bounds raw data volume, NOT solver accuracy or physical jitter.
    text += ('tran tran stop={:.12g} maxstep={} errpreset=conservative '
             'skipdc=no strobeperiod=10p strobeoutput=strobeonly\n').format(
                 duration, '1p' if stage else '10p')
    return text, tstart


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--vco-source', required=True)
    ap.add_argument('--out-dir', default=str(Path(__file__).resolve().parent / 'benches'))
    ap.add_argument('--guest-root', default=GUEST_ROOT)
    ap.add_argument('--physical-pfd-name', default='pll130_pfd')
    ap.add_argument('--duration-us', type=float, default=2.0)
    ap.add_argument('--include-stage2', action='store_true')
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source = Path(args.vco_source).read_text(encoding='utf-8')
    vco_sha = hashlib.sha256(Path(args.vco_source).read_bytes()).hexdigest()
    base = retain_vco(source)
    p = json.loads((Path(__file__).resolve().parent / 'loop_design.json').read_text(encoding='utf-8'))
    records = []
    for stage in ([0, 1, 2] if args.include_stage2 else [0, 1]):
        for initial in [0.6, 0.8359375, 1.0]:
            tag = 'pll_stage{}_fixed26_ctrl{}'.format(stage, int(round(initial*1e6)))
            if stage:
                text = base
            else:
                text = ('simulator lang=spectre\nglobal 0\n'
                        'simulatorOptions options temp=25 reltol=1e-5 '
                        'vabstol=1e-7 iabstol=1e-12\n'
                        'VDD (vdd 0) vsource dc=1.2\n')
            extra, start = staged_top(stage, initial, args.duration_us*1e-6,
                                     args.guest_root, p,
                                     physical_pfd_name=args.physical_pfd_name)
            text += extra
            path = out / (tag+'.scs')
            path.write_text(text, encoding='utf-8')
            records.append(dict(case_id=tag, path=str(path), stage=stage,
                                source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                vco_source_sha256=vco_sha if stage else None,
                                vctrl_initial_V=initial, fixed_code=26,
                                reference_Hz=100e6, target_Hz=3.2e9,
                                loop_enable_s=start, duration_s=args.duration_us*1e-6,
                                analog_solver_maxstep_s=1e-12 if stage else 1e-11,
                                output_strobe_s=1e-11,
                                jitter_scope='No noise; deterministic edge residual only.',
                                physical_scope={
                                    0:'Behavioral VCO/PFD/CP/divider, ideal LPF; '
                                      'declared VCO/CP power estimates.',
                                    1:'Selected mixed-RF transistor VCO; '
                                      'behavioral PFD/CP/divider; ideal LPF/reference.',
                                    2:'Mixed-RF VCO and authored MOS PFD/CP; '
                                      'behavioral divider; ideal LPF/reference.'}[stage]))
    (out/'pll_bench_manifest.json').write_text(json.dumps(records, indent=2)+'\n', encoding='utf-8')
    print('Prepared {} staged PLL benches; simulator was not launched.'.format(len(records)))


if __name__ == '__main__':
    main()
