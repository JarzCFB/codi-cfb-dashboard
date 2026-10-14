# V4 research dataset inventory

`research_dataset_inventory(baseline, evidence, reviewed_rows)` combines
the strict evidence audit with the immutable manual-review reconciliation.

Games are classified as pending outcome, rejected evidence, missing
evidence, awaiting review, or manually reviewed but unverified.

Even a fully reviewed worksheet is not independent authentication of a
historical source. Therefore `trainable_rows` is always empty and
`eligible_for_research_calibration` and `release_ready` are always false.

This is a gap inventory, not a model training pipeline. It never changes
official V3 picks, grades, or prospective capture timestamps.

Run `python -m unittest test_v4_research_dataset`.
