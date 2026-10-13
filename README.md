# 130 nm Ring PLL with Automatic Frequency Calibration

A transistor-level 130 nm ring PLL with a Jeong-2009-inspired automatic frequency calibration (AFC) controller. The nominal target is 3.2 GHz from a 100 MHz reference with divide-by-32 feedback.

The selected R1 implementation completed a noise-free nominal transient simulation at TT, 25 C, and 1.2 V. It selected coarse code 29 and met the engineering acquisition and clamp criteria. This is a redesign with a new AFC implementation; it is not an exact reproduction of the supplied 180 nm student paper.

| Historical nominal result | Value |
| --- | ---: |
| Tested coarse codes | 16 -> 24 -> 28 -> 30 -> 29 |
| AFC start to engineering lock | 4.689528 us |
| Final frequency | 3.199994055 GHz |
| Last 500 ns total supply power | 4.185162440 mW |
| AFC start to lock supply energy | 24.387860 nJ |
| Maximum held control-voltage error | 19.312722 mV, below the 30 mV criterion |
| AFC block size | 7,135 MOS instances and 146 DFF instances |

These are results from the original completed runs. The repository copies have portable include paths and English comments, so their file hashes differ from the original simulated files. The provenance records distinguish the original hashes from the repository hashes. No new simulation is claimed by packaging these files.

## Read the design

- [Architecture and handoff](docs/architecture.md): the ring oscillator, two-phase detector, counters, search, and analog clamp.
- [Results and acceptance criteria](docs/results.md): the successful case, the retained failed clamp case, and the AFC-off control.
- [Relationship to the supplied papers and circuits](docs/source_relationship.md): what was reused, changed, and newly implemented.

The principal benches are [AFC enabled](circuits/benches/pll_afc_on.scs) and [AFC disabled](circuits/benches/pll_afc_off.scs). The AFC controller is [afc_mos.scs](circuits/blocks/afc_mos.scs).

## Run with a local process installation

The repository does not contain process model libraries, simulator binaries, licensed design-kit files, or the reference PDFs. A compatible locally installed process library and Spectre are required. Another 130 nm library is not automatically an electrically equivalent replacement.

1. Create `config/process_models.local.scs` using local model-library paths and the required model sections. This file is ignored by Git. Match the device model names referenced by the circuit blocks, including the RF device dependencies.
2. Check the repository's portable sources and provenance offline:

   ```sh
   python tools/verify_repository.py
   ```

3. Run one bench in the background or a terminal, providing the installed simulator path:

   ```sh
   python tools/run_simulation.py --bench on --spectre /path/to/spectre --threads 4 --timeout 7200
   ```

   For the fixed-code capture control, use `--bench off`. The runner uses a single-job lock to prevent overlapping runs through this tool. A requested thread count does not guarantee that the simulator uses that many threads.

The historical full runs used a 6.5 us stop time, a 4 ps maximum step, a 40 ps saved strobe, `reltol=1e-4`, and trapezoidal integration. Output size depends on the saved signals and simulator format; retain the supplied bounded observation period before extending it.

## What is verified

The VCO, receiver, divider, PFD, drain-switched charge pump, AFC logic, and clamp switches are transistor-level circuits. The benches still use an ideal external reference, ideal bias sources, ideal passive components, and explicit initial conditions. Device models may contain their own implementation languages; the AFC controller itself is implemented with MOS circuits.

The evidence supports nominal engineering acquisition. It does not establish physical jitter, phase noise, SNR, spur performance, a complete tuning-range specification, full PVT or Monte Carlo behavior, CDC MTBF, layout area, LVS, extracted parasitics, an editable schematic database, cold-start robustness, or silicon performance. The transistor count applies to the AFC block, not to the entire PLL or a layout area.
