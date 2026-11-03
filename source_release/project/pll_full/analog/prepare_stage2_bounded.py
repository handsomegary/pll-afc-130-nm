"""Stage2 drain CP candidate + MOS PFD; preserve in-flight stage0/1 files."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def main():
    original=ROOT/'benches/pll_stage2_fixed26_ctrl835938_cpdrain.scs'
    source=original.read_text(encoding='utf-8')
    options='simulatorOptions options temp=25 reltol=1e-5 vabstol=1e-7 iabstol=1e-12'
    tran='tran tran stop=2e-06 maxstep=1p errpreset=conservative skipdc=no strobeperiod=10p strobeoutput=strobeonly'
    if source.count(options)!=1 or source.count(tran)!=1:
        raise ValueError('Unexpected source; no blind analysis replacement.')
    records=[]
    for step in [4,2]:
        tag='pll_stage2_fixed26_ctrl835938_cpdrain_bounded{}p'.format(step)
        text=source.replace(options,
                            'simulatorOptions options temp=25 reltol=1e-4 vabstol=1e-6 iabstol=1e-12')
        text=text.replace(tran,
                          'tran tran stop=2e-06 maxstep={}p errpreset=moderate '
                          'skipdc=no strobeperiod=10p strobeoutput=strobeonly'.format(step))
        text+='// CP variant is provisional pending near-lock phase-charge sweep.\n'
        path=ROOT/'benches'/(tag+'.scs')
        path.write_text(text,encoding='utf-8')
        records.append(dict(case_id=tag,path=str(path),
                            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            duration_s=2e-6,maxstep_s=step*1e-12,
                            loop_enable_s=300e-9,
                            precision='moderate, reltol1e-4, vabstol1e-6, iabstol1e-12',
                            cp_selected_final=False,
                            physical_blocks=['area8 mixed-RF VCO','MOS TSPC PFD','drain-switched MOS CP'],
                            behavioral_blocks=['divide-by-32'],
                            ideal_elements=['reference current','LPF passives','100MHz reference clock'],
                            scope='Staged physical analog/PFD acquisition; divider '
                                  'remains ideal and no physical noise/jitter claimed.'))
    (ROOT/'benches/stage2_bounded_manifest.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    print('Prepared 2 Stage2 bounded candidate benches; no simulator started.')


if __name__=='__main__':main()
