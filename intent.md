# intent.md

Source of truth for the rules. All data, geometry and drivers are SYNTHETIC.

**Context (for reading this file on its own).** Drivers send a GPS ping every 10 s. They are paid, and
advertisers are billed, per km driven inside a campaign zone (Z1) along a road (R1). Both are small
synthetic shapes near latitude 0 (R1 runs from (0, 0) to (0.020, 0.005) in [lon, lat]; Z1 covers lon
0.006-0.012, lat -0.003-0.003). The daily report gives km per driver per local day, cut at 00:00 UTC+9
(15:00 UTC). `fixed.py` is the corrected pipeline; `old_reference.py` is the old pipeline with 17 bugs
planted on purpose (BUG-01..BUG-17); `qa_check.py` checks a pipeline's daily report against ground truth
computed independently by the data generator (seed 42: 2,525 pings, 12 drivers, 54 injected faults).

## Assumptions (decided before coding)
- A1 Road path R1: synthetic polyline, 4 points, label SYNTHETIC. Defined in data/route_R1.json.
- A2 Zone Z1: synthetic polygon, 4 points, label SYNTHETIC. Defined in data/zone_Z1.json.
- A3 Noise if more than 100 m from R1. Exactly 100.000 m is kept (inclusive).
- A4 Noise if implied speed is more than 150 km/h. Exactly 150.0 km/h is kept (inclusive).
- A5 Implied speed is measured from the last accepted ping of the same driver, in timestamp order, using the actual time delta.
- A6 Duplicate = same driver_id and same ts_utc. Keep the first occurrence in file order; log any conflicting coordinates.
- A7 A segment counts toward distance only for the part inside Z1. Segments crossing the boundary are clipped at the edge, and only the inside part is measured. Inside includes the boundary (covers, per B-01). *(Text corrected on 2026-11-08, see P-01.)*
- A8 A segment belongs to the local day (UTC+9) of its starting ping.
- A9 Irregular intervals are reported as warnings. They do not change distance, because A5 uses actual deltas.
- B-01 Ping exactly on the zone edge is inside (covers).
- Monetary rate per km: out of scope. The brief defines no rate; AC 2 pay amount is not tested.
- Pipeline order: A6 dedup, then sort by ts_utc (stable, so file order breaks ties), then A3 off-road filter, then A4 speed filter, then A7 clipping, then A8 day assignment.

## Assumptions added during the build (2026-11-08)
Each one fills a gap the rules above leave open. None of them changes A1-A9 or B-01.
- A10 Distance is great-circle (haversine) with mean Earth radius R = 6,371,000 m. This matches the hand worksheet (0.001 deg = 111.195 m).
- A11 QA tolerance: |pipeline km - ground truth km| <= 0.001 km (1 m) per driver per local day. Reports round km to 6 dp. (No tolerance was defined before; see P-02.) Unit tests use 1 mm, because fixture values are exact.
- A12 Boundary comparisons are made at the precision the rules state: off-road distance rounded to 0.001 m, speed rounded to 0.001 km/h, then compared with `<= 100` and `<= 150`. Decimal coordinates cannot land exactly on 100 m or 150 km/h, so without this "exactly" could never be tested (P-08).
- A13 Off-road distance = shortest distance from the ping to the R1 polyline, in a local equirectangular projection centred on the ping's latitude.
- A14 Clipping: a segment is a straight line in lon/lat. It is split where it crosses a zone edge; each piece whose midpoint is inside (boundary counts) is measured with haversine. On-edge tolerance is 1e-12 deg.
- A15 Daily report: one row per (driver, local day) that has at least one accepted segment starting on that day, even when the inside km is 0. No segment means no row, and the checker reads a missing row as 0 km. Driver totals list every driver in the input (0 if no segment).
- A16 Interval warnings are computed on deduplicated pings sorted by ts_utc, before the noise filters. Any delta other than exactly 10 s is a warning: "gap" if larger, "short" if smaller. Pings dropped as noise do not create warnings.
- A17 Invalid input rejects the whole file (no partial run, no output files). The error lists every bad line by its file line number (header = line 1). Invalid means: a missing required column (driver_id, ping_id, ts_utc, lon, lat), an empty id, a timestamp without Z or with an offset, a non-numeric value, or lon outside [-180, 180] or lat outside [-90, 90]. Extra columns (such as `label`) are allowed.
- A18 Lat/lon swap detection. Pings: rejected if fewer than 50% are within 100 m of R1 as given while at least 50% are after swapping lat and lon. Zone: rejected if R1 does not touch the zone but does touch the swapped zone. The pipeline and the checker both apply these.
- A19 Timestamp format: `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` (upper-case Z). Parsing never reads the machine time zone. Duplicates are matched on the parsed instant, so `09:00:00Z` and `09:00:00.000Z` are the same timestamp.
- A20 A ping is logged LATE_ARRIVAL (information only) if, after dedup, its ts_utc is earlier than a ping of the same driver that came before it in the file.
- A21 The first ping of a driver (in timestamp order) that passes the off-road filter becomes the speed anchor without a speed check. Known limitation: if that ping is itself a spike, later pings are judged against it.
- A22 A duplicate is "conflicting" when lon or lat differs, compared as parsed numbers. Each dropped duplicate row gets a DUPLICATE_DROPPED event; each conflicting group gets one DUPLICATE_CONFLICT event, carrying the kept ping's id.
- A23 Data labelling: every generated CSV has a `label` column with value SYNTHETIC; every JSON geometry file has `"label": "SYNTHETIC"`.

