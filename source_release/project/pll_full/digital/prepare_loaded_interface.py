"""Prepare exactly two MOS VCO+AC-receiver+MOS-div32 open-loop checks.
Requires a measured passing receiver selection; never picks an unverified one.
No simulation launch; preserves exact VCO devices and changes only code/ctrl.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

GUEST_ROOT='@PROJECT_ROOT@/pll_full'


def base(source,code,ctrl):
    if 'n12_ckt_rf' not in source or 'LREF=3.12u' not in source:
        raise ValueError('Require exact selected area8 source')
    lines=[]
    for line in source.splitlines():
        stripped=line.strip()
        if re.match(r'^(save|ic)\s',stripped) or stripped.startswith('saveOptions '):continue
        if re.match(r'^\S+\s+(?:\([^)]*\)\s+)?(?:tran|dc|pss|pnoise|info)\b',stripped):continue
        if stripped.startswith('// Actual code 26'):continue
        lines.append(line)
    text='\n'.join(lines)+'\n'
    text,n=re.subn(r'\bVCTRLVAL=\S+','VCTRLVAL={:.12g}'.format(ctrl),text,count=1)
    if n!=1:raise ValueError('Expected one VCTRLVAL')
    for bit in range(5):
        text,n=re.subn(r'\bCODE'+str(bit)+r'=\S+','CODE{}={}'.format(bit,(code>>bit)&1),text,count=1)
        if n!=1:raise ValueError('Expected one CODE{}'.format(bit))
    text,n=re.subn(r'(simulatorOptions options temp=25 )reltol=1e-5 vabstol=1e-7 iabstol=1e-12',
                   r'\1reltol=1e-4 vabstol=1e-6 iabstol=1e-12',text)
    if n!=1:raise ValueError('Expected one tolerance line')
    return text


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vco-source',required=True)
    ap.add_argument('--receiver-results',required=True)
    ap.add_argument('--guest-root',default=GUEST_ROOT)
    args=ap.parse_args();root=Path(__file__).resolve().parent
    result=json.loads(Path(args.receiver_results).read_text())
    chosen=result.get('selected_candidate')
    if not chosen or result.get('all_three_present') is not True:
        raise ValueError('Require completed three-case receiver selection')
    matches=[r for r in result.get('cases',[]) if r.get('name')==chosen and r.get('valid') is True]
    if len(matches)!=1:raise ValueError('Selection must reference a passing electrical case')
    variant=[r for r in json.loads((root/'benches/receiver_ac_manifest.json').read_text()) if r['name']==chosen]
    if len(variant)!=1:raise ValueError('Unknown receiver variant')
    rx=variant[0]
    current_sha=hashlib.sha256(Path(rx['path']).read_bytes()).hexdigest()
    if matches[0].get('bench_sha256')!=current_sha:raise ValueError('Receiver bench bytes changed after measured result')
    source=Path(args.vco_source).read_text(encoding='utf8');records=[]
    for code,ctrl in [(28,0.8359375),(27,1.0)]:
        name='tb_loaded_interface_code{}_ctrl{}'.format(code,int(round(ctrl*1e6)))
        text=base(source,code,ctrl)
        text+='// Open-loop load/interface check, not a PLL/noise/jitter analysis.\n'
        text+='include "{}/digital/pll130_digital_mos.scs"\n'.format(args.guest_root)
        text+='include "{}/digital/pll130_receiver_ac.scs"\n'.format(args.guest_root)
        # Digital is at the positive terminal so -V*I matches VDD:p convention.
        text+='VDDIG (vdddig vdd) vsource dc=0\n'
        text+='VRST (rst 0) vsource type=pwl wave=[0 1.2 2n 1.2 2.01n 0]\n'
        text+='XRX (vdddig 0 bn out0 out180 clk rxp rxn) pll130_receiver_ac CC={:.12g} RB={:.12g}\n'.format(rx['coupling_C_F'],rx['bias_feedback_R_ohm'])
        text+='XD (vdddig 0 clk rst q1 q2 q3 q4 q5) pll130_div32_cmos\n'
        text+='CQ (q5 0) capacitor c=5f\n'
        text+='ic out0=0.935 out180=0.933 out90=0.934 out270=0.934\n'
        text+='saveOptions options save=selected\n'
        text+='save vdd vdddig bn bp ctrl out0 out180 out90 out270 VDD:p VDDIG:p\n'
        text+='save clk rst q1 q2 q3 q4 q5 rxp rxn XRX.src XRX.inv_bias XRX.clkn XRX.XT.main:d\n'
        text+='save XOSC.XSTAGE0.XTAILMAIN.main:d XOSC.XSTAGE0.XTAILREGEN.main:d XOSC.XSTAGE1.XTAILMAIN.main:d XOSC.XSTAGE1.XTAILREGEN.main:d\n'
        text+='tran tran stop=80n maxstep=4p errpreset=moderate skipdc=no strobeperiod=5p strobeoutput=strobeonly\n'
        path=root/'benches'/(name+'.scs');path.write_text(text)
        records.append({'name':name,'path':str(path),'bench_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'source_vco_sha256':hashlib.sha256(Path(args.vco_source).read_bytes()).hexdigest(),
                        'receiver_case':chosen,'receiver_unit_bench_sha256':current_sha,'code':code,'vctrl_V':ctrl,
                        'coupling_C_F':rx['coupling_C_F'],'bias_feedback_R_ohm':rx['bias_feedback_R_ohm'],
                        'duration_s':80e-9,'maxstep_s':4e-12,'errpreset':'moderate',
                        'scope':'Actual MOS VCO+RF receiver+AC selfbias CMOS+MOS divide32, ideal reference/passives, nominal open loop only; no PFD/CP/AFC/noise/PEX'})
    (root/'benches/loaded_interface_manifest.json').write_text(json.dumps(records,indent=2)+'\n')
    print('Prepared exactly two actual VCO/interface benches; no simulation launch.')


if __name__=='__main__':main()
