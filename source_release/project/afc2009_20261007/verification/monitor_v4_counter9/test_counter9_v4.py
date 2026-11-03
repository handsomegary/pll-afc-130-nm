"""Counter9 reader and source binding fixtures only; never physical R2 PASS."""
from __future__ import print_function
import copy
import json
from pathlib import Path
import tempfile
import sys
import measure_afc2009 as m
import measure_afc2009_unit as u
import test_measure_afc2009_unit as legacy
import postprocess_completed_case_v4 as p

HERE=Path(__file__).resolve().parent


def main():
    cfg=u.config(HERE/'physical_portmap_r2.json')
    cases=[]
    assert all(len(cfg['words'][key])==9 for key in ['sync_lead','sync_lag','sync_div','n_lead','n_lag','n_div'])
    assert cfg['counter_contract']['near_window_lag_counts']==224
    assert cfg['counter_contract']['counter_epoch_watchdog_REF_clocks']==248
    cases.append('R2 map and dynamically derived unit sync words have 9 bits / NEAR224 / global age248')
    with tempfile.TemporaryDirectory(prefix='counter9-reader-',dir=str(HERE)) as directory:
        raw=Path(directory)/'synthetic.tran'
        text=['HEADER','VALUE']
        for index in range(32):
            text.append('"time" '+repr(index*1e-9))
            for key,number in [('n_lead',255 if index<16 else 256),('n_lag',257),('n_div',255)]:
                text.extend('"{}" {}'.format(name,1.2 if number&(1<<bit) else 0)
                    for bit,name in enumerate(cfg['words'][key]))
        text.append('END')
        raw.write_text('\n'.join(text)+'\n',encoding='utf8')
        data,digital,words,evidence=m.read_saved_vectors(raw,cfg)
        assert words['n_lead']==[[0.0,255],[16e-9,256]]
        assert words['n_lag']==[[0.0,257]]
        cases.append('Streaming 9-bit scalar reader preserves exact 255 to 256 boundary rather than truncating MSB')
    def snapshot(lead,lag,div,slow,fast):
        digital={'trial_arm':legacy.event(0,[(150e-9,1),(200e-9,0)]),
            'counter_reset':legacy.event(1,[(151e-9,0),(300e-9,1)]),
            'epoch_ack':legacy.event(0,[(153e-9,1)]),
            'decision_valid':legacy.event(0,[(250e-9,1),(260e-9,0)]),
            'decision_slow':legacy.event(0,[(260.2e-9,slow)]),
            'decision_fast':legacy.event(0,[(260.2e-9,fast)])}
        words={'code':[[0,16]],'n_lead':[[0,0],[260.2e-9,lead]],
            'n_lag':[[0,0],[260.2e-9,lag]],'n_div':[[0,0],[260.2e-9,div]]}
        return m.audit_round_edges(digital,words,cfg)['rounds'][0]
    a=snapshot(258,257,255,1,0)
    assert a['sign_proof'] is True and a['observed_counter_snapshot']['n_lag']==257
    cases.append('Frozen slow snapshot 257 minus 255 equals guard2 across old 8-bit boundary')
    a=snapshot(255,254,257,0,1)
    assert a['sign_proof'] is True and a['observed_counter_snapshot']['n_div']==257
    cases.append('Frozen fast snapshot 257 minus 255 equals guard2 across old 8-bit boundary')
    assert snapshot(255,254,256,0,1)['sign_proof'] is False
    cases.append('256 minus 255 still only guard1 and cannot prove fast direction')
    assert snapshot(258,257,255,1,1)['sign_proof'] is False
    cases.append('Paired contradictory fast/slow frozen facts still rejected without changing common sign mathematics')
    original=m.read_saved_vectors
    try:
        fixture=list(legacy.fake('near100_phase_high'))
        for key,number in [('n_lead',225),('n_lag',224),('n_div',225)]:
            fixture[2][key]=[[0,0],[1450.2e-9,number]]
        m.read_saved_vectors=lambda *args,**kwargs:fixture
        a=u.measure_unit('synthetic-no-real-raw','near100_phase_high',portmap=HERE/'physical_portmap_r2.json')
        assert a['unit_functional_pass'] and a['declared_counter_bits']==9 and a['declared_near_window_lag_counts']==224
        assert a['PLL_locked'] is None and a['afc_success'] is None
        cases.append('Declared NEAR224 lower bound accepts exact 224 lag count in synthetic held snapshot')
        fixture[2]['n_lag']=[[0,0],[1450.2e-9,223]]
        a=u.measure_unit('synthetic-no-real-raw','near100_phase_high',portmap=HERE/'physical_portmap_r2.json')
        assert not a['unit_functional_pass'] and 'Near decision precedes specified lag-count window.' in a['violations']
        cases.append('223 count does not pass a declared NEAR224 window even though it exceeds R1 128')
    finally:
        m.read_saved_vectors=original
    bad=json.loads((HERE/'physical_portmap_r2.json').read_text(encoding='utf8'))
    bad['counter_contract']['counter_bits']=8
    try:
        u.config(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('Counter width mismatch not rejected')
    cases.append('Declared width8 with saved nine frozen bits fails before extraction')
    original_sha=p.sha
    try:
        for revision in ['r0','r1','r2']:
            map_name,source=p.REVISION_MAP[revision]
            execution={'specification':{'revision':revision,'mos_source_sha256':source},
                'own_dependencies':{'/synthetic/'+revision+'/afc2009_mos.scs':{'sha256':source}}}
            p.sha=lambda path:source
            got=mapped=p.select_revision(execution)
            assert got[0]==revision and got[1]==map_name
        cases.append('r0/r1/r2 select distinct explicit maps with exact source SHA binding')
        source=p.REVISION_MAP['r2'][1]
        p.sha=lambda path:source
        bad={'specification':{'revision':'r1'},'own_dependencies':{'/synthetic/afc2009_mos.scs':{'sha256':source}}}
        try:
            p.select_revision(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('R2 execution silently accepted as R1')
        cases.append('R2 source with R1 revision cannot silently use R1 eight-bit map')
        for revision in ['r3','unknown']:
            bad['specification']['revision']=revision
            try:
                p.select_revision(bad)
            except ValueError:
                pass
            else:
                raise AssertionError('Unknown revision accepted')
        cases.append('Unsupported explicit revision is rejected rather than falling back to R0 or R1')
        legacy_cache={'specification':{},'own_dependencies':{'/synthetic/afc2009_mos.scs':{'sha256':source}}}
        got=p.select_revision(legacy_cache)
        assert got[0]=='r2' and got[1]=='physical_portmap_r2.json'
        cases.append('Legacy missing-revision cache resolves only through unique exact source SHA; R2 still maps to R2')
        p.sha=lambda path:'changed-source'
        try:
            p.select_revision(legacy_cache)
        except ValueError:
            pass
        else:
            raise AssertionError('Changed source accepted')
        cases.append('Changed owned AFC source after execution is rejected before raw extraction')
    finally:
        p.sha=original_sha
    original_args=sys.argv
    original_unit=u.measure_unit
    try:
        with tempfile.TemporaryDirectory(prefix='counter9-wrapper-',dir=str(HERE)) as directory:
            directory=Path(directory)
            bench=directory/'synthetic.scs'
            bench.write_text('// Synthetic input-binding fixture; never simulated.\n',encoding='utf8')
            cache=directory/'synthetic_execution.json'
            source=HERE.parent.parent/'mos_r2'/'afc2009_mos.scs'
            source_sha=p.REVISION_MAP['r2'][1]
            execution={'state':'completed','spectre_rc':0,'source_models_unchanged_at_completion':True,
                'bench':str(bench),'bench_sha256':p.sha(bench),'raw':str(directory/'no-PSF'),
                'name':'synthetic_source_binding_fixture',
                'specification':{'revision':'r2','mos_source_sha256':source_sha,'fixture_name':'afc_unit_near100_phase_high'},
                'own_dependencies':{str(source):{'sha256':source_sha}}}
            def reset_cache():
                cache.write_text(json.dumps(execution)+'\n',encoding='utf8')
            def synthetic_no_physical_pass(*args,**kwargs):
                return {'name':'afc_unit_near100_phase_high','unit_functional_pass':False,
                    'synthetic_wrapper_fixture':True,'physical_R2_PASS':None,'violations':['Synthetic fixture has no physical PSF.']}
            reset_cache()
            output=directory/'binding_result.json'
            u.measure_unit=synthetic_no_physical_pass
            sys.argv=['postprocess_completed_case_v4.py','--execution',str(cache),'--output',str(output),'--kind','unit']
            assert p.main()==2
            measured=json.loads(output.read_text(encoding='utf8'))
            assert measured['execution_evidence']['sha256']==p.sha(cache)
            assert measured['monitor_revision_binding']['revision']=='r2'
            assert measured['simulator_electrical_pass'] is False
            cases.append('Wrapper binds actual synthetic cache/bench/source hashes while leaving physical PASS false')
            try:
                p.main()
            except ValueError as error:
                assert 'OutputExists' in str(error)
            else:
                raise AssertionError('Existing output overwritten')
            cases.append('Wrapper refuses to overwrite existing measurement output before extraction')
            output=directory/'mutated-cache-result.json'
            sys.argv=['postprocess_completed_case_v4.py','--execution',str(cache),'--output',str(output),'--kind','unit']
            def mutate_cache(*args,**kwargs):
                cache.write_text(cache.read_text(encoding='utf8')+' ',encoding='utf8')
                return synthetic_no_physical_pass()
            u.measure_unit=mutate_cache
            try:
                p.main()
            except ValueError as error:
                assert 'Execution cache changed' in str(error)
            else:
                raise AssertionError('Mutated input cache accepted')
            assert not output.exists()
            cases.append('Cache mutation during extraction cannot receive a misleading final execution SHA binding')
            reset_cache()
            def mutate_bench(*args,**kwargs):
                bench.write_text('// Mutated synthetic bench; never simulated.\n',encoding='utf8')
                return synthetic_no_physical_pass()
            u.measure_unit=mutate_bench
            try:
                p.main()
            except ValueError as error:
                assert 'Bench changed during raw extraction' in str(error)
            else:
                raise AssertionError('Mutated bench accepted')
            assert not output.exists()
            cases.append('Bench mutation during extraction cannot receive a false bench_matches binding')
    finally:
        sys.argv=original_args
        u.measure_unit=original_unit
    out={'fixtures_passed':len(cases),'checks':cases,'simulator_started':False,
        'R2_status':'prepared_unverified_offline_candidate_not_selected',
        'physical_R2_PASS':None,'scope':'Synthetic parser/counter9/map/source-binding fixtures only. '
            'No physical R2 AFC, engineering PLL lock, noise, CDC, overflow or PVT result.'}
    (HERE/'counter9_fixture_results.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
    print(json.dumps(out,indent=2))


if __name__=='__main__':
    main()
