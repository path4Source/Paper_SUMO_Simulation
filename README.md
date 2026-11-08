# Beyond Throughput

Research materials for **Beyond Throughput: Interpreting Traffic Performance in Oversaturated Signalized Corridors Using SUMO Simulation**.

An increase in completed traffic can reflect better service, a different demand load, or simulator handling of warnings. This study combines evidence rules, vehicle accounting, local measurements, and intervention tests to distinguish these explanations in an oversaturated three-signal SUMO corridor.

## Study and evidence

The repository follows the paper's three contributions:

1. **Explicit evidence rules.** Matched-seed uncertainty, demand exposure, and warning records determine whether an interpretation is accepted, qualified, or withheld. Coexisting flags and conflicting evidence remain in the decision record.
2. **Network-to-lane accounting.** Entry backlog, unfinished trips, phase-aligned crossings, and detected queues link corridor output to local service and redistribution between movements.
3. **Intervention assessment under retained adverse conditions.** Matched-seed green reallocation tests a different operational lever while retaining the original adverse condition. Target-lane gains are assessed alongside donor-lane queues and corridor-wide recovery.

The case study demonstrates why these distinctions matter: compatible numerical settings change the short-headway response, and local benefits from green reallocation do not establish joint corridor recovery. The repository provides recorded inputs, analysis programs, reference results, and figure sources for examining those findings.

| Evidence | Reproduction command |
| --- | --- |
| Response interpretation and warning qualification | `analyze original`, `analyze warnings`, `analyze settings` |
| Population accounting, phase-aligned service, and observation horizon | `analyze original`, `analyze local` |
| Different-lever intervention with target and donor measurements | `analyze local` |
| Joint-input screening and diagnostic-score robustness | `analyze morris`, `analyze scores` |
| Prospective holdout, per-case rule triggers, and stochastic-update bridge | `analyze holdout` |
| Measurement-channel checks and fixed-clock step refinements | `analyze followup` |

## Getting started

Use Python 3.12. Recorded simulations use SUMO 1.24.0; install SUMO separately.

On Windows, extract the repository into a short path such as `E:/bt`. Deeply nested download folders can exceed Windows path limits when raw data are restored. The entry point checks this before restoration. Keep analysis output paths short as well.

```sh
python reproduce.py list
python reproduce.py verify
python reproduce.py cases original
python -m unittest discover -s tests -v
```

These commands inspect the repository and test the entry point without starting simulations. For a selected simulation, provide its case identifier and a new output directory:

```sh
python reproduce.py simulate original --case original/baseline --output ../baseline-replay
```

Use the identifier printed by `cases`. Simulation runs preserve the archived settings and seed. The runner compares new measurements with the recorded values and does not overwrite previous outputs.

## Contents

| Location | Contents |
| --- | --- |
| `reproduction/` | Simulation inputs, analysis code, reference tables, and manifests |
| `figures/` | Assets used by the current manuscript and supplementary source |
| `catalog.json` | Analysis entry points and data dependencies |
| `data_manifest.json` | Checksums and destinations of companion data archives |
| `docs/reproduction.md` | Analysis commands, environments, and output checks |
| `docs/data.md` | Archive-to-analysis map and data availability |
| `docs/chronology.md` | Original and revision experiment dates and their sources |
| `tests/` | Entry-point integrity and safe-restoration tests |
| `CITATION.cff` | Study citation metadata |
| `THIRD_PARTY_NOTICES.md` | Attribution and license information for included third-party source |

The input inventory contains 240 original runs, 166 revision diagnostic runs, 22 exploratory runs, 660 Morris design runs, five separate Morris equivalence controls, and 80 later holdout/bridge executions: 1,173 executions before the measurement and step-refinement follow-up. The bridge also reuses 15 already counted references. The holdout comprises 12 conditions, each with five seeds, plus five shared baseline runs. Conditions, seed repetitions and reused references are separate counting units. Original runs were recorded in April-May 2026; revision runs were recorded in October 2026. Replicated seeds, controls, and exploratory checks are identified separately in the [experiment chronology](docs/chronology.md).

## Reproducing the analyses

Install the analysis environment, then restore the companion data archives:

