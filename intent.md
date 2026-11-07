# intent.md

## Assumptions (decided before coding)
- A1 Road path R1: synthetic polyline, 4 points, label SYNTHETIC. Defined in data/route_R1.json.
- A2 Zone Z1: synthetic polygon, 4 points, label SYNTHETIC. Defined in data/zone_Z1.json.
- A3 Noise if more than 100 m from R1. Exactly 100.000 m is kept (inclusive).
- A4 Noise if implied speed is more than 150 km/h. Exactly 150.0 km/h is kept (inclusive).
- A5 Implied speed is measured from the last accepted ping of the same driver, in timestamp order, using the actual time delta.
- A6 Duplicate = same driver_id and same ts_utc. Keep the first occurrence in file order; log any conflicting coordinates.
- A7 A segment counts toward distance only when both endpoints are inside Z1. No clipping. Known limitation: segments crossing the boundary are under-counted. This is quantified in the analysis (see Problems found).
- A8 A segment belongs to the local day (UTC+9) of its starting ping.
- A9 Irregular intervals are reported as warnings. They do not change distance, because A5 uses actual deltas.
- B-01 Ping exactly on the zone edge is inside (covers).
- Monetary rate per km: out of scope. The brief defines no rate; AC 2 pay amount is not tested.

## Problems found

## Out of scope
- Performance and load testing
- UI and end-to-end testing
- Antimeridian and polar routes
- Daylight saving time (not applicable at UTC+9)
- Monetary amount per km (no rate defined in the brief)