"""Bounded mixed-RF reference-noise search; import-safe, headless, one worker.

Run only after review in the VM. Each result is free-running VCO-domain SSB PM
noise with ideal reference/passives, assumed stress geometry and no PEX/load/PLL.
Names area2/4/8 denote linear W/L scaling; actual gate area scales by 4/16/64.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

import run_background_phase3 as helper

VERSION = 'biasopt-v3'
PROJECT = helper.DEFAULT_PROJECT
SEED = 'netlists/rfrefine_d0_c26_v835938_target5.scs'
SCOPE = ('Equal-carrier optimized TT/1.2V/25C mixed RF VCO comparison; '
         'RF core/tails and ordinary reference/fine/bank; code/control may change, '
         'ideal reference DC-calibrated to baseline mean BN, ideal passives and assumed stress geometry; free-running '
         'VCO-domain SSB PM noise only; matched mean BN/available RF tails, not '
         'an isolated causal reference-noise comparison; no PEX/load/full PLL FoM.')
VARIANTS = [{'name': 'area' + str(k), 'WREF_um': k, 'LREF_um': .39*k,
             'IREF_uA': 10, 'WREFP_um': 3, 'gate_area_scale': k*k}
            for k in (2, 4, 8)] + [
            {'name': 'width4', 'WREF_um': 4, 'LREF_um': .39,
             'IREF_uA': 40, 'WREFP_um': 12, 'gate_area_scale': 4}]
NOISE_KEYS=('PN1M_dBc_Hz','PN1M_oscillator_FoM_dB','PN10M_dBc_Hz','PN10M_oscillator_FoM_dB')


def noise_improved(measurement, baseline):
    return all(measurement[k]<baseline[k]-.1 for k in NOISE_KEYS[:2]) and all(
        measurement[k]<=baseline[k]+.05 for k in NOISE_KEYS[2:])


def ordinary_include(source):
    matches=re.findall(r'(?m)^include\s+"([^"]*ms013_io33_v2p6_7p_spe\.lib)"\s+section=tt\s*$',source)
    if len(matches)!=1: raise ValueError('Expected one ordinary TT model include.')
    return matches[0]


def calibration_fixture(source, variant, bn_target):
    if not .1 < bn_target < 1.1: raise ValueError('Unexpected baseline BN target.')
    return ('// Isolated DC reference fixture; force actual baseline PSS mean BN.\n'
        'simulator lang=spectre\nglobal 0\ninclude "{lib}" section=tt\n'
        'fixtureOptions options temp=25 reltol=1e-6 vabstol=1e-8 iabstol=1e-13\n'
        'VDD (vdd 0) vsource dc=1.2\nVBN (bn 0) vsource dc={bn:.15g}\n'
        'MNREF (bn bn 0 0) n12 w={w:.12g}u l={l:.12g}u\n'
        'saveOptions options save=selected\nsave bn vdd MNREF:d VBN:p\n'
        'dcBias dc\ndcOP info what=oppoint where=rawfile\n').format(
            lib=ordinary_include(source),bn=bn_target,w=variant['WREF_um'],l=variant['LREF_um'])


def model_bins(source):
    path=Path(ordinary_include(source)).with_suffix('.mdl')
    text=path.read_text(errors='replace'); result={}
    number=r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?(?:[unp])?'
    def value(s):
        scale={'u':1e-6,'n':1e-9,'p':1e-12}
        return float(s[:-1])*scale[s[-1]] if s[-1] in scale else float(s)
    for name in ('n12','p12'):
        blocks=re.findall(r'(?ims)^\s*model\s+'+name+r'\s+bsim3v3\b(.*?)(?=^\s*model\s+\w+\s+bsim|\Z)',text)
        bins=[]
        for block in blocks:
            starts=list(re.finditer(r'\blmin\s*=\s*'+number,block,re.I))
            for i,start in enumerate(starts):
                chunk=block[start.start():starts[i+1].start() if i+1<len(starts) else len(block)]
                fields={key:re.search(r'\b'+key+r'\s*=\s*('+number+r')',chunk,re.I)
                        for key in ('lmin','lmax','wmin','wmax')}
                if all(fields.values()): bins.append({k:value(v.group(1))*1e6 for k,v in fields.items()})
        if not bins: raise ValueError('Unable to verify ordinary '+name+' W/L model bin bounds.')
        result[name]=bins
    return {'source':str(path),'units':'um','bins':result}


def geometry_ok(bounds, model, width, length):
    return any(b['wmin'] <= width <= b['wmax'] and b['lmin'] <= length <= b['lmax']
               for b in bounds['bins'][model])


def parse_dc(path):
    """Nonswept PSFASCII values can contain a quoted type and PROP suffix."""
    data={}; reading=False
    number=r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?'
    for line in path.read_text(errors='replace').splitlines():
        if line.strip()=='VALUE': reading=True; continue
        if line.strip()=='END': break
        if not reading: continue
        match=re.match(r'^\s*"([^"]+)"\s+(?:"[^"]+"\s+)?('+number+r')(?:\s|$)',line)
        if match:
            value=float(match.group(2))
            if math.isfinite(value): data[match.group(1)]=value
    return data


def validate_dc(data, target):
    current=data.get('MNREF:d'); supply=data.get('VBN:p'); bn=data.get('bn')
    if current is None or not 0 < current <= .001: raise ValueError('DC MNREF current outside0..1mA.')
    if bn is None or abs(bn-target)>1e-5: raise ValueError('Forced DC BN does not match target.')
    tolerance=max(1e-12,abs(current)*1e-4)
    if supply is None or abs(supply+current)>tolerance:
        raise ValueError('Forced-source/drain current KCL fails1e-4 relative plus1pA tolerance.')
    return current, {'MNREF_drain_A':current,'VBN_p_A':supply,'kcl_residual_A':supply+current,
                     'kcl_tolerance_A':tolerance,'measured_bn_V':bn}


def make_base(source, variant):
    if 'n12_ckt_rf' not in source or 'section=mos_tt' not in source:
        raise ValueError('Expected reviewed mixed-RF TT seed.')
    for key, wanted in [('LTAIL', '.39u'), ('LFINE', '5.2u'), ('WBANK', '1.1u')]:
        if float(helper.assignment(source, key).rstrip('u')) != float(wanted[:-1]):
            raise ValueError('Unexpected protected geometry ' + key)
    text = '\n'.join(line for line in source.splitlines()
                     if not re.match(r'^\s*(tran|pss|pnoise|rfBiasDC|rfDCOP)\s', line))+'\n'
    text = re.sub(r'(?m)^// Code .*\n', '', text)
    text = text.replace('// The only ideal current branch is the original 10 uA reference.',
        '// Only ideal current branch: {} uA reference for {}.'.format(variant['IREF_uA'],variant['name']))
    text = text.replace('// Oscillator tails, coarse bands and fine branches are actual n12 MOSFETs.',
        '// RF main/regen/tails; ordinary n12 reference, coarse bank and fine branches.')
    text += ('// Protected RF geometry: wr=3u; main nf=12, regen nf=8; tails nf=12/16, lr=.39u.\n'
             '// Ordinary fine WFINE=.8u/LFINE=5.2u; coarse WBANK=1.1u/LTAIL=.39u.\n'
             '// {}: reference W={}u, L={}u; nominal W/L {}; actual area scale={}.\n').format(
                 variant['name'],variant['WREF_um'],variant['LREF_um'],
                 'conserved; IREF DC calibrated' if variant['name'].startswith('area') else '4x; IREF DC calibrated',
                 variant['gate_area_scale'])
    text += 'parameters LREF={:.12g}u\n'.format(variant['LREF_um'])
    for key, value in [('WREF', '{}u'.format(variant['WREF_um'])),
                       ('IREFVAL', '{}u'.format(variant['IREF_uA'])),
                       ('WREFP', '{}u'.format(variant['WREFP_um']))]:
        text = helper.change_parameter(text, key, value)
    for device in ('MNREF', 'MNPMIRROR'):
        text, count = re.subn(r'(?m)(^\s*'+device+r'\s+[^\n]*\bl=)LTAIL\b',
                              r'\g<1>LREF', text)
        if count != 1:
            raise ValueError('Expected one reference length assignment: '+device)
    for stage in ('XSTAGE0', 'XSTAGE1'):
        text += 'save XOSC.{}.XTAILMAIN.main:d XOSC.{}.XTAILREGEN.main:d\n'.format(stage, stage)
    text += 'save bp XREF.MNREF:d XREF.MNPMIRROR:d XREF.MPREF:d\n'
    return text


def operating_measurement(path, start, stop):
    m = helper.measure_transient(path, start, stop)
    stats = m['waveform_stats']
    m['actual_bn_mean_V'] = stats['bn']['mean']
    m['actual_tail_mean_A'] = {k: v['mean'] for k, v in stats.items()
                             if '.XTAIL' in k and k.endswith('.main:d')}
    m['actual_reference_branch_mean_A']={k:v['mean'] for k,v in stats.items()
                                       if k.startswith('XREF.') and k.endswith(':d')}
    m['actual_bp_mean_V']=stats['bp']['mean']
    return m


def transient_screen(path):
    early = operating_measurement(path, 25e-9, 33e-9)
    late = operating_measurement(path, 40e-9, 48e-9)
    ratio = late['differential_vpp_V']/early['differential_vpp_V']
    stability = {k: abs(late['actual_tail_mean_A'][k]/v-1)
                 for k, v in early['actual_tail_mean_A'].items() if v}
    stability['bn'] = abs(late['actual_bn_mean_V']/early['actual_bn_mean_V']-1)
    late.update({'early': early, 'amplitude_ratio_late_over_early': ratio,
                 'bias_and_tail_relative_drift': stability,
                 'target_relative_error': abs(late['frequency_Hz']/3.2e9-1) if late['frequency_Hz'] else None})
    late['valid_persistent_90deg'] = bool(early['valid_screen'] and late['valid_screen'] and
        min(early['differential_vpp_V'], late['differential_vpp_V'],
            early['q_differential_vpp_V'], late['q_differential_vpp_V']) > .1 and
        .9 < ratio < 1.1 and abs(late['frequency_Hz']/early['frequency_Hz']-1) < .01 and
        stability and all(v < .01 for v in stability.values()) and len(stability) == 5)
    return late


def pss_screen(path):
    m = helper.measure_pss(path)
    _, data = helper.read_psf(path)
    t = data['time']; period = 1/m['actual_carrier_Hz']
    qdiff = [a-b for a,b in zip(data['out90'], data['out270'])]
    diff = [a-b for a,b in zip(data['out0'], data['out180'])]
    a, b = helper.crossings(t, diff), helper.crossings(t, qdiff)
    phase = ((b[0]-a[0])/period*360) % 360 if a and b else None
    m['q_rising_phase_deg'] = phase
    m['q_differential_vpp_V'] = max(qdiff)-min(qdiff)
    m['actual_bn_mean_V'] = helper.time_mean(t, data['bn'])
    m['actual_tail_mean_A'] = {k: helper.time_mean(t,v) for k,v in data.items()
                             if '.XTAIL' in k and k.endswith('.main:d') and len(v)==len(t)}
    m['actual_reference_branch_mean_A']={k:helper.time_mean(t,v) for k,v in data.items()
        if k.startswith('XREF.') and k.endswith(':d') and len(v)==len(t)}
    m['actual_bp_mean_V']=helper.time_mean(t,data['bp'])
    m['valid_target_swing_phase'] = bool(m['target_relative_error'] <= .001 and
        min(m['differential_vpp_V'], m['q_differential_vpp_V']) > .1 and
        phase is not None and helper.phase_distance(phase, 90) <= 10 and
        len(m['actual_tail_mean_A']) == 4 and len(m['actual_reference_branch_mean_A']) == 3)
    return m


class Driver:
    def __init__(self, args):
        self.args = args; self.project = Path(args.project).resolve()
        self.source_path = helper.contained(self.project, self.project/SEED)
        self.source = self.source_path.read_text()
        self.source_hash = hashlib.sha256(self.source.encode()).hexdigest()
        self.root = self.project/'results/biasopt'; self.netlists = self.project/'netlists/biasopt'
        self.logs = self.project/'logs/biasopt'; self.status = self.project/'results/biasopt_status.json'
        for p in (self.root, self.netlists, self.logs):
            helper.contained(self.project,p).mkdir(parents=True, exist_ok=True)
        self.spectre = shutil.which(args.spectre); self.ocean = shutil.which(args.ocean)
        if not self.spectre or not self.ocean: raise ValueError('Spectre and headless OCEAN required.')
        self.results = []; self.started = time.time()
        import fcntl
        self.lock = (self.root/'driver.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.bounds=None; self.bn_target=None; self.baseline_tail_mean={}
        self.baseline_code=None; self.baseline_ctrl=None
        self.baseline_noise=None

    def update(self, stage, **fields):
        payload = {'version': VERSION, 'stage': stage, 'pid': os.getpid(), 'scope': SCOPE,
                   'started_unix': self.started, 'updated_unix': time.time(),
                   'max_workers': 1, 'case_timeout_s': self.args.timeout,
                   'cases_recorded': len(self.results), 'source_sha256': self.source_hash}
        payload.update(fields); helper.atomic_json(self.status,payload)
        print(json.dumps(payload), flush=True)

    def calibrate(self, variant):
        w,l=variant['WREF_um'],variant['LREF_um']
        if not geometry_ok(self.bounds,'n12',w,l): raise ValueError('Reference W/L outside ordinary n12 bins.')
        text=calibration_fixture(self.source,variant,self.bn_target)
        digest=hashlib.sha256((VERSION+self.source_hash+text).encode()).hexdigest()
        ident='dc_cal_{}_{}'.format(variant['name'],digest[:12]); cache=self.root/(ident+'.json')
        if cache.exists() and not self.args.force:
            prior=json.loads(cache.read_text())
            if prior.get('state')=='completed' and prior.get('identity_sha256')==digest and all(
                    Path(p).is_file() for p in prior.get('artifacts',[])):
                calibrated=dict(variant); calibrated.update(prior['calibrated_variant'])
                self.results.append(prior); return calibrated
        attempt=1
        while (self.netlists/('{}_a{:03d}.scs'.format(ident,attempt))).exists(): attempt+=1
        tag='{}_a{:03d}'.format(ident,attempt); netlist=self.netlists/(tag+'.scs')
        raw=self.root/(tag+'.raw'); log=self.logs/(tag+'.log'); netlist.write_text(text)
        rec={'state':'running','case_id':ident,'identity_sha256':digest,'attempt':attempt,
             'nominal_variant':variant,'dc_target_bn_V':self.bn_target,'mos_bounds':self.bounds,
             'netlist_path':str(netlist),'raw_path':str(raw),'log_path':str(log),'scope':SCOPE}
        helper.atomic_json(cache,rec); self.update('dc_reference_calibration',current_case=tag)
        try:
            rc=helper.run_process([self.spectre,str(netlist),'-format','psfascii','-raw',str(raw),'+log',str(log)],
                self.logs/(tag+'.stdout'),self.project,time.monotonic()+self.args.timeout)
            rec['spectre_log_summary']=helper.spectral_log_summary(log)
            if rc or rec['spectre_log_summary']['errors']!=0: raise RuntimeError('DC calibration Spectre failed.')
            data=None; waveform=None
            for p in sorted(raw.iterdir()):
                if p.is_file() and 'dcBias' in p.name:
                    d=parse_dc(p)
                    if 'MNREF:d' in d: data=d; waveform=p; break
            if data is None: raise ValueError('DC raw MNREF:d missing; manual review required.')
            current,dc_check=validate_dc(data,self.bn_target)
            pm_width=3*current/10e-6
            if pm_width>100 or not geometry_ok(self.bounds,'p12',pm_width,.39):
                raise ValueError('Calibrated PMREF width outside p12 model bins/100um limit.')
            actual_bn=data['bn']
            calibrated=dict(variant); calibrated.update(IREF_uA=current*1e6,WREFP_um=pm_width,
                nominal_IREF_uA=variant['IREF_uA'],nominal_WREFP_um=variant['WREFP_um'],
                dc_calibration={'target_bn_V':self.bn_target,'measured_bn_V':actual_bn,'actual_MNREF_drain_A':current,
                    'fixture_path':str(netlist),'waveform_path':str(waveform),'mos_bounds':self.bounds,'dc_check':dc_check})
            rec.update(state='completed',calibrated_variant=calibrated,
                artifacts=[str(netlist),str(log),str(waveform)])
        except Exception as error:
            rec.update(state='failed',failure=repr(error)); calibrated=None
        finally:
            rec['finished_unix']=time.time(); helper.atomic_json(cache,rec)
            helper.atomic_json(self.root/(tag+'.manifest.json'),rec)
        self.results.append(rec); helper.atomic_json(self.root/'biasopt_v3_cases.json',self.results)
        return calibrated

    def case(self, variant, code, ctrl, sidebands=0):
        base = make_base(self.source, variant)
        base = helper.change_parameter(base,'VCTRLVAL',ctrl)
        for bit in range(5): base = helper.change_parameter(base,'CODE'+str(bit),(code>>bit)&1)
        base += '// Actual code {} = {:05b}; control={:.12g}V.\n'.format(code,code,ctrl)
        analysis = ('pss (out0 out180) pss fund=3.2G tstab=50n harms={n} errpreset=conservative '
                    'harmonicbalance=no maxstep=0.5p tstabmethod=gear2only method=gear2only\n'
                    'pnoise (out0 out180) pnoise start=10k stop=100M dec=30 sweeptype=relative '
                    'relharmnum=1 maxsideband={n} noiseout=[pm] noisetype=timeaverage\n').format(n=sidebands) if sidebands else (
                    'tran tran stop=50n maxstep=1p errpreset=conservative skipdc=no\n')
        text = base+analysis
        digest = hashlib.sha256((VERSION+self.source_hash+text).encode()).hexdigest()
        ident = '{}_c{}_v{}_sb{}_{}'.format(variant['name'],code,round(ctrl*1e9),sidebands,digest[:12])
        cache = self.root/(ident+'.json')
        if cache.exists() and not self.args.force:
            prior=json.loads(cache.read_text())
            if prior.get('identity_sha256')==digest and prior.get('state')=='completed' and all(
                    Path(p).is_file() for p in prior.get('artifacts',[])):
                prior['resumed']=True; self.results.append(prior); return prior
        attempt=1
        while (self.netlists/('{}_a{:03d}.scs'.format(ident,attempt))).exists(): attempt+=1
        tag='{}_a{:03d}'.format(ident,attempt)
        netlist=self.netlists/(tag+'.scs'); raw=self.root/(tag+'.raw'); log=self.logs/(tag+'.log')
        record={'case_id':ident,'identity_sha256':digest,'attempt':attempt,'state':'running',
                'variant':variant,'code':code,'vctrl_V':ctrl,'sidebands':sidebands,'scope':SCOPE,
                'netlist_path':str(netlist),'raw_path':str(raw),'log_path':str(log),'resumed':False}
        netlist.write_text(text); helper.atomic_json(cache,record); self.update('running',current_case=tag)
        deadline=time.monotonic()+self.args.timeout
        try:
            rc=helper.run_process([self.spectre,str(netlist),'-format','psfascii','-raw',str(raw),
                '+log',str(log)],self.logs/(tag+'.stdout'),self.project,deadline)
            summary=helper.spectral_log_summary(log); record['spectre_log_summary']=summary
            if rc or summary['errors'] != 0: raise RuntimeError('Spectre incomplete/error: '+str(rc))
            waveform=helper.pss_waveform(raw) if sidebands else raw/'tran.tran.tran'
            m=pss_screen(waveform) if sidebands else transient_screen(waveform)
            artifacts=[str(p) for p in (netlist,log,waveform)]
            record['measurement']=m
            if sidebands:
                if not m['valid_target_swing_phase']: raise ValueError('PSS target/swing/quadrature screen failed.')
                m['baseline_bn_target_V']=self.bn_target
                m['bn_error_from_baseline_V']=m['actual_bn_mean_V']-self.bn_target
                m['fair_core_bias_match']=abs(m['bn_error_from_baseline_V'])<=.001
                if not m['fair_core_bias_match']: raise ValueError('PSS BN differs from baseline >1mV; manual review required.')
                compared={k:abs(m['actual_tail_mean_A'][k]/v-1) for k,v in self.baseline_tail_mean.items()
                          if k in m['actual_tail_mean_A'] and v}
                m['baseline_available_RF_tail_mean_A']=self.baseline_tail_mean
                m['baseline_tail_relative_error']=compared
                m['matched_RF_tail_count']=len(compared)
                m['fair_RF_tail_mean_match']=len(compared)>=2 and len(compared)==len(self.baseline_tail_mean) and all(v<=.01 for v in compared.values())
                m['baseline_code']=self.baseline_code; m['baseline_vctrl_V']=self.baseline_ctrl
                m['code_change_from_baseline']=code-self.baseline_code
                m['vctrl_change_from_baseline_V']=ctrl-self.baseline_ctrl
                if not m['fair_RF_tail_mean_match']: raise ValueError('Available baseline RF tail means not matched within1%; manual review required.')
                ocn=self.netlists/(tag+'.ocn'); curve=self.root/(tag+'_pn_ssb.txt'); scalar=self.root/(tag+'_pn_scalars.txt')
                ocn.write_text(helper.ocean_script(raw,curve,scalar))
                rc=helper.run_process([self.ocean,'-nograph','-restore',str(ocn)],
                    self.logs/(tag+'_ocean.stdout'),self.project,deadline)
                if rc or not curve.is_file() or not scalar.is_file(): raise RuntimeError('OCEAN extraction failed.')
                points=dict(line.split() for line in scalar.read_text().splitlines() if len(line.split())==2)
                for key,offset in [('PN1M',1e6),('PN10M',1e7)]:
                    value=float(points[key])
                    if not math.isfinite(value): raise ValueError('Nonfinite PN.')
                    m[key+'_dBc_Hz']=value
                    m[key+'_oscillator_FoM_dB']=value-20*math.log10(m['actual_carrier_Hz']/offset)+10*math.log10(m['pss_supply_power_W']*1000)
                m['noise_delta_vs_baseline_dB']={k:m[k]-self.baseline_noise[k] for k in NOISE_KEYS}
                m['carrier_change_from_baseline_Hz']=m['actual_carrier_Hz']-self.baseline_noise['actual_carrier_Hz']
                artifacts += [str(p) for p in (ocn,curve,scalar)]
            record.update(state='completed',measurement=m,artifacts=artifacts)
        except (Exception,) as error:
            record.update(state='failed',failure=repr(error))
        finally:
            record['finished_unix']=time.time(); helper.atomic_json(cache,record)
            helper.atomic_json(self.root/(tag+'.manifest.json'),record)
        self.results.append(record); helper.atomic_json(self.root/'biasopt_v3_cases.json',self.results)
        return record

    def target(self, variant):
        lower,upper,code=0,31,26
        for unused in range(6):
            pair=[self.case(variant,code,v) for v in (.3,1.0)]
            if not all(r.get('measurement',{}).get('valid_persistent_90deg') for r in pair): return None
            f0,f1=[r['measurement']['frequency_Hz'] for r in pair]
            if f1 <= f0: return None
            if f0 <= 3.2e9 <= f1: break
            if f1 < 3.2e9: lower=code+1
            else: upper=code-1
            if lower>upper: return None
            code=(lower+upper)//2
        else: return None
        low,high=.3,1.0; candidates=list(pair)
        for unused in range(6):
            value=self.case(variant,code,(low+high)/2); candidates.append(value)
            if not value.get('measurement',{}).get('valid_persistent_90deg'): return None
            if value['measurement']['frequency_Hz'] < 3.2e9: low=value['vctrl_V']
            else: high=value['vctrl_V']
        best=min(candidates,key=lambda r:r['measurement']['target_relative_error'])
        if best['measurement']['target_relative_error'] > .001: return None
        return {'variant':variant,'code':code,'band_endpoints':pair,'operatingpoint':best}


def confirm_candidates(driver, promising, baseline):
    """Confirm at most four PN30-ranked candidates, reusing normal PN60 caches."""
    ranked=sorted(promising,key=lambda c:c['noise30']['measurement']['PN1M_oscillator_FoM_dB'])[:4]
    attempts=[]
    progress=driver.root/'biasopt_pn60_confirmations.json'
    helper.atomic_json(progress,{'version':VERSION,'scope':SCOPE,'confirmation_limit':4,
                                'promising_candidates':len(promising),'pn60_attempts':attempts})
    for candidate in ranked:
        outcome={'name':candidate['variant']['name'],'state':'running','passed':False}
        attempts.append(outcome)
        helper.atomic_json(progress,{'version':VERSION,'scope':SCOPE,'confirmation_limit':4,
                                    'promising_candidates':len(promising),'pn60_attempts':attempts})
        n60=driver.case(candidate['variant'],candidate['code'],candidate['operatingpoint']['vctrl_V'],60)
        outcome.update(case_id=n60.get('case_id'),state=n60['state'],resumed=n60.get('resumed',False))
        if n60['state']=='completed':
            deltas={k:n60['measurement'][k]-candidate['noise30']['measurement'][k]
                    for k in ('PN1M_dBc_Hz','PN10M_dBc_Hz')}
            convergence=all(abs(v)<.05 for v in deltas.values())
            improved=noise_improved(n60['measurement'],baseline)
            outcome.update(sideband_doubling_delta_dB=deltas,convergence_passed=convergence,
                           noise_improvement_passed=improved,passed=convergence and improved)
        else:
            outcome['failure']=n60.get('failure','PN60 did not complete.')
        helper.atomic_json(progress,{'version':VERSION,'scope':SCOPE,'confirmation_limit':4,
                                    'promising_candidates':len(promising),'pn60_attempts':attempts})
        if outcome['passed']:
            selected={'name':candidate['variant']['name'],'variant':candidate['variant'],
                      'candidate_selected':True,'netlistpath':candidate['operatingpoint']['netlist_path'],
                      'operatingpoint':candidate['operatingpoint'],
                      'noisemeasurements':{'sb30':candidate['noise30'],'sb60':n60},
                      'sideband_doubling_delta_dB':outcome['sideband_doubling_delta_dB']}
            return selected,attempts
    return None,attempts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',default=PROJECT); parser.add_argument('--spectre',default='spectre')
    parser.add_argument('--ocean',default='ocean'); parser.add_argument('--timeout',type=int,default=300)
    parser.add_argument('--force',action='store_true'); args=parser.parse_args()
    if not 1 <= args.timeout <= 300: parser.error('Timeout must be 1..300 seconds per case.')
    def interrupted(signum,frame): raise KeyboardInterrupt('Signal '+str(signum))
    signal.signal(signal.SIGTERM,interrupted); signal.signal(signal.SIGINT,interrupted)
    driver=None
    try:
        helper.STOP.clear(); driver=Driver(args)
        driver.update('checking_model_bounds')
        helper.atomic_json(driver.project/'results/biasopt_selected.json',
            {'version':VERSION,'verified':False,'candidate_selected':False,'scope':SCOPE,
             'reason':'v3 comparison pending; previous selection is not valid for this search.'})
        driver.bounds=model_bins(driver.source)
        baseline=json.loads((driver.project/'results/rfnoise/rfnoise_completion_summary.json').read_text())
        records=[r for r in baseline['cases'] if r.get('state')=='completed']
        by_n={r['maxsideband']:r for r in records}
        if 30 not in by_n or 60 not in by_n or not baseline.get('sampled_sideband_agreement_within_0p5dB'):
            raise ValueError('Completed/converged existing RF baseline required.')
        for r in records:
            if not all(Path(p).is_file() for p in r['artifacts']): raise ValueError('Baseline artifacts missing.')
        base=by_n[60]['measurement']; driver.baseline_noise=base; assessed=[]
        _,bn_data=helper.read_psf(Path(base['waveform_path']))
        driver.bn_target=helper.time_mean(bn_data['time'],bn_data['bn'])
        driver.baseline_tail_mean={k:helper.time_mean(bn_data['time'],v) for k,v in bn_data.items()
            if '.XTAIL' in k and k.endswith('.main:d') and len(v)==len(bn_data['time'])}
        if len(driver.baseline_tail_mean)<2: raise ValueError('Baseline PSS lacks minimum two RF tail currents.')
        driver.baseline_code=by_n[60]['selected']['code']
        driver.baseline_ctrl=by_n[60]['selected']['best_measured']['vctrl_V']
        driver.update('starting',variants=VARIANTS,baseline_actual_pss_bn_V=driver.bn_target)
        calibrated_count=0
        for variant in VARIANTS:
            calibrated=driver.calibrate(variant)
            if calibrated is None: continue
            calibrated_count+=1
            chosen=driver.target(calibrated)
            if chosen:
                point=chosen['operatingpoint']; noise=driver.case(calibrated,chosen['code'],point['vctrl_V'],30)
                chosen['noise30']=noise; assessed.append(chosen)
            helper.atomic_json(driver.root/'biasopt_candidates.json',assessed)
        if calibrated_count==0 or not any(c['noise30']['state']=='completed' for c in assessed):
            reason='All DC calibrations failed.' if calibrated_count==0 else 'No calibrated candidate completed fair-bias target/noise checks.'
            helper.atomic_json(driver.root/'biasopt_completion_summary.json',
                {'version':VERSION,'scope':SCOPE,'state':'needs_design_review','reason':reason,'candidates':assessed})
            driver.update('needs_design_review',reason=reason,calibrated_candidates=calibrated_count)
            return 2
        promising=[c for c in assessed if c['noise30']['state']=='completed' and noise_improved(c['noise30']['measurement'],base)]
        selected,confirmations=confirm_candidates(driver,promising,base)
        if selected is None:
            selected={'name':'baseline_rf','candidate_selected':False,'netlistpath':str(driver.source_path),
                'operatingpoint':by_n[60]['selected']['best_measured'],'noisemeasurements':{'sb30':by_n[30],'sb60':by_n[60]},
                'selection_reason':('No attempted PN30-ranked candidate passed own PN60 noise/convergence checks; retain measured baseline. '
                    'Any unattempted candidates remain unconfirmed.' if confirmations else
                    'No completed PN30 candidate met preselection noise/FoM checks; retain measured baseline.')}
        selected.update(scope=SCOPE,source_sha256=driver.source_hash,
            version=VERSION,baseline_actual_pss_bn_V=driver.bn_target,
            baseline_available_RF_tail_mean_A=driver.baseline_tail_mean,
            pn60_attempts=confirmations,pn60_candidates_available=len(promising),pn60_confirmation_limit=4,
            comparison_type='equal-carrier optimized VCO; code/control may differ; not isolated reference-noise attribution',
            selection_rule='DC-calibrated reference; PSS BN within1mV and available baseline RF mean tails within1%; PN/FoM1M each improve >0.1dB; PN/FoM10M no worse by >0.05dB; own 30/60 PN agreement <0.05dB at1M/10M; confirm at most4 in ascending PN30 FoM1M rank and select first passing; persistent90deg, both diff>100mV, PSS carrier within0.1%; four actual RF tails and both reference branches recorded.',
            remaining='Physical-reference/noise startup, PVT/all32 coverage, real passives, PEX, buffer/divider/full PLL.')
        selected['netlist_path']=selected['netlistpath']
        point=selected['operatingpoint']
        selected['code']=point.get('code',26)
        selected['vctrl_V']=point['vctrl_V']
        selected['verified']=True
        helper.atomic_json(driver.project/'results/biasopt_selected.json',selected)
        helper.atomic_json(driver.root/'biasopt_completion_summary.json',
            {'scope':SCOPE,'candidates':assessed,'selected':selected,'pn60_attempts':confirmations})
        driver.update('complete',selected_name=selected['name'],candidate_selected=selected['candidate_selected'])
        return 0
    except KeyboardInterrupt:
        if driver: driver.update('interrupted',completed_records_retained=True)
        return 130
    except Exception as error:
        if driver: driver.update('failed',error=repr(error))
        else: print(json.dumps({'stage':'failed','error':repr(error)}),flush=True)
        return 1
    finally:
        helper.STOP.set()
        with helper.ACTIVE_LOCK: processes=list(helper.ACTIVE.values())
        for process in processes: helper.stop_process_group(process)
        if driver: driver.lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
