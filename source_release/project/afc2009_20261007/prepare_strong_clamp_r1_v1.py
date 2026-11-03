"""Create a distinct R1 integration bench with a stronger physical clamp.

The completed original bench and the R1 AFC MOS source remain unchanged.
"""
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    here = Path(__file__).resolve().parent
    old_dir = here/'integration/r1/pll_6500n'
    record = json.loads((old_dir/'integration_manifest.json').read_text())[0]
    source = old_dir/(record['name']+'.scs')
    expected = '4538b92a7027f82e808d90c40230bf101f54c870c2bb6eca96a67902c9ab9793'
    if sha(source) != expected or record['bench_sha256'] != expected:
        raise ValueError('Preserved original R1 integration bench changed')
    afc = here/'mos_r1/afc2009_mos.scs'
    if sha(afc) != '12044e0dc052c06682a3372f17c0b8612d637954af88e0d8662cf1d8c0f8f6b8':
        raise ValueError('Frozen R1 AFC source changed')
    text = source.read_text()
    replacements = [
        ('CHOLD (vhold 0) capacitor c=1p','CHOLD (vhold 0) capacitor c=10p'),
        ('MHOLDCTRL (ctrl hold_all vhold 0) n12 w=4u l=.13u','MHOLDCTRL (ctrl hold_all vhold 0) n12 w=16u l=.13u'),
        ('PHOLDCTRL (ctrl hold_b vhold vddafc) p12 w=8u l=.13u','PHOLDCTRL (ctrl hold_b vhold vddafc) p12 w=32u l=.13u'),
        ('MHOLDMID (filter_mid hold_all vhold 0) n12 w=4u l=.13u','MHOLDMID (filter_mid hold_all vhold 0) n12 w=16u l=.13u'),
        ('PHOLDMID (filter_mid hold_b vhold vddafc) p12 w=8u l=.13u','PHOLDMID (filter_mid hold_b vhold vddafc) p12 w=32u l=.13u')]
    for old,new in replacements:
        if text.count(old) != 1:
            raise ValueError('Unexpected original clamp topology: '+old)
        text = text.replace(old,new)
    text = '// Revised physical clamp:4x TG widths and10pF half-supply reservoir; unchanged30mV audit limit.\n'+text
    name = 'pll_afc2009_physical_halfvdd_ref10000_4p_r1_strongclamp6500n_v1'
    out = here/'integration/r1/pll_strongclamp6500n_v1'
    if out.exists():
        raise ValueError('Refuse overwrite of an immutable revision')
    out.mkdir(parents=True)
    bench = out/(name+'.scs')
    bench.write_text(text)
    guest = '@PROJECT_ROOT@/afc2009_20261007'
    record.update(name=name,path=guest+'/integration/r1/pll_strongclamp6500n_v1/'+bench.name,
        bench_sha256=sha(bench),status='prepared_unverified',
        integration_revision='strong_clamp_v1',
        physical_clamp={'n_width_m':16e-6,'p_width_m':32e-6,'length_m':.13e-6,
            'half_supply_reservoir_F':10e-12,'resistors_ohm':[20000,20000]},
        unchanged_clamp_tolerance_V=.03,
        previous_completed_bench_sha256=expected,
        change_reason='Original completed R1 selected29 and fine-captured, but heldCTRL deviation35.5467mV exceeded unchanged30mV acceptance.')
    (out/'integration_manifest.json').write_text(json.dumps([record],indent=2)+'\n')
    (out/(name+'_manifest.json')).write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
