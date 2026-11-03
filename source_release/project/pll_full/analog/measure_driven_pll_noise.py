"""Read-only physical driven-PLL PSS/SSB-PM-noise evidence, Python 3.6+.

No simulation, process control, SSH, GUI or raw modification. A missing/failed
periodic solution, wrong harmonic/database, or incomplete noise band stays
unavailable. Deterministic harmonic31/33 lines never enter the noise integral.
"""
import argparse
import bisect
import cmath
import hashlib
import json
import math
from pathlib import Path
import re
from measure_pll import read_psf,edge_times,edge_frequency,integral_mean


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()


def header(path):
    result={}
    with Path(path).open(errors='replace') as f:
        for line in f:
            if line.strip() in ['TYPE','VALUE']:break
            m=re.match(r'^"([^\"]+)"\s+(.*)$',line.strip())
            if not m:continue
            key,value=m.groups()
            if value.startswith('"'):result[key]=value.strip('"')
            else:
                try:result[key]=float(value)
                except ValueError:pass
    return result


def pss_td_file(path):
    path=Path(path)
    if path.is_file():return path
    candidates=[p for p in path.iterdir() if p.is_file() and 'pss' in p.name and 'pnoise' not in p.name]
    matches=[p for p in candidates if header(p).get('analysis type')=='td.pss']
    if len(matches)!=1:raise ValueError('Expected one exact td.pss waveform, not tstab transient or FD.')
    return matches[0]


def periodic_crossings(t,y,threshold=0):
    return [x for x in edge_times(t,y,threshold) if t[0]<=x<t[-1]-1e-16]


def fourier_coefficient(t,y,n,period):
    z=[value*cmath.exp(-2j*math.pi*n*(time-t[0])/period) for time,value in zip(t,y)]
    return sum((t[i+1]-t[i])*(z[i+1]+z[i])*0.5 for i in range(len(t)-1))/period


