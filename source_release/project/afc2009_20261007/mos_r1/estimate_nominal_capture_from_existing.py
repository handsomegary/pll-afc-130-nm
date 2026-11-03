"""Read-only planning estimate from old measured unloaded/loaded cases.

No simulation. Frequencies at Vctrl=.6 with actual new MOS AFC loading have
NOT been measured. Quadratic interpolation and loading transfer are explicit
engineering estimates and cannot be used to certify capture or PVT coverage.
"""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit_three(values):
    f0,f1,f2=(values[v]['frequency_Hz'] for v in (.3,.65,1.0))
    a=(f2-2*f1+f0)/(2*.35**2);b=(f1-f0)/.35-a*(.65+.3);c=f0-a*.3**2-b*.3
    return {'quadratic_A_Hz_V2':a,'linear_B_Hz_V':b,'constant_C_Hz':c}


def evaluate(fit,ctrl):return fit['quadratic_A_Hz_V2']*ctrl**2+fit['linear_B_Hz_V']*ctrl+fit['constant_C_Hz']


def main():
    root=Path(__file__).resolve().parents[2];old=root/'resume_20261007'
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--rf',default=str(old/'rfvalidation_all_cases.json'));ap.add_argument('--loaded',default=str(old/'loaded_interface_measurements.json'));ap.add_argument('--out',required=True);args=ap.parse_args()
    rf=json.loads(Path(args.rf).read_text(encoding='utf-8'));loaded=json.loads(Path(args.loaded).read_text(encoding='utf-8'))
    tt={}
    for row in rf:
        s=row['specification']
        if s['condition']!='tt_1200_25' or not row['valid_sustained_screen']:continue
        tt.setdefault(s['code'],{})[s['vctrl_V']]={'frequency_Hz':row['measurement']['frequency_Hz'],'case_id':row['case_id'],'source_sha256':row['source_sha256'],'scope':row['scope']}
    fit={code:fit_three(tt[code]) for code in (16,24,26,27)}
    loaded27=next(row for row in loaded['cases'] if row['name']=='tb_loaded_interface_code27_ctrl1000000')
    unloaded27=tt[27][1.0]['frequency_Hz'];observed_loaded=loaded27['actual_vco_frequency_Hz']
    cross_offset=unloaded27-observed_loaded;cross_ratio=observed_loaded/unloaded27
    rows=[]
    for code in (16,24,28,29,30,31):
        if code in fit:prediction=evaluate(fit[code],.6);method='Unloaded quadratic interpolation through measured .3/.65/1.0V at this code.'
        else:
            offset=((tt[code][.3]['frequency_Hz']-tt[27][.3]['frequency_Hz'])+(tt[code][1.0]['frequency_Hz']-tt[27][1.0]['frequency_Hz']))/2
            prediction=evaluate(fit[27],.6)+offset;method='Unloaded code27 quadratic shape transferred by average measured same-voltage endpoint code offset.'
        rows.append({'code':code,'clamp_V':.6,'unloaded_interpolated_not_measured_Hz':prediction,'method':method,
                     'illustrative_loaded_offset_transfer_Hz':prediction-cross_offset,'illustrative_loaded_ratio_transfer_Hz':prediction*cross_ratio,
                     'measured_unloaded_endpoints':{str(ctrl):tt[code][ctrl] for ctrl in (.3,1.0)},
                     'actual_new_AFC_loaded_at_clamp_measured':False})
    highcode=30;near_low=tt[highcode][.3]['frequency_Hz']-cross_offset
    result={'version':'existing-evidence-nominal-capture-planning-v1','simulator_started':False,'actual_new_AFC_capture_proven':False,
            'source_hashes':{args.rf:sha(args.rf),args.loaded:sha(args.loaded)},
            'actual_unloaded_tt_midpoints':{str(code):tt[code][.65] for code in (16,24,26,27)},'unloaded_quadratic_fits':fit,
            'actual_previous_loaded_interface':{'name':loaded27['name'],'frequency_Hz':observed_loaded,'code':27,'ctrl_V':1,'scope':loaded27['scope'],'source_set_sha256':loaded27['source_set_sha256'],'raw_sha256':loaded27['raw_sha256']},
            'cross_bench_loading_example':{'unloaded_code27_ctrl1_Hz':unloaded27,'loaded_code27_ctrl1_Hz':observed_loaded,'offset_Hz':cross_offset,'ratio':cross_ratio,'limits':'Different bench/source wrapper and solver step; this is an illustrative cross-bench loading estimate, not matched same-solver loading isolation. R1 counter/code-driver/PFD/clamp loading is additional and unmeasured.'},
            'rows':rows,
            'expected_tested_candidate_direction':'Nominal planning estimate16 slow->24 slow->28 slow->30 fast or provisional near->29 near, depending finite integer count aperture/guard.',
            'potential_code30_capture_risk':{'illustrative_loaded_at_ctrl_0p3_Hz':near_low,'above_target_by_Hz':near_low-3.2e9,'meaning':'Transferred old loading suggests code30 low-fine endpoint may be above target. This is a risk indication, not evidence that physical R1 code30 cannot capture. Exact loaded fullPLL waveform must decide.'},
            'finite_window_risk':'2-count guarded128-lag deadline can terminate a near candidate before demonstrating fine-control capture margin; near is explicitly provisional. If actual fine loop cannot capture, extend/refine frequency decision or test adjacent band; do not call DONE equivalent to lock.',
            'duration_risk':'Five measured trials including one128-count near window and slow early comparisons may exceed4us total once fine-lock hold is included. A bounded4us no-lock result may need distinction from an electrical inability to capture.',
            'limits':['No new loaded-at.6V measurements, PVT/MC/PEX or frequency-monotonicity proof.','Local Kvco423MHz/V atcode26/.835V must not be extrapolated linearly down to.6V; existing.65midpoints show substantial curvature.','The old R1k CML noise/loading experiment is a different receiver and was not used as physical AC R3k loaded evidence.']}
    out=Path(args.out)
    if out.exists():raise ValueError('Immutable planning output already exists')
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'rows':[{k:r[k] for k in ('code','unloaded_interpolated_not_measured_Hz','illustrative_loaded_offset_transfer_Hz')} for r in rows], 'code30_risk':result['potential_code30_capture_risk']},indent=2))


if __name__=='__main__':main()
