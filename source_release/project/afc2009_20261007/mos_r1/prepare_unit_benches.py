"""Create bounded electrical AFC unit fixtures; stimulus clocks are ideal.

These are tests of the transistor logic, not the RF VCO/PLL or measured jitter.
Constant fast/slow clocks deliberately remain out of range as code changes;
they must select FAIL at the final endpoint rather than assert handover.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT='@PROJECT_ROOT@'
PDK='@TECH_ROOT@/models/spectre/ms013_io33_v2p6_7p_spe.lib'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--guest-source-dir',default=ROOT+'/afc2009_20261007/mos_r1')
    ap.add_argument('--out-dir',default=str(Path(__file__).resolve().parent/'benches'))
    args=ap.parse_args();here=Path(__file__).resolve().parent
    m=json.loads((here/'port_manifest.json').read_text(encoding='utf-8'));out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    diags=[]
    for value in m['diagnostic_hierarchy'].values():
        if isinstance(value,str):diags.append(value)
        elif isinstance(value,list):diags.extend(value)
        elif isinstance(value,dict):diags.extend(value.values())
    diags=list(dict.fromkeys(diags))
    cases=[('afc_unit_near100_phase_high',100e6,13e-9,1.8e-6,'DONE code16, provisional near'),
           ('afc_unit_near100_phase_low',100e6,17e-9,1.8e-6,'DONE code16, provisional near'),
           ('afc_unit_fast140',140e6,13e-9,1.8e-6,'FAIL at code1, no handover'),
           ('afc_unit_slow70',70e6,13e-9,1.8e-6,'FAIL at code31, no handover'),
           ('afc_unit_no_feedback',0,0,.65e-6,'FAIL ARM watchdog, no handover')]
    records=[]
    pins=['vdd','0','ref','fb','rst','afc_start']+['s'+str(i) for i in range(5)]+['afc_done','afc_fail','hold_all','fine_enable','pfd_reset','afc_active']
    for name,freq,delay,duration,expected in cases:
        text='// Physical MOS AFC unit; ideal test clocks, not a RF VCO/PLL.\nsimulator lang=spectre\nglobal 0\n'
        text+='include "{}" section=tt\n'.format(PDK)
        text+='include "{}/afc2009_mos.scs"\n'.format(args.guest_source_dir)
        text+='simulatorOptions options temp=25 reltol=1e-4 vabstol=1e-6 iabstol=1e-12\n'
        text+='VDD (vdd 0) vsource dc=1.2\n'
        text+='VREF (ref 0) vsource type=pulse val0=0 val1=1.2 delay=10n rise=20p fall=20p width=4.98n period=10n\n'
        if freq:
            period=1/freq;text+='VFB (fb 0) vsource type=pulse val0=0 val1=1.2 delay={:.12g} rise=20p fall=20p width={:.12g} period={:.12g}\n'.format(delay,period/2-20e-12,period)
        else:text+='VFB (fb 0) vsource dc=0\n'
        text+='VRST (rst 0) vsource type=pwl wave=[0 1.2 100n 1.2 100.02n 0]\n'
        text+='VSTART (afc_start 0) vsource type=pwl wave=[0 0 120n 0 120.02n 1.2]\n'
        text+='XAFC ({}) afc2009_mos\n'.format(' '.join(pins))
        for node in pins[6:]:text+='CLOAD_{} ({} 0) capacitor c=2f\n'.format(node,node)
        text+='saveOptions options save=selected\n'
        text+='save '+' '.join(pins[2:])+' VDD:p\n'
        text+='save '+' '.join('XAFC.'+n for n in diags)+'\n'
        text+='tran tran stop={:.12g} maxstep=20p errpreset=moderate skipdc=no strobeperiod=20p strobeoutput=strobeonly\n'.format(duration)
        path=out/(name+'.scs');path.write_text(text,encoding='utf-8')
        records.append({'name':name,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'mos_source_sha256':m['source_sha256'],'feedback_Hz':freq,'feedback_delay_s':delay,'reference_Hz':100e6,'duration_s':duration,'maxstep_s':20e-12,'strobeperiod_s':20e-12,'expected':expected,'actual_status':'not_run'})
    (out/'unit_manifest.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'cases':len(records),'source_sha256':m['source_sha256'],'guest_source_dir':args.guest_source_dir,'out_dir':str(out)},indent=2))


if __name__=='__main__':main()