```sh
python -m pip install -r requirements-analysis.txt
python reproduce.py restore --archive-dir ../data-deposit-candidate
python reproduce.py verify --complete
python reproduce.py analyze original --output ../original-analysis
```

Place `data-deposit-candidate/` next to the extracted repository directory. See [Data](docs/data.md) for restoring only the archive required by one analysis. Allow space for the uncompressed raw files and additional analysis outputs; ZIP sizes are not the working-space requirement.

Individual analysis commands and plotting environments are described in [Reproduction](docs/reproduction.md). Restore and verification do not run SUMO.

For the current manuscript figures, install `reproduction/portable_figures_v5/requirements.txt` and run:

```sh
python reproduce.py figures --group current --output ../current-figures
```

This generates the 14 data figures and the framework used in the current main text and supplement. The `publication_figures/` output contains exactly those 15 PDFs; numerical traces and paired intervals are checked. Figure 1 has an editable draw.io source; its verified PDF is copied by default. Add `--drawio /path/to/draw.io` to re-export that source. Historical figure groups remain available for earlier presentation versions.

## Scope

The evidence concerns one synthetic, uncalibrated corridor. Seed replication characterizes within-model variability; the fixed-rule challenge and prospective holdout are author-prepared and parameter-hidden. The 12-condition, seven-comparator ledger records decisions and triggers; the returned reference comparison is provisional pending process confirmation. Local crossings and detector queues measure service response, rather than saturation flow. Morris estimates apply to the tested ranges and retain warning-exposed runs. The revised primary score uses throughput, delay, and halting; historical emission outputs remain auxiliary. These distinctions define how to interpret and extend the case study.

## Citation and reuse

The accompanying manuscript is under review; its author and title metadata are in `CITATION.cff`. Raw-data access is described in [Data](docs/data.md). No license is assigned to the authors' materials in this distribution. Included third-party source retains the notices and license listed in `THIRD_PARTY_NOTICES.md`.

## Measurement and step-refinement records

The pre-n1 inventory contains 1,344 unique executions. The follow-up adds 110 passive measurement replays, 60 fixed-clock step refinements and one technical equivalence control. Thirty numerical reference runs are reused.

Restore both `holdout-raw` and `followup-raw`, then run:

```sh
python reproduce.py analyze followup --output ../followup-results
```

This reconstructs lane counts, sampled detector extent, run metrics, paired intervals and frozen comparator outputs. It retains measurement residuals and every numerical outcome. No simulation is started by the analysis command. The calculation-function provenance and execution ledger are in `reproduction/portable_followup_v1/`.

The current figure index contains the 15 figures referenced by the full-length manuscript. Author predictions in this repository are separate from the assessor-only packet and must remain withheld from the reference assessor until the returned judgments have been locked.

The legacy `freeze_submission.py` helper is imported only for its unchanged SHA-256 function. Its two private document paths have been replaced by relative placeholders in this distribution; private submission and review files are not included. Protocol records retain the hashes of the original executed source, while package manifests identify the distributed copies. This path-only adaptation does not change any calculation function.

## Evidence included in this release

This version covers the original study, revision measurement and numerical
checks, the provisional twelve-case reference comparison, and n1 event and
controller-development evidence. It corresponds to the completed parts of
manuscript baseline `20261108_v4_4_1`. Companion data are available under the
repository's Releases tab. Archive filenames and checksums are recorded in
`data_manifest.json` and `addenda_manifest.json`.

The 1,344-execution inventory predates the n1 follow-up. The later event probes,
eight-run speed-gain check and 45-record controller panel are listed separately
in [Supplementary archives](docs/supplementary_archives.md). Of the 45 records,
27 are reused and 18 are additions. Neither development candidate was adopted.

The original twelve-case comparison remains provisional while its assessment
process is confirmed. The subsequent six-condition supplement is not included
in this release because its reference assessment is pending. Its inputs,
construction mapping and predictions will be deposited separately after the
reference return is locked or the assessment scope is explicitly changed.
This release therefore does not establish completion of independent assessment
or full deposition of every supplement. Personal declarations, correspondence,
manuscript drafts and reviewer responses are not included.
