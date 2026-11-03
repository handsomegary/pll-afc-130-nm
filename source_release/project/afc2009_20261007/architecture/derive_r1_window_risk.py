"""Read-only electrical-source risk math; emits new assessment artifacts only.

No simulator launch and no edits to any existing RTL/MOS/bench/measurement.
Bounds are conditional counting-model envelopes, never a physical MTBF claim.
"""
from fractions import Fraction as F
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "mos_r1" / "afc2009_mos.scs"
MAP = ROOT / "mos_r1" / "port_manifest.json"
GEN = ROOT / "mos_r1" / "build_afc2009_mos.py"
PLAN = ROOT / "evidence" / "r1" / "nominal_capture_planning_estimate.json"
UNIT = ROOT / "evidence" / "r1" / "r1_near100_high_measurement.json"
SOURCES = [SRC, MAP, GEN, PLAN, UNIT]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound(name, N, D, W, assumption):
    # For ideal counts at a common observation time:
    # n_lag=N, n_lead is N or N+1, and t/Tref is in [N-1+v,N+v),
    # v in [0,.5]. If n_div lies between n_lag-D and n_lead+D,
    # floor(r*t/Tref)=n_div-1. Correlated lead/lag phase tightens the
    # upper endpoint to (N+D+1)/(N-.5), not (N+D+1)/(N-1).
    lo = F(N - D - 1) / F(2 * N + 1, 2)
    hi = F(N + D + 1) / F(2 * N - 1, 2)
    return {"name": name, "window": W, "effective_lag_min": N,
            "relative_count_allowance_D": D, "assumption": assumption,
            "ratio_lower": float(lo), "ratio_upper": float(hi),
            "error_lower_percent": float(100 * (lo - 1)),
            "error_upper_percent": float(100 * (hi - 1)),
            "VCO_error_lower_MHz": float(3200 * (lo - 1)),
            "VCO_error_upper_MHz": float(3200 * (hi - 1)),
            "physical_accuracy_proven": False}


def native_budget(name, watchdog, overhead, assumption):
    cycles = watchdog + overhead
    count = 1 + (113 * cycles) // 100
    return {"name": name, "watchdog_MEASURE_REF_cycles": watchdog,
            "first_div_to_freeze_extra_REF_cycles_allowance": overhead,
            "total_REF_cycles": cycles,
            "feedback_ceiling_Hz": 113000000,
            "native_Div_max_count_conditional": count,
            "modulo256_wrap_possible": count >= 256,
            "remaining_counts_to_wrap": 256 - count,
            "assumption": assumption}


