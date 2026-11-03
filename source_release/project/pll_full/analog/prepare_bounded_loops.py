"""Separate bounded acquisition diagnostics; never overwrite in-flight bench."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def main():
    records=[]
    source=ROOT/'benches/pll_stage1_fixed26_ctrl835938.scs'
    text=source.read_text(encoding='utf-8')
    original='tran tran stop=2e-06 maxstep=1p errpreset=conservative skipdc=no strobeperiod=10p strobeoutput=strobeonly'
    if text.count(original)!=1:
        raise ValueError('Unexpected original analysis; no adaptive overwrite.')
    for maxstep in [2,1]:
        tag='pll_stage1_fixed26_ctrl835938_bounded{}p'.format(maxstep)
        analysis=('tran tran stop=1.2e-06 maxstep={}p errpreset=conservative '
                  'skipdc=no strobeperiod=10p strobeoutput=strobeonly').format(maxstep)
        out=text.replace(original,analysis)
        out+='// Separate bounded ACQUISITION diagnostic: 1.2us; no physical noise.\n'
        out+='// 2ps is at least156 steps/3.2GHz period; tolerance still conservative.\n'
        path=ROOT/'benches'/(tag+'.scs')
        path.write_text(out,encoding='utf-8')
        records.append(dict(case_id=tag,path=str(path),
                            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            original_bench_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                            duration_s=1.2e-6,maxstep_s=maxstep*1e-12,
                            loop_enable_s=300e-9,output_strobe_s=10e-12,
                            precision='conservative, reltol1e-5, vabstol1e-7, iabstol1e-12',
                            lock_required_hold_s=500e-9,
                            maximum_settling_after_enable_for_500ns_hold_s=400e-9,
                            scope='Acquisition diagnostic at fixed code26, MOS '
                                  'VCO but VA PFD/CP/divider; not noise jitter.'))
    original_options='simulatorOptions options temp=25 reltol=1e-5 vabstol=1e-7 iabstol=1e-12'
    if text.count(original_options)!=1:
        raise ValueError('Unexpected original simulatorOptions; no blind rewrite.')
    for maxstep in [4,2]:
        tag='pll_stage1_fixed26_ctrl835938_bounded{}'.format(maxstep)+'p'
        if maxstep==2:
            tag+='_moderate'
        out=text.replace(original_options,
                         'simulatorOptions options temp=25 reltol=1e-4 vabstol=1e-6 iabstol=1e-12')
        analysis=('tran tran stop=2e-06 maxstep={}p errpreset=moderate '
                  'skipdc=no strobeperiod=10p strobeoutput=strobeonly').format(maxstep)
        out=out.replace(original,analysis)
        out+='// Separate bounded engineering ACQUISITION diagnostic: no physical noise.\n'
        out+='// Tolerances deliberately relaxed and reported; never label noise jitter.\n'
        path=ROOT/'benches'/(tag+'.scs')
        path.write_text(out,encoding='utf-8')
        records.append(dict(case_id=tag,path=str(path),
                            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            original_bench_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                            duration_s=2e-6,maxstep_s=maxstep*1e-12,
                            loop_enable_s=300e-9,output_strobe_s=10e-12,
                            precision='moderate, reltol1e-4, vabstol1e-6, iabstol1e-12',
                            lock_required_hold_s=500e-9,
                            maximum_settling_after_enable_for_500ns_hold_s=1.2e-6,
                            scope='Engineering acquisition only, fixed code26 '
                                  'MOS VCO with VA PFD/CP/divider; not noise jitter.'))
    (ROOT/'benches/bounded_loop_manifest.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    print('Prepared 4 separate bounded benches; original was not changed.')


if __name__=='__main__':main()
