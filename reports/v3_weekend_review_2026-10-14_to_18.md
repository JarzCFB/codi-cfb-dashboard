# V3 frozen selections — postgame investigation (October 14–18, 2026)

Source: `prospective/graded_selections.csv` on main, joined by `game_id` to `prospective/investigation_cohort.csv`. Only **settled V3** selections with kickoff UTC >= 2026-10-14 and < 2026-10-19. All units assume hypothetical one-unit stakes and the originally frozen odds. This is retrospective exploratory analysis, **not a newly validated selection rule**.

## Weekend result

33 settled V3 selections: **15 wins, 18 losses, 0 pushes; -4.422234 units (-13.40% per selection)**. Season-to-date: 67–52–2, +8.988764 units across 121 settled selections.

## By frozen model edge

| Edge (points) | W–L–P | Net units |
| --- | ---: | ---: |
| 3 to <5 | 7–13–0 | -6.609307 |
| 5 to <7 | 4–4–0 | -0.359872 |
| 7 to <10 | 3–0–0 | +2.637854 |
| 10+ | 1–1–0 | -0.090909 |

For all 121 settled V3 selections: 3 to <5: 30–32–1, -4.750394u; 5 to <7: 24–11–1, +10.950568u; 7 to <10: 10–3–0, +5.974737u; 10+: 3–6–0, -3.186147u.

**Interpretation:** The 3–<5 group contributed 13/18 weekend losses. Do **not** optimize the live threshold using these same observed outcomes. Evaluate a proposed 5-point minimum only as a separately labeled shadow strategy, prospectively and against the unchanged frozen V3 baseline.

## V1/V2 disagreement cohorts

The frozen `investigation_cohort.csv` joins to **27 of 33** weekend settled V3 selections; six have no frozen classification and must stay **UNCLASSIFIED**, not inferred after kickoff.

| Frozen status | Weekend W–L–P | Units |
| --- | ---: | ---: |
| PASS | 11–11–0 | -1.019072 |
| CAUTION | 1–2–0 | -1.090909 |
| UNSTABLE | 1–1–0 | -0.130435 |
| UNCLASSIFIED | 2–4–0 | -2.181818 (derived remainder; verify individual prices before reuse) |

**Important:** Classification coverage is incomplete and status cohorts are small. Neither PASS nor CAUTION implies guaranteed success.

## Notable misses for review

- Missouri +7.5 at Ole Miss: V3 projected Missouri losing by ~2.61, but the recorded home margin was +28; loss with a 10.11-point frozen edge.
- Sam Houston +1.5 vs Western Kentucky: V3 projected Sam Houston by ~4.95, actual home margin -13; loss with 6.45-point edge.
- Baylor -5 vs TCU: V3 projected Baylor by ~8.23, actual home margin -11; loss with 3.23-point edge.
- Bowling Green -6.5 vs Ball State: V3 projected Bowling Green by ~9.63, actual home margin -1; loss with 3.13-point edge.
- Colorado State +11.5 at Texas State: V3 projected Texas State by ~7.59, actual home margin +39; loss with 3.91-point edge.

## Next research checks

1. Diagnose the **six unclassified games** by investigating why the frozen investigation-cohort join lacks them; do not reconstruct a purported pregame classification using final outcomes.
2. Validate team/score joins and division safety for surprising results; flag any anomalies for source inspection rather than silently changing historical grades.
3. Track **shadow-only** performance of thresholds >=5, >=7 and >=10 prospectively, with original odds and pre-kickoff snapshots; compare against the frozen >=3 V3 baseline on the same future games.
4. Examine projection errors and V1/V2 disagreement over multiple future slates; do not promote V4 without independent out-of-sample evidence.
5. Preserve V3's 25% V1 / 75% V2 calibrated formula, existing frozen picks and grading history.

This report does not change official model selection logic or recommend increasing stakes.
