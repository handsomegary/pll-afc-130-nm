"""Independent v2 reanalysis of immutable, already extracted R0 evidence.

Uses actual saved transition ledgers from the original measurement and the
read-only state extractor. Does not read/change raw or launch simulations.
"""
from array import array
import json
from pathlib import Path
import measure_afc2009 as m
import measure_afc2009_unit as unit


def main():
    here=Path(__file__).resolve().parent
    root=here.parent
    original=root/'evidence/r0/near100_high_measurement.json'
    state=root/'evidence/r0/r0_state_ledger.json'
    before_original=m.sha(original)
    before_state=m.sha(state)
    old=json.loads(original.read_text(encoding='utf-8'))
    extracted=json.loads(state.read_text(encoding='utf-8'))
    if old['source_evidence']['raw_sha256']!=extracted['source_evidence']['raw_sha256']:
        raise ValueError('Original measurement and state ledger raw hashes differ.')
    digital=old['digital_transition_ledgers']
    for name,levels in extracted['digital_transition_ledgers'].items():
        if not levels:
            continue
        digital[name]={'levels':levels,
            'rising':[t for i,(t,v) in enumerate(levels) if i and v==1],
            'falling':[t for i,(t,v) in enumerate(levels) if i and v==0]}
    # The v1 extractor used two canonical names for the same actual ARM node;
    # its compact arm ledger is authoritative and equal to original trial_arm.
    if digital.get('arm',{}).get('levels'):
        digital['trial_arm']=digital['arm']
    # Unit logical checks use t only for actual recorded start/end limits;
    # analog arrays and electrical lock are deliberately not fabricated.
    end=old['source_evidence']['saved_samples']
    clock_end=max(t for event in digital.values() for t,_ in event['levels'])
    raw_end=1.8e-6
    if clock_end>raw_end+1e-12:
        raise ValueError('Extracted event outside completed R0 bench duration.')
    evidence=dict(old['source_evidence'])
    evidence['reanalysis_reads_raw']=False
    evidence['reanalysis_uses_already_extracted_saved_transitions']=True
    evidence['raw_unchanged_during_extraction']=None
    fixture=({'time':array('d',[0,raw_end])},digital,
             extracted['word_transition_ledgers'],evidence)
    old_reader=m.read_saved_vectors
    try:
        m.read_saved_vectors=lambda *args,**kwargs:fixture
        result=unit.measure_unit(old['source_evidence']['raw_file'],old['name'])
    finally:
        m.read_saved_vectors=old_reader
    result['reanalysis_original_measurement']={'path':str(original),
        'sha256':before_original,'version':old['version'],'original_unmodified':m.sha(original)==before_original}
    result['reanalysis_state_ledger']={'path':str(state),'sha256':before_state,
        'unmodified':m.sha(state)==before_state}
    result['original_unit_functional_pass']=old['unit_functional_pass']
    result['original_guard_false_samples']=len(old['equal_frequency_guarded_false_direction_samples'])
    result['original_raw_ARM_round_count']=len(old['round_edge_audit']['rounds'])
    result['monitor_sha256']={p.name:m.sha(p) for p in [here/'measure_afc2009.py',
        here/'measure_afc2009_unit.py',here/'physical_portmap_proposed.json',Path(__file__)]}
    result['conclusion']=('R0 retains a real one-hot FSM failure despite corrected trial grouping '
        'and post-propagation counter sampling. Original +1ns binary-decode observations '
        'were transient artifacts; they did not become qualified fast/slow decisions.')
    result['scope']=('Reanalysis from hash-linked actual R0 saved transition ledgers only. '
        'No additional analog waveform, simulation, acquisition power or noise metric inferred.')
    out=here/'r0_independent_reanalysis_v2.json'
    out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'output':str(out),'unit_functional_pass':result['unit_functional_pass'],
        'actual_counter_trials':len(result['round_edge_audit']['rounds']),
        'ARM_reentries':len(result['round_edge_audit']['ARM_reentries_without_new_counter_epoch_s']),
        'stable_guard_false_samples':len(result['equal_frequency_guarded_false_direction_samples']),
        'stable_state_overlap_samples':len(result['stable_state_overlap_samples']),
        'violations':result['violations']}))


if __name__=='__main__':
    main()
