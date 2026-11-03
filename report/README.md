# Coarse Acquisition and Analog Handoff in a 3.2 GHz Ring PLL in 130 nm CMOS

[Read the report](pll130-afc.pdf) or open [main.tex](main.tex). The report uses the IEEEtran conference class and the American CircuitikZ symbol convention. All circuit figures are editable vectors.

| To study | Open |
|---|---|
| System feedback, acquisition criteria and AFC-on/off frequency curves | [Main report source](main.tex) |
| Ring stages, current banks, bias, receiver, divider, PFD, pump and filter clamps | [Selected-loop schematics](analog_modules.tex) |
| Two-phase counting, search states and transistor cells | [AFC controller](afc_modules.tex), [CMOS cells](afc/device_cells.tex), [latch and interlock](afc/latch_and_clock.tex) |
| Earlier receiver, pump and switch configurations | [Historical circuits](historical_modules.tex) |
| Original module names and the implementing circuit figure | [Module index](module-index.md) |
| Device terminals for each archived wiring family | [90-page device atlas](atlas/gallery.pdf) and [commands to draw any instance range](atlas/README.md) |
| Simulator netlists, SKILL, OCEAN, behavioral models and CAD library configuration | [Source release](../source_release/README.md) |

Build from this directory with a TeX distribution that provides IEEEtran, CircuitikZ, pgfplots, Latin Modern, booktabs and hyperref. The second pass resolves figure and bibliography references.

```sh
mkdir -p build
pdflatex -no-shell-escape -halt-on-error -output-directory=build -jobname=pll130-afc main.tex
pdflatex -no-shell-escape -halt-on-error -output-directory=build -jobname=pll130-afc main.tex
```

[acquisition.dat](acquisition.dat) contains the 129 window centers shared by [the enabled trace](../results/afc_on_trace.json) and [the fixed-code trace](../results/afc_off_trace.json). The frequency plot uses their `frequency_windows.windows` entries. Each output frequency is divided by one billion to express it in GHz. All reported capture times retain their labeled reference event.
