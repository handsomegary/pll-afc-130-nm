"""Wait for verified bias selection, then run only its four RF startup checks.

Import-safe; headless; one Spectre worker. Baseline selection reuses the four
completed baseline RF startup records. No physical/noise startup guarantee.
Requires unchanged sibling run_background_phase3/startup_late helper modules.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import shutil
import time

import run_background_phase3 as helper
import run_background_startup_late as startup

VERSION = 'selected-startup-v1'


def scope(reference):
    return ('Selected TT/1.2V/25C mixed-RF VCO; actual selected reference '
            'IREFVAL={} and geometry {}; ideal reference/passives and assumed '
            'stress geometry. Four deterministic 5ns matched-ramp/no-IC/250ns '
            'tests, including explicit kicks; not unforced physical/noise '
            'startup, PVT, loaded or full-PLL signoff.').format(
                reference['IREFVAL'], json.dumps(reference['geometry'], sort_keys=True))


def reference_parameters(source):
    geometry = {key: helper.assignment(source, key) for key in ['WREF', 'WREFP', 'LTAIL']}
    geometry['LREF'] = helper.assignment(source, 'LREF') if 'parameters LREF=' in source else geometry['LTAIL']
    return {'IREFVAL': helper.assignment(source, 'IREFVAL'), 'geometry': geometry}


def selected_reference(project, selection):
    record = selection['noisemeasurements']['sb60']
    if record.get('state') != 'completed' or record.get('sidebands') != 60:
        raise ValueError('Selected candidate requires completed sb60 bias/noise record.')
    if not record.get('measurement', {}).get('valid_target_swing_phase'):
        raise ValueError('Selected sb60 target/swing/quadrature was not verified.')
    path = helper.contained(project, Path(record['measurement']['waveform_path']))
    header, data = helper.read_psf(path)
    t = data.get('time', [])
    needed = ['bn', 'bp'] + startup.tail_names('rf')
    if len(t) < 2 or any(len(data.get(name, [])) != len(t) for name in needed):
        raise ValueError('Selected PSS must contain BN/BP and four actual RF tail currents.')
    carrier = header.get('fundamental')
    if not carrier or abs(carrier / 3.2e9 - 1) > .001:
        raise ValueError('Selected actual PSS carrier outside target screening tolerance.')
    return {'available': True, 'kind': 'Selected calibrated candidate sb60 PSS bias.',
            'waveform_path': str(path), 'waveform_sha256': startup.file_hash(path),
            'actual_carrier_Hz': carrier,
            'means': {name: helper.time_mean(t, data[name]) for name in needed}}


def baseline_records(project, source_hash):
    path = project / 'results/startup_late/startup_late_completion_summary.json'
    records = json.loads(path.read_text())['records']
    by_mode = {r['specification']['mode']: r for r in records if
               r.get('specification', {}).get('model') == 'rf' and r.get('state') == 'completed'}
    if set(by_mode) != {mode for mode, _, _ in startup.MODES}:
        raise ValueError('All four completed baseline RF startup records are required; no automatic repeats.')
    for record in by_mode.values():
        artifacts = record.get('required_artifacts', [])
        if record.get('source_sha256') != source_hash or len(artifacts) < 3 or not all(
                helper.contained(project, Path(p)).is_file() for p in artifacts):
            raise ValueError('Baseline startup source/artifacts do not match selected baseline.')
    return [dict(by_mode[mode], reused_prior_baseline=True) for mode, _, _ in startup.MODES], path


class Driver:
    def __init__(self, args):
        self.args = args; self.project = Path(args.project).resolve()
        self.root = helper.contained(self.project, self.project / 'results/selectedstartup')
        self.netlists = helper.contained(self.project, self.project / 'netlists/selectedstartup')
        self.logs = helper.contained(self.project, self.project / 'logs/selectedstartup')
        for directory in (self.root, self.netlists, self.logs): directory.mkdir(parents=True, exist_ok=True)
        import fcntl
        self.lock = (self.root / 'driver.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.status = self.project / 'results/selectedstartup_status.json'
        self.started = time.time(); self.results = []
        self.helper_digest = {name: startup.file_hash(Path(module.__file__))
                              for name, module in [('phase3', helper), ('startup_late', startup)]}

    def update(self, stage, **fields):
        helper.atomic_json(self.status, {'version': VERSION, 'pid': os.getpid(), 'stage': stage,
            'started_unix': self.started, 'updated_unix': time.time(), 'max_spectre_workers': 1,
            'case_timeout_s': self.args.timeout, 'cases_recorded': len(self.results), **fields})
        if stage != 'waiting_bias_selection':
            print(json.dumps({'stage': stage, 'cases_recorded': len(self.results), **fields}), flush=True)

    def wait_selection(self):
        deadline = time.monotonic() + self.args.wait_seconds
        status = self.project / 'results/biasopt_status.json'
        selected = self.project / 'results/biasopt_selected.json'
        while True:
            dependency = json.loads(status.read_text()) if status.exists() else {}
            if dependency.get('stage') == 'complete':
                choice = json.loads(selected.read_text())
                if choice.get('verified') is not True or choice.get('version') != dependency.get('version'):
                    raise ValueError('Completed bias run lacks matching verified selection.')
                if dependency.get('source_sha256') != choice.get('source_sha256'):
                    raise ValueError('Bias status/selection source identities disagree.')
                return choice
            if dependency.get('stage') in ['failed', 'interrupted', 'needs_design_review', 'stopped']:
                raise RuntimeError('Bias selection needs attention: ' + str(dependency.get('stage')))
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError('Verified bias selection not available within bounded wait.')
            self.update('waiting_bias_selection', dependency_stage=dependency.get('stage'),
                        remaining_wait_s=remaining)
            time.sleep(min(30, remaining))

    def case(self, source, source_path, reference, ref_params, mode, delay, current):
        text, spec = startup.render(source, 'rf', delay, current)
        spec.update(mode=mode, actual_reference=ref_params)
        diagnostic_scope = scope(ref_params)
        identity = {'version': VERSION, 'source_sha256': startup.file_hash(source_path),
                    'netlist': text, 'reference': reference, 'specification': spec,
                    'helper_digests': self.helper_digest}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        case_id = 'selectedstartup_{}_{}'.format(mode, digest[:12]); cache = self.root / (case_id + '.json')
        if cache.exists() and not self.args.force:
            prior = json.loads(cache.read_text()); artifacts = prior.get('required_artifacts', [])
            if prior.get('identity_sha256') == digest and prior.get('state') == 'completed' and len(artifacts) >= 3 and all(
                    helper.contained(self.project, Path(p)).is_file() for p in artifacts):
                return dict(prior, resumed=True)
        attempt = 1
        while (self.netlists / ('{}_a{:03d}.scs'.format(case_id, attempt))).exists(): attempt += 1
        tag = '{}_a{:03d}'.format(case_id, attempt)
        netlist, raw = self.netlists / (tag + '.scs'), self.root / (tag + '.raw')
        log = self.logs / (tag + '.log'); manifest = self.root / (tag + '.manifest.json')
        netlist.write_text(text)
        record = {'case_id': case_id, 'identity_sha256': digest, 'source_path': str(source_path),
                  'source_sha256': identity['source_sha256'], 'attempt': attempt, 'state': 'running',
                  'specification': spec, 'scope': diagnostic_scope, 'reference': reference,
                  'netlist_path': str(netlist), 'raw_path': str(raw), 'log_path': str(log), 'resumed': False}
        helper.atomic_json(manifest, record); self.update('running', current_case=case_id)
        started = time.monotonic()
        try:
            rc = helper.run_process([self.spectre, str(netlist), '-format', 'psfascii', '-raw', str(raw), '+log', str(log)],
                                    self.logs / (tag + '.stdout'), self.project, started + self.args.timeout)
            record['spectre_rc'] = rc; record['spectre_log_summary'] = helper.spectral_log_summary(log)
            if rc or record['spectre_log_summary']['errors'] not in (None, 0): raise RuntimeError('Spectre failed.')
            waveform = raw / 'tran.tran.tran'; _, data = helper.read_psf(waveform)
            record['measurement'] = startup.diagnose(data, spec, reference)
            record['measurement']['scope'] = diagnostic_scope  # Remove inherited nominal-10uA wording.
            record.update(state='completed', required_artifacts=[str(netlist), str(log), str(waveform)])
        except Exception as error:
            record.update(state='failed', failure=repr(error))
        except BaseException:
            record.update(state='interrupted'); helper.atomic_json(manifest, record); raise
        record.update(elapsed_s=time.monotonic() - started, finished_unix=time.time())
        helper.atomic_json(manifest, record); helper.atomic_json(cache, record)
        return record

    def run(self):
        selection = self.wait_selection()
        source_path = helper.contained(self.project, Path(selection['netlist_path']))
        source = source_path.read_text(); ref_params = reference_parameters(source)
        # Validate actual selected source even when reusing prior baseline checks.
        _, point = startup.render(source, 'rf', None, None)
        if point['code'] != selection['code'] or abs(point['vctrl_V'] - selection['vctrl_V']) > 1e-9:
            raise ValueError('Selected netlist operating point disagrees with selection metadata.')
        self.update('selected', selected_name=selection['name'], actual_reference=ref_params)
        prior_path = None
        if selection.get('candidate_selected') is False:
            self.results, prior_path = baseline_records(self.project, startup.file_hash(source_path))
            action = 'Reused four completed baseline RF records; no new Spectre runs.'
        elif selection.get('candidate_selected') is True:
            reference = selected_reference(self.project, selection)
            self.spectre = shutil.which(self.args.spectre)
            if not self.spectre: raise ValueError('Spectre unavailable; use --spectre executable.')
            for mode, delay, current in startup.MODES:
                self.results.append(self.case(source, source_path, reference, ref_params, mode, delay, current))
                helper.atomic_json(self.root / 'selectedstartup_all_cases.json', self.results)
            action = 'Four selected calibrated-reference RF startup analyses.'
        else: raise ValueError('Selection must explicitly specify candidate_selected true/false.')
        failures = [r['case_id'] for r in self.results if r['state'] != 'completed']
        summary = {'version': VERSION, 'scope': scope(ref_params), 'selection': selection,
                   'action': action, 'prior_summary_path': str(prior_path) if prior_path else None,
                   'records': self.results, 'process_or_parse_failed_case_ids': failures,
                   'final_screen_passed': sum(r.get('measurement', {}).get('final_valid_screen', False) for r in self.results),
                   'final_screen_invalid_case_ids': [r['case_id'] for r in self.results if
                       r['state'] == 'completed' and not r['measurement']['final_valid_screen']],
                   'conclusion': 'Analysis completion and deterministic kick response only; unforced/noise startup remains unverified.'}
        helper.atomic_json(self.root / 'selectedstartup_completion_summary.json', summary)
        self.update('complete_with_process_failures' if failures else 'complete_analyses',
                    final_screen_passed=summary['final_screen_passed'], action=action,
                    process_or_parse_failed_case_ids=failures)
        return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=helper.DEFAULT_PROJECT); parser.add_argument('--spectre', default='spectre')
    parser.add_argument('--timeout', type=float, default=300); parser.add_argument('--wait-seconds', type=float, default=3600)
    parser.add_argument('--force', action='store_true'); args = parser.parse_args()
    if not 0 < args.timeout <= 300 or not 0 < args.wait_seconds <= 3600: parser.error('Timeout <=300s and wait <=3600s must be positive.')
    def interrupted(signum, frame): raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, interrupted); signal.signal(signal.SIGTERM, interrupted)
    helper.STOP.clear(); driver = None
    try:
        driver = Driver(args); return driver.run()
    except BaseException as error:
        if driver: driver.update('interrupted' if isinstance(error, KeyboardInterrupt) else 'failed', error=repr(error))
        else: print(json.dumps({'stage': 'setup_failed', 'error': repr(error)}), flush=True)
        return 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        helper.STOP.set()
        with helper.ACTIVE_LOCK: processes = list(helper.ACTIVE.values())
        for process in processes: helper.stop_process_group(process)
        if driver: driver.lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
