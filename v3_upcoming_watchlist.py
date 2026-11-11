"""Upcoming-game V3 movement watchlist; read-only with respect to frozen locks."""
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cfb_team_matching import canonical_school
from snapshot_capture import utc
from v3_line_movement import summarize, read_snapshots

FIELDS = ["kickoff_utc","away_team","home_team","sportsbook","sportsbook_key",
          "first_home_spread","latest_home_spread","movement_points",
          "severity","crossed_key_numbers","locked_decision","locked_selection",
          "locked_spread","locked_edge","current_edge_at_same_book",
          "edge_change","lock_status","latest_seen_utc"]


def read_locks(root):
    for path in sorted(Path(root).glob("*/*.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            yield from csv.DictReader(f)


def watchlist(movements, locks, now):
    frozen = {}
    for r in locks:
        key=(canonical_school(r.get("home_team","")),
             canonical_school(r.get("away_team","")), r.get("kickoff_utc",""))
        # First lock wins; do not replace frozen decisions.
        frozen.setdefault(key,r)
    out=[]
    for m in movements:
        kickoff=utc(m["kickoff_utc"])
        if not kickoff or kickoff<=now: continue
        key=(canonical_school(m["home_team"]),canonical_school(m["away_team"]),m["kickoff_utc"])
        lock=frozen.get(key)
        decision=lock.get("decision","") if lock else ""
        lock_book=lock.get("sportsbook_key","") if lock else ""
        locked_edge=lock.get("edge_points","") if lock else ""
        current_edge=""
        edge_change=""
        status="NOT_LOCKED"
        if lock:
            status="OTHER_SPORTSBOOK" if lock_book!=m["sportsbook_key"] else "NO_LOCKED_EDGE"
            if lock_book==m["sportsbook_key"] and decision=="PLAY" and locked_edge not in ("",None):
                try:
                    locked_spread=float(lock["spread"])
                    latest_home=float(m["latest_home_spread"])
                    side=lock["selection"]
                    latest_side=latest_home if canonical_school(side)==key[0] else -latest_home
                    updated=float(locked_edge)+(latest_side-locked_spread)
                    current_edge=round(updated,5)
                    edge_change=round(updated-float(locked_edge),5)
                    status=("EDGE_BELOW_3" if updated<3 else
                            "EDGE_IMPROVED" if updated>float(locked_edge) else
                            "EDGE_WEAKENED" if updated<float(locked_edge) else "EDGE_UNCHANGED")
                except (ValueError,TypeError,KeyError):
                    status="MISSING_LOCKED_EDGE"
        if abs(float(m["movement_points"]))<3 and status!="EDGE_BELOW_3":
            continue
        out.append(dict(kickoff_utc=m["kickoff_utc"],away_team=m["away_team"],
                        home_team=m["home_team"],sportsbook=m["sportsbook"],
                        sportsbook_key=m["sportsbook_key"],
                        first_home_spread=m["first_home_spread"],
                        latest_home_spread=m["latest_home_spread"],
                        movement_points=m["movement_points"],severity=m["severity"],
                        crossed_key_numbers=m["crossed_key_numbers"],
                        locked_decision=decision,locked_selection=lock.get("selection","") if lock else "",
                        locked_spread=lock.get("spread","") if lock else "",
                        locked_edge=locked_edge,current_edge_at_same_book=current_edge,
                        edge_change=edge_change,lock_status=status,
                        latest_seen_utc=m["latest_seen_utc"]))
    return sorted(out,key=lambda r:(r["kickoff_utc"],-abs(float(r["movement_points"])),r["sportsbook_key"]))


def main():
    now=datetime.now(timezone.utc)
    movements=summarize(read_snapshots(Path("snapshots")/str(now.year)))
    rows=watchlist(movements,list(read_locks("locks")),now)
    root=Path("reports");root.mkdir(exist_ok=True)
    (root/"v3_upcoming_line_watchlist.json").write_text(json.dumps({
        "generated_at_utc":now.isoformat().replace("+00:00","Z"),
        "warning":"Earliest observed quote is not necessarily true opening line. Current edge uses frozen V3 margin and same sportsbook spread only; no updated injuries or odds price validation.",
        "games":rows},indent=2)+"\n",encoding="utf-8")
    with (root/"v3_upcoming_line_watchlist.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
    print(f"Upcoming line watchlist: {len(rows)} alerts, {sum(r['lock_status']=='EDGE_BELOW_3' for r in rows)} locked PLAY edges below 3")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("\n## Upcoming V3 line movement watchlist\n\n")
            f.write(f"- Alerts: **{len(rows)}**\n")
            f.write(f"- Locked PLAY edges now below 3: **{sum(r['lock_status']=='EDGE_BELOW_3' for r in rows)}**\n")
            for r in rows[:30]:
                f.write(f"- {r['away_team']} at {r['home_team']} ({r['sportsbook']}): "
                        f"{float(r['movement_points']):+g} points; {r['lock_status']}"
                        f"{' (current edge '+str(r['current_edge_at_same_book'])+')' if r['current_edge_at_same_book']!='' else ''}\n")


if __name__=="__main__":
    main()
