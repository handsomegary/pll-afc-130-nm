"""One loaded PN30 analysis, compared with the completed same-point PN60.

Import safe. No baseline, transient sweep, retuning or receiver selection runs.
Only main() can start one reviewed receiver Driver.run_case(noise=True).
Original receiver status/selection/summary files are never written by this script.
Python 3.6+, with the two reviewed drivers beside this file on the guest.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import time

import run_background_receiver_load as receiver

helper = receiver.helper
VERSION = 'loaded-pn30-check-20261007-v1'
EXPECTED_SOURCE = '7e3a3b99b097c4a2d4a3b8fbe0355f5d1ec01ea7451b4a18cfd284bf21eef342'
EXPECTED_RECEIVER_DRIVER = '108fed3523bdc85fb4c8c7154a2ddb01b602fa672f48aa792826667598c20087'
EXPECTED_HELPER = '240edb11708d2856c1318ad3689e8a4d6c19daca495ec1ae736433ed564a242a'
PN_DELTA_LIMIT_DB = 0.05
SCOPE = ('One same-point unloaded-selection-derived mixed-RF VCO plus receiver PN30/PN60 comparison; '
         'width=6um EACH input MOS, pair total=12um; code27/control1V; TT/1.2V/25C. '
         'Agreement only at 1MHz and 10MHz offsets, not full noise-curve convergence, physical reference '
         'noise, real divider loading, PEX, locked-PLL jitter or all-FoM signoff.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(value):
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float)) and math.isfinite(value)


def normalize_analysis_count(text):
    """Normalize only the reviewed PSS harms/Pnoise maxsideband pair."""
    text, n1 = re.subn(r'(?m)^(pss .*\bharms=)(30|60)(?=\s)', r'\g<1>COUNT', text)
    text, n2 = re.subn(r'(?m)^(pnoise .*\bmaxsideband=)(30|60)(?=\s)', r'\g<1>COUNT', text)
    if n1 != 1 or n2 != 1:
        raise ValueError('Expected exactly one PSS harms and one Pnoise maxsideband setting.')
    return text


class PN30Driver(receiver.Driver):
    def __init__(self, args):
        # No simulation, status mutation or model edit occurs in parent __init__.
        # It acquires the existing receiver driver.lock, preventing concurrent
        # changes to the shared immutable-per-case cache while this check runs.
        super(PN30Driver, self).__init__(args)
        self.status = helper.contained(self.project, self.project / 'results' / 'loaded_pn30_check_status_20261007.json')
        self.check_root = helper.contained(self.project, self.project / 'results' / 'loaded_pn30_check_20261007')
        self.check_root.mkdir(parents=True, exist_ok=True)
        self.protected_paths = [
            self.project / 'results' / 'receiverload_status.json',
            self.project / 'results' / 'receiverload_selected.json',
            self.project / 'results' / 'receiverload_completion_summary.json',
            self.root / 'receiverload_completion_summary.json',
            self.root / 'receiverload_progress.json',
        ]
        self.protected_sha256 = {str(p): digest(p) if p.exists() else None for p in self.protected_paths}

    def update(self, stage, **fields):
        value = {'version': VERSION, 'stage': stage, 'pid': os.getpid(),
                 'started_unix': self.started, 'updated_unix': time.time(),
                 'cases_completed_or_resumed': len(self.records), 'max_workers': 1,
                 'single_noise_case_only': True, 'scope': SCOPE}
        value.update(fields)
        helper.atomic_json(self.status, value)
        print(json.dumps(value), flush=True)

    def protected_unchanged(self):
        current = {str(p): digest(p) if p.exists() else None for p in self.protected_paths}
        return current == self.protected_sha256, current

    def check_record(self, record, sidebands):
        if record.get('state') != 'completed' or record.get('valid') is not True:
            raise ValueError('PN{} record is not explicitly completed and valid.'.format(sidebands))
        if record.get('sidebands') != sidebands or record.get('source_sha256') != self.args.expected_source_sha256:
            raise ValueError('PN{} sideband/source identity mismatch.'.format(sidebands))
        if record.get('input_pair_total_width_um') != 6 or record.get('code') != 27 or record.get('vctrl_V') != 1.0:
            raise ValueError('Required physical point is EACH MOS width6um, code27, control1V.')
        if record.get('spectre_log_summary', {}).get('errors') != 0 or record.get('rc') != 0:
            raise ValueError('PN{} has simulator errors or missing error evidence.'.format(sidebands))
        m = record.get('measurement', {})
        keys = ['PN1M_dBc_Hz', 'PN10M_dBc_Hz', 'actual_carrier_Hz', 'pss_supply_power_W',
                'differential_vpp_V', 'receiver_differential_vpp_V']
        if not all(finite(m.get(k)) for k in keys):
            raise ValueError('PN{} record lacks finite carrier/power/noise/swing evidence.'.format(sidebands))
        if m['actual_carrier_Hz'] <= 0 or m['pss_supply_power_W'] <= 0:
            raise ValueError('Carrier/power must be positive.')
        if min(m['differential_vpp_V'], m['receiver_differential_vpp_V']) <= 0.1:
            raise ValueError('VCO and receiver PSS differential swings must exceed 100mV.')
        if abs(m['actual_carrier_Hz'] / receiver.TARGET - 1) > 0.001:
            raise ValueError('PSS carrier target error exceeds reviewed 0.1% limit.')
        for artifact in record.get('artifacts', []):
            p = helper.contained(self.project, Path(artifact))
            if not p.exists():
                raise ValueError('Existing completed record artifact is missing: ' + str(p))
        return m

    def execute(self):
        if digest(receiver.__file__) != EXPECTED_RECEIVER_DRIVER or digest(helper.__file__) != EXPECTED_HELPER:
            raise ValueError('Reviewed receiver/helper driver SHA256 mismatch; no simulations started.')
        status = receiver.read_json(self.project / 'results' / 'receiverload_status.json') or {}
        if status.get('stage') != 'complete' or status.get('version') != receiver.VERSION:
            raise ValueError('Original receiver26 run must be explicitly complete before this independent check.')
        if status.get('cases_completed_or_resumed') != 26:
            raise ValueError('Expected original completed receiver26 status; refusing changed run state.')
        summary_path = self.project / 'results' / 'receiverload_completion_summary.json'
        summary = receiver.read_json(summary_path) or {}
        if summary.get('version') != receiver.VERSION or summary.get('source_sha256') != self.args.expected_source_sha256:
            raise ValueError('Original receiver completion summary version/source mismatch.')
        selected = summary.get('selected') or {}
        point = selected.get('retune', {}).get('best_measured', {})
        if selected.get('input_pair_total_width_um') != 6 or point.get('code') != 27 or point.get('vctrl_V') != 1.0:
            raise ValueError('Original selected loaded point no longer equals width6_each/code27/control1V.')
        if selected.get('retune', {}).get('verified') is not True or point.get('valid') is not True:
            raise ValueError('Original selected loaded point is not verified.')
        pn60 = summary.get('noise') or {}
        m60 = self.check_record(pn60, 60)
        # select_source validates completed biasopt-v3 status/selection metadata.
        # update() dispatches only to this subclass's independent status file.
        self.select_source()
        if self.source_hash != self.args.expected_source_sha256 or str(self.source_path) != summary.get('source_netlist'):
            raise ValueError('Actual selected source differs from completed PN60 source; no simulations started.')
        if self.selection_kind != 'biasopt_selected':
            raise ValueError('No RF fallback is allowed for this selected-source convergence check.')
        text60 = receiver.render(self.base, self.saves, 6, 27, 1.0, noise=True, sidebands=60)
        text30 = receiver.render(self.base, self.saves, 6, 27, 1.0, noise=True, sidebands=30)
        pn60_netlist = helper.contained(self.project, Path(pn60['netlist_path']))
        if pn60_netlist.read_text() != text60:
            raise ValueError('PN60 netlist is not exact same-source reviewed render; no simulations started.')
        if normalize_analysis_count(text30) != normalize_analysis_count(text60):
            raise ValueError('PN30/PN60 differ beyond the analysis harms/sideband pair.')
        expected60_id = 'rx6_c27_v1000000_pn_' + hashlib.sha256((receiver.VERSION + text60).encode()).hexdigest()[:16]
        expected30_id = 'rx6_c27_v1000000_pn_' + hashlib.sha256((receiver.VERSION + text30).encode()).hexdigest()[:16]
        if pn60.get('case_id') != expected60_id or expected30_id == expected60_id:
            raise ValueError('PN60 identity or unique PN30 cache identity mismatch.')
        unchanged, _ = self.protected_unchanged()
        if not unchanged:
            raise ValueError('Protected receiver documents changed during preflight; no simulations started.')
        self.update('one_pn30_case_preflight_passed', source_netlist=str(self.source_path), source_sha256=self.source_hash,
                    existing_PN60_case_id=expected60_id, new_PN30_case_id=expected30_id,
                    width_each_MOS_um=6, width_pair_um=12, code=27, vctrl_V=1.0,
                    comparison_criterion='abs(PN30-PN60) < 0.05dB at BOTH 1MHz and 10MHz')
        # The only simulation call in this driver. Reviewed parent uses a combined
        # 300s Spectre/OCEAN deadline and resumes only this matching PN30 case.
        pn30 = self.run_case(6, 27, 1.0, noise=True)
        m30 = self.check_record(pn30, 30)
        if pn30.get('case_id') != expected30_id:
            raise ValueError('Returned PN30 case identity differs from preflight.')
        unchanged, after_hashes = self.protected_unchanged()
        if not unchanged:
            raise ValueError('Protected receiver status/selected/summary/progress changed; refusing successful conclusion.')
        deltas = {key: m30[key] - m60[key] for key in ['PN1M_dBc_Hz', 'PN10M_dBc_Hz']}
        passed = all(abs(value) < PN_DELTA_LIMIT_DB for value in deltas.values())
        comparison = {
            'version': VERSION, 'scope': SCOPE, 'state': 'complete',
            'convergence_passed': passed, 'classification': 'sampled_PN30_PN60_agreement_at_two_offsets_only',
            'criterion': {'absolute_PN_delta_dB_strictly_less_than': PN_DELTA_LIMIT_DB,
                          'offsets_Hz': [1e6, 1e7], 'direction': 'PN30_minus_PN60'},
            'same_rendered_physical_design_except_analysis_harms_sideband_count': True,
            'source_netlist': str(self.source_path), 'source_sha256': self.source_hash,
            'actual_each_input_MOS_total_width_um': 6, 'actual_sum_of_pair_width_um': 12,
            'code': 27, 'vctrl_V': 1.0, 'PN30_case': pn30, 'PN60_case': pn60,
            'PN30_minus_PN60_dB': deltas,
            'carrier_delta_Hz': m30['actual_carrier_Hz'] - m60['actual_carrier_Hz'],
            'carrier_delta_fraction': m30['actual_carrier_Hz'] / m60['actual_carrier_Hz'] - 1,
            'power_delta_W': m30['pss_supply_power_W'] - m60['pss_supply_power_W'],
            'power_delta_fraction': m30['pss_supply_power_W'] / m60['pss_supply_power_W'] - 1,
            'same_operating_point': True,
            'protected_receiver_files_unchanged': unchanged,
            'protected_receiver_sha256_before': self.protected_sha256,
            'protected_receiver_sha256_after': after_hashes,
            'PN60_netlist_sha256': digest(pn60_netlist),
            'PN30_netlist_sha256': digest(pn30['netlist_path']),
            'reviewed_receiver_driver_sha256': EXPECTED_RECEIVER_DRIVER,
            'reviewed_helper_sha256': EXPECTED_HELPER,
            'finished_unix': time.time(),
        }
        result_path = self.check_root / 'loaded_pn30_comparison.json'
        helper.atomic_json(result_path, comparison)
        self.update('complete_passed' if passed else 'complete_needs_design_review',
                    summary_path=str(result_path), convergence_passed=passed,
                    PN30_minus_PN60_dB=deltas, protected_receiver_files_unchanged=True)
        return 0 if passed else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=helper.DEFAULT_PROJECT)
    parser.add_argument('--spectre', default='@SPECTRE_ROOT@/bin/spectre')
    parser.add_argument('--ocean', default='@IC_ROOT@/tools/dfII/bin/ocean')
    parser.add_argument('--expected-source-sha256', default=EXPECTED_SOURCE,
                        help='Reviewed selected ORIGINAL file SHA256, not RF prepared-base or bias driver source hash.')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{64}', args.expected_source_sha256):
        parser.error('--expected-source-sha256 must be 64 lowercase hex digits.')
    args.wait_bias_opt = True
    args.wait_seconds = 1
    args.ctrl_min = 0.3
    args.ctrl_max = 1.0
    args.noise = True
    args.sidebands = 30
    driver = None

    def interrupt(signum, frame):
        helper.STOP.set()
        raise KeyboardInterrupt('Signal {}'.format(signum))

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    try:
        driver = PN30Driver(args)
        return driver.execute()
    except KeyboardInterrupt:
        helper.STOP.set()
        with helper.ACTIVE_LOCK:
            processes = list(helper.ACTIVE.values())
        for process in processes:
            helper.stop_process_group(process)
        if driver:
            unchanged, _ = driver.protected_unchanged()
            driver.update('stopped', completed_results_retained=True,
                          protected_receiver_files_unchanged=unchanged)
        return 130
    except Exception as error:
        if driver:
            unchanged, _ = driver.protected_unchanged()
            driver.update('failed', error=repr(error), protected_receiver_files_unchanged=unchanged)
        else:
            print(json.dumps({'version': VERSION, 'stage': 'failed_before_simulation', 'error': repr(error)}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
