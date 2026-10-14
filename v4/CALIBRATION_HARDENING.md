# V4 candidate calibration input hardening

The existing research-only ridge residual candidate now validates **all six**
feature values using the same constraints as `v4_evidence_audit`.
Previously it checked only a subset of feature ranges. The shared validator
rejects fractional player/rest differences, out-of-range travel, excessive
wind and invalid neutral-site values.

Timestamps are normalized to UTC before comparison; boolean or nonpositive
sample thresholds are rejected. No training data is generated or inferred
by this change. The candidate still requires independent point-in-time
evidence and remains research-only, with `release_ready=False`.

Run `python -m unittest test_v4_calibration_hardening`.
