# directive.md: GPS distance QA tool

**Bottom line:** I fixed the day cut first. It put km on the wrong local day for 10 of 17 driver-days; after the fix, 17 of 17 match ground truth.
The old pipeline, with all 17 bugs, reported 58.872196 km; the correct total is 53.802293 km.

All data, drivers, roads and zones are SYNTHETIC. Repository: https://github.com/Ratikasubarza/must-company-assessment-ratika

Effort: about 6 hours of my own focused time, in short sessions on 7, 8, 10 and 11 Nov 2026. Not counted: time waiting for the AI or the test suite, and slow runs caused by iCloud.

## Objective
Build and verify a QA tool for pay-per-km GPS distance. Drivers send a ping every 10 s and are paid
(advertisers billed) only for km driven inside a campaign zone Z1 along road R1, reported per driver per
local day (cut at 00:00 UTC+9). The tool must show where an old implementation goes wrong, fix it, and prove
the fix with a checker and tests whose numbers all come from real runs.

## Scope
**In scope**
- Seed-42 synthetic dataset (>= 2,000 pings, >= 10 drivers) with ground truth and an injected-fault list
- Fixtures for every scenario in the Test Cases sheet (zone boundary, noise, duplicates, UTC and day cut,
  late pings, interval gaps, invalid input)
- `old_reference.py` with planted bugs BUG-01..BUG-17, `fixed.py` (corrected), `qa_check.py` (checker)
- pytest suite (functional, regression, checker validation), before/after report, per-problem impact,
  measured limitations, run history

**Out of scope**
- Performance and load testing; UI and end-to-end testing
- Antimeridian and polar routes; daylight saving time (not used at UTC+9)
- Money per km (the brief defines no rate)

## Requirements (one rule per line)
1. Pings are nominally every 10 s; irregular intervals are warnings and do not change distance.
2. Only distance inside Z1 counts; segments crossing the edge are clipped at the edge.
3. A point on the zone boundary counts as inside.
4. A ping more than 100 m from R1 is noise; exactly 100 m is kept.
5. A ping implying more than 150 km/h from the last accepted ping is noise; exactly 150 km/h is kept.
6. Duplicate = same driver_id and ts_utc; keep the first in file order; log conflicting coordinates.
7. Timestamps are UTC with a Z suffix; offsets and timestamps without Z are rejected.
8. The daily report is cut at 00:00 UTC+9; a segment belongs to the local day of its starting ping.
9. Each driver's pings are sorted by ts_utc before filtering; late pings are placed by their own timestamp.
10. Every data file is labelled SYNTHETIC.
11. The checker compares per driver per local day within 0.001 km, exits non-zero on failure, supports
    `--help`, and rejects swapped lat/lon, out-of-range coordinates, missing columns, missing Z and offsets.
12. Regression tests fail on old_reference.py and pass on fixed.py; every bug is caught by at least one.
13. Every number in a report comes from an actual run; every added assumption gets an ID in intent.md.

Full rules and assumptions A1-A23: [intent.md](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/intent.md).

## Completion criteria (all measurable)
| # | Criterion | Target |
|---|---|---|
| C1 | `python run_all.py` | exit 0, every step OK |
| C2 | Hand-calculation gate: qa_check on F_BOUNDARY | PASS against 0.778364 km |
| C3 | qa_check on fixed.py, faulty dataset | 0 failed driver-days; fault precision 1.000, recall 1.000 |
| C4 | qa_check on fixed.py, clean dataset | 0 failed driver-days, 0 interval violations |
| C5 | qa_check on old_reference.py | exit 1 (FAIL) |
| C6 | Each planted bug, switched on alone, fails its own regression test | 17 / 17 |
| C7 | Regression checks: fail on old / pass on fixed | 18 / 18 and 18 / 18 |
| C8 | Worst-case regression guards pass on fixed.py | 14 / 14 |
| C9 | pytest | 0 failed |
| C10 | Sheet coverage: docs/test_cases.csv (TC-01..TC-69) and docs/regression_test_cases.csv (RTC-01..RTC-14) | 68 of 69 TC cases covered (62 by a test with the same ID, 6 via the mapping in intent.md); TC-69 on fixed.py only (missing feature in the old code, intent.md P-12); 14 of 14 RTC |
| C11 | Same seed gives the same dataset | sha256 matches the pinned values (TC-59) |
| C12 | No committed file contains a local home-folder path or the user name | 0 files (grep) |

## Appendix: results and handoff

**Run cited:** `20261110T143329Z` on commit `3dd3daf` (branch main): git_dirty = no, overall OK,
pytest 119 passed, 28 xfailed, 5 xpassed. Row in [results/history/runs.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/history/runs.csv);
full log: [run.log](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/history/20261110T143329Z/run.log). Every number below comes from this run.

