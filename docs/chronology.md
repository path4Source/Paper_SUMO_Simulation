# Experiment chronology

Experiment dates are taken from the `generated on` header in each preserved SUMO `summary.xml`. The original configuration was evaluated in April-May 2026; the major-revision experiments were performed in October 2026.

| Run group | Runs | Recorded period | Role |
| --- | ---: | --- | --- |
| Original experiments | 240 | 26 April-27 May 2026 | Original scenario, seed, interaction, and supplementary checks |
| Revision diagnostics | 166 | 19-20 October 2026 | Population, local-service, intervention, warning, horizon, and setting checks |
| Revision exploratory runs | 22 | 19 October 2026 | Numerical-setting and instrumentation checks |
| Morris design | 660 | 20-21 October 2026 | 12 trajectories, 11 points per trajectory, five seeds |
| Morris equivalence controls | 5 | 20 October 2026 | Separate output-equivalence checks |

The machine-readable [run chronology](experiment_chronology.json) lists all 1,093 runs, their case identifiers, seeds, recorded timestamps, and summary-file SHA-256 hashes. The Morris controls are separate from the 660 design runs. Some data archives contain copies of the same source records so that analyses can be restored independently; those copies do not add experimental runs.

## Dates in downloaded files

- **Simulation date:** the timestamp written by SUMO in the preserved output header. The headers have no UTC offset, so the chronology retains the recorded values without conversion.
- **File modification date:** preserved from an identified source when the distributed file is byte-identical to it. Inputs reconstructed for portability and outputs newly produced by revision analyses retain their later dates.
- **Repository date:** the date of a Git commit or release. A new publication of earlier experiments has a new repository date; it does not change when those experiments were run.

ZIP timestamps represent source modification times in UTC+08:00 and have two-second precision. Git checkouts and raw-data restoration can show checkout or extraction times instead. Use the run chronology and its source hashes when identifying the experimental period.

No source output headers, completion records, or experimental values were altered to prepare this chronology.

## Later holdout and bridge executions

The later addition comprises 80 October 2026 executions and 15 reused October references. Per-run dates are retained from SUMO headers in `reproduction/portable_holdout_v2/input_inventory.json` (`sumo_generated_on`). Source file modification times are preserved when copying and packing. New release adapters and documentation retain their actual preparation times. Nothing is backdated.

## Measurement and numerical follow-up

The additional October 2026 records comprise 110 passive replays, 60 step refinements and one technical control. Their original completion records and output timestamps are preserved in the companion archive. See `reproduction/portable_followup_v1/execution_lineage.json` for the counting relationship; the combined inventory is 1,344 executions, not independent causal scenarios.
