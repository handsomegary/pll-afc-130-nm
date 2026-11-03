"""Prepare isolated bounded CP revisions, no simulator. Python 3.6+."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
GUEST='@PROJECT_ROOT@/pll_full/analog'


def main():
    records=[]
    for scale in [4,8]:
        tag='cp_gate{}_pulse'.format(scale)
        text=(ROOT/'benches/cp_pulse.scs').read_text(encoding='utf-8')
        text=text.replace('XCP (vdd 0 up dn ctrl) pll130_cp_transistor',
                          'XCP (vdd 0 up dn ctrl) pll130_cp_transistor '
                          'WN_SW={}u WP_SW={}u'.format(.5*scale,1.5*scale))
        path=ROOT/'benches'/(tag+'.scs')
        path.write_text(text,encoding='utf-8')
        records.append(dict(name=tag,kind='pulse',model='gate-switched',
                            gate_mux_width_scale=scale,path=str(path),
                            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    baseline=[ROOT/'benches/cp_pulse.scs']
    baseline += [ROOT/'benches'/('cp_dc_v835938_'+s+'.scs')
                 for s in ['up','dn','both','off']]
    for original in baseline:
        tag=original.stem.replace('cp_','cp_drain_',1)
        text=original.read_text(encoding='utf-8')
        text=text.replace('include "'+GUEST+'/pll130_cp_transistor.scs"',
                          'include "'+GUEST+'/pll130_cp_drain_candidate.scs"')
        text=text.replace('pll130_cp_transistor\n','pll130_cp_drain\n')
        text=text.replace(' XCP.gp XCP.gn',' XCP.pinternal XCP.ninternal')
        # Pulse saved mirror drain currents equal output SWITCH current only
        # in steady-state. Save actual output-switch terminals for KCL/charge.
        text=text.replace('XCP.MPUP:d XCP.MNDN:d','XCP.MPUSW:d XCP.MNDSW:d')
        path=ROOT/'benches'/(tag+'.scs')
        path.write_text(text,encoding='utf-8')
        records.append(dict(name=tag,kind='pulse' if 'pulse' in tag else 'dc',
                            model='drain-switched',path=str(path),
                            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (ROOT/'benches/cp_revision_manifest.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    print('Prepared {} CP revision cases, none started.'.format(len(records)))


if __name__=='__main__':
    main()
