"""Freeze prepare-only counter9 monitor manifest; no simulator launches."""
from __future__ import print_function
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
V3=HERE.with_name('monitor_v3_first_edge')
ROOT=HERE.parent.parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    if (HERE/'source_manifest.json').exists() or (HERE/'checks.json').exists():
        raise ValueError('Counter9 capsule already frozen; create a new version for changes.')
    original=json.loads((V3/'source_manifest.json').read_text(encoding='utf8'))
    assert all(digest(V3/name)==sha for name,sha in original['sources'].items())
    assert digest(HERE/'measure_afc2009.py')==digest(V3/'measure_afc2009.py')
    assert digest(HERE/'physical_portmap_r1.json')==digest(V3/'physical_portmap_r1.json')
    assert digest(HERE/'physical_portmap_proposed.json')==digest(V3/'physical_portmap_proposed.json')
    r2source=ROOT/'mos_r2'/'afc2009_mos.scs'
    r2manifest=ROOT/'mos_r2'/'port_manifest.json'
    assert digest(r2source)=='45654975e7b53873559fd157955c1d8a922f40550fea81687dfd675fe9de4cc0'
    r2=json.loads((HERE/'physical_portmap_r2.json').read_text(encoding='utf8'))
    assert r2['mapped_MOS_source_sha256']==digest(r2source)
    fixtures={name:json.loads((HERE/name).read_text(encoding='utf8')) for name in
        ['postprocessor_fixture_results.json','unit_postprocessor_fixture_results.json',
         'first_edge_fixture_results.json','counter9_fixture_results.json']}
    assert [fixtures[name]['fixtures_passed'] for name in fixtures]==[16,10,13,18]
    checks={'version':'monitor-v4-counter9-prepared-only','source_design_status':r2['source_design_status'],
        'simulator_started':False,'physical_R2_PASS':None,'common_math_byte_identical_to_v3':True,
        'original_39_fixtures_pass':True,'new_counter9_binding_fixtures_pass':True,
        'total_synthetic_fixture_checks':57,'fixtures':fixtures,
        'root_scope':'Prepared monitoring only; root waits for actual R1 full-PLL evidence before selecting R2.',
        'scope':'No physical R2 simulation, implementation change, watchdog/overflow, '
            'CDC/metastability, all-PVT or noise/FoM proof.'}
    (HERE/'checks.json').write_text(json.dumps(checks,indent=2)+'\n',encoding='utf8')
    sources=['measure_afc2009.py','measure_afc2009_unit.py','physical_portmap_proposed.json',
        'physical_portmap_r1.json','physical_portmap_r2.json','postprocess_completed_case_v4.py',
        'prepare_v4_portmap.py','test_measure_afc2009.py','test_measure_afc2009_unit.py',
        'test_first_edge_v3.py','test_counter9_v4.py','README_zh.txt','freeze_counter9_capsule.py']
    output={'version':'monitor-v4-counter9','source_design_status':r2['source_design_status'],
        'simulator_started':False,'physical_R2_PASS':None,'source_models_or_benches_modified':False,
        'sources':{name:digest(HERE/name) for name in sources},
        'checks_sha256':digest(HERE/'checks.json'),
        'fixture_result_sha256':{name:digest(HERE/name) for name in fixtures},
        'preserved_v3_manifest_sha256':digest(V3/'source_manifest.json'),
        'common_math_byte_identical_to_v3':True,
        'prepared_R2_source':{'path':str(r2source),'sha256':digest(r2source)},
        'prepared_R2_port_manifest':{'path':str(r2manifest),'sha256':digest(r2manifest)},
        'revision_map':{'r0':'physical_portmap_proposed.json','r1':'physical_portmap_r1.json','r2':'physical_portmap_r2.json'}}
    (HERE/'source_manifest.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'capsule':str(HERE),'source_manifest_sha256':digest(HERE/'source_manifest.json'),
        'R2_portmap_sha256':digest(HERE/'physical_portmap_r2.json'),
        'unit_monitor_sha256':digest(HERE/'measure_afc2009_unit.py'),
        'postprocessor_sha256':digest(HERE/'postprocess_completed_case_v4.py'),
        'total_synthetic_checks':57,'physical_R2_PASS':None,'simulator_started':False}))


if __name__=='__main__':
    main()