## Problems found
- P-01 **A7 contradicted itself.** It said "clipped at the edge" and, in the same item, "No clipping. Known limitation: segments crossing the boundary are under-counted." The brief, the AC sheet ("Segments crossing the boundary are clipped at the edge") and TC-08/09/10/15 all require clipping. Resolved: clipping, and the "No clipping" remnant was removed from A7. Counting only segments with both ends inside (the "no clipping" reading), F_BOUNDARY gives 0.756126 km instead of 0.778364 km (measured with fixed.py's geometry, not hand-waved).
- P-02 The brief says the checker uses "the tolerance in intent.md", but intent.md had none. Added A11.
- P-03 **The day-cut test cases use the wrong clock time** (rows: `docs/test_cases.csv` line 40 = TC-39, line 41 = TC-40; `docs/regression_test_cases.csv` line 7 = its TC-06, tested as RTC-06). With UTC+9, local midnight is 15:00Z, not 17:00Z. TC-39 says 17:00:00Z is 00:00 local, but it is 02:00 local; 16:59:59.999Z and 17:00:00Z fall on the same local day. TC-40's segment 16:59:55Z-17:00:05Z does not cross midnight either. RTC-06 calls 16:30Z "00:30 local"; it is 01:30 (the day it names is right). The tests follow A8 and use 14:59:59.999Z / 15:00:00Z. TC-39 also checks that the sheet's 17:00Z pair falls on one day, and TC-43 is unaffected (17:00Z is still the next local day relative to the UTC date). **The sheet should be corrected.**
- P-04 The "Regression Test Cases" tab reuses IDs TC-01..TC-14 for different tests (all of them positive). The tab is in the repository as `docs/regression_test_cases.csv`. They are implemented as RTC-01..RTC-14 to avoid the clash.
- P-05 TC-04 ("only one ping inside Z1, then leaves -> 0 km") conflicts with A7. If that inside ping is joined to outside pings, the clipped inside parts of those segments are not 0. The test uses a driver with a single ping (no segment), which gives 0 km.
- P-06 TC-12's vertex (0.006, 0.003) is 333 m from R1, so an end-to-end run drops it as off-road noise before zone logic applies. Tested at the zone-predicate and clipping level. Likewise TC-24 (two pings 100 km apart) cannot happen on R1, which is 2.78 km long, so it uses a SYNTHETIC long road (fixtures/route_LONG.json).
- P-07 TC-46 ("entire file reversed -> same result") interacts with A6, because reversing a file changes which copy of a duplicate comes first. Measured on data/pings.csv (2026-11-10): reversed and original give **identical km** for every driver-day (max difference 0.0). The **events change**: the 8 conflicting duplicates keep the other copy (the DUPLICATE_DROPPED / DUPLICATE_CONFLICT ping ids change), and LATE_ARRIVAL goes from 10 to 2,495, since almost every ping now arrives after a later one. km does not change only because of how this dataset was generated. Conflicting copies are shifted in latitude only, and the 4 kept inside Z1 all lie on R1's north-south leg (lon 0.010), so the shift runs along the road and stays between the neighbouring pings, leaving the path length unchanged. The other 4 are outside Z1. This does not hold in general: reversing fixtures/F_DUPLICATES.csv, where conflicts lie across the east-west leg, changes km (DRV-B 0.177912 -> 0.200151, DRV-E 0.222390 -> 0.259237, DRV-F 0.222390 -> 0.243390). TC-46 runs on the clean dataset and on data/pings.csv, and compares km only.
- P-08 "Exactly 100 m" and "exactly 150 km/h" cannot be represented with decimal coordinates. A12 defines the precision, and the fixtures use the nearest 9-dp coordinate (100.00004 m; 150.0000257 km/h).
- P-09 **Repo-only tests use X-xx IDs.** The sheet (docs/test_cases.csv) uses TC-01..TC-69, so the repo's own extra tests were renamed from TC-61..TC-71 to X-01..X-11 on 2026-11-10 to avoid a clash: X-01..X-05 (checker or pipeline rejects offset, no Z, out of range, missing column; checker --help), X-06 (149.9 km/h, just under the limit, is kept), X-07 (10.1 s and 9.99 s intervals inside Z1), X-08 (negative coordinates), X-09/X-10 (same driver, new timestamp, same or new coordinates: not duplicates), X-11 (impossible time 08:59:99 rejected). TC-00 (the Step 6 hand-calculation gate) is also repo-only; the sheet has no TC-00. Which repo test covers each sheet case TC-61..TC-69 is in the mapping table below.
- P-10 **GPS jitter while parked is counted as distance** (known limitation, not fixed). No rule filters small movements, so jitter of at most 5 m over 1 hour parked inside Z1 adds 1.655136 km (fixtures/F_PARKED_JITTER.csv, measured with fixed.py on 2026-11-10). TC-05 and TC-28 cover identical coordinates only. NC-01 records the jitter case as a strict expected failure. Fixing it needs a new rule (e.g. a minimum-movement threshold), which is a decision for the rule owner, not something to add silently.
- P-11 **A pings file with a header and no rows is accepted, not rejected** (open, needs a rule decision).
  Measured on 2026-11-10: fixed.py exits 0 and writes empty reports (0 driver-day rows); qa_check.py does not
  reject it as input. A 0-byte file is rejected by both (exit 2, no output). Sheet TC-62 expects "explicit error,
  not partial result" for an empty file; the test TC-62 covers the 0-byte case only. Rejecting a header-only file
  would need a change to fixed.py.
- P-12 **TC-69 is covered on fixed.py only** (decided 2026-11-10). The sheet marks TC-69 as a Regression case, but old_reference.py emits no interval warnings at all: 0 INTERVAL_WARNING events on data/pings.csv both with all 17 bugs on and with none (fixed.py: 8). A check that fails on old would therefore fail even with no planted bug, which breaks TC-57's rule that old_reference.py with no bugs passes every regression check. So TC-69 is treated as a missing feature in the old code, not as a planted bug: the 17 bugs, TC-57 and all counts are unchanged, and the sheet's Regression type is not met for this case.

### Sheet cases TC-61..TC-69 and the repo tests that cover them

| Sheet case | Sheet expectation | Covered by |
|---|---|---|
| TC-61 | abs(lat) > 90 or abs(lon) > 180 rejected | X-03: `test_TC_60_and_X_01_X_03_X_04_pipeline_rejects_bad_pings[F_INVALID_range.csv]` (pipeline) and `test_TC_60_and_X_01_to_X_04_X_11_checker_rejects_bad_input[...X-03...]` (checker); the fixture has lat 91.0 and lon -181.5 |
| TC-62 | missing column or empty file: explicit error, no partial result | `test_TC_62_empty_pings_file_explicit_error_no_partial_result`, `test_TC_62_checker_rejects_empty_pings_file` (0-byte file); X-04 (missing column). Header-only file: not covered, see P-11 |
| TC-63 | checker on data with a known injected fault reports it | `test_TC_55_each_injected_fault_flagged_with_precision_recall` (all 54 injected faults) |
| TC-64 | generated route without faults: every interval exactly 10 s | `test_RTC_10_generated_intervals_are_exactly_10s` |
| TC-65 | one 30 s gap (two pings missing): warning; distance uses the actual delta | `test_RTC_14_irregular_intervals_do_not_change_distance`; `test_TC_67_irregular_driver_does_not_affect_regular_driver` (warning on DRV-B ping 7); `test_TC_24_actual_time_delta_used` |
| TC-66 | one 5 s interval: warning, not error | `test_RTC_14_irregular_intervals_do_not_change_distance`; `test_RTC_13_interval_summary_per_driver` (short = 1); `test_TC_67_...` (warning on DRV-B ping 13) |
| TC-67 | A regular, B irregular: warnings per driver, A unaffected | `test_TC_67_irregular_driver_does_not_affect_regular_driver` |
| TC-68 | injected 30 s gap in ground truth appears in the violation list | `test_RTC_11_injected_gap_in_violation_list` |
| TC-69 | regression: a 30 s gap is reported as a warning | On fixed.py: RTC-14, RTC-11, TC-67. Not a regression check: old_reference.py has no interval warnings at all (0 with all bugs on and with none), so this is a missing feature, not a planted bug. Decision: covered on fixed.py only (see P-12) |

## Ranking and choice

All numbers in this section were measured on 2026-11-10 by `python tools/problem_impact.py` and
`python tools/limitations.py` (both run by `python run_all.py`), on the seed-42 dataset `data/pings.csv`.
Method: for each problem group, old_reference.py runs with **only that group's bugs on**, and is compared
with old_reference.py with **no bugs on**. The latter gives exactly the same daily km as fixed.py
(checked by the script: `baseline check: old_reference with no bugs == fixed.py daily km: True`).
Baseline total: 53.802292 km (sum of unrounded daily km; the sum of the six-decimal report rows is 53.802293 km).
"Driver-days wrong" counts driver-days off by more than 1 m (0.001 km), out of the **union** of driver-days
present in either output (17 when a group moves km onto days the baseline does not have, otherwise 15).

### Ranking

Ranking rule (mine): km wrong per driver per local day, because the daily report is what advertisers pay and
drivers get paid on. Measured as **gross km wrong** = the sum over driver-days of |km reported - correct km|.
Ties go to whatever hurts both sides (there were no ties). "Over" = km billed to the advertiser on a
driver-day where they were not driven; "under" = km missing from a driver-day the driver did drive.

| Rank | Problem | Bugs | Gross km wrong | Total change | Over / under (km) | Driver-days wrong | Who's hurt |
|---|---|---|---|---|---|---|---|
| 1 | Day cut | BUG-14, BUG-15 | 20.081898 | -0.087300 km (-0.16%): km driven but missing from every daily report (DRV-11, 0.087300 km; still in the driver total), so the driver is unpaid for them (BUG-15) | 9.997299 / 10.084599 | 10 of 17 | Both: advertiser billed on the wrong day, driver sees 0 km on a day driven |
| 2 | Noise | BUG-04..BUG-09 | 2.269227 | +2.269227 km (+4.22%) | 2.269227 / 0 | 5 of 15 | Advertiser (pays for noise) |
| 3 | Late pings | BUG-17 | 1.325634 | +1.325634 km (+2.46%) | 1.325634 / 0 | 2 of 15 | Advertiser |
| 4 | Zone boundary | BUG-01, BUG-02 | 0.907773 | -0.395253 km (-0.73%) | 0.256260 / 0.651513 | 14 of 15 | Both, mostly drivers (under-paid) |
| 5 | Duplicates | BUG-10..BUG-13 | 0.070231 | +0.070231 km (+0.13%) | 0.070231 / 0 | 1 of 15 | Advertiser |
| 6 | Earth radius | BUG-03 | 0.060271 | +0.060271 km (+0.11%) | 0.060271 / 0 | 15 of 15 | Advertiser (every km +0.11%) |
| 7 | No-Z input | BUG-16 | 0 | 0 km | 0 / 0 | 0 of 15 | None on this data (every timestamp has Z); the old code accepts a file the rules reject |
| - | All 17 bugs together | BUG-01..BUG-17 | 24.569582 | +5.069904 km (+9.42%) | 14.819743 / 9.749839 | 17 of 17 | Both |

Worst driver-day per group: day cut DRV-10 2026-11-10 (-3.249215 km); noise DRV-07 2026-11-09 (+0.710600);
late pings DRV-01 2026-11-07 (+0.964148); zone boundary DRV-09 2026-11-09 (-0.328781); duplicates
DRV-03 2026-11-07 (+0.070231); Earth radius DRV-11 2026-11-10 (+0.006774).

Two things the rule choice hides, measured from the same table: counted by number of driver-days wrong,
Earth radius (15) and zone boundary (14) would rank above the day cut (10); and per *affected* driver-day,
late pings (1.325634 / 2 = 0.66 km) would rank above noise (2.269227 / 5 = 0.45 km).

### Why the day cut is fixed first

Why I fixed the day cut first: I ranked the problems by km wrong per driver per local day, because the daily report, cut at 00:00 UTC+9, is what advertisers are billed on and drivers are paid on. On that measure the day cut is the biggest problem by far: with only BUG-14/15 on, 10 of 17 driver-days are wrong, and about 10 km of the 53.8 km land on the wrong day. The total barely moves, which is exactly why it's easy to miss if you only check totals.

It also hurts both sides at once. The advertiser is billed for km on a day they didn't happen. The driver sees 0 km for a day they actually drove (DRV-03 on 2026-11-08). And it's systematic, not random: every shift that runs past 15:00Z gets it wrong, every night.

Noise came second. It's the problem that adds the most to what the advertiser pays overall (+2.27 km, +4.2%), but it hit 5 driver-days, compared with 10 for the day cut, and mainly one party. The root cause of the day cut is also a single line, the UTC date used instead of UTC+9, so the fix is small, easy to verify, and the before/after makes it obvious.

### How each problem was found

The 17 bugs were **planted on purpose**, as the brief requires, to test the QA tool. The checker found them
without knowing about them: `qa_check.py` imports neither pipeline. It only compares a daily report with
the generator's ground truth and the injected-fault list. For each group: the qa_check FAIL row (old with only
that group on, checked against ground truth), the attribution in before_after.csv (old with all bugs vs fixed,
naming every bug that moves that row), and the ping_status / events rows that change. One real driver-day each:

