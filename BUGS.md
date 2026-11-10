# BUGS.md: planted bugs in old_reference.py (SYNTHETIC data)

Every bug in `old_reference.py` is wrapped in `if bug("BUG-xx")`. With all of them on, the file
behaves as "the old implementation". With all of them off, it gives the same output as `fixed.py`
on the full dataset; the test suite and `regression_summary.py` both check this.

"Caught by" lists the regression test written for that bug. `results/regression_summary.csv`
records, from an actual run, which tests fail when **only** that bug is switched on.

| Bug | Area | What the old code does | Rule broken | Caught by |
|---|---|---|---|---|
| BUG-01 | Zone | A ping exactly on the zone edge counts as outside | B-01, A7 (covers) | TC-14 `test_TC_14_boundary_ping_is_inside` |
| BUG-02 | Zone | No clipping: the whole segment counts if its start ping is inside, otherwise none of it | A7 | TC-15 `test_TC_15_outside_to_inside_segment_is_clipped`, TC-06 `test_TC_06_outside_zone_distance_excluded` |
| BUG-03 | Distance | Haversine uses the equatorial radius 6,378,137 m instead of 6,371,000 m (all distances +0.11%) | A10 | TC-24 `test_TC_24_long_distance_uses_mean_earth_radius` |
| BUG-04 | Noise | A ping at exactly 100 m from the road is dropped (`>=` instead of `>`) | A3 inclusive | TC-18 `test_TC_18_ping_exactly_100m_off_road_is_kept` |
| BUG-05 | Noise | Off-road pings are logged as noise but still used for distance | A3 | TC-29 `test_TC_29_ping_150m_off_road_excluded` |
| BUG-06 | Noise | Implied speed always assumes a 10 s delta instead of the actual time delta | A5 | TC-24 `test_TC_24_actual_time_delta_used` |
| BUG-07 | Noise | A dropped ping becomes the speed anchor for the next ping | A5 | TC-31 `test_TC_31_speed_anchored_on_last_accepted_ping` |
| BUG-08 | Noise | A ping at exactly 150 km/h is dropped (`>=` instead of `>`) | A4 inclusive | TC-23 `test_TC_23_speed_exactly_150_kept` |
| BUG-09 | Noise | For a too-fast pair, drops the earlier (already accepted) ping and keeps the spike | A4, A5 | TC-30 `test_TC_30_ping_at_160kmh_excluded` |
| BUG-10 | Duplicates | Keeps the last occurrence of a duplicate instead of the first | A6 | TC-33 `test_TC_33_duplicate_first_occurrence_kept` |
| BUG-11 | Duplicates | Dedup key is ts_utc only, so different drivers at the same second are merged | A6 | TC-34 `test_TC_34_same_timestamp_other_driver_not_deduplicated` |
| BUG-12 | Duplicates | Only compares each row with the row directly above it; a duplicate arriving later is kept | A6 | TC-37 `test_TC_37_duplicate_pair_counted_once` |
| BUG-13 | Duplicates | Conflicting coordinates are not logged | A6 | TC-33 `test_TC_33_conflicting_duplicate_is_logged` |
| BUG-14 | Day cut | Local day is the UTC date, not UTC+9 | A8 | TC-43 `test_TC_43_ping_at_17z_goes_to_next_local_day` |
| BUG-15 | Day cut | A segment whose two pings fall on different days is left out of the daily report (still in the driver total) | A8 | TC-53 `test_TC_53_daily_totals_sum_to_driver_totals` |
| BUG-16 | Input | Timestamps without Z are accepted and read as UTC | Timestamp rule, A17 | TC-44 `test_TC_44_timestamp_without_z_rejected` |
| BUG-17 | Order | Pings are processed in file order, not sorted by ts_utc | Late pings rule | TC-49 `test_TC_49_late_ping_placed_by_timestamp` |

## Notes on interactions (seen in actual runs)
- BUG-03 changes every distance, so with BUG-03 alone most km-based tests also fail (the
  +0.11% is larger than the 1 mm test tolerance). The dedicated test is TC-24 (100 km, +112 m).
- With every bug on, BUG-14 hides BUG-15 on F_DAYCUT. UTC dates never change at 15:00Z, so no
  segment "crosses midnight" there. TC-53 therefore runs on the full dataset: DRV-04 and DRV-11
  cross 00:00Z, and that exposes the combination.
- BUG-03 also moves the speed limit. A legitimate 149.9 km/h step (F_NOISE DRV-O, X-06) reads about
  150.07 km/h with the equatorial radius, so old_reference.py with only BUG-03 on drops it as a spike.
- BUG-05 and BUG-09 together turn an off-road ping into a "speed" drop of the *previous* ping,
  so TC-31 also checks the dropped ping's status, not only the km.
