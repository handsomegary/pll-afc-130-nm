"""Prepare-only explicit R2 counter9 map; no circuit or simulation mutation."""
from __future__ import print_function
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    destination=HERE/'physical_portmap_r2.json'
    if destination.exists():
        raise ValueError('Prepared R2 map already exists; preserve immutable version.')
    source=ROOT/'mos_r2'/'afc2009_mos.scs'
    manifest=json.loads((ROOT/'mos_r2'/'port_manifest.json').read_text(encoding='utf8'))
    expected='45654975e7b53873559fd157955c1d8a922f40550fea81687dfd675fe9de4cc0'
    assert digest(source)==manifest['source_sha256']==expected
    assert manifest['counter_bits']==9 and manifest['window_lag_counts']==224
    assert manifest['counter_epoch_watchdog_REF_clocks']==248
    mapped=json.loads((HERE/'physical_portmap_r1.json').read_text(encoding='utf8'))
    diagnostic=manifest['diagnostic_hierarchy']
    for name,key in [('n_lead','decision_lead'),('n_lag','decision_lag'),('n_div','decision_div')]:
        mapped['words'][name]=['XAFC.'+node for node in diagnostic[key]]
        assert len(mapped['words'][name])==9
    mapped['words']['counter_epoch_age']=['XAFC.'+node for node in diagnostic['counter_epoch_age']]
    mapped['digitals']['epoch_watchdog']='XAFC.'+diagnostic['epoch_watchdog']
    mapped['digitals']['reference_counter_reset']='XAFC.'+diagnostic['reference_counter_reset']
    contract=mapped['counter_contract']
    contract.update(counter_bits=9,CDC='registered 9-bit native Gray to two matched REF-stage synchronizers',
        near_window_lag_counts=224,counter_epoch_watchdog_REF_clocks=248,
        global_counter_age_REF_clocks=248,counter_epoch_age_word='counter_epoch_age',
        counter_epoch_watchdog_scope=manifest['counter_epoch_watchdog_scope'],
        counter_overflow_guard_scope=manifest['counter_overflow_guard'])
    mapped['map_status']='R2 prepared_unverified_offline_candidate_not_selected; MOS source '+expected
    mapped['counter_proof_scope']='Frozen 9-bit snapshots support signed 2-count comparisons; '
    mapped['counter_proof_scope']+='phase bracket does not prove startup credits, CDC/metastability or overflow limits.'
    mapped['source_design_status']=manifest['source_design_status']
    mapped['mapped_MOS_source_sha256']=expected
    destination.write_text(json.dumps(mapped,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'output':str(destination),'sha256':digest(destination),
        'source_status':manifest['source_design_status'],'simulator_started':False}))


if __name__=='__main__':
    main()