def pss_screen(path):
    raw=pss_td_file(path);h=header(raw);d=read_psf(raw);t=d.get('time',[])
    if len(t)<100 or any(t[i+1]<=t[i] for i in range(len(t)-1)):
        raise ValueError('Malformed periodic time grid.')
    fundamental=h.get('fundamental');period=h.get('period')
    if not isinstance(fundamental,(int,float)) or not isinstance(period,(int,float)):
        raise ValueError('Missing actual PSS fundamental/period header.')
    if abs(fundamental/1e8-1)>1e-6 or abs(period*fundamental-1)>1e-6:
        raise ValueError('Expected driven100MHz fundamental and consistent10ns period.')
    if h.get('oscillator node'):
        raise ValueError('Autonomous PSS is not this driven physical PLL analysis.')
    if abs((t[-1]-t[0])/period-1)>1e-4:
        raise ValueError('Periodic waveform does not cover one full fundamental period.')
    for k in ['out0','out180','ctrl','filter_mid','vdd','VDD:p','ref','fb','clk','rst']:
        if len(d.get(k,[]))!=len(t):raise ValueError('Missing physical periodic waveform '+k)
    diff=[a-b for a,b in zip(d['out0'],d['out180'])]
    out_edges=periodic_crossings(t,diff)
    fb_edges=periodic_crossings(t,d['fb'],0.6)
    ref_edges=periodic_crossings(t,d['ref'],0.6)
    clk_edges=periodic_crossings(t,d['clk'],0.6)
    vpp=max(diff)-min(diff)
    power=integral_mean(t,[-v*i for v,i in zip(d['vdd'],d['VDD:p'])])
    coefficients={n:fourier_coefficient(t,diff,n,period) for n in [31,32,33]}
    carrier=abs(coefficients[32]);spurs={}
    for n in [31,33]:
        amplitude=abs(coefficients[n])
        spurs[str(n)]=dict(frequency_Hz=n*fundamental,offset_Hz=(n-32)*fundamental,
                          complex_coefficient_V=[coefficients[n].real,coefficients[n].imag],
                          coefficient_magnitude_V=amplitude,
                          dBc=20*math.log10(amplitude/carrier) if amplitude>0 and carrier>0 else None)
    closure={k:abs(d[k][-1]-d[k][0]) for k in ['out0','out180','ctrl','filter_mid','ref','fb','clk']}
    valid=bool(len(out_edges)==32 and len(clk_edges)==32 and len(fb_edges)==1 and len(ref_edges)==1
               and vpp>=0.05 and carrier>0.005 and power>0
               and min(d['fb'])<=0.2 and max(d['fb'])>=1.0
               and min(d['clk'])<=0.2 and max(d['clk'])>=1.0
               and max(abs(x) for x in d['rst'])<=0.1
               and min(d['ctrl'])>=0.1 and max(d['ctrl'])<=1.1
               and max(closure.values())<=1e-3)
    result=dict(periodic_screen_pass=valid,fundamental_Hz=fundamental,carrier_harmonic=32,
                actual_carrier_Hz=32*fundamental,period_s=period,
                VCO_rising_cycles_per_period=len(out_edges),CMOS_clock_cycles_per_period=len(clk_edges),
                feedback_rising_cycles_per_period=len(fb_edges),reference_rising_cycles_per_period=len(ref_edges),
                VCO_edge_measured_Hz=edge_frequency(out_edges,t[0],t[-1],10),
                differential_vpp_V=vpp,pss_total_VDD_power_W=power,
                ctrl_mean_V=integral_mean(t,d['ctrl']),ctrl_ripple_pp_V=max(d['ctrl'])-min(d['ctrl']),
                filter_mid_mean_V=integral_mean(t,d['filter_mid']),endpoint_closure_abs_V=closure,
                harmonic32_time_integral_coefficient_magnitude_V=carrier,
                deterministic_reference_spurs=spurs,
                deterministic_spur_scope='Differential periodic Fourier harmonics31/33 relative to32, '
                    'at +/-100MHz. Coefficients from nonuniform-time quadrature; '
                    'cross-check OCEAN PSS FD ratios. Not a noise PSD or random jitter.',
                raw_waveform_path=str(raw),raw_waveform_sha256=sha(raw),samples=len(t),
                power_scope='Main VDD source covers physical fine-loop blocks plus ideal bias-source '
                    'consumption; zero-volt monitors are not added again. External reference oscillator '
                    'and real supply/regulator noise/power are excluded.')
    if len(d.get('VREF:p',[]))==len(t):
        result['ideal_reference_drive_net_power_W']=integral_mean(t,[-v*i for v,i in zip(d['ref'],d['VREF:p'])])
    return result


def read_curve(path,allow_negative_frequency=False):
    points=[]
    for line in Path(path).read_text(errors='replace').splitlines():
        tokens=line.split()
        if len(tokens)!=2:continue
        try:f,y=map(float,tokens)
        except ValueError:continue
        if not math.isfinite(f) or not math.isfinite(y) or (f<0 and not allow_negative_frequency):
            raise ValueError('Invalid/nonfinite curve data.')
        points.append((f,y))
    if len(points)<2 or any(points[i+1][0]<=points[i][0] for i in range(len(points)-1)):
        raise ValueError('Malformed or nonmonotonic exported curve.')
    return points


def log_interpolate(points,f):
    xs=[x[0] for x in points]
    i=bisect.bisect_left(xs,f)
    if i<len(points) and abs(xs[i]/f-1)<1e-10:return points[i][1]
    if i==0 or i==len(points):raise ValueError('Cannot extrapolate noise outside measured band.')
    a,b=points[i-1],points[i]
    return a[1]+(b[1]-a[1])*math.log(f/a[0])/math.log(b[0]/a[0])