| Problem | Driver-day | qa_check FAIL row (expected / actual / diff) | before_after.csv attribution | ping_status / events evidence |
|---|---|---|---|---|
| Day cut | DRV-10 2026-11-10 | 3.249215 / 0.000000 / -3.249215; RESULT: FAIL (10 failures) | BUG-02; BUG-03; BUG-14 | pings 89, 90, 91: local_date 2026-11-10 -> 2026-11-09 |
| Noise | DRV-07 2026-11-09 | 3.045302 / 3.755902 / +0.710600; FAIL (5) | BUG-02; BUG-03; BUG-05; BUG-14 | pings 75, 158: DROPPED_OFFROAD -> ACCEPTED |
| Late pings | DRV-01 2026-11-07 | 2.742678 / 3.706826 / +0.964148; FAIL (2) | BUG-02; BUG-03; BUG-05; BUG-09 (combined); BUG-12 (combined); BUG-17 | no status change: same pings joined in file order instead of time order |
| Zone boundary | DRV-09 2026-11-09 | 4.571235 / 4.242454 / -0.328781; FAIL (14) | BUG-02; BUG-03; BUG-09 (combined) | no status change: segments counted whole by start ping instead of clipped |
| Duplicates | DRV-03 2026-11-07 | 1.144128 / 1.214358 / +0.070230; FAIL (1) | BUG-02; BUG-03; BUG-12; BUG-14; BUG-15; BUG-17 | pings 10001, 10002: DUPLICATE -> ACCEPTED; events DUPLICATE_DROPPED 2 -> 0, DUPLICATE_CONFLICT 1 -> 0 |
| Earth radius | DRV-11 2026-11-10 | 6.047244 / 6.054019 / +0.006775; FAIL (15) | BUG-02; BUG-03; BUG-05; BUG-12 (combined); BUG-14; BUG-17 (combined) | no status change: every length x 6,378,137 / 6,371,000 |
| No-Z input | (none in data/pings.csv) | RESULT: PASS (0 failures) on data/pings.csv | - | fixtures/F_INVALID_no_z.csv: old_reference exit 0 with BUG-16 on (file accepted), exit 2 with no bugs (rejected) |

