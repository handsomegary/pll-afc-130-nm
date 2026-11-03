"""Generate exactly four complementary PFD checks; does not simulate.
Phase lead/lag use time-integral duty. Unequal-frequency cases check frequency
ordering/net UP-DN sign, not a fictitious fixed phase error.
"""
import hashlib
import json
from pathlib import Path


def main():
    root=Path(__file__).resolve().parent
    template=(root/'benches/tb_pfd_mos.scs').read_text()
    variants=[('tb_pfd_ref_lag',7e-9,6e-9,100e6,100e6,100e-9,'pfd',-1.0),
              ('tb_pfd_equal_phase',6e-9,6e-9,100e6,100e6,100e-9,'pfd',0.0),
              ('tb_pfd_ref99_fb100',5e-9,5e-9,99e6,100e6,500e-9,'pfd_frequency',None),
              ('tb_pfd_ref100_fb99',5e-9,5e-9,100e6,99e6,500e-9,'pfd_frequency',None)]
    results=[]
    for name,rdelay,fdelay,fr,ff,duration,kind,phase in variants:
        text=template.replace('parameters VD=1.2 REF_DELAY=5n FB_DELAY=6n',
          'parameters VD=1.2 REF_DELAY={:.12g} FB_DELAY={:.12g} FREF={:.12g} FFB={:.12g}'.format(rdelay,fdelay,fr,ff))
        text=text.replace('VRST (rst 0) vsource type=pulse val0=0 val1=VD delay=0 rise=20p fall=20p width=3n period=200n',
                          'VRST (rst 0) vsource type=pwl wave=[0 VD 3n VD 3.02n 0]')
        text=text.replace('delay=REF_DELAY rise=20p fall=20p width=5n period=10n',
                          'delay=REF_DELAY rise=20p fall=20p width=0.5/FREF-20p period=1/FREF')
        text=text.replace('delay=FB_DELAY rise=20p fall=20p width=5n period=10n',
                          'delay=FB_DELAY rise=20p fall=20p width=0.5/FFB-20p period=1/FFB')
        text=text.replace('tran tran stop=100n maxstep=5p errpreset=conservative',
                          'tran tran stop={:.12g} maxstep=5p errpreset=conservative strobeperiod=5p strobeoutput=strobeonly'.format(duration))
        text='\n'.join(l for l in text.splitlines() if not l.startswith('// REF_DELAY=') and not l.startswith('// Reverse REF_DELAY='))+'\n'
        path=root/'benches'/(name+'.scs');path.write_text(text)
        results.append({'name':name,'path':str(path),'bench_sha256':hashlib.sha256(text.encode()).hexdigest(),
                        'kind':kind,'phase_ns':phase,'ref_hz':fr,'fb_hz':ff,
                        'measurement_begin_s':20e-9 if kind=='pfd' else 50e-9,
                        'measurement_end_s':95e-9 if kind=='pfd' else 490e-9,
                        'duration_s':duration,'scope':'Ideal clock inputs and real transistor PFD; nominal only.'})
    (root/'benches/pfd_extended_manifest.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Prepared four complementary PFD benches; no simulation launch.')


if __name__=='__main__':main()
