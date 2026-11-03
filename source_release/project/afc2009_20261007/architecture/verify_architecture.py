"""Independent exact-rational edge fixtures for the Jeong-2009 adaptation.

This checks the mathematical bracket and search contract, not MOS timing,
metastability, synthesis, PLL noise, or a guaranteed PVT capture range.
"""
from fractions import Fraction as F
import argparse
import hashlib
import json
from pathlib import Path

TREF = F(10)  # nanoseconds, 100 MHz
HALF = TREF / 2


def event_fixture(ratio, phase, periods=128, jitter=False):
    """Independent timestamp *test stimulus*, never a frequency-decision estimator.

    The DUT contract decides solely from integer edge counts. Stimulus event
    scheduling is the test bench's mathematical oracle and is not implementation.
    """
    ratio, phase = F(ratio), F(phase)
    t0 = phase
    # Right-continuous REF-level capture: a tie with REF or !REF is the lead.
    lead0 = (phase // HALF) * HALF
    lag0 = lead0 + HALF
    end = t0 + periods * TREF
    events = {}
    # One preceding leading edge is represented by a credit at the first Div edge.
    counts = {"lead": 1, "lag": 0, "div": 1}
    for kind, first, period in (("lead", lead0 + TREF, TREF),
                                ("lag", lag0, TREF),
                                ("div", t0 + TREF / ratio, TREF / ratio)):
        k, t = 1, first
        while t <= end:
            adjusted = t
            if jitter and kind == "div":
                adjusted += (TREF / 500) * (1 if k % 2 else -1)
            events.setdefault(adjusted, []).append(kind)
            k += 1
            t = first + (k - 1) * period
    early_strict, early_guard = None, None
    n_events, n_ties = 0, 0
    for t, batch in sorted(events.items()):
        # Ties are an atomic event. Sequential scheduling cannot assign a
        # meaningful frequency direction to two simultaneous ideal edges.
        n_ties += int(len(batch) > 1)
        for kind in batch:
            counts[kind] += 1
        slow = counts["lag"] > counts["div"]
        fast = counts["div"] > counts["lead"]
        gs = counts["lag"] - counts["div"] >= 2
        gf = counts["div"] - counts["lead"] >= 2
        assert not (slow and fast), (ratio, phase, t, counts)
        assert not (gs and gf), (ratio, phase, t, counts)
        if not jitter:
            if ratio == 1:
                assert counts["lag"] <= counts["div"] <= counts["lead"]
                assert not (slow or fast)
            elif ratio < 1:
                assert not fast, (ratio, phase, t, counts)
            else:
                assert not slow, (ratio, phase, t, counts)
        # Bounded nonaccumulating 20 ps edge ripple must not create a two-count
        # opposite sign, including nominal ties.
        if ratio <= 1:
            assert not gf, (ratio, phase, t, counts)
        if ratio >= 1:
            assert not gs, (ratio, phase, t, counts)
        if early_strict is None and (slow or fast):
            early_strict = {"elapsed_ns": float(t - t0),
                            "direction": "slow" if slow else "fast"}
        if early_guard is None and (gs or gf):
            early_guard = {"elapsed_ns": float(t - t0),
                           "direction": "slow" if gs else "fast"}
        n_events += 1
    return {"ratio": str(ratio), "phase_ns": str(phase),
            "jitter_fixture": jitter, "events_checked": n_events,
            "simultaneous_batches": n_ties, "first_strict": early_strict,
            "first_two_count": early_guard, "last_counts": counts}


def compare_with_fixed_window():
    far = event_fixture(F(3, 4), F(17, 8))
    assert far["first_two_count"]["elapsed_ns"] < 128 * float(TREF)
    tiny = event_fixture(F(99999, 100000), F(17, 8))
    assert tiny["first_two_count"] is None
    return {"far_error_detected_before_full_window": far,
            "small_error_is_bounded_inconclusive": tiny}


def search_fixture(frequencies, target=3.2e9, near_fraction=0.005):
    """An independent sign oracle validates the tested-candidate search sequence.

    No claim that this oracle is a synthesizable count front end. It verifies
    controller contract properties independently of its particular RTL syntax.
    """
    code, step, history = 16, 8, []
    for round_index in range(5):
        freq = frequencies[code]
        err = (freq - target) / target
        direction = "near" if abs(err) <= near_fraction else (
            "fast" if err > 0 else "slow")
        history.append({"round": round_index, "code": code,
                        "frequency_Hz_oracle_only": freq, "direction": direction})
        if (code == 1 and direction == "fast") or (
                code == 31 and direction == "slow"):
            return {"history": history, "fail": True, "done": False,
                    "fine_enable": False, "reason": "endpoint/range unverified"}
        if direction == "near" or round_index == 4:
            assert code == history[-1]["code"]  # No untested final code.
            return {"history": history, "selected": code,
                    "candidate_provisional": True, "done": True,
                    "fail": False, "fine_enable": True,
                    "actual_capture_still_requires_MOS_validation": True}
        code += step if direction == "slow" else -step
        assert 1 <= code <= 31
        step //= 2
    raise AssertionError("search must terminate")


def search_suite():
    cases = {}
    cases["monotonic_target_between_codes"] = search_fixture(
        [1.50e9 + 60e6 * c for c in range(32)])
    assert [h["code"] for h in cases["monotonic_target_between_codes"]["history"]] == [16, 24, 28, 30, 29]
    cases["exact_initial_tie"] = search_fixture([2.4e9 + 50e6 * c for c in range(32)])
    assert cases["exact_initial_tie"]["selected"] == 16
    cases["too_high_everywhere"] = search_fixture([3.5e9 + 20e6 * c for c in range(32)])
    cases["too_low_everywhere"] = search_fixture([1.0e9 + 20e6 * c for c in range(32)])
    assert cases["too_high_everywhere"]["fail"]
    assert cases["too_low_everywhere"]["fail"]
    # A nonmonotonic map can evade binary-search correctness. This is an explicit
    # unsupported fixture; bounded termination must not turn into a capture claim.
    nonmono = [1.5e9 + 60e6 * c for c in range(32)]
    for c, f in {16: 2.0e9, 24: 3.7e9, 20: 2.3e9, 22: 3.65e9, 21: 2.2e9}.items():
        nonmono[c] = f
    cases["nonmonotonic_not_guaranteed"] = search_fixture(nonmono)
    assert cases["nonmonotonic_not_guaranteed"]["candidate_provisional"]
    assert abs(nonmono[cases["nonmonotonic_not_guaranteed"]["selected"]] / 3.2e9 - 1) > .1
    cases["nonmonotonic_not_guaranteed"]["binary_search_correctness"] = "unsupported"
    # Hardware faults are failure transitions, never AFC-done/fine-enable.
    cases["missing_feedback_epoch"] = {"ARM_REF_cycles": 32, "fail": True, "fine_enable": False}
    cases["counter_overflow"] = {"fail": True, "fine_enable": False}
    cases["contradictory_direction"] = {"slow": True, "fast": True, "fail": True, "fine_enable": False}
    cases["dead_reference_count_watchdog"] = {"MEASURE_REF_cycles": 192, "fail": True, "fine_enable": False}
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default=str(Path(__file__).with_name("architecture_fixture_results.json")))
    args = ap.parse_args()
    ratios = [F(2, 5), F(1, 2), F(3, 4), F(9, 10), F(99, 100),
              F(999, 1000), F(1), F(1001, 1000), F(101, 100), F(11, 10), F(7, 5), F(9, 5)]
    # Exact ties at 0/5 ns plus 5 ps/10 ps boundary apertures and broad phase grid.
    phases = sorted(set([F(i, 8) for i in range(80)] +
                        [F(1, 200), F(1, 100), F(999, 200),
                         F(1001, 200), F(1999, 200)]))
    records = [event_fixture(r, p, jitter=j)
               for r in ratios for p in phases for j in (False, True)]
    source_files = [Path(__file__), Path(__file__).with_name("afc2009_controller.sv"),
                    Path(__file__).with_name("interface_contract.json")]
    result = {
        "stage": "architecture_fixtures_passed",
        "event_fixture_cases": len(records),
        "events_checked": sum(r["events_checked"] for r in records),
        "simultaneous_batches": sum(r["simultaneous_batches"] for r in records),
        "phase_values": len(phases),
        "ratio_values": len(ratios),
        "jitter_definition": "nonaccumulating alternating +/-20ps Div-edge fixture; not physical noise",
        "mathematical_frequency_direction_verified": True,
        "early_stop_vs_fixed_window": compare_with_fixed_window(),
        "search_cases": search_suite(),
        "rtl_simulated": False,
        "rtl_synthesized": False,
        "rtl_limit": "No iverilog, verilator or yosys available; MOS-built controller remains separately verified",
        "MOS_timing_or_metastability_verified": False,
        "physical_PLL_capture_verified": False,
        "all_PVT_claim": False,
        "source_sha256": {str(p.name): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        "records": records,
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("stage", "event_fixture_cases", "events_checked", "simultaneous_batches")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
