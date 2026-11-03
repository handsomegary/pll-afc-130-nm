"""Create bounded physical CP DC/pulse benches; never start a simulator.

Python 3.6+. PDK includes stay on guest, authored files contain no PDK data.
Run this from analog/ after loop_design.py. Default generated paths are local.
Root may change --guest-analog-dir when copying the authored directory to VM.
"""
from __future__ import print_function
import argparse
import hashlib
import json
from pathlib import Path

DEFAULT_PDK = '@TECH_ROOT@/models/spectre'
DEFAULT_GUEST = '@PROJECT_ROOT@/pll_full/analog'


def header(pdk, guest):
    return ('simulator lang=spectre\nglobal 0\n'
            'include "{pdk}/ms013_io33_v2p6_7p_spe.lib" section=tt\n'
            'include "{guest}/pll130_cp_transistor.scs"\n'
            'simulatorOptions options temp=25 reltol=1e-5 '
            'vabstol=1e-7 iabstol=1e-12\n'
            'VDD (vdd 0) vsource dc=1.2\n').format(pdk=pdk, guest=guest)


def dc_bench(ctrl, up, dn, pdk, guest):
    return header(pdk, guest) + (
        '// DC current/compliance screen. VCLAMP supplies balancing current.\n'
        'VCLAMP (ctrl 0) vsource dc={ctrl:.9g}\n'
        'VUP (up 0) vsource dc={up:.9g}\n'
        'VDN (dn 0) vsource dc={dn:.9g}\n'
        'XCP (vdd 0 up dn ctrl) pll130_cp_transistor\n'
        'saveOptions options save=selected\n'
        'save ctrl up dn VDD:p VCLAMP:p XCP.bncp XCP.bpcp XCP.gp XCP.gn\n'
        'save XCP.MPUP:d XCP.MNDN:d XCP.MNREF:d '
        'XCP.MNPMIRROR:d XCP.MPREF:d\n'
        'cpdc dc\n'
        'cpop info what=oppoint where=rawfile\n'
    ).format(ctrl=ctrl, up=1.2 * up, dn=1.2 * dn)


def pulse_bench(p, pdk, guest):
    # Single pulses, no periodic forcing after the declared times.
    return header(pdk, guest) + (
        '// UP 20-22ns; DN 30-32ns; both 40-40.2ns.\n'
        '// Useful for charge feedthrough, settling and matching screen.\n'
        'VUP (up 0) vsource type=pwl wave=[0 0 20n 0 20.02n 1.2 '
        '22n 1.2 22.02n 0 40n 0 40.02n 1.2 40.2n 1.2 40.22n 0 60n 0]\n'
        'VDN (dn 0) vsource type=pwl wave=[0 0 30n 0 30.02n 1.2 '
        '32n 1.2 32.02n 0 40n 0 40.02n 1.2 40.2n 1.2 40.22n 0 60n 0]\n'
        'XCP (vdd 0 up dn ctrl) pll130_cp_transistor\n'
        'CSHUNT (ctrl 0) capacitor c={c1:.12g}\n'
        'RSERIES (ctrl filter_mid) resistor r={r:.12g}\n'
        'CSERIES (filter_mid 0) capacitor c={c2:.12g}\n'
        'ic ctrl=0.8359375 filter_mid=0.8359375\n'
        'saveOptions options save=selected\n'
        'save ctrl filter_mid up dn VDD:p XCP.bncp XCP.bpcp '
        'XCP.gp XCP.gn XCP.MPUP:d XCP.MNDN:d\n'
        'tran tran stop=60n maxstep=10p errpreset=conservative skipdc=yes\n'
    ).format(c1=p['C_shunt_F'], c2=p['C_series_F'], r=p['R_ohm'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(Path(__file__).resolve().parent / 'benches'))
    ap.add_argument('--guest-analog-dir', default=DEFAULT_GUEST)
    ap.add_argument('--pdk-model-dir', default=DEFAULT_PDK)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = json.loads((Path(__file__).resolve().parent / 'loop_design.json').read_text(encoding='utf-8'))
    cases = []
    for ctrl in [0.2, 0.4, 0.6, 0.8359375, 1.0]:
        for name, up, dn in [('up', 1, 0), ('dn', 0, 1), ('both', 1, 1), ('off', 0, 0)]:
            tag = 'cp_dc_v{}_{}'.format(int(round(ctrl * 1e6)), name)
            txt = dc_bench(ctrl, up, dn, args.pdk_model_dir, args.guest_analog_dir)
            path = out / (tag + '.scs')
            path.write_text(txt, encoding='utf-8')
            cases.append(dict(case_id=tag, path=str(path), ctrl_V=ctrl,
                              state=name, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                              kind='cp_dc', expected_ideal_current_A=(up-dn)*20e-6,
                              validation='Measure actual sourcing/sinking, off leakage, '
                                         'mismatch, reference power and compliance.'))
    txt = pulse_bench(p, args.pdk_model_dir, args.guest_analog_dir)
    path = out / 'cp_pulse.scs'
    path.write_text(txt, encoding='utf-8')
    cases.append(dict(case_id='cp_pulse', path=str(path), kind='cp_transient',
                      source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      validation='Measure charge/time integral, feedthrough, '
                                 'positive UP and negative DN response; not noise jitter.'))
    (out / 'bench_manifest.json').write_text(json.dumps(cases, indent=2) + '\n', encoding='utf-8')
    print('Prepared {} bounded CP benches; no simulator launched.'.format(len(cases)))


if __name__ == '__main__':
    main()
