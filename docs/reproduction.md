# Reproduction

Run commands from the repository root. Each analysis writes to a new directory and checks its output against the included reference results. The analysis programs do not launch new SUMO experiments.

## Environments

- Python 3.12 for input inspection, simulation replay, and analysis.
- SUMO 1.24.0 for simulation replay only.
- `requirements-analysis.txt` records the statistical and current plotting environment.
- For the November 18 figures, install `reproduction/manuscript_figures/requirements.txt` under Python 3.12. This includes the core plotting environment and ReportLab for Figure 3. The recorded typography of the core figures is Arial; fonts are not redistributed.
- The historical renderer uses Python 3.8 and `requirements-legacy-renderer.txt`. Use that separate interpreter only for the older `scores`, `legacy`, `cycle`, `intervention`, and `horizon` figure groups. Do not install both plotting environments into the same virtual environment.

The tested platform is Windows. Numerical checks use the tolerances recorded by each analysis; pixel-level figure comparisons also require the recorded plotting environment and fonts.

## Analysis map

| Command identifier | Evidence reproduced |
| --- | --- |
| `original` | Vehicle populations, original configuration, warning exposure, and seed precision |
| `local` | Phase-aligned local service, condition-preserving interventions, and observation horizons |
| `warnings` | Warning-policy checks and the fixed-rule internal challenge |
| `settings` | Time-step/action-step compatibility and connector diagnostics |
| `morris` | Raw measurement extraction and the frozen Morris analysis |
| `scores` | Raw measurement extraction and three-component score analysis |
| `holdout` | Raw observation reconstruction, 12-condition rule replay and setting bridge |
| `holdout_processed` | The same rule and interval checks using processed observations only |
| `followup` | Passive-replay count channels, detector extent, frozen decisions and fixed-clock step comparisons |

For example:

```sh
python reproduce.py analyze local --output ../local-analysis
python reproduce.py analyze morris --output ../morris-analysis
python reproduce.py analyze scores --output ../score-analysis
```

`catalog.json` identifies the package and exact entry point for each command. The package's `expected/` directory contains its reference tables. Protocols, seeds, warning counts, and output checks remain with the corresponding experiment. The `warnings` analysis reproduces the internally prepared, parameter-hidden challenge using its frozen rules.

## Simulation inputs

```sh
python reproduce.py cases original
python reproduce.py cases diagnostics
python reproduce.py cases morris
python reproduce.py cases pilots
```

Choose one case from the printed list. `simulate` requires an explicit case and a new output directory. The executable can be set with `--sumo /path/to/sumo`. The archived inputs are never modified.

## Figures

[Browse the 12 figures by number](../figures/README.md). The machine-readable index, `figures/index.json`, records the final figure numbers, filenames, input references and checksums.

```sh
python reproduce.py figures --group current --output ../current-figures
python reproduce.py figures --group current --drawio /path/to/draw.io --output ../current-figures-drawio
```

The current group writes exactly 12 PDFs to `publication_figures/`. Ten data figures reuse the core renderer, whose intermediate results stay in `core-work/`. Figure 3 uses the archived three-seed OAT intervals and their warning flags. Figure 1 uses the revised workflow diagram: its verified PDF is copied by default, or exported from the editable source with `--drawio`. This command does not launch SUMO or compile the manuscript.

The earlier `scores`, `legacy`, `cycle`, `intervention`, `horizon`, `weather`, and `bottleneck` commands are retained for historical reproduction, not as the current submission appearance. Use `current` when matching `figures/index.json`. For historical figures that require the separate interpreter, supply `--python /path/to/legacy/python`.

## Integrity

`python reproduce.py verify` checks the packaged code and input files. `--complete` also checks every companion data file after restoration. Scientific calculation scripts and experimental records retain their verified contents. The repository entry point provides a common interface to the archived analyses; their historical directory identifiers are mapped to local files. See [Chronology](chronology.md) for the distinction between experiment dates and later packaging dates.

A failed check leaves its output available for inspection. Compare the reported difference with the reference result, recorded settings, and warning log. Reproduction uses the complete case and seed inventory, including warning-bearing records and adverse outcomes.

## Prospective holdout replay

```sh
python reproduce.py restore --archive-dir ../data-deposit-candidate --dataset holdout-raw
python reproduce.py analyze holdout --output ../holdout-from-raw
python reproduce.py analyze holdout_processed --output ../holdout-from-tables
```

The first analysis reads archived simulator outputs. The second checks only the processed measurements; it is useful for a quick code check but is not a substitute for raw reconstruction. Both use the frozen rules and their separately implemented comparator. No command in this block starts SUMO.

The original 15-figure set is reproducible with `python reproduce.py figures --group core-20261109 --output ../core-figures`. The core renderer and its reference measurements have not been modified.