def integrate_ssb(points,low=1e4,high=1e8,carrier=3.2e9):
    if low<=0 or high<=low or carrier<=0:raise ValueError('Invalid integration band/carrier.')
    selected=[(low,log_interpolate(points,low))]
    selected.extend(p for p in points if low<p[0]<high)
    selected.append((high,log_interpolate(points,high)))
    area=0;trapezoid=0
    for (f0,l0),(f1,l1) in zip(selected[:-1],selected[1:]):
        n0,n1=10**(l0/10.0),10**(l1/10.0)
        exponent=math.log(n1/n0)/math.log(f1/f0)
        r=f1/f0
        if abs(exponent+1)<1e-9:piece=n0*f0*math.log(r)
        else:piece=n0*f0*math.expm1((exponent+1)*math.log(r))/(exponent+1)
        area+=piece
        trapezoid+=(f1-f0)*(n0+n1)*0.5
    phase_rms=math.sqrt(2*area)
    return dict(integration_band_Hz=[low,high],SSB_integrated_power_ratio=area,
                phase_rms_rad=phase_rms,prelayout_PM_equivalent_jitter_rms_s=phase_rms/(2*math.pi*carrier),
                linear_frequency_trapezoid_jitter_rms_s=math.sqrt(2*trapezoid)/(2*math.pi*carrier),
                numerical_integral_method='Exact piecewise power-law PSD; linear dB versus log-frequency.',
                SSB_to_double_sideband_factor=2,small_phase_approximation_screen_pass=phase_rms<0.3,
                interpretation='Band-limited PM-noise-equivalent rms timing deviation at3.2GHz carrier, '
                    'not period/cycle-to-cycle jitter, not a deterministic spur sum or full real-product jitter.')


def noise_screen(pss,curve_path,fd_path,scalar_path,integrated=True,expected_raw_directory=None):
    if pss.get('periodic_screen_pass') is not True:raise ValueError('Failed PSS cannot produce valid PLL jitter.')
    text=Path(curve_path).read_text(errors='replace')
    if 'pnoise_pm' not in text or 'dBc/Hz' not in text:
        raise ValueError('Require explicit OCEAN pnoise_pm SSB dBc/Hz export, not raw V/sqrtHz or total noise.')
    pn=read_curve(curve_path);fd=read_curve(fd_path,allow_negative_frequency=True)
    scalar={}
    scalar_text=Path(scalar_path).read_text()
    if expected_raw_directory is not None:
        origins=[line[len('RAW_RESULTS_DIR '):].strip() for line in scalar_text.splitlines()
                 if line.startswith('RAW_RESULTS_DIR ')]
        if len(origins)!=1 or Path(origins[0]).resolve()!=Path(expected_raw_directory).resolve():
            raise ValueError('OCEAN extraction origin differs from actual executed PSS raw directory.')
    for line in scalar_text.splitlines():
        p=line.split()
        if len(p)!=2:continue
        try:value=float(p[1])
        except ValueError:continue
        if not math.isfinite(value):raise ValueError('Nonfinite OCEAN scalar.')
        scalar[p[0]]=value
    for key in ['PN1M','PN10M','CARRIER32_MAG','LOWER31_MAG','UPPER33_MAG','PSS_VDD_POWER_W']:
        if key not in scalar:raise ValueError('Missing OCEAN evidence '+key)
    # Exact FD grid, not interpolation between harmonics or guessed carrier.
    magnitudes={}
    for n in [31,32,33]:
        f=n*pss['fundamental_Hz']
        found=[y for x,y in fd if abs(x/f-1)<1e-8]
        if len(found)!=1 or found[0]<0:raise ValueError('Missing exact FD harmonic '+str(n))
        magnitudes[n]=found[0]
    if magnitudes[32]<=0.005:raise ValueError('FD carrier magnitude too small.')
    fd_spurs={str(n):20*math.log10(magnitudes[n]/magnitudes[32]) if magnitudes[n]>0 else None for n in [31,33]}
    crosscheck=[]
    for n in [31,33]:
        from_td=pss['deterministic_reference_spurs'][str(n)]['dBc'];from_fd=fd_spurs[str(n)]
        # Fourier spurs below -100dBc can be limited by ASCII precision; retain
        # values but do not turn a quadrature/format floor into circuit failure.
        if from_fd is not None and from_td is not None and max(from_fd,from_td)>-100:
            crosscheck.append(abs(from_td-from_fd)<=1.0)
    power_delta=abs(scalar['PSS_VDD_POWER_W']/pss['pss_total_VDD_power_W']-1)
    if power_delta>0.005 or not all(crosscheck):
        raise ValueError('OCEAN/PSF PSS power or deterministic FD spur cross-check disagrees.')
    values={'PN1M_dBc_Hz':log_interpolate(pn,1e6),'PN10M_dBc_Hz':log_interpolate(pn,1e7)}
    if any(abs(values[k+'_dBc_Hz']-scalar[k])>0.02 for k in ['PN1M','PN10M']):
        raise ValueError('Exported curve and OCEAN point scalars disagree.')
    result=dict(noise_calculation_available=True,periodic=pss,offset_noise=values,
                deterministic_reference_spurs_fd_dBc=fd_spurs,
                OCEAN_to_PSF_power_relative_delta=power_delta,
                noise_sideband_convergence_checked=False,
                jitter_estimate_valid=None,
                curve_sha256=sha(curve_path),FD_curve_sha256=sha(fd_path),OCEAN_scalar_sha256=sha(scalar_path),
                scope='Physical nominal fine-loop PM noise with frozen coarse code; ideal reference/VDD/IREF, '
                    'ideal-geometry passives, no PEX/PVT/mismatch or post-layout signoff.')
    if integrated:
        integral=integrate_ssb(pn,carrier=pss['actual_carrier_Hz'])
        for key in ['SSB_AREA_RATIO','PM_EQUIVALENT_RMS_JITTER_s']:
            if key not in scalar:raise ValueError('Missing integrated OCEAN cross-check '+key)
        relative=abs(scalar['PM_EQUIVALENT_RMS_JITTER_s']/integral['prelayout_PM_equivalent_jitter_rms_s']-1)
        if relative>0.02:raise ValueError('OCEAN/Python noise integration differs by more than2%.')
        integral['OCEAN_rms_jitter_s']=scalar['PM_EQUIVALENT_RMS_JITTER_s']
        integral['OCEAN_vs_piecewise_powerlaw_jitter_relative_delta']=relative
        jitter=integral['prelayout_PM_equivalent_jitter_rms_s']
        jitter_valid=integral['small_phase_approximation_screen_pass']
        result['jitter_estimate_valid']=jitter_valid
        integral['jitter_estimate_valid']=jitter_valid
        if not jitter_valid:
            integral['formal_small_phase_formula_value_s']=jitter
            integral['prelayout_PM_equivalent_jitter_rms_s']=None
            integral['validity_reason']=('Integrated phase deviation >=0.3rad; small-phase '
                'timing conversion not accepted. PSD remains available; no valid jitter/FoM.')
        result['bandlimited_noise']=integral
        # Standard jitter-power FoM, with seconds and milliwatts, explicitly
        # model-scoped. It becomes a comparison only with identical jitter band.
        result['nominal_pre_layout_jitter_power_FoM_dB']=(10*math.log10(jitter*jitter*pss['pss_total_VDD_power_W']*1000)
            if jitter_valid else None)
        result['jitter_FoM_definition']=('10log10((sigma_t in seconds)^2*(P_VDD in mW)); '
            'compare only identical10k-100M PM-noise-equivalent band and power scope.')
    return result


