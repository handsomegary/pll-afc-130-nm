"""Headless RF-noise checks after the bounded RF search has completed."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import time

import run_background_phase3 as helper

project = Path('@PROJECT_ROOT@')
os.chdir(str(project))
status = project/'results/rfnoise_status.json'
root = project/'results/rfnoise'
root.mkdir(exist_ok=True)
started = time.time()
scope = ('Mixed RF core/tails with ordinary reference/fine/bank, assumed stress '
         'geometry and ideal passives; free-running VCO domain only; no PEX, '
         'buffer/divider load, locked-PLL jitter or complete PLL FoM.')


def update(stage, **fields):
    payload = {'stage': stage, 'pid': os.getpid(), 'started_unix': started,
               'updated_unix': time.time(), 'scope': scope}
    payload.update(fields)
    helper.atomic_json(status, payload)
    print(json.dumps(payload), flush=True)


def interrupted(signum, frame):
    raise KeyboardInterrupt('Signal {}'.format(signum))


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)


try:
    update('waiting_for_rf_selection')
    dependency = project/'results/rfrefine_status.json'
    selection_path = project/'results/rfrefine_selected.json'
    while True:
        dep = json.loads(dependency.read_text()) if dependency.exists() else {}
        if dep.get('stage') == 'complete' and dep.get('selected') and selection_path.exists():
            chosen = json.loads(selection_path.read_text())
            break
        if dep.get('stage') in ['needs_design_review', 'failed', 'stopped']:
            raise RuntimeError('RF selection not available: '+str(dep.get('stage')))
        if time.time()-started > 1800:
            raise RuntimeError('RF selection wait exceeded 30 minutes; no simulation started.')
        time.sleep(10)
    label = chosen['best_measured']['label']
    source = project/'netlists'/('rfrefine_'+label+'.scs')
    base = source.read_text()
    if 'n12_ckt_rf' not in base:
        raise ValueError('Expected mixed-RF selected source.')
    base = '\n'.join(line for line in base.splitlines()
                     if not re.match(r'^\s*(tran|rfBiasDC|rfDCOP)\s', line))+'\n'
    source_hash = hashlib.sha256(base.encode()).hexdigest()
    results = []
    for count in [30, 60]:
        text = base + (
            'pss (out0 out180) pss fund=3.2G tstab=50n harms={n} errpreset=conservative '
            'harmonicbalance=no maxstep=0.5p tstabmethod=gear2only method=gear2only\n'
            'pnoise (out0 out180) pnoise start=10k stop=100M dec=30 sweeptype=relative '
            'relharmnum=1 maxsideband={n} noiseout=[pm] noisetype=timeaverage\n').format(n=count)
        identity = hashlib.sha256(text.encode()).hexdigest()[:12]
        case_id = 'rfnoise_sb{}_{}'.format(count, identity)
        cached = root/(case_id+'.json')
        if cached.exists():
            prior = json.loads(cached.read_text())
            if prior.get('state') == 'completed' and all(Path(p).exists() for p in prior['artifacts']):
                results.append(prior)
                continue
        attempt = 1
        while (project/'netlists'/(case_id+'_a{}.scs'.format(attempt))).exists():
            attempt += 1
        tag = case_id+'_a{}'.format(attempt)
        netlist = project/'netlists'/(tag+'.scs')
        raw = root/(tag+'.raw')
        log = project/'logs'/(tag+'.log')
        netlist.write_text(text)
        update('noise_running', current_case=tag, selected=chosen)
        deadline = time.monotonic()+300
        rc = helper.run_process(['spectre', str(netlist), '-format', 'psfascii', '-raw', str(raw), '+log', str(log)],
                                project/'logs'/(tag+'.stdout'), project, deadline)
        if rc:
            raise RuntimeError('RF Spectre rc {}'.format(rc))
        summary = helper.spectral_log_summary(log)
        if summary['errors'] not in [None, 0]:
            raise RuntimeError('RF Spectre errors')
        waveform = helper.pss_waveform(raw)
        measurement = helper.measure_pss(waveform)
        if measurement['differential_vpp_V'] <= .1 or measurement['target_relative_error'] > .01:
            raise ValueError('RF PSS target/swing screen failed.')
        ocean_file = project/'netlists'/(tag+'.ocn')
        curve, scalar = root/(tag+'_pn_ssb.txt'), root/(tag+'_pn_scalars.txt')
        ocean_file.write_text(helper.ocean_script(raw, curve, scalar))
        rc = helper.run_process(['ocean', '-nograph', '-restore', str(ocean_file)],
                                project/'logs'/(tag+'_ocean.stdout'), project, deadline)
        if rc or not curve.exists() or not scalar.exists():
            raise RuntimeError('RF OCEAN extraction failed.')
        points = dict(line.split() for line in scalar.read_text().splitlines() if len(line.split()) == 2)
        for key, offset in [('PN1M', 1e6), ('PN10M', 1e7)]:
            value = float(points[key])
            if not math.isfinite(value):
                raise ValueError('Nonfinite RF phase noise')
            measurement[key+'_dBc_Hz'] = value
            measurement[key+'_oscillator_FoM_dB'] = value - 20*math.log10(measurement['actual_carrier_Hz']/offset) + 10*math.log10(measurement['pss_supply_power_W']*1000)
        record = {'state': 'completed', 'case_id': case_id, 'harms': count, 'maxsideband': count,
                  'source_sha256': source_hash, 'scope': scope, 'selected': chosen,
                  'measurement': measurement, 'spectre_log_summary': summary,
                  'artifacts': [str(p) for p in [netlist, log, waveform, ocean_file, curve, scalar]],
                  'finished_unix': time.time()}
        helper.atomic_json(cached, record)
        results.append(record)
    deltas = {key: results[1]['measurement'][key]-results[0]['measurement'][key]
              for key in ['PN1M_dBc_Hz', 'PN10M_dBc_Hz']}
    complete = {'scope': scope, 'cases': results, 'sideband_doubling_delta_dB': deltas,
                'sampled_sideband_agreement_within_0p5dB': all(abs(v)<.5 for v in deltas.values()),
                'remaining': 'RF startup/PVT/all32 continuity, PDK R/C implementation, layout/PEX, loaded divider and full PLL.'}
    helper.atomic_json(root/'rfnoise_completion_summary.json', complete)
    update('complete', summary=complete)
except KeyboardInterrupt:
    helper.STOP.set()
    with helper.ACTIVE_LOCK:
        owned = list(helper.ACTIVE.values())
    for process in owned:
        helper.stop_process_group(process)
    update('stopped', completed_results_retained=True)
except Exception as error:
    update('failed', error=repr(error))
    raise
