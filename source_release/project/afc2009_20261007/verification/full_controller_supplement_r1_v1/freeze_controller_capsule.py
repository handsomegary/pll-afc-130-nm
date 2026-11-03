"""Freeze new supplemental source capsule only; no VM/simulator operations."""
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
    output=HERE/'source_manifest.json'
    if output.exists():
        raise ValueError('Capsule already frozen; preserve version.')
    assert sha(HERE/'measure_afc2009.py')==sha(V3/'measure_afc2009.py')
    assert sha(HERE/'physical_portmap_r1.json')==sha(V3/'physical_portmap_r1.json')
    original=json.loads((V3/'source_manifest.json').read_text(encoding='utf8'))
    assert all(sha(V3/name)==expected for name,expected in original['sources'].items())
    source=ROOT/'mos_r1'/'afc2009_mos.scs'
    assert sha(source)=='12044e0dc052c06682a3372f17c0b8612d637954af88e0d8662cf1d8c0f8f6b8'
    fixtures=json.loads((HERE/'controller_fixture_results.json').read_text(encoding='utf8'))
    assert fixtures['fixtures_passed']==14 and fixtures['analogue_actual_results_generated'] is False
    names=['measure_afc2009.py','physical_portmap_r1.json','extract_full_controller.py',
        'test_controller_supplement.py','README_zh.txt','freeze_controller_capsule.py']
    result={'version':'FULL-controller-supplement-R1-v1-prepared-only','simulator_started':False,
        'physical_FULL_PASS':None,'source_or_bench_modified':False,'clamp_criterion_modified':False,
        'sources':{name:sha(HERE/name) for name in names},
        'common_math_byte_identical_to_v3':True,'original_v3_manifest_sha256':sha(V3/'source_manifest.json'),
        'bound_R1_MOS_source_sha256':sha(source),'strict_clamp_tolerance_V':.03,
        'fixture_result_sha256':sha(HERE/'controller_fixture_results.json'),'fixtures':fixtures,
        'scope':'Prepared source-bound supplemental extractor; only completed rc0 exact cache/raw/measurement '
            'pairs may be read. Actual controller result awaits root execution; no new simulation claim.'}
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'capsule':str(HERE),'source_manifest_sha256':sha(output),
        'extractor_sha256':sha(HERE/'extract_full_controller.py'),'fixtures_passed':14,'simulator_started':False}))


if __name__=='__main__':
    main()
