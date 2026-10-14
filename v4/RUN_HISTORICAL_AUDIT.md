# Run V4 historical evidence audit locally

This is the operational entry point for existing V4 research safeguards.
It does not train a model, scrape injury reports, or touch V3 selections.

```bash
python v4_audit_cli.py --baseline path/to/recovered_v3.csv --output-dir v4_audit_output
python v4_audit_cli.py --baseline path/to/recovered_v3.csv --evidence path/to/evidence.csv --output-dir v4_audit_output
python v4_audit_cli.py --baseline path/to/recovered_v3.csv --evidence path/to/evidence.csv --reviews path/to/reviewed.csv --output-dir v4_audit_output
```

Input: original V3 prospective ATS audit or recovered baseline CSV.
Evidence is optional; without it all six features per game are unknown.
Review worksheets must come from the generated review queue; do not edit
original claim fields.

Outputs: `v4_audit_summary.json` (counts and readiness gates),
`v4_missing_evidence.csv` (manual collection tasks), and
`v4_source_review_queue.csv` (human provenance review queue).

Inputs are validated before any output is written. The CLI does not
certify URLs or historical source timestamps. Manual review remains
unverified, all calibration/release gates remain closed, and V3 is
unchanged.

Run `python -m unittest test_v4_audit_cli`.
