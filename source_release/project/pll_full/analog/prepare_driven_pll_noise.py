"""Prepare driven physical-PLL RF analyses; NEVER launch Spectre/OCEAN.

Requires the same physical fine-loop bench whose completed transient locked.
Python 3.6+, stdlib only. PDK includes remain references, never copied here.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
FUND_HZ=100e6
CARRIER_HARMONIC=32
PSS_HARMS=128
SCOPE=('TT1.2V25C pre-layout physical VCO/AC receiver/CMOS divider/PFD/drain CP '
       'fine loop; coarse code frozen. Ideal stiff VDD/reference clock and ideal '
       'bias current sources exclude their real noise. Ideal-geometry R/C and '
       'no PEX; resistor thermal noise follows the Spectre model/default.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def skill_string(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"')+'"'


def ocean_script(raw,prefix,integrated=False):
    """Read-only OCEAN extraction; no design/analysis/run/plot commands.

    phaseNoise is the same validated local-VCO operation, normalized to 32
    rather than 1. Explicit PM database prevents AM/total-noise substitution.
    Python independently validates PSS/power and recomputes the integral.
    """
    prefix=str(prefix)
    text=('openResults({raw})\n'
          'printf("AVAILABLE_RESULTS %L\\n" results())\n'
          'selectResult(\'pnoise_pm)\n'
          'pn=phaseNoise(32 "pss_fd" ?result "pnoise_pm")\n'
          'unless(pn error("No pnoise_pm phaseNoise; do not substitute total/AM noise\\n"))\n'
          'ocnPrint(?output {curve} ?numberNotation \'scientific ?precision 12 pn)\n'
          'd=v("/out0" ?result "pss_fd")-v("/out180" ?result "pss_fd")\n'
          'unless(d error("No differential PSS FD output\\n"))\n'
          'dm=mag(d)\n'
          'ocnPrint(?output {fd} ?numberNotation \'scientific ?precision 12 dm)\n'
          'a32=value(dm 3.2e9)\n'
          'unless(a32 && a32>0 error("Missing positive harmonic32 carrier\\n"))\n'
          'a31=value(dm 3.1e9)\n'
          'a33=value(dm 3.3e9)\n'
          'f=outfile({scalar})\n'
          'fprintf(f "RAW_RESULTS_DIR %s\\n" {raw})\n'
          'fprintf(f "PN1M %.15g\\n" value(pn 1e6))\n'
          'fprintf(f "PN10M %.15g\\n" value(pn 1e7))\n'
          'fprintf(f "CARRIER32_MAG %.15g\\n" a32)\n'
          'fprintf(f "LOWER31_MAG %.15g\\n" a31)\n'
          'fprintf(f "UPPER33_MAG %.15g\\n" a33)\n'
          'when(a31>0 fprintf(f "LOWER_REFERENCE_SPUR_dBc %.15g\\n" db20(a31/a32)))\n'
          'when(a33>0 fprintf(f "UPPER_REFERENCE_SPUR_dBc %.15g\\n" db20(a33/a32)))\n'
          '; Branch name fallback is explicit; waveform absence remains an error.\n'
          'iv=getData("VDD:p" ?result "pss_td")\n'
          'unless(iv iv=getData("/VDD/PLUS" ?result "pss_td"))\n'
          'unless(iv error("No actual VDD branch current; power unavailable\\n"))\n'
          'pv= -v("/vdd" ?result "pss_td")*iv\n'
          'fprintf(f "PSS_VDD_POWER_W %.15g\\n" average(pv))\n')
    if integrated:
        text+=('; Band-limited PM-equivalent RMS timing jitter. Deterministic '
               '31/33 spurs are separate, not added to this continuous PSD integral.\n'
               'area=integ(10**(pn/10.0) 1e4 1e8)\n'
               'unless(numberp(area) && area>=0 error("SSB integral not a nonnegative scalar\\n"))\n'
               'fprintf(f "SSB_AREA_RATIO %.15g\\n" area)\n'
               'fprintf(f "PM_EQUIVALENT_RMS_JITTER_s %.15g\\n" '
               'sqrt(2.0*area)/(2.0*3.141592653589793*3.2e9))\n')
    text+='close(f)\nexit()\n'
    return text.format(raw=skill_string(raw),curve=skill_string(prefix+'_pn_ssb.txt'),
                       fd=skill_string(prefix+'_pss_fd_magnitude.txt'),
                       scalar=skill_string(prefix+'_noise_scalars.txt'))


def require_physical_source(source):
    active='\n'.join(line.split('//',1)[0] for line in source.splitlines())
    if re.search(r'\bahdl_include\b|\b\w+_va\b|\bveriloga\b',active,re.I):
        raise ValueError('PSS source must contain no Verilog-A includes/instances.')
    required=['two_stage_ring_vco','pll130_receiver_ac','pll130_div32_cmos',
              'pll130_pfd','pll130_cp_drain']
    for master in required:
        pattern=r'(?m)^\s*X\S+\s+\([^\n]*\)\s+'+re.escape(master)+r'(?:\s|$)'
        if len(re.findall(pattern,active))!=1:
            raise ValueError('Require one physical top instance of '+master)
    if 'n12_ckt_rf' not in active:
        raise ValueError('Require exact mixed-RF VCO source, not a functional VCO.')
    if re.search(r'(?m)^\s*\S+\s+\(\s*ctrl\s+[^)]*\)\s+vsource\b',active):
        raise ValueError('Fine-control voltage remains driven by an ideal source.')
    if re.search(r'\bX(?:AFC|CLAMP|HAND)\b',active):
        raise ValueError('Remove AFC/clamp/handoff instances from frozen fine loop.')


def render_base(source,ctrl,filter_mid,snapshot=None):
    require_physical_source(source)
    if any(not math.isfinite(x) or not 0.1<=x<=1.1 for x in [ctrl,filter_mid]):
        raise ValueError('Require finite measured control/filter-mid in 0.1..1.1 V.')
    lines=[];froze=[];old_options=0;old_ic=0;found_ref=0
    for line in source.splitlines():
        stripped=line.strip()
        if re.match(r'^\S+\s+(?:\([^)]*\)\s+)?(?:tran|dc|pss|pnoise|info)\b',stripped):
            continue
        if stripped.startswith('simulatorOptions options '):
            old_options+=1
            lines.append('simulatorOptions options temp=25 reltol=1e-5 '
                         'vabstol=1e-7 iabstol=1e-12')
            continue
        if stripped.startswith('ic '):
            old_ic+=1
            line=re.sub(r'\b(?:ctrl|filter_mid)=\S+','',line)
            if snapshot is not None:
                for name,value in snapshot['node_voltage_V'].items():
                    if not re.fullmatch(r'[a-zA-Z0-9_.]+',name) or not math.isfinite(value):
                        raise ValueError('Invalid saved warm-start voltage node.')
                    line=re.sub(r'(?<![\w.])'+re.escape(name)+r'=\S+','',line)
                line+=' '+' '.join('{}={:.15g}'.format(name,value)
                                   for name,value in sorted(snapshot['node_voltage_V'].items()))
            lines.append(line+' ctrl={:.15g} filter_mid={:.15g}'.format(ctrl,filter_mid))
            continue
        m=re.match(r'^(V\S+)\s+\(\s*(rst|div_rst|enable|div_enable)\s+0\s*\)\s+vsource\b',stripped)
        if m:
            name,node=m.groups();volts=0 if node in ['rst','div_rst'] else 1.2
            lines.append('{} ({} 0) vsource dc={}'.format(name,node,volts))
            froze.append(dict(instance=name,node=node,dc_V=volts))
            continue
        if re.match(r'^VREF\s',stripped):
            found_ref+=1
            period=re.search(r'\bperiod=(\S+)',stripped)
            if not period or abs(spectre_number(period.group(1))/1e-8-1)>1e-9:
                raise ValueError('Require actual periodic100MHz VREF.')
            if snapshot is not None:
                delay=re.search(r'\bdelay=(\S+)',stripped)
                phase=spectre_number(delay.group(1))/1e-8 if delay else 0
                if abs(phase-round(phase))>1e-8:
                    raise ValueError('Reference-boundary snapshot needs an integer-period VREF delay.')
        if stripped.startswith('saveOptions '):
            lines.append('saveOptions options save=selected')
            continue
        lines.append(line)
    if old_options!=1 or old_ic!=1 or found_ref!=1:
        raise ValueError('Require one reviewed tolerance/IC/VREF line, no blind rewrites.')
    for required in ['rst','div_rst','enable']:
        if sum(x['node']==required for x in froze)!=1:
            raise ValueError('Require exactly one recognized frozen startup source for '+required)
    text='\n'.join(lines)+'\n'
    active='\n'.join(line.split('//',1)[0] for line in text.splitlines())
    if re.search(r'\btype\s*=\s*pwl\b',active):
        raise ValueError('A nonperiodic PWL source remains after freezing startup.')
    text+='save vdd VDD:p VREF:p ctrl filter_mid ref fb out0 out180 rst div_rst clk\n'
    return text,froze


def spectre_number(token):
    m=re.fullmatch(r'([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)([a-zA-Z]*)',token)
    scales={'':1,'f':1e-15,'p':1e-12,'n':1e-9,'u':1e-6,'m':1e-3,
            'k':1e3,'K':1e3,'M':1e6,'G':1e9}
    if not m or m.group(2) not in scales:raise ValueError('Unsupported literal '+token)
    return float(m.group(1))*scales[m.group(2)]


def analyses(kind,sidebands=128):
    if sidebands not in [128,192] or kind not in ['pss','local','band']:
        raise ValueError('Only reviewed bounded analysis choices.')
    text=('// Driven PLL: no oscillator node pair, fund=fREF100MHz.\n'
          '// Same PSS accuracy/harms across sideband comparison; maxacfreq default\n'
          '// 4*128*100MHz=51.2GHz exceeds (192+32)*100MHz folded source range.\n'
          'pss pss fund=100M tstab=200n harms=128 errpreset=conservative '
          'harmonicbalance=no maxstep=1p tstabmethod=gear2only method=gear2only\n')
    if kind!='pss':
        sweep='start=1M stop=10M dec=1' if kind=='local' else 'start=10k stop=100M dec=30'
        text+=('pnoise (out0 out180) pnoise '+sweep+
               ' sweeptype=relative relharmnum=32 maxsideband={}'.format(sidebands)+
               ' noiseout=[pm] noisetype=timeaverage\n')
    return text


def locked_record(path,name=None,case_id=None):
    data=json.loads(Path(path).read_text(encoding='utf8'))
    if isinstance(data,list):
        matches=[x for x in data if (name is None or x.get('name')==name)
                 and (case_id is None or x.get('case_id')==case_id)]
        if len(matches)!=1:raise ValueError('Select exactly one completed lock record with --case-name.')
        data=matches[0]
    if data.get('locked') is not True or data.get('simulator_state')!='completed':
        raise ValueError('Require a completed actually locked transient, not timeout/acquisition guess.')
    return data


def prepare(source_path,record,outdir):
    source_path=Path(source_path);outdir=Path(outdir)
    source_hash=digest(source_path)
    if record.get('bench_sha256')!=source_hash:
        raise ValueError('Locked transient bench SHA256 does not match the supplied physical source bytes.')
    if record.get('source_files_unchanged_at_completion') is not True:
        raise ValueError('Need actual completion-time verification that executed source/model files stayed unchanged.')
    if not record.get('external_model_set_sha256') or not record.get('external_model_dependencies'):
        raise ValueError('Need the locked execution external PDK model/include graph fingerprints.')
    ctrl=record['final_ctrl_mean_V'];mid=record.get('final_filter_mid_mean_V')
    if mid is None:raise ValueError('Need actual final_filter_mid_mean_V; remeasure saved filter_mid, never assume.')
    snapshot=record.get('final_reference_period_boundary_snapshot')
    if not snapshot or abs(snapshot.get('reference_period_s',0)/1e-8-1)>1e-9:
        raise ValueError('Need actual final100MHz reference-period boundary node snapshot.')
    for node in ['q1','q2','q3','q4','fb','clk','out0','out90','out180','out270',
                 'XRX.inv_bias','XRX.clkn']:
        if node not in snapshot.get('node_voltage_V',{}):
            raise ValueError('Required warm-start node was not saved/measured: '+node)
    models=[]
    for p in [ROOT/'pll130_cp_drain_candidate.scs',ROOT.parent/'digital/pll130_digital_mos.scs',
              ROOT.parent/'digital/pll130_receiver_ac.scs']:
        if not p.is_file():raise ValueError('Missing authored physical dependency '+str(p))
        if re.search(r'\bahdl_include\b|\bveriloga\b',p.read_text(),re.I):
            raise ValueError('Behavioral dependency forbidden '+str(p))
        relative=p.relative_to(ROOT.parent).as_posix();hashed=digest(p)
        if record.get('dependencies',{}).get(relative)!=hashed:
            raise ValueError('Actual MOS dependency differs from locked execution record: '+relative)
        models.append(dict(path=str(p),relative_path=relative,sha256=hashed))
    base,frozen=render_base(source_path.read_text(encoding='utf8'),ctrl,mid,snapshot=snapshot)
    outdir.mkdir(parents=True,exist_ok=True)
    cases=[]
    for kind,sb,deadline in [('pss',128,600),('local',128,600),('band',128,900),('band',192,900)]:
        name='fullpll_driven_{}_sb{}'.format(kind,sb)
        path=outdir/(name+'.scs')
        path.write_text('// '+SCOPE+'\n'+base+analyses(kind,sb),encoding='utf8')
        cases.append(dict(name=name,path=str(path),bench_sha256=digest(path),kind=kind,
                          maxsideband=sb if kind!='pss' else None,
                          PSS_saved_harmonics=128,PSS_fund_Hz=1e8,carrier_harmonic=32,
                          maxstep_s=1e-12,tstab_s=200e-9,walltime_limit_s=deadline,
                          prerequisite='completed passing physical PLL PSS screen' if kind!='pss' else None,
                          optional=sb==192,scope=SCOPE))
    result=dict(version='driven-physical-pll-noise-v1',ready_to_launch=False,
                ready_meaning='Prepared only; root must explicitly schedule bounded jobs after source/model review.',
                source_transient_path=str(source_path),source_transient_sha256=source_hash,
                frozen_periodic_base_sha256=hashlib.sha256(base.encode('utf8')).hexdigest(),
                source_locked_case=record.get('name'),source_lock_time_s=record.get('lock_time_s'),
                measured_IC=dict(ctrl_V=ctrl,filter_mid_V=mid),frozen_sources=frozen,
                actual_warm_node_snapshot=snapshot,
                locked_own_dependency_sha256=record.get('own_dependency_sha256'),
                locked_external_model_set_sha256=record['external_model_set_sha256'],
                locked_external_model_dependencies=record['external_model_dependencies'],
                own_model_dependencies=models,cases=cases,
                execution_policy=dict(max_workers=1,max_total_walltime_s=1800,
                                      max_attempts_per_case=1,
                                      order=['pss128 screen','local128','band128','optional band192'],
                                      on_timeout_or_failure='Keep diagnostics; mark unavailable/unknown; do not infer jitter.'),
                comparison_scope='Same physical source, same PSS128 solution settings; only noise sidebands128/192.',
                free_VCO_comparison_warning='100MHz PLL sideband indexing differs from3.2GHz autonomous VCO; '
                    '128/192 here are not convergence equivalent to free-VCO60 sidebands.',scope=SCOPE)
    (outdir/'driven_noise_manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',required=True)
    ap.add_argument('--lock-json',required=True)
    ap.add_argument('--case-name')
    ap.add_argument('--case-id')
    ap.add_argument('--out-dir',required=True)
    args=ap.parse_args()
    result=prepare(args.source,locked_record(args.lock_json,args.case_name,args.case_id),args.out_dir)
    print(json.dumps(dict(prepared_cases=[x['name'] for x in result['cases']],
                          simulation_started=False,source_sha256=result['source_transient_sha256']),indent=2))


if __name__=='__main__':main()
