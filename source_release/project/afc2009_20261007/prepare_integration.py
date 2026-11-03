"""Add physical AFC2009 to the preserved cmos130 MOS fine loop.

No simulation launch, no original-source edits, no behavioral control decisions.
The ideal external reference, bias-current reference and ideal R/Cs remain.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

GUEST_PROJECT = '@PROJECT_ROOT@'
BASE_SHA = 'cc44e0bb56a8de35ff75d1780b99bc790311ec097f33556fa9046eb4bb0e8f44'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=here.parent/'pll_full/digital/benches/pll_stage3_physical_code28_ctrl835938_cpdrain_bounded2p.scs')
    parser.add_argument('--out-dir', type=Path, default=here/'integration/benches')
    parser.add_argument('--guest-project', default=GUEST_PROJECT)
    parser.add_argument('--duration-us', type=float, default=4.5)
    parser.add_argument('--maxstep-ps', type=int, choices=[2,4], default=4)
    parser.add_argument('--strobe-ps', type=int, choices=[20,40], default=40)
    parser.add_argument('--ref-delay-ns', type=float, default=10)
    args = parser.parse_args()
    if sha(args.baseline) != BASE_SHA:
        raise ValueError('Preserved, locked physical baseline SHA mismatch.')
    if not 3 <= args.duration_us <= 7 or not 0 <= args.ref_delay_ns <= 20:
        raise ValueError('Keep acquisition duration/reference-phase sweep bounded.')
    source = args.baseline.read_text(encoding='utf-8')
    stripped_lines = []
    removed = {'code_parameter':0, 'static_code':0, 'pfd':0, 'cp':0, 'reset':0, 'enable':0, 'ic':0}
    for line in source.splitlines():
        s = line.strip()
        if s.startswith('//') or not s:
            continue
        if s.startswith('parameters CODE0='):
            removed['code_parameter'] += 1; continue
        if re.match(r'^VS[0-4]\s', s):
            removed['static_code'] += 1; continue
        prefix = next((key for prefix,key in [('XPFD ', 'pfd'),('XCP ', 'cp'),('VRSTP ', 'reset'),('VEN ', 'enable'),('ic ', 'ic')] if s.startswith(prefix)), None)
        if prefix is not None:
            removed[prefix] += 1; continue
        if s.startswith('save ') or s.startswith('saveOptions ') or s.startswith('tran tran '):
            continue
        if s.startswith('VREF '):
            line = 'VREF (ref 0) vsource type=pulse val0=0 val1=1.2 delay={:.12g} rise=20p fall=20p width=4.98n period=10n'.format(args.ref_delay_ns*1e-9)
        stripped_lines.append(line)
    expected = {'code_parameter':1,'static_code':5,'pfd':1,'cp':1,'reset':1,'enable':1,'ic':1}
    if removed != expected:
        raise ValueError('Unexpected baseline topology: '+str(removed))
    text = ('// Physical cmos130 PLL with a two-phase counter/early-stop MOS AFC.\n'
            '// Adapted from Jeong2009 to 100MHz REF and increasing-frequency ring bank.\n'
            '// All active VCO/RX/DIV/PFD/CP/AFC/clamp/enable devices are PDK MOS.\n'
            '// External REF and bias IREF, ideal R/Cs, and oscillator IC seed remain.\n'
            '// DONE selects a provisional coarse candidate; actual fine lock qualifies it.\n\n'+
            '\n'.join(stripped_lines)+'\n')
    new_root = args.guest_project+'/afc2009_20261007'
    text += 'include "'+new_root+'/mos/afc2009_mos.scs"\n'
    text += '''
VDDAFC (vddafc vdd) vsource dc=0
// Half-supply clamp reference uses two ideal resistors, not a powered ideal
// voltage source. Its36uW nominal quiescent draw is included in VDD and AFC.
RHOLDUP (vddafc vhold) resistor r=20k
RHOLDDN (vhold 0) resistor r=20k
CHOLD (vhold 0) capacitor c=1p
VRSTAFC (afc_rst 0) vsource type=pwl wave=[0 1.2 100n 1.2 100.02n 0]
VSTARTAFC (afc_start 0) vsource type=pwl wave=[0 0 300n 0 300.02n 1.2]
XAFC (vddafc 0 ref fb afc_rst afc_start s0 s1 s2 s3 s4 afc_done afc_fail hold_all fine_enable pfd_reset afc_active) afc2009_mos
XCPUPEN (vdddig 0 up fine_enable up_g) pll130_and2
XCPDNEN (vdddig 0 dn fine_enable dn_g) pll130_and2
XPFD (vdddig 0 ref fb pfd_reset up dn) pll130_pfd
XCP (vddcp 0 up_g dn_g ctrl) pll130_cp_drain
XHOLDINV (vddafc 0 hold_all hold_b) pll130_inv
MHOLDCTRL (ctrl hold_all vhold 0) n12 w=4u l=.13u
PHOLDCTRL (ctrl hold_b vhold vddafc) p12 w=8u l=.13u
MHOLDMID (filter_mid hold_all vhold 0) n12 w=4u l=.13u
PHOLDMID (filter_mid hold_b vhold vddafc) p12 w=8u l=.13u
// Both LPF capacitor nodes precharge during calibration; no ideal Vctrl drive.
ic ctrl=.6 filter_mid=.6 vhold=.6 out0=.935 out180=.933 out90=.934 out270=.934
saveOptions options save=selected
save vdd vdddig vddcp vddafc vhold bn bp ctrl filter_mid ref fb clk
save VDD:p VDDIG:p VDDCP:p VDDAFC:p out0 out180
save afc_rst afc_start afc_done afc_fail hold_all fine_enable pfd_reset afc_active
save s0 s1 s2 s3 s4 up dn up_g dn_g
save XAFC.phase XAFC.arm XAFC.seen XAFC.decision XAFC.was_slow XAFC.was_fast XAFC.was_near
save XAFC.lead_clock XAFC.lag_clock XAFC.count_run XAFC.count_rst XAFC.measure_watchdog
'''
    for stem in ['dl','dg','dd']:
        text += 'save '+' '.join('XAFC.'+stem+str(i) for i in range(8))+'\n'
    text += 'tran tran stop={:.12g} maxstep={}p errpreset=moderate skipdc=no strobeperiod={}p strobeoutput=strobeonly\n'.format(args.duration_us*1e-6,args.maxstep_ps,args.strobe_ps)
    if 'ahdl_include' in text or re.search(r'\b\w+_va\b', text):
        raise ValueError('Physical integration must not contain VA control models.')
    if re.search(r'(?m)^VS[0-4]\s|^VCTRL\s', text):
        raise ValueError('Static code/control driver remains.')
    args.out_dir.mkdir(parents=True, exist_ok=True)
    name = 'pll_afc2009_physical_halfvdd_ref{}_{}p'.format(int(round(args.ref_delay_ns*1000)),args.maxstep_ps)
    path = args.out_dir/(name+'.scs')
    path.write_text(text, encoding='utf-8')
    record = dict(name=name, path=str(path.resolve()), bench_sha256=sha(path),
        physical_baseline_sha256=BASE_SHA, baseline_path=str(args.baseline.resolve()),
        target_Hz=3.2e9, reference_Hz=100e6, temperature_C=25, vdd_V=1.2,
        initial_code=16, clamp_reference_V=.6, clamp_reference_resistors_ohm=[20000,20000],
        duration_s=args.duration_us*1e-6, maxstep_s=args.maxstep_ps*1e-12,
        strobeperiod_s=args.strobe_ps*1e-12, enable_midpoint_s=300.01e-9,
        ref_delay_s=args.ref_delay_ns*1e-9,
        physical_active_blocks=['VCO','AC/self-bias RX','5TG divider','PFD','drain CP','AFC','CP enable gates','two-node LPF clamp'],
        behavior_control_blocks=[],
        external_ideal_elements=['100MHz REF','13.5594uA IREF','R/C elements','oscillator IC startup seed'],
        status='prepared_unverified',
        handover_note='Physical2REF DONE delay; DONE is a provisional code, not lock. No CP operation on FAIL.',
        reference_adaptations='100MHz REF/!REF first-FB phase selection, 2-count/2-sample guarded CDC;192REF watchdog; increasing ring-code polarity.')
    (args.out_dir/(name+'_manifest.json')).write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    (args.out_dir/'integration_manifest.json').write_text(json.dumps([record], indent=2)+'\n', encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    main()
