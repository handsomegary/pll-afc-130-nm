# Spectre transistor and subcircuit atlas

Open the [compiled device gallery](gallery.pdf) for a terminal-level lookup or the [IEEE-style report](../pll130-afc.pdf) to follow the complete circuit signal paths.

The gallery uses the shared American CircuitikZ profile from [circuit-style.tex](../circuit-style.tex), with black circuit strokes and bold sans-serif terminal labels. The generator embeds these settings in every standalone export. Its TeX dependencies include PSNFSS (Times and Helvetica). Each device has the terminal order from its Spectre card, repeated net labels, local parameters and a source line. Matching net IDs within a module identify an electrical connection. The RF device symbol exposes the four terminals connected by the project. Its internal process model remains part of the licensed technology installation.

The catalog covers all 719 archived decks, including the ones that instantiate blocks through include files. Across those decks it enumerates 6,727 named subcircuit definitions, 33 distinct module names, 38 connectivity families and 50 distinct parameterized bodies. A connectivity family retains each instance name, model name, net, terminal order and formal port. Body variants also distinguish parameters written inside the module. Deck-level parameter values, bias and analysis settings still come from the particular source deck.

The 90-page [gallery](gallery.tex) draws all direct devices in 34 small and medium families. For each of the four large flattened AFC or 9-bit counter families it shows the first four cards. To draw any later device choose its one-based index. Each four-card group fits on a landscape page. The gallery has 305 device panels.

## Generate a drawing

From the atlas directory, use Python 3.7 or later and a TeX installation with CircuitikZ. For the last four MOS instances of the selected R1 AFC:

```sh
python3 draw_atlas.py --family afc2009_mos-21ea6444ebfa --first 7132 --count 4 --output last_four.tex
pdflatex -halt-on-error -no-shell-escape last_four.tex
```

Select the deck directly when you need its parameter variant:

```sh
python3 draw_atlas.py --deck project/netlists/vco_code0.scs --module current_ref --first 1 --count 4 --output bias.tex
```

Use `--mode index --output catalog.json` to rebuild the [catalog](catalog.json), or `--mode gallery --output gallery.tex` to rebuild the gallery. The script verifies published source hashes before reading the subcircuits.

## Module locator

| Module | Family ID | Direct device cards | Definitions | Parameterized bodies |
|---|---|---:|---:|---:|
| `afc2009_mos` | `afc2009_mos-21ea6444ebfa` | 7135 | 1 | 1 |
| `afc2009_mos` | `afc2009_mos-a873d37cff17` | 6908 | 1 | 1 |
| `afc2009_mos` | `afc2009_mos-fd1ef2a6db68` | 7839 | 1 | 1 |
| `and2` | `and2-816260a0d071` | 2 | 607 | 1 |
| `bf_2inv` | `bf_2inv-97ab11497fc6` | 2 | 607 | 1 |
| `cml_load_receiver` | `cml_load_receiver-12eed2451cbf` | 5 | 28 | 2 |
| `counter9_gray_cdc_mos` | `counter9_gray_cdc_mos-7a274891cbd0` | 2400 | 1 | 1 |
| `current_ref` | `current_ref-a648384fc473` | 4 | 607 | 7 |
| `delay` | `delay-f95a2e7b256e` | 2 | 2 | 1 |
| `inv` | `inv-bbc9ea216ec3` | 2 | 607 | 1 |
| `nand2` | `nand2-e08d9ff0185b` | 4 | 607 | 1 |
| `nor2` | `nor2-e9c09461b380` | 4 | 607 | 1 |
| `or2` | `or2-7ab8b69b70dc` | 2 | 607 | 1 |
| `pll130_and2` | `pll130_and2-37d0229f5810` | 2 | 1 | 1 |
| `pll130_cp_drain` | `pll130_cp_drain-156bce7f8c45` | 9 | 1 | 1 |
| `pll130_cp_inv` | `pll130_cp_inv-28e90483c781` | 2 | 1 | 1 |
| `pll130_cp_transistor` | `pll130_cp_transistor-8894127cf4d2` | 16 | 1 | 1 |
| `pll130_cpd_inv` | `pll130_cpd_inv-d97eee629c12` | 2 | 1 | 1 |
| `pll130_dff` | `pll130_dff-ffbf8308013f` | 8 | 1 | 1 |
| `pll130_div2` | `pll130_div2-a78c881ddf29` | 1 | 1 | 1 |
| `pll130_div32_cmos` | `pll130_div32_cmos-22d9bd5f3682` | 5 | 1 | 1 |
| `pll130_inv` | `pll130_inv-6b241e6f2334` | 2 | 1 | 1 |
| `pll130_latch` | `pll130_latch-4356a8a9d324` | 5 | 1 | 1 |
| `pll130_nand2` | `pll130_nand2-00971f9d0809` | 4 | 1 | 1 |
| `pll130_nor2` | `pll130_nor2-c366bab03699` | 4 | 1 | 1 |
| `pll130_or2` | `pll130_or2-d0f56e0a1570` | 2 | 1 | 1 |
| `pll130_pfd` | `pll130_pfd-bd7572bf5d53` | 8 | 1 | 1 |
| `pll130_pfd_tspc` | `pll130_pfd_tspc-ead1e01bf05c` | 6 | 1 | 1 |
| `pll130_receiver` | `pll130_receiver-ba0a82bb08ea` | 7 | 1 | 1 |
| `pll130_receiver_ac` | `pll130_receiver_ac-e4c86aa67319` | 9 | 1 | 1 |
| `pll130_tg` | `pll130_tg-20004b8c9f9d` | 2 | 1 | 1 |
| `s_to_d` | `s_to_d-39789199da9a` | 4 | 2 | 1 |
| `s_to_d` | `s_to_d-9232d664ce57` | 4 | 605 | 1 |
| `tg_delay` | `tg_delay-fb6f32dc3b7a` | 2 | 605 | 1 |
| `two_stage_ring` | `two_stage_ring-66962a1406d1` | 53 | 178 | 1 |
| `two_stage_ring` | `two_stage_ring-6808c58ed797` | 53 | 385 | 6 |
| `two_stage_ring` | `two_stage_ring-ddaed22a25f3` | 50 | 44 | 1 |
| `two_stage_ring_vco` | `two_stage_ring_vco-6a3dcf32823b` | 2 | 607 | 1 |

Each deck entry in the catalog gives the family ID, parameterized body digest, and first and last source lines. Top-level supplies, test stimuli and analysis statements remain in the original decks.