**Tool, dataset, fix and regression checks**
- Checker: [qa_check.py](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/qa_check.py)
- Dataset (seed 42, 2,525 pings, 12 drivers, 54 injected faults): [data/pings.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/data/pings.csv)
  and its ground truth [data/ground_truth.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/data/ground_truth.csv)
- The day-cut fix in fixed.py: [local_date, UTC+9](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/fixed.py#L74-L76) and
  [each segment takes the day of its starting ping](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/fixed.py#L399)
- Regression checks: [TC-43, BUG-14](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/tests/regression_checks.py#L198-L205) and
  [TC-53, BUG-15](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/tests/regression_checks.py#L208-L218)
- The test-case sheet is in the repository: [docs/test_cases.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/docs/test_cases.csv) ("Test Cases" tab, TC-01..TC-69) and [docs/regression_test_cases.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/docs/regression_test_cases.csv) ("Regression Test Cases" tab; its IDs TC-01..TC-14 are RTC-01..RTC-14 in the tests). The AC tab is not included.

**Checker, fixed vs old** ([qa_fixed](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/qa_fixed/qa_summary.txt),
[qa_old](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/qa_old/qa_summary.txt)):
| | Driver-days failed | Fault detection (54 injected) | Result |
|---|---|---|---|
| fixed.py | 0 of 15 | TP 62, FP 0, FN 0; precision 1.000, recall 1.000 | PASS (exit 0) |
| old_reference.py | 17 of 17 | TP 18, FP 13, FN 44; precision 0.581, recall 0.290 | FAIL (exit 1), as expected |

(TP counts 62 for 54 faults because each of the 8 conflicting duplicates is checked twice: dropped row and conflict log.)

**Totals** ([before_after.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/before_after.csv)): ground truth 53.802293 km,
fixed.py 53.802293 km, old_reference.py (all 17 bugs) 58.872196 km.

**Day-cut fix, before/after** ([daycut_before_after.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/daycut_before_after.csv)):
before = old_reference.py with only BUG-14 and BUG-15 on, after = fixed.py. Total 53.714992 -> 53.802292 km
(ground truth 53.802293 km, summed from six-decimal rows). After = ground truth on 17 of 17 driver-days; 10 of 17
driver-days change by more than 1 m. The +0.087300 km is DRV-11's km that were missing from every daily report
before the fix. Per local day (before -> after): 2026-11-07 16.886616 -> 14.953739; 2026-11-08 20.773015 ->
19.660590; 2026-11-09 11.865322 -> 9.891504; 2026-11-10 4.190039 -> 9.296460.

**Why the day cut first** ([problem_impact.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/problem_impact.csv)): with only
BUG-14/15 on, gross km wrong is 20.081898 km over 10 of 17 driver-days (next: noise, 2.269227 km over 5 of 15).
Ranking, reasoning and per-problem evidence: [intent.md, "Ranking and choice"](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/intent.md#ranking-and-choice).

**pytest** ([test_results.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/test_results.csv)): 119 passed, 28 xfailed, 5 xpassed
(run 20261110T143329Z). The 28 xfailed are
18 bug-regression tests on old_reference (must fail), 9 guards on old_reference (recorded only) and NC-01 (known
limitation). The 5 xpassed are guards that old_reference happens to pass.

**Bugs and regression** ([BUGS.md](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/BUGS.md),
[regression_summary.md](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/regression_summary.md)): 17 of 17 bugs caught alone;
14 of 14 guards pass on fixed.py.

**Open items for the next owner**
- The Test Cases sheet puts local midnight at 17:00Z ([TC-39 and TC-40](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/docs/test_cases.csv#L40-L41); [RTC-06](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/docs/regression_test_cases.csv#L7)); under UTC+9 it is 15:00Z
  (intent.md P-03). The sheet should be corrected.
- New test IDs not yet in the sheet: TC-00, X-01..X-11, NC-01 (intent.md P-09).
- Measured limitations, not fixed: parked jitter adds 1.655136 km per hour (L01); zig-zag inside 100 m
  counts +312.3% (L02); one bad row withholds all 53.802292 km (L09). All 11:
  [limitations.csv](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/results/limitations.csv), measured by
  [tools/limitations.py](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/tools/limitations.py).
- TC-56 copies only committed files: commit before running `run_all.py`.

**Reproduce:** see [README.md](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/README.md); one command, `python run_all.py`
([run_all.py](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/run_all.py), [tools/problem_impact.py](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/tools/problem_impact.py)).
History of every run: [results/history/](https://github.com/Ratikasubarza/must-company-assessment-ratika/tree/main/results/history).
AI usage log: [AI_LOG.md](https://github.com/Ratikasubarza/must-company-assessment-ratika/blob/main/AI_LOG.md).
