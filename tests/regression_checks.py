"""Regression checks: each one must FAIL on old_reference.py and PASS on fixed.py.

Each check takes an implementation module (fixed or old_reference) and returns
(expected, actual). The caller compares them with `same()`. Every check is
tagged with the TC_ID it implements and the bug(s) it is designed to catch.
TC-57 proves, by switching each bug on by itself, that every bug makes at
least one of its own checks fail.
"""
from __future__ import annotations

from dataclasses import dataclass

from helpers import DATA, KM_TOL, deg_km, driver_km, fx, status

LONG = dict(route_path=fx("route_LONG.json"), zone_path=fx("zone_LONG.json"))


@dataclass
class Check:
    tc_id: str
    name: str
    bugs: tuple
    func: object

    @property
    def doc(self):
        return self.func.__doc__

    @property
    def test_name(self):
        return f"test_{self.tc_id.replace('-', '_')}_{self.name}"

    def evaluate(self, impl):
        try:
            expected, actual = self.func(impl)
        except Exception as exc:  # a crash is a failure, recorded with its message
            return None, f"{type(exc).__name__}: {exc}", False
        return expected, actual, same(expected, actual)


CHECKS: list[Check] = []


def check(tc_id, *bugs):
    def deco(f):
        CHECKS.append(Check(tc_id, f.__name__, bugs, f))
        return f
    return deco


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= KM_TOL
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


# ------------------------------------------------------------------------------- zone
@check("TC-14", "BUG-01")
def boundary_ping_is_inside(impl):
    """Given F_BOUNDARY, ping 2 at lon 0.0060 exactly on the west edge of Z1,
    When the pipeline runs,
    Then ping 2 is flagged inside the zone (B-01, covers)."""
    res = impl.run_file(fx("F_BOUNDARY.csv"))
    return True, res.ping_status[("DRV-A", "2")]["in_zone"]


@check("TC-15", "BUG-02")
def outside_to_inside_segment_is_clipped(impl):
    """Given F_ZONE DRV-I at lon 0.0050 (outside), 0.0065, 0.0080 on R1,
    When the pipeline runs,
    Then only the inside part counts: (0.0080 - 0.0060) deg = 0.222390 km."""
    res = impl.run_file(fx("F_ZONE.csv"))
    return deg_km(0.0020), driver_km(res, "DRV-I")


@check("TC-06", "BUG-02")
def outside_zone_distance_excluded(impl):
    """Given F_ZONE DRV-F: 3 segments inside Z1 along R1, one crossing the top edge (lat 0.0025 -> 0.0035),
    then segments outside Z1,
    When the pipeline runs,
    Then km = inside part only: 0.002 deg east + 0.003 deg north = 0.005 deg = 0.555975 km."""
    res = impl.run_file(fx("F_ZONE.csv"))
    return deg_km(0.0050), driver_km(res, "DRV-F")


# ------------------------------------------------------------------------------ noise
@check("TC-24", "BUG-06")
def actual_time_delta_used(impl):
    """Given F_LONG (long SYNTHETIC road): two DRV-J pings 100 km apart and 2 hours apart (50 km/h),
    When the pipeline runs,
    Then both pings are kept, because speed uses the actual 7200 s delta (A5)."""
    res = impl.run_file(fx("F_LONG.csv"), **LONG)
    return ["ACCEPTED", "ACCEPTED"], [status(res, "DRV-J", 1), status(res, "DRV-J", 2)]


@check("TC-24", "BUG-03")
def long_distance_uses_mean_earth_radius(impl):
    """Given F_LONG: two pings 0.899321606 deg apart on the equator,
    When the pipeline runs,
    Then the distance is 100.000 km with R = 6371 km (A10), not 100.112 km."""
    res = impl.run_file(fx("F_LONG.csv"), **LONG)
    return deg_km(0.899321606), driver_km(res, "DRV-J")


@check("TC-18", "BUG-04")
def ping_exactly_100m_off_road_is_kept(impl):
    """Given F_NOISE DRV-C ping 4 at 100.000 m from R1 (to the mm, A12),
    When the pipeline runs,
    Then ping 4 is kept and not logged as off-road noise (A3 inclusive)."""
    res = impl.run_file(fx("F_NOISE.csv"))
    logged = any(e["event_type"] == "DROPPED_OFFROAD" and e["driver_id"] == "DRV-C" for e in res.events)
    return ("ACCEPTED", False), (status(res, "DRV-C", 4), logged)


@check("TC-29", "BUG-05")
def ping_150m_off_road_excluded(impl):
    """Given F_NOISE DRV-A: 10 pings along R1, ping 5 is 150 m off the road,
    When the pipeline runs,
    Then ping 5 is dropped and km = 9 x 0.0004 deg = 0.400302 km."""
    res = impl.run_file(fx("F_NOISE.csv"))
    return ("DROPPED_OFFROAD", deg_km(0.0036)), (status(res, "DRV-A", 5), driver_km(res, "DRV-A"))


@check("TC-31", "BUG-07")
def speed_anchored_on_last_accepted_ping(impl):
    """Given F_NOISE DRV-L: ping 3 is 355.8 m off road; ping 4 is on road, 180.8 km/h from ping 3
    but 16.0 km/h from ping 2,
    When the pipeline runs,
    Then ping 3 is dropped as off-road, ping 4 is kept, km = 0.0016 deg = 0.177912 km."""
    res = impl.run_file(fx("F_NOISE.csv"))
    return (("DROPPED_OFFROAD", "ACCEPTED", deg_km(0.0016)),
            (status(res, "DRV-L", 3), status(res, "DRV-L", 4), driver_km(res, "DRV-L")))


