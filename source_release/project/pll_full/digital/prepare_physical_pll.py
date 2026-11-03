"""Prepare a physical MOS fine-loop from a measured loaded operating point.

No simulation launch. Require the exact two-case loaded electrical results,
passing interface and unchanged measured bench bytes. Coarse code is frozen;
this bench has no AFC and no Verilog-A blocks. Reference/passives/bias current
sources and initial conditions remain ideal pre-layout testbench elements.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

GUEST_ROOT='@PROJECT_ROOT@/pll_full'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--loaded-results',required=True)
    ap.add_argument('--case',required=True)
    ap.add_argument('--initial-ctrl',type=float)
    ap.add_argument('--duration-us',type=float,default=2)
    ap.add_argument('--maxstep-ps',type=int,choices=[2,4],default=4)
    ap.add_argument('--guest-root',default=GUEST_ROOT)
    args=ap.parse_args();root=Path(__file__).resolve().parent
    results=json.loads(Path(args.loaded_results).read_text())
    if results.get('all_two_present') is not True:
        raise ValueError('Both bounded loaded cases must have electrical results')
    measured=[r for r in results.get('cases',[]) if r.get('name')==args.case and r.get('interface_valid') is True]
    if len(measured)!=1:raise ValueError('Chosen case must have a passing physical loaded interface')
    records=json.loads((root/'benches/loaded_interface_manifest.json').read_text())
    entry=[r for r in records if r['name']==args.case]
    if len(entry)!=1:raise ValueError('Unknown loaded case')
    chosen=entry[0];sourcepath=Path(chosen['path'])
    if hashlib.sha256(sourcepath.read_bytes()).hexdigest()!=measured[0].get('bench_sha256'):
        raise ValueError('Selected loaded bench bytes changed after measurement')
    ctrl=chosen['vctrl_V'] if args.initial_ctrl is None else args.initial_ctrl
    if not .15<=ctrl<=1.05:raise ValueError('Initial control must lie within provisional CP compliance interval')
    if not 1<=args.duration_us<=3:raise ValueError('Keep acquisition bench bounded to 1..3us')
    lines=[];removed_vctrl=0
    for line in sourcepath.read_text().splitlines():
        stripped=line.strip()
        if re.match(r'^VCTRL\s',stripped):removed_vctrl+=1;continue
        if re.match(r'^(save|ic)\s',stripped) or stripped.startswith('saveOptions '):continue
        if re.match(r'^\S+\s+(?:\([^)]*\)\s+)?(?:tran|dc|pss|pnoise|info)\b',stripped):continue
        if stripped.startswith('// Open-loop load/interface check'):continue
        if stripped.startswith('VRST '):
            lines.append('VRSTD (div_rst 0) vsource type=pwl wave=[0 1.2 2n 1.2 2.01n 0]');continue
        if stripped.startswith('XD '):
            lines.append('XD (vdddig 0 clk div_rst q1 q2 q3 q4 fb) pll130_div32_cmos');continue
        if stripped.startswith('CQ '):
            lines.append('CQ (fb 0) capacitor c=5f');continue
        lines.append(line)
    if removed_vctrl!=1:raise ValueError('Expected one ideal control driver to remove')
    text='\n'.join(lines)+'\n'
    pos=text.find('simulator lang=spectre')
    if pos<0:raise ValueError('Expected Spectre language marker')
    text=('// cmos130 frozen-code physical MOS fine-loop acquisition.\n'
          '// VCO/receiver/divider/PFD/CP active devices are PDK MOS; no AFC or VA.\n'
          '// Ideal reference/bias current sources, R/C passives and IC startup remain.\n'
          '// VCO structure derives from the supplied two-stage SPICE; 130nm sizes\n'
          '// and static-TG divider/AC receiver/drain-switch CP are new candidates.\n\n'+text[pos:])
    text=re.sub(r'\sVCTRLVAL=\S+','',text,count=1)
    text+='// Physical MOS fine loop; frozen coarse code, no AFC and no VA event models.\n'
    text+='include "{}/analog/pll130_cp_drain_candidate.scs"\n'.format(args.guest_root)
    text+='VDDCP (vddcp vdd) vsource dc=0\n'
    text+='VREF (ref 0) vsource type=pulse val0=0 val1=1.2 delay=10n rise=20p fall=20p width=4.98n period=10n\n'
    text+='VRSTP (rst 0) vsource type=pwl wave=[0 1.2 300n 1.2 300.1n 0]\n'
    text+='VEN (enable 0) vsource type=pwl wave=[0 0 300n 0 300.1n 1.2]\n'
    text+='XPFD (vdddig 0 ref fb rst up dn) pll130_pfd\n'
    text+='XCP (vddcp 0 up dn ctrl) pll130_cp_drain\n'
    text+='CSHUNT (ctrl 0) capacitor c=3.3843747954e-13\n'
    text+='RSERIES (ctrl filter_mid) resistor r=49501.46753\n'
    text+='CSERIES (filter_mid 0) capacitor c=6.43031211126e-12\n'
    text+='// IC-based startup, ideal resistor/capacitor LPF and reference/bias sources.\n'
    text+='ic ctrl={0:.12g} filter_mid={0:.12g} out0=0.935 out180=0.933 out90=0.934 out270=0.934\n'.format(ctrl)
    text+='saveOptions options save=selected\n'
    text+='save vdd vdddig vddcp bn bp ctrl filter_mid ref fb rst enable div_rst up dn out0 out180 out90 out270\n'
    text+='save VDD:p VDDIG:p VDDCP:p clk q1 q2 q3 q4 rxp rxn XRX.src XRX.inv_bias XRX.clkn XRX.XT.main:d\n'
    text+='save XCP.bncp XCP.bpcp XCP.pinternal XCP.ninternal\n'
    text+='tran tran stop={:.12g} maxstep={}p errpreset=moderate skipdc=no strobeperiod=10p strobeoutput=strobeonly\n'.format(args.duration_us*1e-6,args.maxstep_ps)
    if 'ahdl_include' in text or re.search(r'\bpll130_\w+_va\b',text):
        raise ValueError('Physical fine loop must not contain VA')
    if re.search(r'^VCTRL\s',text,re.M):raise ValueError('Control driver still present')
    name='pll_stage3_physical_code{}_ctrl{}_cpdrain_bounded{}p'.format(chosen['code'],int(round(ctrl*1e6)),args.maxstep_ps)
    path=root/'benches'/(name+'.scs');path.write_text(text)
    record=dict(name=name,path=str(path),bench_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                measured_loaded_case=args.case,measured_loaded_bench_sha256=measured[0]['bench_sha256'],
                loaded_frequency_Hz=measured[0]['actual_vco_frequency_Hz'],
                fixed_code=chosen['code'],initial_ctrl_V=ctrl,receiver_case=chosen['receiver_case'],
                duration_s=args.duration_us*1e-6,maxstep_s=args.maxstep_ps*1e-12,strobeperiod_s=10e-12,
                fine_enable_midpoint_s=300.05e-9,
                scope='Physical MOS VCO/receiver/divider/PFD/drain-switch CP, static coarse sources, ideal ref/bias/passives, IC startup, nominal acquisition; no AFC/PEX/PVT/noise/jitter signoff',
                lpf_note='R/C retained from candidate 423MHz/V analysis; actual loaded Kvco and loop stability not yet characterized')
    (root/'benches'/(name+'_manifest.json')).write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
