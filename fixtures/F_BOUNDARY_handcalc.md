# F_BOUNDARY: hand calculation (SYNTHETIC)

Worked out by hand before any code ran. The QA checker must match these values
(through `fixtures/F_BOUNDARY_ground_truth.csv`) before it is run on the full dataset.

## Inputs
- R1 (SYNTHETIC): (0,0) -> (0.010,0) -> (0.010,0.005) -> (0.020,0.005), as [lon, lat].
- Z1 (SYNTHETIC): lon 0.006..0.012, lat -0.003..0.003. Boundary counts as inside (B-01).
- Earth radius R = 6,371,000 m (A10). 1 degree = R * pi / 180 = 111,194.92664 m.
- Every segment in this fixture runs along the equator (lat 0) or along the meridian lon 0.010.
  Haversine is exact there: length = R * delta_degrees_in_radians.

## Filters
- Every ping lies on R1, so the off-road distance is 0 m for all 8 pings (A3: kept).
- Fastest segment is S3: 333.585 m in 10 s = 120.09 km/h <= 150 (A4: kept).
- No duplicates. Timestamps strictly increasing, 10 s apart. No warnings.

## Segments
| Seg | From -> to | Full length (m) | Inside Z1 | Inside length (m) | Working |
|---|---|---|---|---|---|
| S1 | P1 (0.005,0) -> P2 (0.006,0) | 111.195 | only the end point P2 (on the west edge) | 0.000 | Inside part is a single point: [0.006, 0.006] has length 0 (TC-08) |
| S2 | P2 (0.006,0) -> P3 (0.007,0) | 111.195 | all (P2 on edge counts as inside) | 111.195 | 0.001 deg * 111194.927 |
| S3 | P3 (0.007,0) -> P4 (0.010,0) | 333.585 | all | 333.585 | 0.003 deg * 111194.927 |
| S4 | P4 (0.010,0) -> P5 (0.010,0.0028) | 311.346 | all | 311.346 | 0.0028 deg * 111194.927 |
| S5 | P5 (0.010,0.0028) -> P6 (0.010,0.0033) | 55.597 | from P5 to the top edge, lat 0.003 | 22.239 | (0.0030 - 0.0028) = 0.0002 deg * 111194.927 (TC-09) |
| S6 | P6 (0.010,0.0033) -> P7 (0.010,0.005) | 189.031 | none (lat > 0.003) | 0.000 | |
| S7 | P7 (0.010,0.005) -> P8 (0.0105,0.005) | 55.597 | none | 0.000 | |

Total inside = (0.001 + 0.003 + 0.0028 + 0.0002) deg = 0.007 deg
= 0.007 * 111194.92664 m = **778.364 m = 0.778364 km** (6 dp).

(The per-segment values rounded to mm add up to 778.365 m. The exact total is 778.36449 m.)

## Day
All pings fall on 2026-11-07 between 01:00Z and 01:01:10Z, which is 10:00 to 10:01 local (UTC+9).
Expected report row: DRV-A, 2026-11-07, 0.778364 km.
