"""First-edge reset/REF adjacency regressions; no MOS or simulator claim."""
from __future__ import print_function
import copy
import json
from pathlib import Path
import measure_afc2009 as m


def event(initial,changes):
    return {'levels':[[0,initial]]+[[t,v] for t,v in changes],
        'rising':[t for t,v in changes if v],
        'falling':[t for t,v in changes if not v]}


def fixture():
    # Exact motivating fast140 pattern in rounded synthetic numbers.
    return {'counter_reset':event(1,[(291.945e-9,0),(400e-9,1)]),
        'divcal':event(0,[(291.750e-9,1),(295e-9,0),(298.905e-9,1),(302e-9,0)]),
        'phase_select':event(0,[]),
        'reference':event(0,[(x*1e-9,int(x%10==0)) for x in range(10,451,5)])}


def audit(digital=None,release=291.945e-9,epoch=299.372e-9):
    return m.audit_first_div_bracket(digital or fixture(),m.DEFAULT_CONFIG,
        290.962e-9,400e-9,release,epoch)


def main():
    cases=[]
    a=audit()
    assert a['bracket_proof'] is True
    assert a['excluded_reset_masked_div_edges_s']==[291.750e-9]
    assert a['first_div_time_s']==298.905e-9
    assert abs(a['pair_span_s']-5e-9)<1e-21
    cases.append('Reset-masked old first clock excluded; next eligible edge has adjacent 5ns low-phase bracket')
    bad=fixture()
    bad['counter_reset']=event(1,[(291e-9,0),(400e-9,1)])
    a=audit(bad,release=291e-9)
    assert a['bracket_proof'] is False and a['captured_phase_matches_original_REF'] is False
    assert a['preceding_REF_edge']=='rising' and a['following_REF_edge']=='falling'
    assert abs(a['pair_span_s']-5e-9)<1e-21
    cases.append('Wrong captured phase fails instead of manufacturing preceding-fall/following-rise 15ns proof')
    bad=fixture()
    bad['phase_select']=event(0,[(299.4e-9,1)])
    assert audit(bad)['bracket_proof'] is False
    cases.append('Actually captured phase at epoch plus settling is checked; stimulus fixture expectation cannot replace it')
    good=fixture()
    good['phase_select']=event(0,[(291.8e-9,1)])
    good['counter_reset']=event(1,[(291e-9,0),(400e-9,1)])
    a=audit(good,release=291e-9,epoch=292.2e-9)
    assert a['bracket_proof'] is True and a['captured_phase']==1
    cases.append('Valid high-phase adjacent rise/fall bracket accepted')
    bad=fixture()
    # Remove the expected REF falling edge: merged adjacency cannot conceal it.
    bad['reference']=event(0,[(x*1e-9,int(x%10==0)) for x in range(10,451,5) if x!=295])
    a=audit(bad)
    assert a['bracket_proof'] is False and not a['half_REF_period_match']
    cases.append('Missing bounding REF edge violates half-period adjacency rather than spanning longer interval')
    a=audit(epoch=297e-9)
    assert a['bracket_proof'] is False and not a['first_div_before_or_at_epoch_ack']
    cases.append('Epoch acknowledgment preceding actual first eligible clock rejected')
    bad=fixture()
    bad['divcal']=event(0,[(300e-9+.5e-12,1),(302e-9,0)])
    bad['phase_select']=event(0,[(300.2e-9,1)])
    a=audit(bad,epoch=300.4e-9)
    assert a['bracket_proof'] is None and a['tie_aperture_below_1ps']
    cases.append('REF tie aperture stays unknown rather than claiming a phase proof')
    a=audit(release=None)
    assert a['bracket_proof'] is None and 'ARM fallback' in a['unavailable_reason']
    cases.append('Missing physical reset release cannot support an ARM-only first-edge proof')
    bad=fixture()
    bad['counter_reset']=event(1,[(291.945e-9,0),(298e-9,1)])
    a=audit(bad)
    assert a['first_div_time_s'] is None and a['bracket_proof'] is None
    cases.append('Clock after release but while reset reasserted remains ineligible')
    bad=fixture()
    bad['raw_divcal']=event(0,[(292e-9,1),(294e-9,0)])
    assert audit(bad)['first_div_time_s']==298.905e-9
    cases.append('Raw stimulus FB edge cannot substitute for physically gated counter clock')
    bad=fixture()
    bad['divcal']=event(0,[(291.945e-9,1),(295e-9,0),(298.905e-9,1),(302e-9,0)])
    a=audit(bad)
    assert a['first_div_time_s']==298.905e-9 and a['excluded_reset_masked_div_edges_s']==[291.945e-9]
    cases.append('Clock exactly at reset threshold release gets no credited post-reset first edge')
    diagnostic=fixture()
    diagnostic['reference_counter_reset']=event(1,[(300.126e-9,0)])
    diagnostic['ref_lag']=event(0,[(300.151e-9,1),(305e-9,0)])
    a=audit(diagnostic)
    credit=a['reference_counter_credit_diagnostics']
    assert a['bracket_proof'] is True
    assert credit['original_lag_edge_precedes_reference_reset_release'] is True
    assert credit['saved_reference_counter_reset_at_buffered_lag_edge']==0
    assert credit['initial_native_counter_credit_proof'] is None
    cases.append('Original lag before reset but buffered lag after reset remains credit-unproven; phase proof stays separate')
    a=audit()
    assert a['reference_counter_credit_diagnostics']['initial_native_counter_credit_proof'] is None
    assert a['reference_counter_credit_diagnostics']['reference_counter_reset_release_time_s'] is None
    cases.append('Absent native-clock/reset increment evidence cannot become initial counter-credit proof')
    out={'fixtures_passed':len(cases),'checks':cases,'simulator_started':False,
        'scope':'Synthetic parser regressions only. No new MOS simulation, circuit repair, '
            'metastability, setup/hold, PVT, jitter or silicon proof.'}
    Path(__file__).with_name('first_edge_fixture_results.json').write_text(
        json.dumps(out,indent=2)+'\n',encoding='utf8')
    print(json.dumps(out,indent=2))


if __name__=='__main__':
    main()
