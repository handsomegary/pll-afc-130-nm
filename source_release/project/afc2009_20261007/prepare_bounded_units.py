"""Create separate larger-step unit copies; preserve20ps originals.

Unit-only digital clocks are100/140/70MHz, not the3.2GHz physical VCO.
Adaptive edge refinement remains enabled; actual electrical checks are required.
"""
import hashlib
import json
from pathlib import Path
import re


def main():
    here = Path(__file__).resolve().parent
    original = here/'mos/benches/unit_manifest.json'
    cases = json.loads(original.read_text())
    dest = here/'integration/unit_bounded'
    dest.mkdir(parents=True, exist_ok=True)
    output = []
    for case in cases:
        base = Path(case['path'])
        source = base.read_text()
        text, replacements = re.subn(r'maxstep=20p', 'maxstep=100p', source)
        if replacements != 1:
            raise ValueError('Expected one20ps unit maxstep.')
        name = case['name']+'_100p'
        path = dest/(name+'.scs')
        path.write_text('// Unit-only100ps maxstep copy;20ps original preserved.\n'+text)
        record = dict(case)
        record.update(name=name, fixture_name=case['name'], path=str(path.resolve()),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), maxstep_s=100e-12,
            original_bench_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),
            scope='SameMOS/clockstimulus/20pssavedstrobe; onlymaxstep20ps->100ps. Actualedgeadaptivefunctionchecksrequired.')
        output.append(record)
    (dest/'unit_bounded_manifest.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(dict(cases=len(output), output=str(dest))))


if __name__=='__main__':
    main()
