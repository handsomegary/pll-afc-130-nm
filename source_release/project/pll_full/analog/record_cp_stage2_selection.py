"""Record a scoped CP choice for Stage2, not a final silicon/noise optimum."""
import hashlib
import json
from pathlib import Path
from loop_design import crossover

ROOT=Path(__file__).resolve().parent
WORK=ROOT.parents[1]


def main():
    measured=WORK/'resume_20261007'
    dc=json.loads((measured/'drain_measurement.json').read_text())
    phase=json.loads((measured/'phase_measurements.json').read_text())
    extended_path=measured/'phase_extended_measurements.json'
    extended=json.loads(extended_path.read_text()) if extended_path.is_file() else None
    if not dc['target_point']['compliance_screen_pass'] or phase['incomplete_or_failed']:
        raise ValueError('Require successful target DC and all completed phase tests.')
    p=json.loads((ROOT/'loop_design.json').read_text())
    p['Icp_A']=phase['effective_phase_gain_Icp_A']
    shifted=crossover(p)
    if extended and extended['incomplete_or_failed']:
        raise ValueError('Extended phase result contains incomplete/failed cases.')
    phase_points=sorted((extended or phase)['points'],key=lambda x:x['phase_skew_s'])
    if any(b['net_charge_C']<=a['net_charge_C'] for a,b in zip(phase_points[:-1],phase_points[1:])):
        raise ValueError('Recorded phase-charge curve is not strictly monotonic.')
    bracket=None;interpolated_balance=None
    for a,b in zip(phase_points[:-1],phase_points[1:]):
        qa,qb=a['net_charge_C'],b['net_charge_C']
        if qa<=0<=qb and qb>qa:
            bracket=[a['phase_skew_s'],b['phase_skew_s']]
            interpolated_balance=a['phase_skew_s']-qa*(b['phase_skew_s']-a['phase_skew_s'])/(qb-qa)
            break
    chosen=dict(
        version='cp-stage2-choice-v2',selected_cell='pll130_cp_drain',
        model_file='pll130_cp_drain_candidate.scs',
        model_sha256=hashlib.sha256((ROOT/'pll130_cp_drain_candidate.scs').read_bytes()).hexdigest(),
        selected_scope='Stage2 MOS VCO/PFD/CP + VA divider acquisition test only.',
        final_silicon_or_all_FoM_optimum=False,
        reasons=['Gate-switched baseline and enlarged mux variants fail short-pulse charge matching.',
                 'Drain-switched candidate keeps long mirror gates biased.',
                 'Measured target DC mismatch0.07154% and short-pulse response improved.',
                 'Measured charge-vs-skew is monotonic over the recorded phase range.'],
        target_DC=dc['target_point'],
        near_lock_phase_fit=phase,
        near_lock_fit_domain_s=[-200e-12,200e-12],
        extended_phase_fit=extended,
        extended_fit_domain_s=[phase_points[0]['phase_skew_s'],phase_points[-1]['phase_skew_s']]
            if extended else None,
        slope_policy='Original nine-point +/-200ps local slope remains the LPF gain comparison. '
            'Extended eleven-point -400..+200ps fit is separate; do not silently replace the local slope.',
        original_filter_retained=True,
        original_filter_nominal_Icp_A=20e-6,
        fixed_filter_using_measured_slope=shifted,
        extrapolated_zero_charge_skew_s=-phase['zero_phase_net_charge_C']/phase['effective_phase_gain_Icp_A'],
        measured_zero_charge_crossing=bracket is not None,
        measured_zero_charge_bracket_s=bracket,
        interpolated_zero_charge_skew_s=interpolated_balance,
        remaining=['Closed-loop physical receiver/divider and CP tuning-range verification.',
                   'CP tuning-voltage/PVT/mismatch/noise/spur and layout verification.',
                   'Real divider/receiver loading and physical current reference.'])
    loops_path=measured/'fullpll_measurements.json'
    if loops_path.is_file():
        loops=json.loads(loops_path.read_text())
        actual=[x for x in loops if x.get('stage')=='stage2' and x.get('locked') is True
                and x.get('simulator_state')=='completed']
        if len(actual)==1:
            loop=actual[0]
            offset=loop.get('deterministic_feedback_principal_static_offset_s')
            chosen['completed_staged_loop']=dict(case_name=loop['name'],bench_sha256=loop['bench_sha256'],
                final_frequency_Hz=loop['final_frequency_Hz'],lock_after_enable_s=loop['lock_after_enable_s'],
                final_ctrl_mean_V=loop['final_ctrl_mean_V'],staged_power_W=loop['final_power_W'],
                actual_feedback_minus_reference_static_offset_s=offset,
                actual_minus_CP_charge_interpolated_balance_s=offset-interpolated_balance
                    if offset is not None and interpolated_balance is not None else None,
                scope='MOS VCO/PFD/drain CP but VA divider without physical receiver/divider power; '
                    '4ps/moderate deterministic acquisition, no physical noise jitter.')
    (ROOT/'cp_stage2_selection.json').write_text(json.dumps(chosen,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:chosen[k] for k in ['selected_cell','selected_scope','fixed_filter_using_measured_slope',
                                         'extrapolated_zero_charge_skew_s','measured_zero_charge_crossing']},indent=2))


if __name__=='__main__':main()
