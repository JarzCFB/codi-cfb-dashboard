# V4 historical baseline audit in GitHub Actions

The repository already stores frozen V3 selections in
`prospective/graded_selections.csv`. No local Python or Streamlit export
is necessary to audit the **currently recorded V3 selections**.

1. Open **Actions → V4 historical baseline audit**.
2. Choose **Run workflow** on the main branch.
3. Open the completed run's **Summary** for settled/pending counts.
4. Download the **v4-historical-audit** artifact for the recovered V3
   baseline, missing-feature work queue, review queue and JSON summary.

The workflow also runs after changes to the frozen grading CSV or audit
code on main. It uses read-only GitHub permissions and uploads artifacts;
it never commits generated files or changes official selections.

**Scope limitation:** current V3 selected games are from 2026 only.
A historical multi-season all-FBS sample and independent pre-capture
situational evidence are still needed to validate V4. An audit artifact
is not a verified injury feed, a fitted model, or evidence that V4
outperforms V3.
