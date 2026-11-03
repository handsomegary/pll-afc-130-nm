"""Generate exactly six receiver interface benches; no simulation launch.
No divider changes. Same .93V CM/.25V differential Vpp/3.2GHz ideal input.
"""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    source = (root/'benches/tb_receiver_div32.scs').read_text()
    line = 'XRX (vdd 0 bn inp inn clk rxp rxn) pll130_receiver'
    if source.count(line) != 1:
        raise ValueError('Expected one receiver instance')
    variants = [(5000,12,3.2), (6000,12,3.2), (5000,12,6.4),
                (3000,20,3.2), (3000,24,3.2), (2500,24,6.4)]
    records = []
    for resistance, nf, wp in variants:
        name = 'tb_receiver_r{}_nf{}_p{}'.format(resistance,nf,int(wp*1000))
        text = source.replace(line, line+' RLOAD_RX={} TAIL_NF={} INV0_WP={}u'.format(resistance,nf,wp))
        text = '// Bounded receiver repair; original input device width/divider remain unchanged.\n'+text
        path = root/'benches'/(name+'.scs')
        path.write_text(text)
        records.append({'case_id':name,'path':str(path),'name':name,
                        'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'R_load_ohm':resistance,'tail_total_width_um':2.5*nf,
                        'tail_nf':nf,'first_inverter_pmos_width_um':wp,
                        'input_each_total_width_um':6.0,'input_pair_total_width_um':12.0,
                        'scope':'Ideal differential source into actual receiver+MOS divider; not loaded VCO'})
    (root/'benches/receiver_sweep_manifest.json').write_text(json.dumps(records,indent=2)+'\n')
    print('Prepared six bounded receiver benches; simulator not launched.')


if __name__ == '__main__':
    main()
