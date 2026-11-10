# S29 and S30 data

[Release v2026.11.10-supplement](https://github.com/path4Source/Paper_SUMO_Simulation/releases/tag/v2026.11.10-supplement)
provides the complete recorded datasets supporting Tables S29 and S30 in the
v4.5.1 manuscript. The earlier
[core release](https://github.com/path4Source/Paper_SUMO_Simulation/releases/tag/v2026.11.09-core)
remains unchanged. Download the two study ZIPs as complete files; no multipart
restoration is needed.

| Table | Download | Contents |
| --- | --- | --- |
| S29 | [s29-six-condition-evidence.zip](https://github.com/path4Source/Paper_SUMO_Simulation/releases/download/v2026.11.10-supplement/s29-six-condition-evidence.zip) | 35 runs, six conditions, 84 paired intervals, 42 implementation outputs and 1,855 lane records |
| S30 | [s30-prospective-confirmation-evidence.zip](https://github.com/path4Source/Paper_SUMO_Simulation/releases/download/v2026.11.10-supplement/s30-prospective-confirmation-evidence.zip) | 45 runs, eight conditions, 112 paired intervals, 72 implementation outputs and 216 local comparisons |

The release includes `RELEASE_SHA256SUMS.txt`, `PUBLIC_FILES_SHA256.json` and
`PUBLIC_DISTRIBUTION.json`. Use the first to verify downloaded assets and the
second to verify study ZIP members. The distribution record identifies the
source archives and the one omitted editorial reply draft. All retained
research files, including frozen code, inputs, outputs and prediction locks,
are unchanged. ZIP member times retain the original records; the release date
is not the experiment date.

## S29 replay

Use Python 3.12 with the pinned requirements. Extract the S29 ZIP to a short,
new path such as `E:/s29` on Windows. Run the following from that directory:

```sh
python archive_addenda.py verify --archive-dir assets
python archive_addenda.py restore six --archive-dir assets --output ../six-study
python -m pip install -r ../six-study/requirements_analysis.txt
python -B test_portable_six_analysis.py
python -B portable_six_analysis.py verify --root ../six-study
python -B portable_six_analysis.py analyze --root ../six-study --locked-analysis assets/six-locked-analysis.zip
```

Use the supplied portable entry point: it resolves recorded Windows paths on
the current host without editing frozen code. The analysis checks all 35 runs
and compares measurements and decisions with the locked archive. It refuses
to overwrite existing analysis outputs.

## S30 replay

Extract the S30 ZIP to a separate short path such as `E:/s30`. From that folder:

```sh
python -m pip install -r requirements.txt
python -B tools/replay_r31_prospective_confirmation_20261109.py --root . --output ../confirmation-replay
```

For an additional reconstruction from all 45 raw runs, use a different new
output directory:

```sh
python -B tools/replay_r31_prospective_confirmation_20261109.py --root . --output ../confirmation-raw-replay --raw-audit
```

These commands do not start SUMO. The replay verifies frozen source and output
hashes, reproduces the 112 intervals, 72 implementation comparisons and 216
local comparisons, and runs the 22 reference/scoring tests. See `REPRODUCE.txt`
for the comparison tolerances and the recorded schema adapter.

## Record scope

S29 remains an author-designed targeted panel; no independent human reference
answers are added by this release. S30 applies prospectively fixed observable
endpoints. Its full-rule state concordance is 6/8, compared with 4/8 for Q/D;
the two additional matches are the demand-changed conditions. The qualified
positive denominator is zero, so positive-opportunity capture is not estimable.
The development retention policies remain exploratory.

The archives contain construction mappings, rules and predictions. They must
not be represented as undisclosed material for a subsequent blind assessment
of these same cases. Historical `AUTHOR_ONLY`, `PRIVATE`, `public_upload=false`
and preparation-status labels describe earlier workflow stages. The current
release establishes public access, not a change in those historical events.

S29 is byte-identical to the retained portable archive. S30 omits only
`R31_WORKING_ADDITION_EN.txt`, an editorial response draft. Its original
`MANIFEST.json` is preserved as a source-archive record and therefore lists that
omitted file; `PUBLIC_FILES_SHA256.json` describes the distributed member set.
No other S30 member is changed or omitted. Existing third-party notices remain
in force; this release assigns no new reuse licence.