def sideband_comparison(a,b):
    for record in [a,b]:
        if not record.get('noise_calculation_available') or 'bandlimited_noise' not in record:
            raise ValueError('Require two completed full-band noise results.')
        if record.get('jitter_estimate_valid') is not True:
            raise ValueError('Jitter sideband comparison needs applicable small-phase timing conversion.')
    if a.get('source_transient_sha256')!=b.get('source_transient_sha256') or not a.get('source_transient_sha256'):
        raise ValueError('Physical source differs or lacks identity.')
    for key in ['frozen_periodic_base_sha256','own_model_dependencies',
                'locked_external_model_set_sha256','locked_external_model_dependencies']:
        if not a.get(key) or a.get(key)!=b.get(key):
            raise ValueError('Periodic base or authored model identity differs: '+key)
    for key in ['actual_execution_simulator_engine','actual_execution_simulator_threads']:
        if a.get(key) is None or b.get(key) is None or a.get(key)!=b.get(key):
            raise ValueError('Sideband comparison requires complete matching solver engine/threads: '+key)
    if not isinstance(a['actual_execution_simulator_engine'],str) or not a['actual_execution_simulator_engine']:
        raise ValueError('Missing valid actual solver engine identity.')
    if not isinstance(a['actual_execution_simulator_threads'],int) or a['actual_execution_simulator_threads']<1:
        raise ValueError('Missing valid actual solver thread count.')
    if sorted([a.get('maxsideband'),b.get('maxsideband')])!=[128,192]:
        raise ValueError('Require intended128/192 comparison.')
    deltas={key:b['offset_noise'][key]-a['offset_noise'][key] for key in ['PN1M_dBc_Hz','PN10M_dBc_Hz']}
    jr=b['bandlimited_noise']['prelayout_PM_equivalent_jitter_rms_s']/a['bandlimited_noise']['prelayout_PM_equivalent_jitter_rms_s']-1
    return dict(sideband_comparison_completed=True,noise_sidebands=[a['maxsideband'],b['maxsideband']],
                same_engine_required=True,same_engine_verified=True,
                actual_execution_simulator_engine=a['actual_execution_simulator_engine'],
                actual_execution_simulator_threads=a['actual_execution_simulator_threads'],
                point_noise_delta_dB=deltas,integrated_jitter_relative_delta=jr,
                sampled_sideband_agreement=all(abs(x)<=0.5 for x in deltas.values()) and abs(jr)<=0.05,
                agreement_limits=dict(point_noise_dB=0.5,integrated_jitter_fraction=0.05),
                limitation='Only128/192 sideband agreement at1M/10M and integrated10k-100M; '
                    'not proof of all folded frequency convergence or layout/process accuracy.')


