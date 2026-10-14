# V4 source provenance review queue

Use `source_review_queue(baseline, evidence)` after recovering the
immutable V3 historical baseline. Export with `source_review_csv(report)`.

Each task shows the source URL, claimed feature value, claimed publication
and observation timestamps, original V3 capture time, and a blank review
section. The existing strict evidence audit rejects invalid or
post-capture claims before any review queue is produced.

A reviewer must independently inspect an authentic, archived, point-in-time
source and document the supporting passage and timing. A manually edited
review status is **not** automatically accepted as proof. This module
does not fetch external pages, validate archives, train V4, or change V3.
Both `source_authenticity_verified` and `release_ready` remain false.

Run `python -m unittest test_v4_source_review test_v4_evidence_audit`.
