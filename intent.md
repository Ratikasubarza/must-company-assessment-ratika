# intent.md

Source of truth for the rules. All data, geometry and drivers are SYNTHETIC.

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
- P-03 **The day-cut test cases use the wrong clock time.** With UTC+9, local midnight is 15:00Z, not 17:00Z. TC-39 says 17:00:00Z is 00:00 local, but it is 02:00 local; 16:59:59.999Z and 17:00:00Z fall on the same local day. TC-40's segment 16:59:55Z-17:00:05Z does not cross midnight either. RTC-06 calls 16:30Z "00:30 local"; it is 01:30 (the day it names is right). The tests follow A8 and use 14:59:59.999Z / 15:00:00Z. TC-39 also checks that the sheet's 17:00Z pair falls on one day, and TC-43 is unaffected (17:00Z is still the next local day relative to the UTC date). **The sheet should be corrected.**
- P-04 The "Regression Test Cases" tab reuses IDs TC-01..TC-14 for different tests (all of them positive). They are implemented as RTC-01..RTC-14 to avoid the clash.
- P-05 TC-04 ("only one ping inside Z1, then leaves -> 0 km") conflicts with A7. If that inside ping is joined to outside pings, the clipped inside parts of those segments are not 0. The test uses a driver with a single ping (no segment), which gives 0 km.
- P-06 TC-12's vertex (0.006, 0.003) is 333 m from R1, so an end-to-end run drops it as off-road noise before zone logic applies. Tested at the zone-predicate and clipping level. Likewise TC-24 (two pings 100 km apart) cannot happen on R1, which is 2.78 km long, so it uses a SYNTHETIC long road (fixtures/route_LONG.json).
- P-07 TC-46 ("entire file reversed -> same result") interacts with A6, because reversing a file changes which copy of a duplicate comes first. Measured on data/pings.csv (2026-11-10): reversed and original give **identical km** for every driver-day (max difference 0.0). The **events change**: the 8 conflicting duplicates keep the other copy (the DUPLICATE_DROPPED / DUPLICATE_CONFLICT ping ids change), and LATE_ARRIVAL goes from 10 to 2,495, since almost every ping now arrives after a later one. km does not change only because of how this dataset was generated. Conflicting copies are shifted in latitude only, and the 4 kept inside Z1 all lie on R1's north-south leg (lon 0.010), so the shift runs along the road and stays between the neighbouring pings, leaving the path length unchanged. The other 4 are outside Z1. This does not hold in general: reversing fixtures/F_DUPLICATES.csv, where conflicts lie across the east-west leg, changes km (DRV-B 0.177912 -> 0.200151, DRV-E 0.222390 -> 0.259237, DRV-F 0.222390 -> 0.243390). TC-46 runs on the clean dataset and on data/pings.csv, and compares km only.
- P-08 "Exactly 100 m" and "exactly 150 km/h" cannot be represented with decimal coordinates. A12 defines the precision, and the fixtures use the nearest 9-dp coordinate (100.00004 m; 150.0000257 km/h).
- P-09 Test IDs TC-61..TC-65 (checker or pipeline rejects offset, no Z, out of range, missing column; checker --help), TC-66 (149.9 km/h, just under the limit, is kept), TC-67 (10.1 s and 9.99 s intervals inside Z1), TC-68 (negative coordinates), TC-69/TC-70 (same driver, new timestamp, same or new coordinates: not duplicates), TC-71 (impossible time 08:59:99 rejected) and TC-00 (the Step 6 hand-calculation gate) are not in the sheet. Proposed for adding.
- P-10 **GPS jitter while parked is counted as distance** (known limitation, not fixed). No rule filters small movements, so jitter of at most 5 m over 1 hour parked inside Z1 adds 1.655136 km (fixtures/F_PARKED_JITTER.csv, measured with fixed.py on 2026-11-10). TC-05 and TC-28 cover identical coordinates only. NC-01 records the jitter case as a strict expected failure. Fixing it needs a new rule (e.g. a minimum-movement threshold), which is a decision for the rule owner, not something to add silently.

## Out of scope
- Performance and load testing
- UI and end-to-end testing
- Antimeridian and polar routes
- Daylight saving time (not applicable at UTC+9)
- Monetary amount per km (no rate defined in the brief)
