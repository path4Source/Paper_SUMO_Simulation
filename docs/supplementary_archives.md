# Supplementary archives

These materials correspond to manuscript `20261108_v4_4_1`. The earlier code and
eight base-data archives remain available through `reproduce.py`. The later
evidence has a separate manifest, `addenda_manifest.json`, with archive and
member SHA-256 checksums. None of the commands below starts a simulation.

The later six-condition supplement is withheld while its reference assessment is
pending. This release contains no new six-case inputs, construction mapping or
predictions. The original twelve-case reference comparison remains provisional.

## Inspect and restore

Use Python 3.12. Save the companion ZIP files in `../supplemental-assets`.
Choose short, new output directories outside the code checkout on Windows.
Existing outputs are not overwritten.

```sh
python archive_addenda.py list
python archive_addenda.py verify --archive-dir ../supplemental-assets
```

## Original twelve-case reference comparison

```sh
python archive_addenda.py restore reference --archive-dir ../supplemental-assets --output ../reference-study
python ../reference-study/reproduce.py --output ../reference-results
```

This reproduces all 84 case/comparator records for Tables S27 and S28. Reference
agreement remains provisional while the evaluation process is confirmed. State
agreement, mixed-label agreement, coverage and candidate selection are separate
outputs. The original 0/3 reference-positive retention result remains unchanged.
The source package's v3 provenance is retained: the same observations, labels
and predictions underpin v4.4.1. Personal declarations are not included.

## n1 event and speed-gain-only development check

```sh
python archive_addenda.py restore n1-event --archive-dir ../supplemental-assets --output ../n1-event-study
python ../n1-event-study/development/analyze_fixed_batch.py --runs ../n1-event-study/runs --output ../n1-event-results
```

The archive contains the original event slice, three 200-second reproductions,
the eight full-hour development runs and their complete comparisons. A failed
socket-start attempt is retained as an infrastructure record, not a completed
simulation. The speed-gain-only restriction was not adopted. Original runtime
source and recorded output timestamps are preserved.

## n1 five-seed development panel

```sh
python archive_addenda.py check-n1 --archive-dir ../supplemental-assets --output ../n1-five-results
```

The verifier reads the unchanged archive directly. It checks 45 run records,
sampling scope, vehicle-hour burden, collisions, teleports, 30 paired comparisons
and the development safeguards. The panel contains 27 reused runs and 18 added
runs; it must not be added to an earlier execution total as 45 new executions.
The combined candidate remains unadopted. Development safeguards are not
classification-accuracy measurements. Historical source paths in the archive
describe the original environment; the verifier does not use those paths.

## Reuse and provenance

The new archive names are distribution labels, not changes to scientific data.
The complete source and raw archives are byte-identical to the author-retained
versions except for the n1 event package, which selects the research code,
protocols and outputs and omits editorial review prose. The per-file manifest
binds every selected member. No personal process records, correspondence,
manuscript drafts or response letters are included.

No reuse license is assigned to the authors' materials by this preparation.
The third-party notices in the base repository continue to apply. The release tag identifies the code and data version. Archive checksums allow
local verification of downloaded assets.
