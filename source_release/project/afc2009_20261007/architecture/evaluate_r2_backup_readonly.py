"""Offline backup architecture assessment; no circuit, bench or VM mutation.

Imports the frozen R1 generator in memory only to count the width-only cost.
The R2 electrical source is owned elsewhere and is not produced here.
"""
import sys
sys.dont_write_bytecode = True
from fractions import Fraction as F
from pathlib import Path
import hashlib
import importlib.util
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
INPUTS = [ROOT / "mos_r1" / name for name in (
    "build_afc2009_mos.py", "afc2009_mos.scs", "port_manifest.json")]
INPUTS += [ROOT / "evidence" / "r1" / name for name in (
    "nominal_capture_planning_estimate.json",
    "r1_near100_high_measurement_v3.json",
    "r1_near100_low_measurement_v3.json",
    "r1_fast140_measurement_v3.json",
    "r1_slow70_measurement_v3.json",
    "r1_no_feedback_measurement_v3.json")]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def envelope(window, uncertainty_per_word=0):
    # These are conditional common-time, settled-frequency integer-count bounds.
    # A provisional NEAR can have its first raw sign at the deadline: D=2.
    # Assuming each observed word is within +/-1 count gives N=W-1,D=4.
    N = window - uncertainty_per_word
    D = 2 + 2 * uncertainty_per_word
    lo = F(N - D - 1) / F(2 * N + 1, 2)
    hi = F(N + D + 1) / F(2 * N - 1, 2)
    return {"window": window, "N": N, "D": D,
            "assumed_per_word_count_uncertainty": uncertainty_per_word,
            "ratio_lower_inclusive": float(lo), "ratio_upper_exclusive": float(hi),
            "VCO_lower_error_MHz": float(3200 * (lo - 1)),
            "VCO_upper_error_MHz": float(3200 * (hi - 1)),
            "actual_physical_frequency_accuracy_proven": False}


def budget(bits, deadline, after_watch_allowance):
    B = deadline + after_watch_allowance
    count = 1 + (113 * B) // 100
    return {"bits": bits, "modulus": 2 ** bits,
            "global_REF_age_deadline": deadline,
            "after_watch_REF_allowance": after_watch_allowance,
            "first_Div_to_freeze_REF_age_bound": B,
            "FB_frequency_ceiling_Hz": 113000000,
            "native_Div_count_max_conditional": count,
            "remaining_to_wrap": 2 ** bits - count,
            "no_wrap_under_assumptions": count < 2 ** bits,
            "native_credit_and_clock_integrity_proven": False}


