# V4 review worksheet reconciliation

`reconcile_review(baseline, evidence, reviewed_rows)` compares a completed
manual worksheet with the original V4 source review queue.

It fails closed on missing or duplicate rows, unknown game-feature keys,
changes to source URL/value/timestamps, unsupported statuses, and review
decisions lacking a named reviewer, notes and timezone-aware review time.

Allowed statuses: `UNREVIEWED`, `NEEDS_FOLLOWUP`, `REJECTED`,
`REVIEWED_CLAIM`. The last status is a human attestation, **not**
independent source authentication. No worksheet status can unlock
V4 calibration, deployment or official betting actions.

Run `python -m unittest test_v4_review_reconciliation`.