def observed_solver_metadata(spectre_log):
    """Observed Spectre18.1 runtime status, never command-line wishes.

    Exact APS Enabled is affirmative engine evidence. An explicit disabled
    multithreading status proves effective single-thread mode. A requested
    +mt2, +aps flag or recommendation to add ++aps proves neither runtime fact.
    Unknown thread count stays None and cannot pass a convergence comparison.
    """
    if spectre_log is None:
        return dict(actual_execution_simulator_engine=None,actual_execution_simulator_threads=None,
                    actual_execution_simulator_thread_mode='unknown',actual_execution_solver_evidence_lines=[])
    path=Path(spectre_log)
    lines=path.read_text(errors='replace').splitlines()
    aps=[line.strip() for line in lines if re.fullmatch(r'\s*APS Enabled\.\s*',line)]
    disabled=[line.strip() for line in lines if re.fullmatch(
        r'\s*Multithreading is disabled due to the size of the design being too small\.\s*',line)]
    enabled=[line.strip() for line in lines if re.fullmatch(r'\s*Multithreading is enabled\.\s*',line)]
    # If an unfamiliar/mixed enabled+disabled log appears, the count is not
    # unambiguous for this analysis. Preserve unknown rather than assuming.
    thread_mode='disabled' if disabled and not enabled else 'enabled_count_unreported' if enabled and not disabled else 'unknown'
    return dict(actual_execution_simulator_engine='aps' if aps else None,
                actual_execution_simulator_threads=1 if thread_mode=='disabled' else None,
                actual_execution_simulator_thread_mode=thread_mode,
                actual_execution_solver_log_path=str(path.resolve()),actual_execution_solver_log_sha256=sha(path),
                actual_execution_solver_evidence_lines=list(dict.fromkeys(aps+disabled+enabled)),
                actual_execution_solver_metadata_scope='Observed exact runtime status in the bound Spectre log. '
                    'Thread count is1 only for explicit disabled multithreading; otherwise unknown. '
                    'Requested command-line engine/thread flags are separate fields.')