(The qa_check diff for duplicates, +0.070230, differs from +0.070231 in the ranking table by rounding: qa_check
compares the six-decimal report.)

### Before / after for the day-cut fix

Before = old_reference.py with **only** BUG-14 and BUG-15 on. After = fixed.py. Ground truth = the generator's
expected km. km per driver per local day; a driver-day missing from an output counts as 0 km (A15):

| Driver | Local day | Before | After | Ground truth | Change | After = ground truth |
|---|---|---|---|---|---|---|
| DRV-01 | 2026-11-07 | 2.742678 | 2.742678 | 2.742678 | 0 | yes |
| DRV-02 | 2026-11-07 | 5.383819 | 5.383819 | 5.383819 | 0 | yes |
| DRV-03 | 2026-11-07 | 2.305486 | 1.144128 | 1.144128 | -1.161358 | yes |
| DRV-03 | 2026-11-08 | 0 | 1.161358 | 1.161358 | +1.161358 | yes |
| DRV-04 | 2026-11-07 | 0.771518 | 0 | 0 | -0.771518 | yes |
| DRV-04 | 2026-11-08 | 1.541420 | 2.312939 | 2.312939 | +0.771518 | yes |
| DRV-05 | 2026-11-08 | 5.286504 | 5.286504 | 5.286504 | 0 | yes |
| DRV-06 | 2026-11-08 | 3.832871 | 3.832871 | 3.832871 | 0 | yes |
| DRV-07 | 2026-11-08 | 4.133871 | 1.088569 | 1.088569 | -3.045302 | yes |
| DRV-07 | 2026-11-09 | 0 | 3.045302 | 3.045302 | +3.045302 | yes |
| DRV-08 | 2026-11-08 | 5.978349 | 5.978349 | 5.978349 | 0 | yes |
| DRV-09 | 2026-11-09 | 4.571235 | 4.571235 | 4.571235 | 0 | yes |
| DRV-10 | 2026-11-09 | 5.524182 | 2.274967 | 2.274967 | -3.249215 | yes |
| DRV-10 | 2026-11-10 | 0 | 3.249215 | 3.249215 | +3.249215 | yes |
| DRV-11 | 2026-11-09 | 1.769905 | 0 | 0 | -1.769905 | yes |
| DRV-11 | 2026-11-10 | 4.190039 | 6.047244 | 6.047244 | +1.857205 | yes |
| DRV-12 | 2026-11-07 | 5.683115 | 5.683115 | 5.683115 | 0 | yes |

