# Cadence design sources for the 130 nm PLL

Start with the R1 strong-clamp bench below to trace the selected schematic-level design. The 130 nm project also contains earlier VCO sweeps, staged behavioral loops, controller unit tests and a fixed-code control. The bench name and its run record identify the applicable result.

| Entry point | Role |
|---|---|
| [Selected 6.5 us bench](project/afc2009_20261007/integration/r1/pll_strongclamp6500n_v1/pll_afc2009_physical_halfvdd_ref10000_4p_r1_strongclamp6500n_v1.scs) | Top-level electrical connections, external stimuli and analyses |
| [R1 AFC transistor netlist](project/afc2009_20261007/mos_r1/afc2009_mos.scs) | Controller gates and their MOS instances |
| [Analog blocks](project/pll_full/analog/) and [digital blocks](project/pll_full/digital/) | Charge pump, clock interface, divider, PFD and staged behavioral models |
| [SystemVerilog controller](project/afc2009_20261007/architecture/afc2009_controller.sv) | Architecture and functional reference |
| [Sweep netlists](project/netlists/) | Supply, temperature, corner, frequency and load experiments |
| [OCEAN exporters](project/skill/) | Read saved results for noise measurements. Other exporters live beside their individual sweep decks. |
| [Library Manager replay](project/logs/gui-open-20261004-3DIRis/open-library-manager.il) and [library setup](project/cds.lib) | The SKILL file calls `ddsOpenLibManager()`. The library setup inherits the installed IC defaults and defines the local technology library. |
| [Archived host variants](host_variants/) | Alternate revisions with the same logical filename as a retained guest version |

The snapshot was checked against the October 30, 2026 project file inventory. The R0 failure, the R1 weak-clamp iteration, the R1 selected bench and the host-only R2/counter9 design can be distinguished by their directory names. R2/counter9 has prepared sources. The README at the repository root identifies the selected historical evidence.

| Type | Guest files | Additional host source versions | Purpose |
|---|---:|---:|---|
| Spectre `.scs` | 706 | 13 | Circuit definitions, top-level benches and simulation control statements |
| SKILL `.il` | 1 | 0 | Library Manager replay |
| OCEAN `.ocn` | 13 | 3 | Measurement and export |
| Verilog-A `.va` | 4 | 0 | Project-authored behavioral blocks and test stimulus |
| SystemVerilog `.sv` | 1 | 0 | Functional controller model |
| Python `.py` | 138 | 67 | Netlist generation, historical runners and analysis |
| Shell `.sh` | 2 | 0 | Original runtime checks |
| Cadence `cds.lib` | 1 | 0 | Library definitions |
| Design/configuration `.json` | 66 | 27 | Pin maps, parameters, fixtures, source identities and bench manifests |
| Project ownership marker | 1 | 0 | Scope for historical job-control scripts |

All 933 guest inputs have original byte hashes checked against the retention inventory. Each of the 110 host additions has a separate source hash. The manifest also lists 345 host paths whose normalized source matches another published file. No project-local `.ils`, `.cdsinit`, `.cdsenv`, `.simrc` or `hdl.var` appeared in this project snapshot. The site-wide IC initialization included by `cds.lib` belongs to the local installation.

## Verify and configure

The archived file contents use explicit path bindings such as `@PROJECT_ROOT@` and `@TECH_ROOT@`. Run the offline check with Python 3.6 or later:

```sh
python3 materialize.py verify
```

On the licensed Linux machine, configure a fresh run tree. Supply the installed IC root containing `share/cdssetup/cds.lib`, the Spectre root containing `bin/spectre`, and the technology root containing both the OA library directory and `models/spectre`. Use actual local paths for the example arguments.

```sh
python3 materialize.py configure \
  --output /work/pll130/run-tree \
  --tech-root /eda/process130 \
  --oa-library YOUR_LOCAL_OA_LIBRARY_NAME \
  --ic-root /eda/ic \
  --spectre-root /eda/spectre
```

The configurator checks the 22 external model fingerprints recorded for the selected historical run, resolves path bindings and writes the project sources into the new directory. The resulting deck can be opened and run with a licensed Spectre installation. Configuration itself does not run Spectre or Virtuoso. External model files, installation defaults, license setup, compiled simulator libraries and waveforms remain local. The independently portable selected benches in the repository root also support the existing `tools/run_simulation.py` entry point.

Some archived drivers and postprocessors require past results, frozen source digests or the original ownership checks. Those checks remain in the files. For a new run in a different directory use the configured top-level deck, or the selected-bench runner from the repository root. Historical results and source hashes apply to the original run. An OCEAN exporter requires results of the appropriate analysis at its configured results path.

## Trace a source

[manifest.json](manifest.json) records each published alias, original byte digest and public digest. The VM source tree retains the original directory relationships. Host additions whose relative names were unused on the VM appear under `project/` and carry the `host_source` origin in the manifest. Conflicting versions live under `host_variants/`. A few display labels and comments were translated to English. Source line endings use LF.

[include_index.json](include_index.json) enumerates 219 references to project circuit files and 1,100 references to external model entry points. [licensed_inputs.json](licensed_inputs.json) gives the relative local paths, sizes and SHA-256 values for the selected run's technology dependencies.
