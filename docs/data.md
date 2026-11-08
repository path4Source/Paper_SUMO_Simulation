# Data

## Distribution

The code archive contains simulation inputs, analysis programs, processed reference tables, and current figure assets. Large raw simulator outputs are distributed as eight companion archives. Each archive retains its original filename because `data_manifest.json` uses that name to locate it. The manifest records the archive checksum, every member path, and every member checksum.

| Analysis command | Required archive |
| --- | --- |
| `analyze original` | `original_analyses-raw.zip` |
| `analyze local` | `raw_analyses-raw.zip` |
| `analyze warnings` | `diagnostics-raw.zip` |
| `analyze settings` | `setting_connector-raw.zip` |
| `analyze morris` | `morris-raw.zip` |
| `analyze scores` | `scores-raw.zip` |
| `analyze holdout` | `holdout-raw.zip` |
| `analyze followup` | `holdout-raw.zip` and `followup-raw.zip` |

Place the eight ZIP files in `data-deposit-candidate/`, next to the extracted `beyond-throughput/` directory. From `beyond-throughput/`, run:

```sh
python reproduce.py restore --archive-dir ../data-deposit-candidate
python reproduce.py verify --complete
```

On Windows, use a short extraction path, for example rename the extracted repository directory to `E:/bt` and put the data archives in `E:/data-deposit-candidate`. This changes only the outer folder name. The relative commands remain valid. Before writing any raw files, the entry point checks that the selected archive destinations fit the portable Windows path limit.

To restore one group, add its identifier without the `.zip` suffix, for example `--dataset setting_connector-raw`. An analysis checks its complete inputs before it starts. Do not move extracted raw files between analysis packages.

The data directory also contains a copy of this manifest, a dataset description, and archive checksums. Those small files accompany a data deposit; they are not additional measurements. Some archive groups contain overlapping source records so that each analysis can be reproduced independently. Those copies are not additional experimental runs.

## Measurements

The evidence includes vehicle completion and entry records, warnings, simulator summaries, and local detector outputs where those were collected. Warning logs are part of the evidence. The local-service experiments include phase-aligned crossing and queue measurements; the Morris design uses a reduced-output protocol.

The Morris archive contains 660 design runs and five separate equivalence controls. The score archive covers 81 original runs. The revised primary score uses throughput, delay, and halting responses; simulation-based emission quantities remain in the historical comparisons. The study scope is summarized in the repository README.

## File metadata and integrity

Original runs date from April-May 2026; revision experiments date from October 2026. These dates come from the retained SUMO output headers. The [chronology](chronology.md) provides the per-run record and explains how experiment, file, and release dates differ.

ZIP entries preserve the modification times of verified source files in UTC+08:00, at ZIP's two-second precision. Copies that match an identified historical source retain its modification time. Reconstructed inputs, new analyses, updated figures, and documentation keep their later preparation times. Raw member contents are unchanged; use each archive with the matching SHA-256 manifest.

The repository uses `.gitattributes` to disable automatic line-ending conversion. This preserves the bytes covered by its SHA-256 manifests when files pass through Git. Keep this file in the repository. The restoration command checks contents but does not restore filesystem modification times; newly restored files may show the extraction time.

## Availability

The companion raw archives are currently available from the corresponding author on reasonable request. Their filenames and checksums are recorded in `data_manifest.json`. A public data-deposit identifier has not been assigned.

## Provenance records

Package manifests retain the state of each preparation stage, including historical fields such as `public_deposition_complete` and `full_paper_dependency_closure`. Those fields describe the recorded stage, not a live publication status. Current entry points and data dependencies are listed in `catalog.json` and the [reproduction guide](reproduction.md). Recorded source paths support provenance and local path mapping; they are not required directory names for a new installation.

## Prospective holdout and setting bridge

`holdout-raw.zip` contains 95 run records: 65 holdout runs, 15 new setting-bridge runs and 15 reused reference runs. The latter are copies of existing executions, not new experiments. Raw records retain original configuration headers; runnable inputs under `reproduction/portable_holdout_v2/inputs/` resolve their network paths locally. Only the 15 reused input configurations required network-path remapping.

The raw replay reconstructs 65 observation records and 30 bridge rows, checks vehicle accounting, then reproduces 84 semantic predictions and the paired intervals. This checks recorded measurement and software consistency. Independent reference adjudication and the remaining numerical/measurement validation are tracked separately and are not marked complete.

## Measurement and step-refinement archive

`followup-raw.zip` adds 171 executions, including one separately identified technical control. The failed initial control check and its metadata-only resolution are retained. The 30 numerical references are read from `holdout-raw.zip`; duplicated references do not increase the run count. File timestamps and raw-output contents are preserved. Neither the code package nor this candidate data directory contains completed independent reference judgments.
