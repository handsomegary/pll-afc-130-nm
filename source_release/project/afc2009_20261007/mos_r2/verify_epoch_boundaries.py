"""R2 literal generated gate/DFF boundary fixtures, without physical simulation.

Integer synchronized words are injected. Native clock/Gray timing, two-stage
CDC electrical behavior, reset apertures and PLL capture are not modeled.
"""
import hashlib
import importlib.util
import json
from pathlib import Path


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def boundary(circuit,name,ack_delay=5,near_age=None):
    from verify_literal_gate_fsm import LiteralModel
    m=LiteralModel(circuit);rows=[];terminal_state=None
    for cycle in range(360):
        m.values['rst']=int(cycle<3);m.values['start']=int(cycle>=5)
        before_age=m.word('counterage',8)
        epoch=bool(m.arm_age>=ack_delay or m.values.get('measure') or m.values.get('drain'))
        word=224 if near_age is not None and m.values.get('measure') and before_age>=near_age else 0
        m.counts(word,word,word,epoch=epoch)
        m.settle()
        before={'age':before_age,'decision':m.values.get('decision',0),'watchdog':m.values.get('epoch_watchdog',0),'count_run':m.values.get('count_run',0)}
        m.cycle(cycle)
        row={'cycle':cycle,**before,'state':list(m.states[-1]),'age_after':m.word('counterage',8),'done':m.values.get('done',0),'fail':m.values.get('fail',0),'fine_enable':m.values.get('fine_enable',0),'count_rst':m.values.get('count_rst',0)}
        rows.append(row)
        if m.values.get('fail') or m.values.get('fine_enable'):
            state=(m.word('s'),row['done'],row['fail'],row['fine_enable'],m.values.get('hold'),m.values.get('pfd_reset'))
            if terminal_state is None:terminal_state=state
            else:assert state==terminal_state,('Terminal changed',name,row)
            if cycle>(m.fail_cycle or m.fine_cycle)+12:break
    assert terminal_state is not None,('Missing terminal',name)
    if near_age==246:
        assert m.done_cycle is not None and m.fail_cycle is None and m.fine_cycle==m.done_cycle+2
        assert m.word('s')==16 and m.values['hold']==0
        late_drain=[r for r in rows if r['state'][3] and r['age_after']>=248]
        assert late_drain,('Did not exercise DRAIN age248',name)
        assert not any(r['watchdog'] for r in rows if r['state'][3])
    else:
        assert m.fail_cycle is not None and m.done_cycle is None and m.fine_cycle is None
        assert m.values['hold']==1 and m.values['pfd_reset']==1
        fault=[r for r in rows if r['watchdog']]
        assert fault and fault[0]['age']==248,('Global age boundary wrong',name,fault)
        if near_age==248:
            assert fault[0]['decision']==1,('Missing simultaneous NEAR and watchdog',name,fault)
        if ack_delay==29:
            assert any(r['state'][2] for r in rows),('Late ARM must successfully enter MEASURE before global timeout',name)
    return {'name':name,'passed':True,'acknowledgement_delay_REF_cycles':ack_delay,'injected_near_at_age':near_age,'candidate_history':m.history,'done_cycle':m.done_cycle,'fail_cycle':m.fail_cycle,'fine_cycle':m.fine_cycle,'boundary_rows':[r for r in rows if r['age']>=243 or r['done'] or r['fail']]}


def main():
    root=Path(__file__).resolve().parent
    source=load(root/'build_afc2009_mos.py','r2_source');model=load(root/'verify_literal_gate_fsm.py','r2_model')
    circuit=source.build();rows=[]
    rows.append(boundary(circuit,'global_age_includes_late_ARM',ack_delay=29))
    rows.append(boundary(circuit,'NEAR246_DRAIN248_remains_success',near_age=246))
    rows.append(boundary(circuit,'NEAR248_same_edge_watchdog_FAIL_priority',near_age=248))
    m=model.LiteralModel(circuit);m.values.update({'rst':0,'measure':1,'count_run':1,'count_rst':0})
    for value in range(512):
        m.counts(value,value,value,epoch=True);m.settle()
        assert bool(m.values['decision'])==(value>=224),('Unsigned NEAR decode incorrect',value,m.values['decision'])
    # Actual generated storage records must retain every bit through native
    # counters, two-stage CDC and frozen snapshot; avoid a width-only portmap.
    qnames={r['q'] for r in circuit.flop_records}
    for prefix in ('lead_g','lag_g','div_g','lead_sync1_','lead_sync2_','lag_sync1_','lag_sync2_','div_sync1_','div_sync2_','dl','dg','dd'):
        assert all(prefix+str(i) in qnames for i in range(9)),('Missing physical state bit',prefix)
    result={'status':'all_passed','source_sha256':hashlib.sha256((root/'afc2009_mos.scs').read_bytes()).hexdigest(),'source_design_status':'prepared_unverified_offline_candidate_not_selected','fixtures':rows,'unsigned_NEAR_decode_values':512,'all_counter_CDC_snapshot_widths':9,'limits':'Actual generated Boolean gates + ideal edge FF with injected synchronized integer words. Not a MOS, CDC, metastability, timing, edge-credit or PLL capture proof.'}
    (root/'epoch_boundary_fixture_results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='fixtures'},indent=2))
    for row in rows:print(row['name']+' PASS')


if __name__=='__main__':main()
