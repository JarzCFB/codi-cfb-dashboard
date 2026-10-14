# V4 point-in-time evidence collection plan

`collection_plan(baseline, evidence)` accepts the same recovered V3
baseline and feature evidence as the strict `audit_evidence` module.
It returns one task per missing game/feature, prioritizing settled
games, and `collection_plan_csv(plan)` exports a manual research checklist.

Required historical features: quarterback out differential, key-player
out differential, rest differential, travel differential, wind, neutral site.

For each item, independently authenticate its source, the value, and the
publication/observation times *before the archived V3 capture time*.
Do not treat a URL, timestamp, or absence of an injury report as proof.

No V3 records are modified, no features are imputed, and V4 is never
released or used for official picks by this module.

Run `python -m unittest test_v4_collection_plan test_v4_evidence_audit`.
