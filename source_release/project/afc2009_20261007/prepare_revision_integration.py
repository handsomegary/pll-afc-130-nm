"""Produce immutable-named revised physical PLL benches from preserved base."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', choices=['r1','r2','r3'], required=True)
    parser.add_argument('--maxstep-ps', choices=[2,4], type=int, default=4)
    parser.add_argument('--ref-delay-ns', type=float, default=10)
    parser.add_argument('--duration-us', type=float, default=4.5)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    duration_tag = '' if abs(args.duration_us-4.5)<1e-9 else '_{}n'.format(int(round(args.duration_us*1000)))
    out = here/'integration'/args.revision/('pll'+duration_tag)
    source = here/('mos_'+args.revision)/'afc2009_mos.scs'
    subprocess.check_call([sys.executable,str(here/'prepare_integration.py'),
        '--baseline',str(here.parent/'pll_full/digital/benches/pll_stage3_physical_code28_ctrl835938_cpdrain_bounded2p.scs'),
        '--out-dir',str(out/'unlaunched_template'),
        '--maxstep-ps',str(args.maxstep_ps),'--ref-delay-ns',str(args.ref_delay_ns),
        '--duration-us',str(args.duration_us)])
    records = json.loads((out/'unlaunched_template/integration_manifest.json').read_text())
    record = records[0]
    template = Path(record['path']).read_text()
    old = '/afc2009_20261007/mos/afc2009_mos.scs'
    new = '/afc2009_20261007/mos_'+args.revision+'/afc2009_mos.scs'
    if template.count(old) != 1:
        raise ValueError('UnexpectedAFCsourceinclude')
    name = record['name']+'_'+args.revision+duration_tag
    path = out/(name+'.scs')
    text = '// AFC revision '+args.revision+'; source frozen before simulation.\n'+template.replace(old,new)
    diagnostics = ['settle','measure','drain','epoch_valid','control_clock',
        'reference_count_rst','fast_qualified','slow_qualified','counter_fb_clock',
        'fb_clock_enable','fast_raw','slow_raw','fast_prev','slow_prev']
    # Long PLL traces retain frozen24-bit decisions and sign history. Native
    # synchronized24-bit debug words are saved in unit tests, not this longer
    # RF trace, to keep raw within the512MiB streaming-reader guard.
    marker = 'tran tran stop='
    if text.count(marker) != 1:
        raise ValueError('Unexpectedtranstatement')
    text = text.replace(marker,'save '+' '.join('XAFC.'+node for node in diagnostics)+'\n'+marker)
    path.write_text(text)
    record.update(name=name,path=str(path.resolve()),bench_sha256=sha(path),
        mos_source_sha256=sha(source),revision=args.revision,
        status='prepared_unverified',saved_revision_diagnostics=diagnostics,
        saved_counter_scope='24frozen decision bits retained; synchronized/native Gray debug words are unit-only.')
    (out/(name+'_manifest.json')).write_text(json.dumps(record,indent=2)+'\n')
    (out/'integration_manifest.json').write_text(json.dumps([record],indent=2)+'\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