def width_only_inventory():
    # Do not run main(), emit a netlist, edit generator bytes, or write pycache.
    spec = importlib.util.spec_from_file_location("r1_inventory_only", INPUTS[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.build()
    old_counter = module.Circuit.gray_counter
    def nine(self, clk, rst, prefix, initial=0, bits=8):
        return old_counter(self, clk, rst, prefix, initial, bits=9)
    module.Circuit.gray_counter = nine
    try:
        widened = module.build()
    finally:
        module.Circuit.gray_counter = old_counter
    return {"method": "Build R1 in-memory, then only native Gray width forced9; downstream CDC/decode/frozen words follow its vector length. No netlist emitted.",
            "R1_MOS": original.transistors, "R1_DFF": original.dffs,
            "width_only_MOS": widened.transistors, "width_only_DFF": widened.dffs,
            "delta_MOS": widened.transistors - original.transistors,
            "delta_DFF": widened.dffs - original.dffs,
            "delta_MOS_percent": 100 * (widened.transistors / original.transistors - 1),
            "delta_DFF_breakdown": {"native": 3, "two_stage_CDC": 6, "frozen_snapshot": 3},
            "actual_complete_R2_inventory": False,
            "clock_load_timing_or_power_validated": False}


def main():
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in INPUTS}
    manifest = json.loads(INPUTS[2].read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == hashes["mos_r1/afc2009_mos.scs"]
    plan = json.loads(INPUTS[3].read_text(encoding="utf-8"))
    row30 = next(row for row in plan["rows"] if row["code"] == 30)
    estimated_error_MHz = (row30["illustrative_loaded_offset_transfer_Hz"] - 3.2e9) / 1e6
    rows = [envelope(W, E) for W in (128, 192, 224) for E in (0, 1)]
    inventory = width_only_inventory()
    contract = {
        "version": "R2-backup-interface-prepared-unverified-v1",
        "activation": "Wait for full R1 actual result; prepared backup only, no electrical validation here.",
        "paper_relation": "Jeong2009 two-reference first-edge bracket and counter early-stop/binary-search concept; 100MHz REF/!REF selection, guard2/CDC, native Gray9bit, deadlines and staticMOS implementation are engineering additions.",
        "top_port_order": manifest["port_order"],
        "top_port_order_changed": False,
        "reference_Hz": 100000000, "feedback_division": 32,
        "clamp_V": 0.6, "code_increases_frequency": True,
        "initial_code": 16, "tested_search_steps": [8, 4, 2, 1],
        "maximum_tested_candidates": 5,
        "terminal_candidate": "Actual tested near candidate, or fifth tested candidate; no untested final SAR update.",
        "count_word_bits": 9, "native_modulus": 512,
        "all_words_same_width": ["native registered Gray", "two REF-stage synchronized Gray", "binary decoded counts", "guard2 unsigned subtraction", "frozen decision snapshots", "diagnostic portmap/save list"],
        "native_presets": {"lead": 1, "lag": 0, "Div": 0},
        "first_active_Div_increment_intended": "Div0 ->1 after counter-reset release",
        "native_initial_credit_validation": "UNKNOWN; original reference pair is phase evidence, not proof of native counter increment credit.",
        "CDC": "Matched pipeline depth of2 REF-clocked register stages for all3 Gray words; not a guarantee of identical physical sample time or MTBF.",
        "slow_condition": "decoded_lag - decoded_Div >=2 (9bit unsigned, no borrow)",
        "fast_condition": "decoded_Div - decoded_lead >=2 (9bit unsigned, no borrow)",
        "sign_qualification": "Same raw sign at two consecutive REF observations; both qualified signs =>FAIL.",
        "near_lag_deadline": 224,
        "near_decode_9bit": "cg8 OR (cg7 AND cg6 AND cg5), i.e. unsigned lag>=224, not low8bit mask alone.",
        "near_priority": "Same R1 physical behavior: current qualified sign precedes near; first unqualified raw sign may still terminate near at deadline.",
        "settle_REF_cycles": 4, "ARM_timeout_REF_cycles": 32,
        "epoch_guard": "seen2-stage sync then2 additional REF register stages",
        "age_timer": {"bits": 8, "deadline": 248,
            "reset": "count_rst=1; dedicated buffered alias recommended to retain independent clock-control reset group",
            "age_origin": "Actual held counter reset release, covering ARM and MEASURE; does not restart at MEASURE entry",
            "timer_can_continue_DRAIN": True,
            "watch_effective_gate": "count_run AND (arm OR measure); after valid snapshot counters freeze and DRAIN does not create a late false FAIL",
            "watch_decode": "age7 AND age6 AND age5 AND age4 AND age3 (248..255)",
            "invalid_gate": "!count_rst alone is insufficient: reset remains low for2 DRAIN clocks",
            "priority": "Timeout/conflict FAIL has priority over simultaneous decision/near; complete excludes fail_event, done and fail are mutually exclusive; fine_enable excludes fail.",
            "safety_scope": "Physical no-wrap bound requires native clocks freeze/reset within3REF after watch and FB<=113MHz. Electrical validation pending."},
        "DRAIN_REF_cycles": 2, "counter_reset_during_DRAIN": 0,
        "DRAIN_counting": "Native clocks frozen after decision; preserve decision data until drain_finish",
        "DONE_to_fine_REF_cycles": 2,
        "endpoint_failure": "code1 stillFAST or code31 stillSLOW =>FAIL, CP disabled, clamp and PFD reset retained",
        "handover": "hold=!fine_enable; pfd_reset=rst|!fine_enable; CP enabled only when fine_enable",
        "golden": "New R2 literal gate/DFF source records and independent new fixtures, rather than earlier 8bit128 controllerRTL",
        "not_claimed": ["Full PLL capture", "all-phase initial native credit", "MTBF", "all PVT", "PN/jitter improvement", "literal2009 circuit reproduction"]
    }
    tests = [
        {"id": "offline_static_literal", "action": "Audit all9bit datapath/CDC/snapshots/portmap; exercise timeout-vs-valid priority and done/fail exclusion; hash new source and fixtures.", "simulation_needed": False},
        {"id": "five_physical_units", "action": "Re-run near100high/low, fast140, slow70, noFB with new source; expected protection FAIL is unit PASS but not AFC success; save actual counters/signs/FSM.", "simulation_needed": True, "near_unit_recommended_stop_us": 2.75},
        {"id": "small_error_first_decision", "action": "Fixed-feedback diagnostic near code30 estimated101.874658MHz across four start phases, or replace with actual loadedR1 frequency; assess first decision/guard/snapshot. Do not call truncated multi-round run a full unit PASS.", "simulation_needed": True},
        {"id": "global_age_late_epoch", "action": "Late firstFB nearARM acceptance deadline, verify globalage includesARM and boundedFAIL/nohandover; overlap valid and timeout at a control edge to confirm FAIL priority.", "simulation_needed": True},
        {"id": "nine_bit_counter_high_bit", "action": "Small physical registeredGray9bit counter fixture crosses255->256->300; confirm MSB and decode/preset. Ordinary AFC rounds often stop<256 and otherwise do not exercise ninth bit.", "simulation_needed": True},
        {"id": "single_actual_TT_PLL", "action": "Same analog PLL/VCO with newAFC, actual feedback,0.6Vclamp: code history, fineenable, Vctrl rail margin and posthandover frequency/phase lock criteria. Set bounded stop from actualR1 timing (about8us may be needed for224window), no PVT/noise claim.", "simulation_needed": True}
    ]
    result = {
        "version": "R2-read-only-backup-design-assessment-v1",
        "status": "prepared_unverified; wait_full_R1_actual_before_activation",
        "simulator_started": False, "VM_contacted": False,
        "R1_circuit_bench_parser_modified": False,
        "R2_electrical_source_produced_by_this_assessment": False,
        "recommendation": "If actualR1 finecapture passes, deliver bounded nominalR1. If R1 selects provisionalcode30 but fails actualcapture after adequate time, prefer9bit/near224/globalage248 R2 with guard2 and same tested-code binary search. Physical tests must qualify it.",
        "nominal_planning_only": {"estimated_code30_error_MHz": estimated_error_MHz,
            "estimated_code30_FB_Hz": row30["illustrative_loaded_offset_transfer_Hz"] / 32,
            "estimated_code30_low_fine_Hz": plan["potential_code30_capture_risk"]["illustrative_loaded_at_ctrl_0p3_Hz"],
            "new_R1_measurement": False, "actual_capture_failure_proven": False,
            "Kvco_linear_extrapolation_from_0p835_to_0p6_used": False},
        "counting_bound": {"conditional_formula": "(N-D-1)/(N+0.5) <= fb/ref < (N+D+1)/(N-0.5)",
            "assumptions": "Correct initial bracket/native credits, steady periodic settledfrequency, common-time idealcounts. D2 includes first raw sign at near deadline. Extra per-word +/-1 is an assumed sensitivity budget, not an actualCDC proof.",
            "native_credit": "UNKNOWN", "one_count_resolution_is_accuracy": False,
            "envelopes": rows,
            "code30_ideal_D2_exclusion_margins_MHz": {str(W): estimated_error_MHz - envelope(W)["VCO_upper_error_MHz"] for W in (128,192,224)},
            "224_excludes_code30_under_assumed_word1count_errors": False},
        "option_comparison": [
            {"option": "8bit/near192/globalage208", "advantage": "Fewest gates; fixes lateARM age origin, still guard2.", "limitation": "Old code30 ideal exclusion margin about1.5MHz and assumedword uncertainty allows near; less robust than224, not a capture guarantee.", "budget": budget(8,208,3)},
            {"option": "8bit/near224", "recommended": False, "reason": "Cannot count through224 plus pipeline/freeze at113MHz without relying on early sign; watch208 would abort even perfect-near before224. General overflow detector absent."},
            {"option": "9bit/near224/globalage248", "recommended_if_R1_actual_fails": True, "advantage": "About9.88MHz ideal-code30 exclusion margin and roomy no-wrap budget; source remainsMOS hardware.", "limitation": "Extra clocks/area/loading and longercalibration; nativecredit/CDC uncertainty canstillallow near, actualcapture required.", "budget": budget(9,248,3)},
            {"option": "remove_was_near_terminal_to_always5trials", "recommended": False,
                "reason": "Physical toggle mux selects ADD whenever was_fast=0. NEAR has noqualifiedsign, so deleting only terminal_near sends30->31,16->24. Must instead continue counting samecode until a valid direction or boundedfailure; five-trial forcing is not a one-gate safe fix."}
        ],
        "width_only_inventory": inventory,
        "timing_notes": {
            "global248_minus_near224_REF_nominal_margin": 24,
            "near_equal_frequency_lag_count224_occurs_after_first_Div_REF_cycles": "223+v with0<=v<=0.5, plus CDC/control freeze latency",
            "late_epoch": "An epoch accepted nearARM32 can consume about25REF before firstactiveFB;224near plus pipelines can exceedglobal248 and conservativelyFAIL. This is intended bounded safety, not proof of frequency mismatch.",
            "clock_loading": "One more bit per nativeword raises native counter register fanout12.5%; CDC adds6DFFs and frozen snapshots3DFFs. Physical nonoverlap/fanout/reset release must be rechecked.",
            "global_watch_fault_scope": "No arbitrary-clock-fault or metastability-duration guarantee; timer must latchFAIL before8bit agewrap. stop latency allowance3REF is a design constraint, not measured here."},
        "minimal_test_set": tests,
        "source_sha256_before": hashes,
        "source_sha256_after": {p.relative_to(ROOT).as_posix(): sha(p) for p in INPUTS}
    }
    assert result["source_sha256_before"] == result["source_sha256_after"]
    result["source_bytes_unchanged"] = True
    for name, obj in (("r2_backup_design_assessment.json",result),
                      ("r2_backup_interface_contract.json",contract)):
        path = OUT / name
        if path.exists():
            raise FileExistsError("Immutable assessment already exists: " + str(path))
        path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(OUT / "r2_backup_design_assessment.json"),
                      "source_bytes_unchanged":True,"width_only_inventory":inventory,
                      "envelopes":rows,"budget_R2":budget(9,248,3)},ensure_ascii=False))


if __name__ == "__main__":
    main()
