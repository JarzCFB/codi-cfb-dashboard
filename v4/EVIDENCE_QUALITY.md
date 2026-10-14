# V4 evidence quality diagnostics

The research-only `v4_evidence_quality.quality_report(baseline, evidence)` function
builds on the existing fail-closed `audit_evidence` contract.

It reports per-feature coverage, missing feature cells, incomplete games ordered
by completeness, source-host *claims*, and the oldest observation-to-capture lag.

Run `python -m unittest test_v4_evidence_quality test_v4_evidence_audit`.

**Important:** HTTPS URLs, timestamps, and complete feature rows are supplied
claims, not independently authenticated publications. The report always returns
`source_authenticity_verified=False`, `release_ready=False`, and
`status=RESEARCH_ONLY`. Do not use it to certify injuries, train a release
candidate, change official V3 picks, or issue live betting actions.

To graduate V4, build an independent source-authentication process, obtain
representative point-in-time all-FBS samples, and pass multi-season holdout
tests against the frozen V3 baseline.