@check("TC-23", "BUG-08")
def speed_exactly_150_kept(impl):
    """Given F_NOISE DRV-I: ping 3 is 150.000 km/h from ping 2 (to 0.001 km/h, A12),
    When the pipeline runs,
    Then all 5 pings are kept (A4 inclusive)."""
    res = impl.run_file(fx("F_NOISE.csv"))
    return ["ACCEPTED"] * 5, [status(res, "DRV-I", i) for i in range(1, 6)]


@check("TC-30", "BUG-09")
def ping_at_160kmh_excluded(impl):
    """Given F_NOISE DRV-H: ping 3 is 160 km/h from ping 2,
    When the pipeline runs,
    Then ping 3 is dropped, ping 2 is kept, km = 0.0012 deg = 0.133434 km."""
    res = impl.run_file(fx("F_NOISE.csv"))
    return (("ACCEPTED", "DROPPED_SPEED", deg_km(0.0012)),
            (status(res, "DRV-H", 2), status(res, "DRV-H", 3), driver_km(res, "DRV-H")))


# ------------------------------------------------------------------------- duplicates
@check("TC-33", "BUG-10")
def duplicate_first_occurrence_kept(impl):
    """Given F_DUPLICATES DRV-B: ping 3 and ping 103 share a timestamp; 103 comes later in the file
    with a different latitude,
    When the pipeline runs,
    Then ping 3 (first in file order) is kept and km = 0.0016 deg (A6)."""
    res = impl.run_file(fx("F_DUPLICATES.csv"))
    return (("ACCEPTED", "DUPLICATE", deg_km(0.0016)),
            (status(res, "DRV-B", 3), status(res, "DRV-B", 103), driver_km(res, "DRV-B")))


@check("TC-33", "BUG-13")
def conflicting_duplicate_is_logged(impl):
    """Given F_DUPLICATES DRV-B: duplicate pair with conflicting coordinates,
    When the pipeline runs,
    Then exactly one DUPLICATE_CONFLICT entry is logged for DRV-B (A6)."""
    res = impl.run_file(fx("F_DUPLICATES.csv"))
    return 1, sum(e["event_type"] == "DUPLICATE_CONFLICT" and e["driver_id"] == "DRV-B" for e in res.events)


@check("TC-34", "BUG-11")
def same_timestamp_other_driver_not_deduplicated(impl):
    """Given F_DUPLICATES: DRV-C and DRV-D each send pings at 09:00:00Z, 09:00:10Z, 09:00:20Z (adjacent rows),
    When the pipeline runs,
    Then all 6 pings are kept: dedup is per driver."""
    res = impl.run_file(fx("F_DUPLICATES.csv"))
    return ["ACCEPTED"] * 6, [status(res, d, i) for d in ("DRV-C", "DRV-D") for i in (1, 2, 3)]


@check("TC-37", "BUG-12")
def duplicate_pair_counted_once(impl):
    """Given F_DUPLICATES DRV-E: ping 102 duplicates ping 2's timestamp but arrives after ping 4,
    When the pipeline runs,
    Then ping 102 is dropped and km = 5 x 0.0004 deg = 0.222390 km."""
    res = impl.run_file(fx("F_DUPLICATES.csv"))
    return ("DUPLICATE", deg_km(0.0020)), (status(res, "DRV-E", 102), driver_km(res, "DRV-E"))


# --------------------------------------------------------------------------- time
@check("TC-43", "BUG-14")
def ping_at_17z_goes_to_next_local_day(impl):
    """Given F_DAYCUT DRV-C: pings at 2026-11-07T17:00:00Z, 17:00:10Z, 17:00:20Z (02:00 local on 11-08),
    When the pipeline runs,
    Then both segments are reported on local day 2026-11-08 (A8, UTC+9)."""
    res = impl.run_file(fx("F_DAYCUT.csv"))
    rows = {day: km for (d, day), km in res.daily_km.items() if d == "DRV-C"}
    return {"2026-11-08": deg_km(0.0008)}, rows


@check("TC-53", "BUG-15")
def daily_totals_sum_to_driver_totals(impl):
    """Given the full dataset data/pings.csv (shifts that cross 15:00Z and 00:00Z),
    When the pipeline runs,
    Then for every driver the daily rows add up to the driver total."""
    res = impl.run_file(f"{DATA}/pings.csv")
    sums = {}
    for (d, _), km in res.daily_km.items():
        sums[d] = sums.get(d, 0.0) + km
    bad = {d: round(sums.get(d, 0.0) - t, 6) for d, t in res.total_km.items() if abs(sums.get(d, 0.0) - t) > KM_TOL}
    return {}, bad


@check("TC-44", "BUG-16")
def timestamp_without_z_rejected(impl):
    """Given F_INVALID_no_z: line 4 has '2026-11-07 09:00:00' (no Z),
    When the pings are loaded,
    Then the file is rejected with an error naming line 4, and no result is produced."""
    try:
        impl.run_file(fx("F_INVALID_no_z.csv"))
    except Exception as exc:
        return True, "line 4" in str(exc)
    return True, "accepted (no error)"


# ---------------------------------------------------------------------------- order
@check("TC-49", "BUG-17")
def late_ping_placed_by_timestamp(impl):
    """Given F_LATE DRV-A: the 09:00:30 ping is the last row in the file, after the 09:01:00 ping,
    When the pipeline runs,
    Then it is placed by its timestamp: all 7 kept and km = 6 x 0.0004 deg = 0.266868 km."""
    res = impl.run_file(fx("F_LATE.csv"))
    return ((["ACCEPTED"] * 7, deg_km(0.0024)),
            ([status(res, "DRV-A", i) for i in range(1, 8)], driver_km(res, "DRV-A")))


def checks_for_bug(bug_id):
    return [c for c in CHECKS if bug_id in c.bugs]

