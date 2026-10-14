# V4 baseline audit using repository records

The repository already contains frozen V3 selections at
`prospective/graded_selections.csv`. No Streamlit export is necessary.

To produce a read-only local report from a repository checkout:

```bash
python v4_repo_baseline.py --output-dir v4_audit_output
```

The report contains a recovered V3 CSV, missing-feature work queue,
source-review queue, and readiness summary. The original prospective
selections remain untouched.

**GitHub Actions automation is not yet installed.** The proposed
workflow could not be committed; do not expect an Actions button or
automatic artifacts from this change.

This is a single-season selection sample, not a representative all-FBS
training set. Independent pre-capture evidence and earlier seasons
remain necessary before V4 calibration.
