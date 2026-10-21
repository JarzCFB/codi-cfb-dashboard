"""Offline data collection template for V4. Does not fabricate historical observations."""
import csv
from pathlib import Path
from v4_evidence_audit import FEATURES

BASELINE_FIELDS = ("game_id", "season", "kickoff_utc", "captured_at_utc",
                   "source_grading_status", "v3_home_margin", "actual_home_margin")
EVIDENCE_FIELDS = ("game_id", "feature", "value", "source_url",
                   "published_at_utc", "observed_at_utc")

def write_templates(folder="v4/templates"):
    directory = Path(folder)
    directory.mkdir(parents=True, exist_ok=True)
    for name, fields in (("baseline_template.csv", BASELINE_FIELDS),
                         ("evidence_template.csv", EVIDENCE_FIELDS)):
        path = directory / name
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(fields)
    return directory

if __name__ == "__main__":
    location = write_templates()
    print("Created blank V4 collection templates in", location)
    print("Required feature names:", ", ".join(FEATURES))
    print("No evidence, status, or outcome values have been inferred.")
