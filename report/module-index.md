# Spectre subcircuit and behavioral-model index

The guest project snapshot contains 32 distinct Spectre `subckt` names. The table lists each name once. Figure labels refer to the LaTeX sources beside this index and remain stable if the printed figure numbers change. A gate symbol or labeled connection can be expanded through the referenced transistor plate. Each bench netlist retains its instance-specific geometry, multiplicity, loading, stimuli and controls.

| Spectre name | Figure label or section | Implementation and applicability |
|---|---|---|
| `afc2009_mos` | `fig:r1afc-datapath`, `fig:r1afc-fsm`, `fig:r1afc-cells`, `fig:r1afc-latch` | R1 selected. The original R0 uses raw FB clocking and a different reset/clock implementation. Historical Circuits describes this revision. The prepared counter9 option has a separate design status. |
| `and2` | `fig:apdecode`, `fig:r1afc-cells` | VCO decoder with NAND2 followed by INV. |
| `bf_2inv` | `fig:apdecode`, `fig:r1afc-cells` | Two inverters in series produce a noninverting buffered output. |
| `cml_load_receiver` | `fig:hist-rx` | RF differential CML load test exposes both resistor-loaded drains. Input width changes between the two load variants. |
| `current_ref` | `fig:apcore` | Current-driven NMOS reference, second NMOS and diode-connected PMOS. The instance dimensions and bias source can vary between benches. |
| `delay` | `fig:apdecode`, `fig:r1afc-cells` | Seed name for the always-on TG used by the complementary driver. NMOS gate goes to VDD and PMOS gate to VSS. |
| `inv` | `fig:r1afc-cells` | CMOS inverter in the oscillator library. The bench sets its geometry. |
| `nand2` | `fig:r1afc-cells` | Oscillator library, two series NMOS and two parallel PMOS. |
| `nor2` | `fig:r1afc-cells` | Oscillator library, two parallel NMOS and two series PMOS. |
| `or2` | `fig:apdecode`, `fig:r1afc-cells` | VCO decoder with NOR2 followed by INV. |
| `pll130_and2` | `fig:apdecode`, `fig:r1afc-cells` | Digital library NAND2 followed by INV. |
| `pll130_cp_drain` | `fig:apcp` | Selected drain-switched charge pump with always-biased mirror gates. |
| `pll130_cp_inv` | `fig:hist-cp`, `fig:r1afc-cells` | Inverter in the archived gate-switched pump. NMOS/PMOS widths 0.5/1.5 um. |
| `pll130_cp_transistor` | `fig:hist-cp` | Candidate with four TGs steering its two output-device gates. |
| `pll130_cpd_inv` | `fig:apcp`, `fig:r1afc-cells` | Inverter in the drain-switched pump. NMOS/PMOS widths 0.8/2.4 um. |
| `pll130_dff` | `fig:apdiv` | Master and slave static latches with shared clock and reset controls for this divider cell. |
| `pll130_div2` | `fig:apdiv` | Toggle flip-flop with complementary output returned to D. |
| `pll130_div32_cmos` | `fig:apdiv` | Five cascaded divide-by-two stages. |
| `pll130_inv` | `fig:r1afc-cells` | Digital-library CMOS inverter with width and length parameters. |
| `pll130_latch` | `fig:apdiv`, `fig:r1afc-latch` | Two TGs, two inverters and a reset NMOS. Control routing for the divider is specified in `fig:apdiv`. |
| `pll130_nand2` | `fig:r1afc-cells` | Digital-library two-input NAND gate. |
| `pll130_nor2` | `fig:r1afc-cells` | Digital-library two-input NOR gate. |
| `pll130_or2` | `fig:apdecode`, `fig:r1afc-cells` | Digital-library NOR2 followed by INV. |
| `pll130_pfd` | `fig:appfd` | Two TSPC slices, NOR reset logic and a buffered reset path. |
| `pll130_pfd_tspc` | `fig:appfd` | Six-device dynamic PFD slice. |
| `pll130_receiver` | `fig:hist-rx` | Direct coupling from one differential output drain to two CMOS inverters. |
| `pll130_receiver_ac` | `fig:aprx` | Selected AC-coupled receiver with feedback bias on the first output inverter. |
| `pll130_tg` | `fig:r1afc-cells`, `fig:apdiv` | Digital transmission gate, parallel NMOS and PMOS with complementary enables. |
| `s_to_d` | `fig:apdecode` | Two unequal paths produce complementary outputs. The seed calls the always-on branch `delay`, later decks call it `tg_delay`. |
| `tg_delay` | `fig:apdecode`, `fig:r1afc-cells` | Always-on TG with gates tied to the supply rails, same two device connections as `delay`. |
| `two_stage_ring` | `fig:apcore`, `fig:apbank`, `fig:hist-rx` | One differential delay cell. Ordinary and mixed-RF transistor models occur in the archive. Earlier supplemental gates pass CTRL through an NMOS, later versions add a PMOS to make a TG. |
| `two_stage_ring_vco` | `fig:apcore`, `fig:apbank`, `fig:apdecode` | Two differential cells, cross-connected into a ring. |

## Verilog-A modules used by staged benches

| Module | Modeled function |
|---|---|
| `pll130_cp_va` | Enabled current injection and removal with declared bias and mismatch parameters. |
| `pll130_precharge_va` | Switched conductance that draws CTRL toward the specified precharge voltage. |
| `pll130_vco_linear_va` | Limited linear control-to-frequency relation and integrated phase driving differential sinusoidal outputs. |
| `pll130_div32_va` | Crossing-triggered count and divided output. |
| `pll130_pfd_va` | Behavioral reference/feedback edge detector and UP/DN generation. |
| `pll130_afc_va` | Frequency estimation from edge timestamps and an interval search over band codes. |
| `pll130_afc_handoff_va` | ENABLE and DONE determine FineEnable and the complementary hold signal. |
| `pll130_afc_test_source` | Unit stimulus with feedback frequency `(2.5 GHz + code x 27 MHz)/32`. |

Model values and module availability depend on the chosen bench. Select the R1 strong-clamp bench to reproduce the nominal transistor loop described in the paper.
