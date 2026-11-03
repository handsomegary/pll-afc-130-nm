"""Regression checks for the educational PLL workflow comparator.

These tests use completed historical measurement JSON files. They do not start
Spectre, SSH, a GUI, or any circuit simulation.
"""

import copy
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "outputs" / "pll130_workflow.py"
FIXTURES = ROOT / "pll130-afc" / "results"
SPEC = importlib.util.spec_from_file_location("pll130_workflow", MODULE_PATH)
WORKFLOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKFLOW)


def fixture(name):
    with (FIXTURES / name).open(encoding="utf-8") as stream:
        return json.load(stream)


class HistoricalMeasurements(unittest.TestCase):
    def setUp(self):
        self.strong = fixture("afc_on_measurement.json")
        self.weak = fixture("weak_clamp_measurement.json")
        self.off = fixture("afc_off_measurement.json")

    def compare(self, measurement=None, **limits):
        if measurement is None:
            measurement = self.strong
        return WORKFLOW.compare_measurement(measurement, **limits)

    def assert_not_passed(self, result):
        self.assertIn(result["status"], {"FAIL", "INCOMPLETE"})

    def test_actual_strong_case_passes_checked_criteria_only(self):
        result = self.compare()
        self.assertEqual(result["status"], "PASS_CHECKED_CRITERIA")
        self.assertAlmostEqual(result["metrics"]["frequency_error_ppm"],
                               -1.8578922674, places=6)
        self.assertIs(result["all_specifications_verified"], False)
        self.assertTrue(result["unverified"])
        for check in result["checks"]:
            self.assertTrue({"name", "observed", "target", "status", "required"}
                            .issubset(check))

    def test_actual_weak_case_preserves_strict_failure(self):
        self.assertTrue(self.weak["fine_loop"]["locked"])
        self.assertFalse(self.weak["afc_success"])
        self.assertEqual(self.compare(self.weak)["status"], "FAIL")

    def test_actual_afc_off_fails_without_an_invented_clamp_pass(self):
        result = self.compare(self.off)
        self.assertEqual(result["status"], "FAIL")
        self.assertLess(result["metrics"]["frequency_error_ppm"], -200000)
        clamp_checks = [check for check in result["checks"]
                        if "clamp" in check["name"].lower()]
        self.assertFalse(any(check["status"] == "PASS"
                             for check in clamp_checks))

    def test_1p6_microsecond_target_fails_total_acquisition_time(self):
        result = self.compare(max_lock_time_s=1.6e-6)
        self.assertEqual(result["status"], "FAIL")

    def test_unmeasured_requested_jitter_is_incomplete(self):
        result = self.compare(max_noise_jitter_s=1e-12)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertTrue(any(check["required"] and check["status"] == "UNKNOWN"
                            for check in result["checks"]))

    def test_failed_measurement_dominates_unknown_requested_jitter(self):
        self.assertEqual(self.compare(self.weak, max_noise_jitter_s=1e-12)
                         ["status"], "FAIL")

    def test_optional_power_limit_uses_total_without_branch_double_count(self):
        self.assertEqual(self.compare(max_power_w=0.0042)["status"],
                         "PASS_CHECKED_CRITERIA")
        self.assertEqual(self.compare(max_power_w=0.0041)["status"], "FAIL")

    def test_exact_frequency_tolerance_edge_is_accepted(self):
        data = copy.deepcopy(self.strong)
        data["fine_loop"]["final_frequency_Hz"] = 3.2e9 * 1.001
        self.assertEqual(self.compare(data)["status"], "PASS_CHECKED_CRITERIA")

    def test_outside_frequency_tolerance_is_rejected(self):
        data = copy.deepcopy(self.strong)
        data["fine_loop"]["final_frequency_Hz"] = 3.2e9 * 1.001001
        self.assertEqual(self.compare(data)["status"], "FAIL")

    def test_near_target_frequency_cannot_override_unlocked_status(self):
        data = copy.deepcopy(self.strong)
        data["fine_loop"]["locked"] = False
        self.assertEqual(self.compare(data)["status"], "FAIL")

    def test_missing_frequency_never_passes(self):
        data = copy.deepcopy(self.strong)
        del data["fine_loop"]["final_frequency_Hz"]
        self.assert_not_passed(self.compare(data))

    def test_missing_handoff_result_never_passes(self):
        data = copy.deepcopy(self.strong)
        del data["handoff"]["success_handoff"]
        self.assert_not_passed(self.compare(data))

    def test_failed_handoff_cannot_be_overridden_by_aggregate_success(self):
        data = copy.deepcopy(self.strong)
        data["handoff"]["success_handoff"] = False
        self.assertEqual(self.compare(data)["status"], "FAIL")

    def test_missing_lock_indicator_never_passes(self):
        data = copy.deepcopy(self.strong)
        del data["fine_loop"]["locked"]
        self.assert_not_passed(self.compare(data))

    def test_parser_error_is_not_interpreted_as_measurement_success(self):
        data = copy.deepcopy(self.strong)
        data["measurement_error"] = "PSF reader did not reach END"
        with self.assertRaises(ValueError):
            self.compare(data)

    def test_nonfinite_and_boolean_measurements_are_rejected(self):
        for invalid in (math.nan, math.inf, -math.inf, True):
            with self.subTest(invalid=invalid):
                data = copy.deepcopy(self.strong)
                data["fine_loop"]["final_frequency_Hz"] = invalid
                with self.assertRaises(ValueError):
                    self.compare(data)

    def test_invalid_numeric_target_is_rejected(self):
        for invalid in (True, False, math.nan, math.inf, -1, 0):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.compare(target_frequency_hz=invalid)

    def test_invalid_optional_limit_is_rejected(self):
        for option in ("max_power_w", "max_lock_time_s", "max_noise_jitter_s"):
            for invalid in (True, math.nan, math.inf, -1, 0):
                with self.subTest(option=option, invalid=invalid):
                    with self.assertRaises(ValueError):
                        self.compare(**{option: invalid})

    def test_compare_does_not_mutate_original_measurement(self):
        before = copy.deepcopy(self.strong)
        self.compare()
        self.assertEqual(self.strong, before)


class CommandLineSafety(unittest.TestCase):
    def cli(self, *arguments):
        return subprocess.run([sys.executable, "-B", str(MODULE_PATH), *arguments],
                              cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", timeout=15, check=False)

    def test_help_has_no_simulation_side_effects(self):
        process = self.cli("--help")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("compare", process.stdout)

    def test_compare_actual_json_cli(self):
        process = self.cli("compare", str(FIXTURES / "afc_on_measurement.json"),
                           "--format", "json")
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["status"], "PASS_CHECKED_CRITERIA")
        self.assertIs(result["all_specifications_verified"], False)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="pll130-comparator-test-",
                                         dir=str(ROOT / "work")) as temp:
            output = Path(temp) / "comparison.json"
            sentinel = b"keep this pre-existing file\n"
            output.write_bytes(sentinel)
            process = self.cli("compare", str(FIXTURES / "afc_on_measurement.json"),
                               "--output", str(output))
            self.assertEqual(process.returncode, 2, process.stderr)
            self.assertEqual(output.read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
