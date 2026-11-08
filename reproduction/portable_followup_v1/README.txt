Measurement-channel and fixed-clock step checks

Run from the repository root after restoring holdout-raw and followup-raw:
  python reproduce.py analyze followup --output ../followup-results

The command checks the archived files, reconstructs 110 replay count records
across 53 lanes, 57,240,000 sampled queue records, 90 step-check run metrics,
84 frozen comparator outputs and all step-response tables. No SUMO run is started.
BH replay records are checked against saved original digests; BK original and
replay records are both reparsed. The technical-control FCD metadata exception
is retained with its original failed check and explicit resolution.

For a separate rerun, list cases with: python reproduce.py cases followup
Use SUMO 1.24.0. Archived outputs are never overwritten.
The packet contains author predictions; it is not the assessor handoff packet.