After = ground truth on 17 of 17 driver-days; 10 of 17 change by more than 1 m.

Per-driver subtotals (before / after / ground truth): every driver is unchanged except DRV-11,
5.959944 / 6.047244 / 6.047244 (+0.087300): the km that were missing from every daily report.
DRV-01 2.742678; DRV-02 5.383819; DRV-03 2.305486; DRV-04 2.312939; DRV-05 5.286504; DRV-06 3.832871;
DRV-07 4.133871; DRV-08 5.978349; DRV-09 4.571235; DRV-10 5.524182; DRV-12 5.683115 (same before and after).

| Local day | Before | After | Ground truth | Change |
|---|---|---|---|---|
| 2026-11-07 | 16.886616 | 14.953739 | 14.953740 | -1.932876 |
| 2026-11-08 | 20.773015 | 19.660590 | 19.660590 | -1.112425 |
| 2026-11-09 | 11.865322 | 9.891504 | 9.891504 | -1.973818 |
| 2026-11-10 | 4.190039 | 9.296460 | 9.296459 | +5.106421 |
| **Total** | **53.714992** | **53.802292** | **53.802293** | **+0.087300** |

Day subtotals for "after" and ground truth can differ by 0.000001 km because ground truth is stored rounded
to six decimals per row; every driver-day matches. Context: with the other 15 bugs also on, removing BUG-14/15
moves the total 58.872196 -> 58.959594 km.

