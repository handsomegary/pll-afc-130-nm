# Relationship to the Supplied Sources

This project is a 130 nm redesign assembled from supplied ring-PLL concepts and a newly implemented AFC controller inspired by the 2009 reference. It is not a transistor-for-transistor replica of the supplied 3.2 GHz, 180 nm student paper.

## Which source informed which block

| Source | Contribution and boundary |
| --- | --- |
| Supplied 3.2 GHz fast-locking, low-jitter PLL student paper | Provides a two-stage multiband ring-VCO concept and a PLL/AFC architecture. Its AFC uses a numeric frequency error and an update of the form `S <- S + E`. |
| Supplied two-stage VCO SPICE files | Inform the two-stage delay-cell and coarse current-bank topology. The 130 nm design changes device sizing, bias, supply, and operating point. |
| Supplied four-stage PLL system SPICE file | Contains a conventional PFD/charge-pump/filter/four-stage-VCO/divider loop without an instantiated AFC. It is a different supplied design branch from the two-stage VCO files. |
| Jeong, Choi, and Yoo, RFIC 2009, pp. 583-586 | Supplies the two-phase frequency-detection, early-termination, and binary-search ideas. The reference uses an LC VCO and switched-capacitor coarse tuning. |
| This project | Implements MOS AFC logic, CDC handling, qualification guards, bounded search/fault control, physical hold clamps, and integration with a redesigned two-stage ring PLL. |

The supplied basic-cell file contains AFC/frequency-detector definitions, but definitions alone do not show that the supplied four-stage top-level netlist instantiates or exercises them. The supplied student paper also presents AFC diagrams and simulation effects. The incomplete match between the provided top-level files and that paper identifies a missing implementation/evidence link; it does not establish that the paper's AFC was never implemented.

## Differences from the student paper

| Topic | Student paper | Selected repository design |
| --- | --- | --- |
| Process and supply | 180 nm, 1.8 V | 130 nm, 1.2 V |
| VCO | Two-stage multiband ring VCO | Redesigned two-stage differential ring VCO with a current-bank coarse code |
| AFC update | Error-based `S <- S + E` | Direction-based steps of 8, 4, 2, and 1 from code 16 |
| Frequency detector | Numeric error generation shown in its block diagrams | Two-phase lead/lag/feedback counts with qualified fast/slow/near decisions |
| Charge pump | Source-switched structure with an amplifier | Redesigned drain-switched charge pump; the original amplifier structure is not reproduced |
| Verified performance | Paper's reported simulation results | One completed nominal noise-free acquisition case, a retained failed-clamp case, and a bounded fixed-code control |

Matching a 3.2 GHz nominal output is insufficient to reproduce the paper's architecture or reported jitter, lock time, and FoMs. The measured 4.689528 us AFC-start-to-lock result belongs to this new design.

## Differences from the 2009 AFC

The 2009 circuit applies coarse calibration to an LC oscillator's capacitor bank and uses a divide-by-four phase generator with 0-degree and 315-degree reference outputs. This implementation applies the coarse code to a ring oscillator current bank and selects between the 100 MHz reference and its inverse. Its bracketing phase separation is 180 degrees, or 5 ns, rather than the original phase-generator arrangement.

Increasing the code raises frequency in the tested ring-VCO region. Capacitor-bank code polarity depends on its switch definition and cannot be copied into the ring design without checking it. The present design also adds registered Gray counters, matched two-stage synchronization, a count-difference guard of two, two-observation direction qualification, watchdogs, frozen-decision drain timing, and delayed analog handoff.

The reference's reported calibration time, noise, area, and power are properties of its own LC implementation. They are not inherited by this ring-PLL adaptation. The 7,135-MOS, 146-DFF count is the expanded AFC block in this project; it is not a published transistor count from the 2009 paper.

## Portable files and historical evidence

The repository uses English descriptions and portable include paths. Device statements and circuit connectivity are preserved when making portable copies, with provenance checks recording the transformation. Original simulated file hashes remain labeled as original hashes. A transformed file's hash is a repository-copy identifier, not proof that the transformed file itself was used in the historical run.

Historical results are retained with their original pass/fail meaning. In particular, the weak clamp remains a strict failure and the AFC-off case remains a bounded failure to capture. Process models, reference PDFs, and archived learning packages are not redistributed in this repository. No layout, extracted circuit, silicon result, or new simulation is created merely by publishing the portable source package.
