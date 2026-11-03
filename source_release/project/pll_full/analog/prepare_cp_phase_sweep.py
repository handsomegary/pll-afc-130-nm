"""Near-lock drain-CP charge-vs-phase benches. No simulator; Python3.6+."""
import hashlib
import json
import argparse
from pathlib import Path

ROOT=Path(__file__).resolve().parent
GUEST='@PROJECT_ROOT@/pll_full/analog'


def pwl(on,off):
    edge=20e-12
    return '[0 0 {a:.12g} 0 {b:.12g} 1.2 {c:.12g} 1.2 {d:.12g} 0 50n 0]'.format(
        a=on,b=on+edge,c=off,d=off+edge)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--extended',action='store_true')
    args=ap.parse_args()
    records=[]
    skews=[-400,-300] if args.extended else [-200,-150,-100,-50,0,50,100,150,200]
    for skew_ps in skews:
        skew=skew_ps*1e-12
        start=20e-9; reset=200e-12
        up_on=start+max(-skew,0)
        dn_on=start+max(skew,0)
        off=max(up_on,dn_on)+reset
        tag='cp_drain_phase_{}'.format('m'+str(-skew_ps) if skew_ps<0 else 'p'+str(skew_ps))
        txt=('simulator lang=spectre\nglobal 0\n'
             'include "@TECH_ROOT@/models/spectre/ms013_io33_v2p6_7p_spe.lib" section=tt\n'
             'include "{guest}/pll130_cp_drain_candidate.scs"\n'
             'simulatorOptions options temp=25 reltol=1e-5 vabstol=1e-7 iabstol=1e-12\n'
             'VDD (vdd 0) vsource dc=1.2\n'
             'VCLAMP (ctrl 0) vsource dc=0.8359375\n'
             'VUP (up 0) vsource type=pwl wave={up}\n'
             'VDN (dn 0) vsource type=pwl wave={dn}\n'
             'XCP (vdd 0 up dn ctrl) pll130_cp_drain\n'
             'saveOptions options save=selected\n'
             'save vdd ctrl up dn VCLAMP:p VDD:p XCP.bncp XCP.bpcp '
             'XCP.pinternal XCP.ninternal XCP.MPUSW:d XCP.MNDSW:d\n'
             'tran tran stop=50n maxstep=2p errpreset=conservative skipdc=no\n').format(
                 guest=GUEST,up=pwl(up_on,off),dn=pwl(dn_on,off))
        path=ROOT/'benches'/(tag+'.scs')
        path.write_text(txt,encoding='utf-8')
        records.append(dict(name=tag,phase_skew_s=skew,common_reset_s=reset,
                            ctrl_V=.8359375,path=str(path),
                            ideal_net_charge_C=20e-6*skew,
                            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            scope='Physical drain-switched MOS CP with ideal '
                                  'reference/controls/voltage clamp; no PFD noise.'))
    manifest='cp_phase_extended_manifest.json' if args.extended else 'cp_phase_manifest.json'
    (ROOT/'benches'/manifest).write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    print('Prepared {} CP phase benches; no simulator started.'.format(len(records)))


if __name__=='__main__':main()