def validate_execution(record,manifest,case,executed_bench,raw=None,spectre_log=None):
    """Check actual launch evidence, not copied manifest identity claims."""
    if record.get('state')!='completed' or record.get('spectre_rc')!=0:
        raise ValueError('Need the completed zero-error simulator execution record.')
    if sha(executed_bench)!=case['bench_sha256'] or record.get('bench_sha256')!=case['bench_sha256']:
        raise ValueError('Actual executed bench identity differs from prepared case.')
    actual=record.get('dependencies',{})
    for model in manifest['own_model_dependencies']:
        relative=model['relative_path']
        if actual.get(relative)!=model['sha256']:
            raise ValueError('Actual executed MOS dependency differs/missing: '+relative)
    if record.get('source_files_unchanged_at_completion') is not True:
        raise ValueError('Actual execution lacks completion-time source/model identity verification.')
    for field in ['external_model_set_sha256','external_model_dependencies']:
        if not manifest.get('locked_'+field) or record.get(field)!=manifest['locked_'+field]:
            raise ValueError('External PDK/model graph differs from locked physical source: '+field)
    if raw is not None or spectre_log is not None:
        if raw is None or spectre_log is None:raise ValueError('Bind both raw and log to actual execution.')
        paths={Path(x).resolve() for x in record.get('artifacts',[])}
        raw=Path(raw);raw_dir=raw.parent if raw.is_file() else raw
        if raw_dir.resolve() not in paths or Path(spectre_log).resolve() not in paths:
            raise ValueError('Selected raw directory/log are not this exact actual execution artifacts.')
    result=dict(actual_execution_own_dependency_sha256=record.get('own_dependency_sha256'),
                actual_execution_case_id=record.get('case_id'),actual_execution_dependencies=actual,
                requested_execution_simulator_engine=record.get('simulator_engine'),
                requested_execution_simulator_threads=record.get('simulator_threads'))
    result.update(observed_solver_metadata(spectre_log))
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--kind',choices=['pss','local','band'],default='pss')
    ap.add_argument('--spectre-log',required=True)
    ap.add_argument('--spectre-rc',required=True,type=int)
    ap.add_argument('--ocean-rc',type=int)
    ap.add_argument('--curve');ap.add_argument('--fd-curve');ap.add_argument('--scalars')
    ap.add_argument('--manifest');ap.add_argument('--case-name');ap.add_argument('--bench')
    ap.add_argument('--execution-record-json')
    args=ap.parse_args()
    if args.spectre_rc!=0:raise ValueError('Simulator did not complete successfully.')
    log=Path(args.spectre_log).read_text(errors='replace')
    counts=re.findall(r'(\d+)\s+errors?\s*[,;]\s*(\d+)\s+warnings?',log,re.I)
    if not counts or int(counts[-1][0])!=0:raise ValueError('Require completed zero-error Spectre log.')
    pss=pss_screen(args.raw)
    if args.kind=='pss':result=pss
    else:
        if args.ocean_rc!=0 or not all([args.curve,args.fd_curve,args.scalars]):
            raise ValueError('Require successful OCEAN extraction and all curve/scalar evidence.')
        raw_path=Path(args.raw);raw_dir=raw_path.parent if raw_path.is_file() else raw_path
        result=noise_screen(pss,args.curve,args.fd_curve,args.scalars,integrated=args.kind=='band',
                            expected_raw_directory=raw_dir)
    if args.kind!='pss' or any([args.manifest,args.case_name,args.bench,args.execution_record_json]):
        if not all([args.manifest,args.case_name,args.bench,args.execution_record_json]):
            raise ValueError('Noise identity needs manifest/case-name/actual bench/execution-record-json.')
        manifest=json.loads(Path(args.manifest).read_text())
        cases=[c for c in manifest['cases'] if c['name']==args.case_name and c['kind']==args.kind]
        if len(cases)!=1 or sha(args.bench)!=cases[0]['bench_sha256']:
            raise ValueError('Executed bench identity does not match prepared periodic/noise case.')
        execution=json.loads(Path(args.execution_record_json).read_text())
        if isinstance(execution,list):
            matches=[r for r in execution if r.get('name')==args.case_name]
            if len(matches)!=1:raise ValueError('Select one exact noise execution record.')
            execution=matches[0]
        result.update(validate_execution(execution,manifest,cases[0],args.bench,args.raw,args.spectre_log))
        result.update(source_transient_sha256=manifest['source_transient_sha256'],
                      frozen_periodic_base_sha256=manifest['frozen_periodic_base_sha256'],
                      own_model_dependencies=manifest['own_model_dependencies'],
                      locked_external_model_set_sha256=manifest['locked_external_model_set_sha256'],
                      locked_external_model_dependencies=manifest['locked_external_model_dependencies'],
                      maxsideband=cases[0]['maxsideband'],PSS_saved_harmonics=128,
                      executed_bench_sha256=sha(args.bench),case_name=args.case_name)
    Path(args.out).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(out=args.out,periodic_screen_pass=pss['periodic_screen_pass'],
                          noise_calculation_available=args.kind!='pss'),indent=2))


if __name__=='__main__':main()
