"""Exactly three AC-coupled self-bias receiver units; no simulator launch."""
import hashlib
import json
from pathlib import Path


def main():
    root=Path(__file__).resolve().parent
    template=(root/'benches/tb_receiver_div32.scs').read_text()
    template=template.replace('include "../pll130_digital_mos.scs"',
                              'include "../pll130_digital_mos.scs"\ninclude "../pll130_receiver_ac.scs"')
    old='XRX (vdd 0 bn inp inn clk rxp rxn) pll130_receiver'
    if template.count(old)!=1:raise ValueError('Expected one receiver')
    results=[]
    for cfemto,r in [(20,1000000),(40,1000000),(40,500000)]:
        name='tb_receiverac_c{}_r{}'.format(cfemto,r)
        text=template.replace(old,'XRX (vdd 0 bn inp inn clk rxp rxn) pll130_receiver_ac CC={}f RB={}'.format(cfemto,r))
        text=text.replace('save vdd bn inp inn rxp rxn clk rst q1 q2 q3 q4 q5 VDD:p VP:p VN:p XRX.src XRX.XT.main:d',
                          'save vdd bn inp inn rxp rxn clk rst q1 q2 q3 q4 q5 VDD:p VP:p VN:p XRX.src XRX.XT.main:d XRX.inv_bias XRX.clkn')
        # Bound waveform storage while the analog solver still resolves 2ps.
        text=text.replace('tran tran stop=100n maxstep=2p errpreset=conservative',
                          'tran tran stop=100n maxstep=2p errpreset=conservative strobeperiod=2p strobeoutput=strobeonly')
        text='// Alternative AC self-bias receiver; original MOS divider unchanged.\n'+text
        path=root/'benches'/(name+'.scs');path.write_text(text)
        results.append({'name':name,'path':str(path),'bench_sha256':hashlib.sha256(text.encode()).hexdigest(),
                        'coupling_C_F':cfemto*1e-15,'bias_feedback_R_ohm':r,
                        'input_each_total_width_um':6.0,'input_pair_total_width_um':12.0,
                        'tail_nf':12,'tail_total_width_um':30.0,'R_load_ohm':3000,
                        'scope':'Ideal diff clock into real RF receiver+AC selfbias CMOS+real divide32, nominal prelayout only'})
    (root/'benches/receiver_ac_manifest.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Prepared three AC receiver cases, original preserved; simulator not launched.')


if __name__=='__main__':main()