### What I left out (measured, not fixed)

Measured by `tools/limitations.py` on fixed.py with small SYNTHETIC inputs; written to `results/limitations.csv`.
None is a pytest test except L01, which is also NC-01 (`xfail(strict=True)`).

| ID | Limitation | Scenario | Measured | Compared with |
|---|---|---|---|---|
| L01 | Parked GPS jitter is counted | parked 1 h inside Z1, 361 pings within 5 m of one point | 1.655136 km | true 0 km |
| L02 | Zig-zag inside the 100 m corridor is counted in full | 10 pings 0.0004 deg apart, alternating 89 m either side of R1, all kept | 1.650486 km | 0.400302 km along the road (+312.3%) |
| L03 | A 3-hour gap is bridged as a straight line | (0.0070, 0) then, 3 h later, (0.0100, 0.0025); accepted | 0.434230 km | 0.611572 km shortest along-road route; real route unknown |
| L04 | A spike on the first ping becomes the speed anchor | first ping at R1's far end, then 10 normal pings in Z1; 3 valid pings dropped | 0.817166 km | 0.400302 km without the spike |
| L05 | A duplicate whose first copy is noise loses the good copy | corner ping sent twice; first copy 167 m off road | 0.189822 km | 0.222390 km if the good copy were kept |
| L06 | A segment crossing local midnight goes wholly to the start day | 14:59:55Z -> 15:00:05Z segment of 0.044478 km | 0.022239 km booked on the previous day | in data/pings.csv all 3 crossing segments end exactly at 15:00:00Z, so 0 km there |
| L07 | A (0,0) "null island" fix lies on R1 | distance from (0,0) to R1 | 0.0 m off road | near R1's start such a ping is ACCEPTED; inside Z1 only the speed filter drops it |
| L08 | All geometry and tests sit at latitude 0 | F_BOUNDARY, R1 and Z1 moved to lat 60 N | 0.0 km difference | fixed.py 0.555975 km = independent calculation 0.555975 km; the test suite never covers this |
| L09 | One bad row rejects the whole file | Z removed from 1 of 2,525 rows | 53.802292 km withheld | all 12 drivers held back by one row |
| L10 | Late pings after the daily cut change a reported day | DRV-03's last 6 pings before 15:00Z arrive after the report | +0.031366 km | no restatement or versioning of a published day |
| L11 | The checker needs generator ground truth | correct fixed.py output vs a ground truth with no km rows | exit 1, 15 of 15 rows fail | real data has no ground truth to check against |

## Out of scope
- Performance and load testing
- UI and end-to-end testing
- Antimeridian and polar routes
- Daylight saving time (not applicable at UTC+9)
- Monetary amount per km (no rate defined in the brief)
