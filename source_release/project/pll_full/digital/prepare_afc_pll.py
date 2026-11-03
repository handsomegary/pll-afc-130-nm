"""Generate MOS-VCO + functional AFC//32/PFD/CP PLL benches; no simulation.
Maintains the exact area's transistor core/bias and removes only fixed ctrl,
code drivers, analyses/saves/ICs. Three bounded start codes; 3us each.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

GUEST_ROOT='@PROJECT_ROOT@/pll_full'


def base(source):
    if 'n12_ckt_rf' not in source or 'LREF=3.12u' not in source:
        raise ValueError('Require selected area8 mixed-RF source')
    counts={'VCTRL':0,'VS0':0,'VS1':0,'VS2':0,'VS3':0,'VS4':0}
    keep=[]
    for line in source.splitlines():
        stripped=line.strip()
        hit=re.match(r'^(VCTRL|VS[0-4])\s+\(',stripped)
        if hit:
            counts[hit.group(1)]+=1
            continue
        if re.match(r'^(save|ic)\s',stripped) or stripped.startswith('saveOptions '):
            continue
        if re.match(r'^\S+\s+(?:\([^)]*\)\s+)?(?:tran|dc|pss|pnoise|info)\b',stripped):
            continue
        keep.append(line)
    if any(value!=1 for value in counts.values()):
        raise ValueError('Expected one each control/code ideal driver: '+repr(counts))
    return '\n'.join(keep)+'\n'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vco-source',required=True)
    ap.add_argument('--guest-root',default=GUEST_ROOT)
    ap.add_argument('--duration-us',type=float,default=3.0)
    args=ap.parse_args()
    root=Path(__file__).resolve().parent
    source=Path(args.vco_source).read_text(encoding='utf8')
    core=base(source)
    filt=json.loads((root.parent/'analog/loop_design.json').read_text())
    manifest=[]
    for initial in [0,16,31]:
        name='pll_afc_stage1_initial{}'.format(initial)
        text=core+'\n// Stage1A: exact MOS VCO; functional AFC/divider/PFD/CP, ideal filter.\n'
        text+='ahdl_include "{}/digital/pll130_digital_va.va"\n'.format(args.guest_root)
        text+='ahdl_include "{}/digital/pll130_afc_handoff.va"\n'.format(args.guest_root)
        text+='ahdl_include "{}/analog/pll130_analog.va"\n'.format(args.guest_root)
        text+='VREF (ref 0) vsource type=pulse val0=0 val1=1.2 delay=10n rise=20p fall=20p width=4.98n period=10n\n'
        text+='VEN (afc_enable 0) vsource type=pwl wave=[0 0 300n 0 300.1n 1.2]\n'
        text+='VDIVEN (div_enable 0) vsource dc=1.2\n'
        text+='XDIV (vdd 0 out0 out180 div_enable fb) pll130_div32_va\n'
        text+='XAFC (vdd 0 ref fb ctrl afc_enable s0 s1 s2 s3 s4 afc_hold afc_done) pll130_afc_va INITIAL_CODE={} CONTROL_EXPECTED=0.8359375 WATCHDOG_TIMEOUT=2u\n'.format(initial)
        text+='XHAND (vdd 0 afc_enable afc_done fine_enable hold_all) pll130_afc_handoff_va\n'
        text+='XCLAMP (vdd 0 ctrl hold_all) pll130_precharge_va ron=100 vpre=0.8359375\n'
        text+='XPFD (vdd 0 ref fb hold_all up dn) pll130_pfd_va\n'
        text+='XCP (vdd 0 up dn fine_enable ctrl) pll130_cp_va icp=20u mismatch=0\n'
        text+='CSHUNT (ctrl 0) capacitor c={:.12g}\n'.format(filt['C_shunt_F'])
        text+='RSERIES (ctrl filter_mid) resistor r={:.12g}\n'.format(filt['R_ohm'])
        text+='CSERIES (filter_mid 0) capacitor c={:.12g}\n'.format(filt['C_series_F'])
        text+='ic ctrl=0.8359375 filter_mid=0.8359375 out0=0.935 out180=0.933 out90=0.934 out270=0.934\n'
        text+='saveOptions options save=selected\n'
        text+='save vdd ctrl filter_mid ref fb up dn bn bp out0 out180 out90 out270 VDD:p\n'
        text+='save afc_enable s0 s1 s2 s3 s4 afc_hold afc_done hold_all fine_enable\n'
        text+='tran tran stop={:.12g} maxstep=1p errpreset=conservative skipdc=no strobeperiod=10p strobeoutput=strobeonly\n'.format(args.duration_us*1e-6)
        path=root/'benches'/(name+'.scs');path.write_text(text)
        manifest.append({'case_id':name,'name':name,'path':str(path),'initial_code':initial,
                         'bench_sha256':hashlib.sha256(text.encode()).hexdigest(),
                         'vco_source_sha256':hashlib.sha256(source.encode()).hexdigest(),
                         'afc_enable_s':300.1e-9,'duration_s':args.duration_us*1e-6,
                         'scope':'MOS VCO + ideal event AFC/divider/PFD/CP, ideal LPF/reference; no physical digital power/noise/PEX',
                         'validity':'AFC done required before fine-loop lock accepted'})
    (root/'benches/afc_pll_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Prepared three bounded MOS-VCO/AFC staged benches, simulator not launched.')


if __name__=='__main__':
    main()
