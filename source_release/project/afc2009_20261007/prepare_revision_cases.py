"""Versioned electrical diagnostic and unit benches, without changing R0.

Unit clocks <=140MHz;100ps saved samples and adaptive edge integration.
This bounded timing experiment does not validate any3.2GHz VCO waveform.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', choices=['r1','r2','r3'], required=True)
    parser.add_argument('--project', default='@PROJECT_ROOT@')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    source_dir = here/('mos_'+args.revision)
    source_hash = sha(source_dir/'afc2009_mos.scs')
    manifest = json.loads((source_dir/'port_manifest.json').read_text())
    if source_hash != manifest['source_sha256']:
        raise ValueError('MOSsourcehashmismatch')
    out = here/'integration'/args.revision/'units'
    out.mkdir(parents=True, exist_ok=True)
    originals = out/'original20p'
    subprocess.check_call([sys.executable,str(source_dir/'prepare_unit_benches.py'),
        '--guest-source-dir',args.project+'/afc2009_20261007/mos_'+args.revision,
        '--out-dir',str(originals)])
    records = json.loads((originals/'unit_manifest.json').read_text())
    units = []
    for old in records:
        old_path = Path(old['path'])
        text = old_path.read_text()
        text,nstep = re.subn(r'maxstep=20p','maxstep=100p',text)
        text,nstrobe = re.subn(r'strobeperiod=20p','strobeperiod=100p',text)
        if (nstep,nstrobe) != (1,1):
            raise ValueError('Unexpectedfixturesteporstrobecount')
        name = old['name']+'_'+args.revision+'_100p'
        path = out/(name+'.scs')
        path.write_text('// Versionedunit100psmaxstep/strobe; adaptiveedges.\n'+text)
        record = dict(old)
        record.update(name=name,fixture_name=old['name'],path=str(path.resolve()),
            sha256=sha(path),mos_source_sha256=source_hash,revision=args.revision,
            maxstep_s=100e-12,strobeperiod_s=100e-12,
            original_bench_sha256=sha(old_path),actual_status='not_run',
            scope='Ideal100/140/70MHzunitclocks; physicalMOScontrol;100pssavedstrobe; adaptiveedges; noVCO/PLLclaim.')
        units.append(record)
    (out/'unit_manifest.json').write_text(json.dumps(units,indent=2)+'\n')
    diag = dict(units[0])
    diag_name = 'afc_unit_near100_phase_high_'+args.revision+'_diagnostic600n'
    path = out/(diag_name+'.scs')
    text = Path(units[0]['path']).read_text()
    text,count = re.subn(r'(?m)^tran tran stop=\S+','tran tran stop=600n',text)
    if count != 1:
        raise ValueError('Unexpectedtranstatement')
    path.write_text('// ShortFSMdiagnostic; notterminal-successfixture.\n'+text)
    diag.update(name=diag_name,path=str(path.resolve()),sha256=sha(path),
        duration_s=600e-9,fixture_name=None,
        expected='SingleSETTLE->ARM->MEASURE; nofalseDONE/FAIL beforeprovisionalwindow.',
        scope='Short0.6usFSMtimingdiagnosticonly; nofullunitPASSclaim.')
    (out/'diagnostic_manifest.json').write_text(json.dumps([diag],indent=2)+'\n')
    print(json.dumps(dict(revision=args.revision,source_sha256=source_hash,
                         units=str(out/'unit_manifest.json'),diagnostic=str(out/'diagnostic_manifest.json'))))


if __name__ == '__main__':
    main()