def main():
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in SOURCES}
    manifest = json.loads(MAP.read_text(encoding="utf-8"))
    assert hashes["mos_r1/afc2009_mos.scs"] == manifest["source_sha256"]
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    row30 = next(row for row in plan["rows"] if row["code"] == 30)
    f30 = F(str(row30["illustrative_loaded_offset_transfer_Hz"]))
    err30 = f30 / F(3200000000) - 1
    ideal_min_window = int(F(1, 2) + F(7, 2) / err30) + 1
    uncertainty_min_window = int(F(3, 2) + F(11, 2) / err30) + 1
    rows = [
        bound("128_instantaneous_no_raw_sign",128,1,128,
              "Correct bracket/credits, stable common-time ideal counts, neither raw difference>=2."),
        bound("128_qualified_near_first_raw_sign_allowed",128,2,128,
              "Same ideal count assumptions; current first raw sign may exist; previous REF sample lacked it; stable frequency fb/ref<=1.13."),
        bound("128_one_count_per_word_uncertainty_budget",127,4,128,
              "Additionally each observed word differs from common-time ideal by <=1 count; this is an assumed budget, not proven CDC/reset/MTBF behavior."),
        bound("192_qualified_near_first_raw_sign_allowed",192,2,192,
              "Hypothetical192 window under same ideal count assumptions; no source change performed."),
        bound("192_one_count_per_word_uncertainty_budget",191,4,192,
              "Hypothetical192 with assumed <=1 count per-word uncertainty; no source change performed."),
    ]
    budgets = [
        native_budget("R1_watch192_normal_epoch_budget",192,14,
                      "Generous14-cycle total overhead includes nominal5-cycle ARM epoch plus CDC/decision/gate allowances, some double-counting; sources unchanged."),
        native_budget("hypothetical_watch208_normal_epoch_budget",208,14,
                      "Normal epoch <=5REF and conservative extra9 cycles; gives total222REF. Not an unconditional asynchronous-reset safety proof."),
        native_budget("hypothetical_watch208_late_ARM_budget",208,37,
                      "ARM epoch accepted near32REF plus5-cycle CDC/decision/gate allowance. General hardware overflow detector absent."),
    ]
    result = {
        "version": "read-only-R1-finite-window-risk-v1",
        "electrical_sources_modified": False,
        "simulator_started": False,
        "old_planning_estimates_are_new_measurements": False,
        "R1_unit_near_high_pass_context_only": json.loads(UNIT.read_text(encoding="utf-8")).get("unit_functional_pass"),
        "R1_full_PLL_capture_not_claimed_by_this_assessment": True,
        "one_count_128_resolution_MHz": 25,
        "one_count_resolution_is_frequency_accuracy": False,
        "count_model": {
            "Tref_ns": 10,
            "u": "(first_Div - preceding_lead)/Tref in [0,0.5)",
            "v": "0.5-u",
            "x": "(observation_time-first_Div)/Tref",
            "ideal_counts": "n_div=floor(r*x)+1; n_lead=floor(x+u)+1; n_lag=floor(x-v)+1",
            "general_conditional_bound": "(N-D-1)/(N+0.5) <= r < (N+D+1)/(N-0.5)",
            "qualified_near_D2_reason": "No2consecutive sign allows first raw sign at deadline; between consecutive REF observations Div advances<=2, reference advances1, so relative difference can reach2.",
            "no_unconditional_physical_bound": "Metastability duration, missed/ghost startup credit, Gray-decode glitches and nonstationary VCO settling are not proved bounded by this math."
        },
        "frequency_envelopes": rows,
        "code30_planning_only": {
            "loaded_at_0p6_Hz_estimate": float(f30),
            "above_target_Hz_estimate": float(f30-F(3200000000)),
            "relative_error_percent_estimate": float(err30*100),
            "loaded_at_0p3_Hz_estimate": plan["potential_code30_capture_risk"]["illustrative_loaded_at_ctrl_0p3_Hz"],
            "actual_capture_failure_proven": False,
            "128_near_still_possible": True,
            "192_ideal_sign_margin_MHz": float((f30-F(3200000000))/F(1000000))-rows[3]["VCO_error_upper_MHz"],
            "192_is_robust_under_assumed_one_word_count_uncertainty": False,
            "minimum_window_for_estimated_code30_ideal_D2": ideal_min_window,
            "minimum_window_for_estimated_code30_assumed_one_count_per_word": uncertainty_min_window,
            "minimum_window_values_are_guaranteed_physical_performance": False
        },
        "counter_budget": {
            "max_integer_REF_cycles_without_wrap_at_113MHz": 225,
            "first_div_to_freeze_must_be_less_than_REF_cycles": float(F(25500,113)),
            "formula": "native_div_count=1+floor(1.13 * first_div_to_freeze_REF_cycles)",
            "cases": budgets,
            "watch208_safe_if_total_overhead_at_most_REF_cycles": 17,
            "general_32cycle_ARM_plus208_MEASURE_not_safe_with_8bit": True,
            "window192_branch_normally_stops_earlier_than_watch208": True,
            "nine_bit_followup": "Adds one native bit and two CDC bits for each of3countwords (9DFFs plus count/decode/compare gates); permits lateARM+longerwindow budget, but still not MTBF or arbitrary input fault signoff."
        },
        "recommendation": "Run currentR1 fullnominal physicalloop first. If actualAFC selects a testedcode and finecapture passes with Vctrlmargin, deliver boundednominal version; window192/watch208 is an optimization followup, not a needed speculative source mutation now.",
        "required_failure_diagnosis": "Ifactualcode30finefails, inspectselectedcode,Vctrlrail,frequencyandclamp/power afterhandover; distinguish1.28us-windowselection error frominsufficientsimulationstop. Existingcrossbenchf(.3/.6) estimates alone cannot decide.",
        "source_sha256_before": hashes,
        "source_sha256_after": {p.relative_to(ROOT).as_posix(): sha(p) for p in SOURCES},
    }
    assert result["source_sha256_before"] == result["source_sha256_after"]
    result["source_bytes_unchanged"] = True
    out = Path(__file__).with_name("r1_window_counter_risk_assessment.json")
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"report":str(out),"source_bytes_unchanged":True,
                      "code30_ideal_minW":ideal_min_window,
                      "code30_uncertainty_minW":uncertainty_min_window},ensure_ascii=False))


if __name__ == "__main__": main()
