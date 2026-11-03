"""Freeze prepare-only diagnostic source capsule without simulator actions."""
from __future__ import print_function
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
V3=HERE.with_name('monitor_v3_first_edge')
ROOT=HERE.parent.parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    if (HERE/'source_manifest.json').exists():
        raise ValueError('Terminal-partial capsule already frozen; preserve this version.')
    assert sha(HERE/'measure_afc2009.py')==sha(V3/'measure_afc2009.py')
    assert sha(HERE/'physical_portmap_r1.json')==sha(V3/'physical_portmap_r1.json')
    source=ROOT/'mos_r1'/'afc2009_mos.scs'
    bench=ROOT/'integration'/'r1'/'pll_6500n'/'pll_afc2009_physical_halfvdd_ref10000_4p_r1_6500n.scs'
    assert sha(source)=='12044e0dc052c06682a3372f17c0b8612d637954af88e0d8662cf1d8c0f8f6b8'
    assert sha(bench)=='4538b92a7027f82e808d90c40230bf101f54c870c2bb6eca96a67902c9ab9793'
    fixtures=json.loads((HERE/'prefix_fixture_results.json').read_text(encoding='utf8'))
    assert fixtures['fixtures_passed']==9 and fixtures['analogue_waveforms_generated'] is False
    names=['measure_afc2009.py','physical_portmap_r1.json','collect_terminal_partial_proof.py',
        'postprocess_terminal_partial.py','test_terminal_partial_prefix.py','README_zh.txt','freeze_terminal_partial_capsule.py']
    output={'version':'terminal-partial-R1-v1-prepared-only','simulator_started':False,
        'numerical_completion':False,'full_case_pass':None,'analogue_actual_results_generated':False,
        'common_math_byte_identical_to_v3':True,'active_R1_source_and_bench_unchanged':True,
        'sources':{name:sha(HERE/name) for name in names},
        'fixture_results_sha256':sha(HERE/'prefix_fixture_results.json'),
        'fixture_checks':fixtures,'original_v3_manifest_sha256':sha(V3/'source_manifest.json'),
        'fixed_R1_source_sha256':sha(source),'fixed_R1_bench_sha256':sha(bench),
        'scope':'Prepared read-only terminal diagnostic. Accepts only exact stopped TimeoutExpired case '
            'with independent process-gone/cache/raw/source proof. No live/incomplete raw extraction.'}
    (HERE/'source_manifest.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'capsule':str(HERE),'source_manifest_sha256':sha(HERE/'source_manifest.json'),
        'collector_sha256':sha(HERE/'collect_terminal_partial_proof.py'),
        'postprocessor_sha256':sha(HERE/'postprocess_terminal_partial.py'),
        'fixtures_passed':9,'simulator_started':False}))


if __name__=='__main__':
    main()
