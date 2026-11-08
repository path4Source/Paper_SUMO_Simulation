Prospective holdout and stochastic-update bridge

Inputs: 60 held-out treatment runs, five shared baseline runs, 15 new bridge runs,
and 15 reused bridge references. This is 80 added executions, not 95.

From the repository root, restore holdout-raw.zip and run:
  python reproduce.py analyze holdout --output ../holdout-analysis
This reconstructs measurements from raw output before replaying both implementations.
For processed-input checks only, use analyze holdout_processed.

Source modules remain byte-identical. The raw-replay adapter maps paths and joins
the archived observations; it neither retunes the rules nor runs SUMO.
The 12 x 7 ledger records rule outputs and triggers, not adjudicated accuracy.
Do not give prediction or construction files to a reference assessor before locking
their judgments. The separate assessor-only packet is the intended handoff.
