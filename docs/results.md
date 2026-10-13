# Results and Evidence Scope

The selected result is a completed noise-free transient run at nominal TT, 25 C, 1.2 V, a 100 MHz reference, and a 3.2 GHz target. The observation spans 0 to 6.5 us. Results in this document belong to the original simulated sources; portable repository copies have different hashes because comments and include paths were edited.

## Selected stronger-clamp case

| Measurement | Result |
| --- | ---: |
| AFC start, absolute time | 0.300020 us |
| AFC DONE, absolute time | 3.850960409 us |
| Fine enable, absolute time | 3.870948717 us |
| Engineering lock, absolute time | 4.989547658 us |
| AFC start to DONE | 3.550940409 us |
| Fine enable to engineering lock | 1.118598941 us |
| AFC start to engineering lock | 4.689527658 us |
| Selected and final coarse code | 29 |
| Final frequency | 3.199994054745 GHz |
| Final control-voltage mean | 0.647503170 V |
| Final differential peak-to-peak swing | 0.227054543 V |
| Maximum held control-voltage error | 19.312721520 mV |
| Code changes after fine enable | None observed |

The overall acceptance passes both the analog hold/handoff checks and the fine-loop engineering acquisition checks. Simulator completion alone is not used as electrical acceptance.

Frozen count snapshots support the search directions:

| Tested code | Lead count | Lag count | Feedback count | Decision |
| ---: | ---: | ---: | ---: | --- |
| 16 | 9 | 9 | 7 | SLOW |
| 24 | 25 | 24 | 22 | SLOW |
| 28 | 81 | 81 | 79 | SLOW |
| 30 | 67 | 67 | 69 | FAST |
| 29 | 130 | 128 | 129 | NEAR |

Stable tested candidates are 16 -> 24 -> 28 -> 30 -> 29. The saved code transition from 30 to 29 includes a 40 ps intermediate word of 28; it is not an extra stable tested candidate. A frozen count snapshot supports the observed direction but does not prove the entire live CDC sequence or metastability margin.

## Engineering lock definition

Lock is an offline acceptance measurement, not a lock detector implemented in the AFC hardware. The same algorithm and thresholds are used for the AFC-on and AFC-off cases:

- Frequency error is at most 0.1% of the target, evaluated in 100 ns windows with a 50 ns stride.
- Acquisition must persist for a 500 ns hold interval.
- Unwrapped feedback/reference phase peak-to-peak variation is at most 100 ps under the reader's hold-window calculation.
- Differential output peak-to-peak swing is at least 50 mV.
- Every later complete hold window in the saved observation must also pass.

The phase criterion describes deterministic transient acquisition. It is not an RMS jitter or phase-noise measurement. Static phase offset, waveform swing, numerical ripple, and physical noise are separate quantities.

The hold criterion additionally requires the control voltage to remain within 30 mV of the 0.6 V target during the audited hold interval. Handoff sequencing, failure signals, final code stability, and saved first-feedback/reference brackets are audited separately.

## Power and acquisition energy

| Interval or branch | Result |
| --- | ---: |
| AFC start to DONE: total average supply power | 5.523711588 mW |
| AFC start to DONE: total supply energy | 19.614370685 nJ |
| AFC start to engineering lock: total average supply power | 5.200493888 mW |
| AFC start to engineering lock: total supply energy | 24.387859923 nJ |
| Last 500 ns: total average supply power | 4.185162440 mW |
| Last 500 ns: AFC supply branch average power | 164.852954 uW |

Power is integrated from the saved instantaneous supply voltage and current. The total already includes the diagnostic supply branches; adding them again would double-count. The AFC branch includes its logic, hold inverter and switches, and the hold-reference divider/capacitor network. Charge-pump enable logic is accounted for in the digital branch. Ideal external reference generation and the implementation cost of unspecified physical bias generators are excluded.

## Retained weak-clamp failure

The original R1 weak-clamp run numerically completed and its fine loop acquired approximately 3.2 GHz. However, its maximum held error was 35.546660 mV, above the same 30 mV limit. The overall strict AFC/PLL acceptance remains failed. Its later acquisition does not erase the hold failure, and the limit was not relaxed to accept it.

The selected bench changes the two clamp widths and the hold-reference capacitance. It does not change the R1 AFC search algorithm or the acceptance limit. The repository preserves the distinction between this historical failure and the selected passing bench.

## AFC-off fixed-code control

The comparison bench uses the same physical fine loop, fixed code 16, and 0.6 V initial loop-filter conditions. The actual activation event is release of the PFD reset at 0.300020 us. Its saved enable waveform is an ideal time marker; it is not the AFC fine-enable gate, and the 0.6 V value is an initial condition rather than an active hold clamp.

| Measurement over the 6.5 us observation | AFC-off result |
| --- | ---: |
| Engineering acquisition | No capture observed |
| Final frequency | 2.469028276526 GHz |
| Final control-voltage mean | 1.187899927 V |
| Last 500 ns average total supply power | 3.382610365 mW |

The control voltage approaches the 1.2 V supply while the fixed band remains below the target. All 129 evaluated frequency windows are outside the 0.1% criterion. This supports the value of selecting a suitable coarse band in this case. It establishes failure to capture within 6.5 us, not failure for infinite time.

The AFC-off bench removes AFC logic, hold clamps, and charge-pump enable gates, and drives its code with ideal DC sources. Its loading therefore differs from the enabled bench. The last-window power is not locked-tail power, and these two runs do not establish an exact matched power ratio, a lock-speed improvement factor, or a PLL noise FoM improvement.

## Unit and audit evidence

The five completed controller unit cases cover two near-frequency starts, fast feedback, slow feedback, and absent feedback. Both near cases select code 16 and hand off. Fast and slow out-of-range cases reach a safe failure without handoff; absent feedback reaches the ARM watchdog failure. Passing these unit expectations does not mean the failure cases achieve PLL capture.

Saved full-run controller checks support stable one-hot state behavior, fresh measurement epochs, qualified direction logic, frozen decisions, and the two-edge DONE-to-fine delay. Samples too close to transitions are not treated as stable Boolean proof. These are bounded observable checks, not full native timing or CDC signoff.

## Unmeasured specifications

Physical phase noise, RMS jitter, integrated jitter, SNR, reference spurs, complete tuning-range limits, full PVT, mismatch, CDC MTBF, layout area, LVS, parasitic-extracted performance, editable schematic-database equivalence, and silicon behavior remain unverified. No noise or area FoM is reported. A larger process node or an added AFC block does not, by itself, establish an SNR or jitter advantage.
