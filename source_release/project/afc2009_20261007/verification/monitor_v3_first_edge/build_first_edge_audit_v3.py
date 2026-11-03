"""Read-only ledger re-audit and immutable monitor/source preservation record."""
from __future__ import print_function
import copy
import hashlib
import json
from pathlib import Path
import measure_afc2009 as m
import measure_afc2009_unit as u


HERE=Path(__file__).resolve().parent
VERIFICATION=HERE.parent
ROOT=VERIFICATION.parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    original=['measure_afc2009.py','measure_afc2009_unit.py','physical_portmap_r1.json',
        'frozen_monitor_v2_terminal/source_manifest.json',
        'frozen_monitor_v2_terminal/measure_afc2009.py',
        'frozen_monitor_v2_terminal/measure_afc2009_unit.py',
        'frozen_monitor_v2_terminal/physical_portmap_r1.json']
    preservation={str(VERIFICATION/path):digest(VERIFICATION/path) for path in original}
    assert preservation[str(VERIFICATION/'measure_afc2009.py')]=='b2898c42d28918f00b095e763427f4bacae7cb08e2b6c4ac4d551b328c214d10'
    assert digest(HERE/'physical_portmap_r1.json')==digest(VERIFICATION/'physical_portmap_r1.json')
    cfg=u.config(HERE/'physical_portmap_r1.json')
    records=[]
    for path in sorted((ROOT/'evidence'/'r1').glob('*measurement.json')):
        old=json.loads(path.read_text(encoding='utf8'))
        if not old.get('digital_transition_ledgers') or not old.get('word_transition_ledgers'):
            continue
        audit=m.audit_round_edges(old['digital_transition_ledgers'],old['word_transition_ledgers'],cfg)
        old_rounds=old.get('round_edge_audit',{}).get('rounds',[])
        rounds=[]
        for row in audit['rounds']:
            previous=old_rounds[row['trial_index']] if row['trial_index']<len(old_rounds) else {}
            rounds.append({'trial_index':row['trial_index'],'trial_code':row.get('trial_code'),
                'previous_first_edge_bracket':previous.get('first_edge_bracket'),
                'corrected_first_edge_bracket':row['first_edge_bracket'],
                'sign_proof_unchanged':previous.get('sign_proof')==row.get('sign_proof'),
                'counter_snapshot_unchanged':previous.get('observed_counter_snapshot')==row.get('observed_counter_snapshot')})
        acknowledged=[row for row in audit['rounds'] if row.get('epoch_ack_time_s') is not None]
        records.append({'measurement_path':str(path),'measurement_sha256':digest(path),
            'name':old['name'],'raw_evidence_from_existing_extraction':old.get('source_evidence'),
            'rounds':rounds,'acknowledged_first_edge_count':len(acknowledged),
            'all_acknowledged_first_edge_brackets_valid':all(
                row['first_edge_bracket'].get('bracket_proof') is True
                for row in acknowledged) if acknowledged else None,
            'extraction_scope':'Read-only reanalysis of previously extracted, SHA-bound transition ledgers. '
                'No reread of original PSF, new simulator result or replacement of old measurement JSON.'})
    source_files=['measure_afc2009.py','measure_afc2009_unit.py','physical_portmap_r1.json',
        'physical_portmap_proposed.json','postprocess_completed_case_v3.py',
        'test_measure_afc2009.py','test_measure_afc2009_unit.py','test_first_edge_v3.py',
        'build_first_edge_audit_v3.py','README_zh.txt']
    manifest={'version':'monitor-v3-first-edge','sources':{name:digest(HERE/name) for name in source_files},
        'preserved_original_monitor_sources':preservation,'source_models_or_benches_modified':False,
        'simulator_started':False}
    (HERE/'source_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    fixtures={name:json.loads((HERE/name).read_text(encoding='utf8')) for name in
        ['postprocessor_fixture_results.json','unit_postprocessor_fixture_results.json','first_edge_fixture_results.json']}
    out={'version':'first-edge-audit-v3','parser_fix_not_new_MOS_fix':True,
        'simulator_started':False,'source_models_or_benches_modified':False,
        'legacy_monitor_sources_preserved':preservation,
        'v3_monitor_manifest_path':str(HERE/'source_manifest.json'),
        'v3_monitor_manifest_sha256':digest(HERE/'source_manifest.json'),
        'fixtures':fixtures,'existing_actual_ledger_reanalysis':records,
        'root_next_step':'Use v3 postprocessor to reread each completed original PSF with source/bench binding. '
            'Write new v3 measurement JSON filenames; preserve all previous v2 results.',
        'scope':'Saved counter-reset and gated-clock threshold eligibility plus actual original REF adjacency. '
            'No MOS modification, stimulus redefinition, setup/hold, metastability, MTBF or PVT proof.'}
    (VERIFICATION/'first_edge_audit_v3.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'output':str(VERIFICATION/'first_edge_audit_v3.json'),
        'actual_ledgers_reaudited':len(records),'synthetic_checks':sum(row['fixtures_passed'] for row in fixtures.values()),
        'monitor_source_sha256':manifest['sources']['measure_afc2009.py']}))


if __name__=='__main__':
    main()
