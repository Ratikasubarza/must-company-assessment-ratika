"""Functional group: runs on fixed.py only. Test names carry the TC_ID from the Test Cases tab
(TC-xx) or from the 'Regression Test Cases' tab (RTC-xx; that tab reuses TC-01..14 for
different tests, see intent.md P-04). Expected values are worked out by hand in each docstring.
"""
import csv
import filecmp
import functools
import math
import os
import subprocess
import sys

import pytest

import fixed
from helpers import DATA, DEG_M, KM_TOL, ROOT, deg_km, driver_km, fx, hav, path_inside_km, status

pytestmark = pytest.mark.functional
IMPL = "fixed"


@functools.lru_cache(maxsize=None)
def run(name, **kw):
    path = name if os.path.isabs(name) else fx(name)
    return fixed.run_file(path, **kw)


def close(a, b, tol=KM_TOL):
    return abs(a - b) <= tol


def events(res, etype, driver=None):
    return [e for e in res.events if e["event_type"] == etype and (driver is None or e["driver_id"] == driver)]


# ----------------------------------------------------------------------- A. Inside zone
def test_TC_01_full_in_zone_route_total(record):
    """Given F_ZONE DRV-A: 20 pings every 10 s along R1 from lon 0.0062 to 0.0100, all inside Z1,
    When the pipeline runs,
    Then total km = sum of the 19 segment lengths = 19 x 0.0002 deg = 0.422541 km."""
    res = run("F_ZONE.csv")
    seg_sum = sum(s["length_m"] for s in res.segments if s["driver_id"] == "DRV-A") / 1000
    record("TC-01", IMPL, (deg_km(0.0038), deg_km(0.0038)), (driver_km(res, "DRV-A"), seg_sum))
    assert close(driver_km(res, "DRV-A"), deg_km(0.0038)) and close(seg_sum, deg_km(0.0038))


def test_TC_02_driver_totals_are_separate(record, tmp_path):
    """Given F_ZONE DRV-A (01:00Z) and DRV-B (03:00Z) both on R1 inside Z1 on local day 2026-11-07,
    When the pipeline runs on the whole file and on DRV-B's rows alone,
    Then DRV-A = 0.0038 deg, DRV-B = 0.0018 deg = 0.200151 km, and DRV-B is the same either way."""
    res = run("F_ZONE.csv")
    rows = list(csv.DictReader(open(fx("F_ZONE.csv"))))
    only_b = tmp_path / "b.csv"
    with open(only_b, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(r for r in rows if r["driver_id"] == "DRV-B")
    b_alone = fixed.run_file(str(only_b)).total_km["DRV-B"]
    exp = (deg_km(0.0038), deg_km(0.0018), deg_km(0.0018))
    act = (driver_km(res, "DRV-A"), driver_km(res, "DRV-B"), b_alone)
    record("TC-02", IMPL, exp, act)
    assert all(close(a, b) for a, b in zip(exp, act))


def test_TC_03_route_entirely_outside_zone_is_zero(record):
    """Given F_ZONE DRV-C: 10 pings on R1's last leg (lat 0.005), outside Z1,
    When the pipeline runs,
    Then DRV-C has 0 km."""
    res = run("F_ZONE.csv")
    record("TC-03", IMPL, 0.0, driver_km(res, "DRV-C"))
    assert driver_km(res, "DRV-C") == 0.0


def test_TC_04_single_inside_ping_gives_zero_and_no_error(record):
    """Given F_ZONE DRV-D: a single ping inside Z1 and no other ping (see intent.md P-05),
    When the pipeline runs,
    Then DRV-D total is 0 km, there is no daily row, and no error."""
    res = run("F_ZONE.csv")
    rows = [k for k in res.daily_km if k[0] == "DRV-D"]
    record("TC-04", IMPL, (0.0, []), (driver_km(res, "DRV-D"), rows))
    assert driver_km(res, "DRV-D") == 0.0 and rows == []


def test_TC_05_parked_one_hour_identical_coordinates_only_is_zero(record):
    """Given F_ZONE DRV-E: parked at (0.0080, 0) inside Z1, 361 pings over 1 hour, all with IDENTICAL coordinates,
    When the pipeline runs,
    Then 0 km and all 361 pings kept.
    Scope: identical coordinates only. Real parked GPS jitters; that case is NC-01 (not filtered, known limitation)."""
    res = run("F_ZONE.csv")
    kept = sum(v["status"] == "ACCEPTED" for k, v in res.ping_status.items() if k[0] == "DRV-E")
    record("TC-05", IMPL, (0.0, 361), (driver_km(res, "DRV-E"), kept))
    assert driver_km(res, "DRV-E") == 0.0 and kept == 361


# --------------------------------------------------------------------- B. Zone boundary
def test_TC_07_ping_on_edge_is_inside(record):
    """Given F_BOUNDARY ping 2 at lon 0.0060, exactly on Z1's west edge,
    When the pipeline runs,
    Then ping 2 is inside (covers, B-01) and kept."""
    st = run("F_BOUNDARY.csv").ping_status[("DRV-A", "2")]
    record("TC-07", IMPL, (True, "ACCEPTED"), (st["in_zone"], st["status"]))
    assert st["in_zone"] is True and st["status"] == "ACCEPTED"


def test_TC_08_outside_to_edge_segment_has_zero_inside_length(record):
    """Given F_BOUNDARY S1: ping 1 (0.0050, outside) to ping 2 (0.0060, on the edge),
    When the pipeline runs,
    Then S1's inside length is 0 m (the inside part is a single point)."""
    seg = next(s for s in run("F_BOUNDARY.csv").segments if s["from_ping"] == "1")
    record("TC-08", IMPL, 0.0, seg["inside_m"])
    assert seg["inside_m"] == 0.0


def test_TC_09_inside_to_outside_segment_clipped_at_top_edge(record):
    """Given F_BOUNDARY S5: ping 5 (lat 0.0028, inside) to ping 6 (lat 0.0033, outside), crossing lat 0.0030,
    When the pipeline runs,
    Then only 0.0002 deg = 22.239 m counts (hand calculation, fixtures/F_BOUNDARY_handcalc.md)."""
    seg = next(s for s in run("F_BOUNDARY.csv").segments if s["from_ping"] == "5")
    record("TC-09", IMPL, round(0.0002 * DEG_M, 3), round(seg["inside_m"], 3))
    assert abs(seg["inside_m"] - 0.0002 * DEG_M) < 1e-6


def test_TC_10_segment_crossing_two_edges_clipped(record):
    """Given F_ZONE DRV-G: a 20 s segment from (0.0055, 0) to (0.0100, 0.0035) that enters through the
    west edge (t = 1/9) and leaves through the top edge (t = 6/7),
    When the pipeline runs,
    Then only the inside part counts: (6/7 - 1/9) x chord = 47/63 x 633.91 m = 0.472916 km."""
    res = run("F_ZONE.csv")
    exp = 47 / 63 * hav(0.0055, 0, 0.0100, 0.0035) / 1000
    record("TC-10", IMPL, exp, driver_km(res, "DRV-G"))
    assert close(driver_km(res, "DRV-G"), exp)


def test_TC_11_multiple_entries_and_exits_add_up(record):
    """Given F_ZONE DRV-H: 10 pings going back and forth across the west edge lon 0.0060 (in, out, in again),
    When the pipeline runs,
    Then inside parts add up: 0.0004+0.0012+0.0008+0.0008+0.0002+0.0012 = 0.0046 deg = 0.511497 km."""
    res = run("F_ZONE.csv")
    record("TC-11", IMPL, deg_km(0.0046), driver_km(res, "DRV-H"))
    assert close(driver_km(res, "DRV-H"), deg_km(0.0046))


def test_TC_12_ping_on_vertex_is_inside(record):
    """Given the Z1 vertex (0.0060, 0.0030) and a segment along the top edge from it to (0.0080, 0.0030),
    When the zone predicate and clipping are applied (the vertex is 333 m from R1, so an end-to-end
    run would drop it as noise; see intent.md P-06),
    Then the vertex is inside and the whole edge segment counts (covers)."""
    zone = fixed.load_zone()
    inside = fixed.in_zone(0.006, 0.003, zone)
    length = fixed.inside_length_m((0.006, 0.003), (0.008, 0.003), zone)
    exp = hav(0.006, 0.003, 0.008, 0.003)
    record("TC-12", IMPL, (True, round(exp, 6)), (inside, round(length, 6)))
    assert inside and abs(length - exp) < 1e-6


def test_TC_13_swapped_zone_file_rejected(record):
    """Given fixtures/zone_Z1_swapped.json (Z1 with [lat, lon] instead of [lon, lat]),
    When the zone is loaded,
    Then it is rejected with an error and no run starts."""
    with pytest.raises(fixed.InputError) as ei:
        fixed.run_file(fx("F_BOUNDARY.csv"), zone_path=fx("zone_Z1_swapped.json"))
    record("TC-13", IMPL, "InputError mentioning swapped", str(ei.value).splitlines()[-1].strip())
    assert "swapped" in str(ei.value)


# ------------------------------------------------------------------------- C. GPS noise
def test_TC_16_ping_150m_off_road_dropped(record):
    """Given F_NOISE DRV-A: ping 5 is 150 m off R1 mid-route,
    When the pipeline runs,
    Then ping 5 is dropped and km = 0.0036 deg = 0.400302 km (straight line without it)."""
    res = run("F_NOISE.csv")
    act = (status(res, "DRV-A", 5), driver_km(res, "DRV-A"))
    record("TC-16", IMPL, ("DROPPED_OFFROAD", deg_km(0.0036)), act)
    assert act[0] == "DROPPED_OFFROAD" and close(act[1], deg_km(0.0036))


def test_TC_17_ping_99m_kept_101m_dropped(record):
    """Given F_NOISE DRV-B: ping 3 is 99 m off R1 and ping 6 is 101 m off R1,
    When the pipeline runs,
    Then ping 3 is kept and ping 6 is dropped; km is the clipped path through the kept pings."""
    res = run("F_NOISE.csv")
    rows = [r for r in csv.DictReader(open(fx("F_NOISE.csv"))) if r["driver_id"] == "DRV-B" and r["ping_id"] != "6"]
    exp_km = path_inside_km([(float(r["lon"]), float(r["lat"])) for r in rows])
    act = (status(res, "DRV-B", 3), status(res, "DRV-B", 6), driver_km(res, "DRV-B"))
    record("TC-17", IMPL, ("ACCEPTED", "DROPPED_OFFROAD", exp_km), act)
    assert act[:2] == ("ACCEPTED", "DROPPED_OFFROAD") and close(act[2], exp_km)


def test_TC_19_first_valid_ping_becomes_speed_anchor(record):
    """Given F_NOISE DRV-D: the first ping of the day is 667 m off road (240 km/h from ping 2), the rest on road,
    When the pipeline runs,
    Then ping 1 is dropped, ping 2 is the first accepted ping (no speed check) and pings 2-5 are kept."""
    res = run("F_NOISE.csv")
    act = [status(res, "DRV-D", i) for i in range(1, 6)] + [res.ping_status[("DRV-D", "2")]["speed_kmh"]]
    exp = ["DROPPED_OFFROAD"] + ["ACCEPTED"] * 4 + [None]
    record("TC-19", IMPL, exp, act)
    assert act == exp


def test_TC_20_every_ping_off_road_gives_zero_no_nan(record):
    """Given F_NOISE DRV-E: all 7 pings 445 m off R1 (GPS fault),
    When the pipeline runs,
    Then DRV-E total is 0.0 km (a number, not NaN) and there is no daily row."""
    res = run("F_NOISE.csv")
    tot = driver_km(res, "DRV-E")
    record("TC-20", IMPL, (0.0, False), (tot, any(k[0] == "DRV-E" for k in res.daily_km)))
    assert tot == 0.0 and not math.isnan(tot) and not any(k[0] == "DRV-E" for k in res.daily_km)


def test_TC_21_noise_of_one_driver_does_not_change_another(record):
    """Given F_NOISE DRV-F (all pings off road) and DRV-G (valid) sending at the same timestamps,
    When the pipeline runs,
    Then DRV-G = 5 x 0.0004 deg = 0.222390 km, and DRV-F's pings are all dropped."""
    res = run("F_NOISE.csv")
    f_drop = all(v["status"] == "DROPPED_OFFROAD" for k, v in res.ping_status.items() if k[0] == "DRV-F")
    record("TC-21", IMPL, (deg_km(0.002), True), (driver_km(res, "DRV-G"), f_drop))
    assert close(driver_km(res, "DRV-G"), deg_km(0.002)) and f_drop


def test_TC_22_ping_at_160kmh_dropped(record):
    """Given F_NOISE DRV-H: ping 3 is 160.000 km/h from ping 2 (the last accepted ping),
    When the pipeline runs,
    Then ping 3 is dropped with a DROPPED_SPEED event."""
    res = run("F_NOISE.csv")
    ev = [e for e in events(res, "DROPPED_SPEED", "DRV-H")]
    record("TC-22", IMPL, ("DROPPED_SPEED", ["3"]), (status(res, "DRV-H", 3), [e["ping_id"] for e in ev]))
    assert status(res, "DRV-H", 3) == "DROPPED_SPEED" and [e["ping_id"] for e in ev] == ["3"]


def test_X_06_speed_149_9_kmh_just_below_limit_kept(record):
    """Given F_NOISE DRV-O: ping 3 is 149.9 km/h from ping 2 (0.1 km/h under the A4 limit),
    When the pipeline runs,
    Then all 5 pings are kept, ping 3's speed reads 149.900 km/h, and km = 0.0040 deg = 0.444780 km
    (lon 0.0060 -> 0.0100 along R1, inside Z1). X-06 is a repo-only test, not a sheet case (P-09)."""
    res = run("F_NOISE.csv")
    sts = [status(res, "DRV-O", i) for i in range(1, 6)]
    v = res.ping_status[("DRV-O", "3")]["speed_kmh"]
    exp = (["ACCEPTED"] * 5, 149.9, deg_km(0.0040))
    act = (sts, v, driver_km(res, "DRV-O"))
    record("X-06", IMPL, exp, act)
    assert sts == exp[0] and abs(v - 149.9) < 0.001 and close(act[2], exp[2])


def test_X_07_intervals_10_1s_and_9_99s_inside_zone(record):
    """Given F_ZONE DRV-J: 5 pings inside Z1, 0.0004 deg apart, at 0, 10, 20.1, 30.09, 40.09 s
    (intervals 10, 10.1, 9.99, 10 s),
    When the pipeline runs,
    Then all pings are kept, km = 4 x 0.0004 deg = 0.177912 km (same as a regular 10 s run, A9),
    and exactly two INTERVAL_WARNINGs are logged: 10.1 s (gap) after ping 2, 9.99 s (short) after ping 3.
    X-07 is a repo-only test, not a sheet case (P-09)."""
    res = run("F_ZONE.csv")
    warns = [(e["ping_id"], e["detail"].split(" after")[0]) for e in events(res, "INTERVAL_WARNING", "DRV-J")]
    kept = [status(res, "DRV-J", i) for i in range(1, 6)]
    exp = (["ACCEPTED"] * 5, deg_km(0.0016), [("3", "interval 10.1 s"), ("4", "interval 9.99 s")])
    act = (kept, driver_km(res, "DRV-J"), warns)
    record("X-07", IMPL, exp, act)
    assert kept == exp[0] and close(act[1], exp[1]) and warns == exp[2]


def test_X_08_negative_coordinates(record):
    """Given F_ZONE DRV-K at lon -0.0004, 0, 0.0004 (lat 0; ping 1 is 44.478 m before R1's start, outside Z1)
    and DRV-L at (0.0070, 0), (0.0074, -0.0004), (0.0078, 0), (0.0082, 0) (ping 2 is 44.478 m south of R1,
    inside Z1, which spans lat -0.003..0.003),
    When the pipeline runs,
    Then every ping is kept (all within 100 m); DRV-K = 0 km (outside Z1);
    DRV-L = 2 x diagonal + 0.0004 deg = 2 x 62.901 m + 44.478 m = 0.170281 km, with ping 2 inside Z1.
    X-08 is a repo-only test, not a sheet case (P-09)."""
    res = run("F_ZONE.csv")
    l_pts = [(0.0070, 0.0), (0.0074, -0.0004), (0.0078, 0.0), (0.0082, 0.0)]
    exp_l = path_inside_km(l_pts)
    k_kept = [status(res, "DRV-K", i) for i in (1, 2, 3)]
    l_kept = [status(res, "DRV-L", i) for i in (1, 2, 3, 4)]
    l2_in = res.ping_status[("DRV-L", "2")]["in_zone"]
    exp = (["ACCEPTED"] * 3, 0.0, ["ACCEPTED"] * 4, True, exp_l)
    act = (k_kept, driver_km(res, "DRV-K"), l_kept, l2_in, driver_km(res, "DRV-L"))
    record("X-08", IMPL, exp, act)
    assert act[0] == exp[0] and act[1] == 0.0 and act[2] == exp[2] and l2_in is True and close(act[4], exp_l)
    assert abs(exp_l * 1000 - 170.281) < 0.001  # hand value from the docstring


def test_X_09_same_driver_new_timestamp_same_coordinates_not_duplicate(record):
    """Given F_DUPLICATES DRV-G: pings 1 and 2 at the same coordinates (0.0070, 0) but 10 s apart,
    then ping 3 at (0.0074, 0),
    When the pipeline runs,
    Then no ping is treated as a duplicate (A6 matches on timestamp, not coordinates): all 3 kept,
    no DUPLICATE events, km = 0 (ping 1->2) + 0.0004 deg = 0.044478 km. X-09 is a repo-only test, not a sheet case (P-09)."""
    res = run("F_DUPLICATES.csv")
    dups = [e for e in res.events if e["driver_id"] == "DRV-G" and e["event_type"].startswith("DUPLICATE")]
    seg12 = next(s["inside_m"] for s in res.segments if s["driver_id"] == "DRV-G" and s["from_ping"] == "1")
    exp = (["ACCEPTED"] * 3, 0, 0.0, deg_km(0.0004))
    act = ([status(res, "DRV-G", i) for i in (1, 2, 3)], len(dups), seg12, driver_km(res, "DRV-G"))
    record("X-09", IMPL, exp, act)
    assert act[:3] == exp[:3] and close(act[3], exp[3])


def test_X_10_same_driver_new_timestamp_new_coordinates_not_duplicate(record):
    """Given F_DUPLICATES DRV-H: 3 pings 10 s apart at (0.0070, 0), (0.0074, 0), (0.0078, 0),
    When the pipeline runs,
    Then none is a duplicate: all 3 kept, no DUPLICATE events, km = 0.0008 deg = 0.088956 km.
    X-10 is a repo-only test, not a sheet case (P-09)."""
    res = run("F_DUPLICATES.csv")
    dups = [e for e in res.events if e["driver_id"] == "DRV-H" and e["event_type"].startswith("DUPLICATE")]
    exp = (["ACCEPTED"] * 3, 0, deg_km(0.0008))
    act = ([status(res, "DRV-H", i) for i in (1, 2, 3)], len(dups), driver_km(res, "DRV-H"))
    record("X-10", IMPL, exp, act)
    assert act[:2] == exp[:2] and close(act[2], exp[2])


def test_X_11_invalid_time_08_59_99_rejected_for_both_drivers(record, tmp_path):
    """Given F_INVALID_bad_second: DRV-G (X-09) and DRV-H (X-10) both send a ping stamped
    2026-11-07T08:59:99Z (lines 3 and 5; second 99 does not exist),
    When fixed.py loads it through the CLI,
    Then exit code 2, the error names line 3 and line 5 as invalid date/time, and no output is written.
    X-11 is a repo-only test, not a sheet case (P-09)."""
    out = tmp_path / "out"
    p = subprocess.run([sys.executable, os.path.join(ROOT, "fixed.py"), "--pings", fx("F_INVALID_bad_second.csv"),
                        "--out", str(out)], capture_output=True, text=True)
    act = (p.returncode, "line 3" in p.stderr, "line 5" in p.stderr, "not a valid date/time" in p.stderr, out.exists())
    record("X-11", IMPL, (2, True, True, True, False), act)
    assert act == (2, True, True, True, False), p.stderr


def test_TC_62_empty_pings_file_explicit_error_no_partial_result(record, tmp_path):
    """Given an empty pings file (0 bytes),
    When fixed.py loads it through the CLI,
    Then exit code 2 with an explicit error on stderr, and no output directory is written (no partial result).
    (Sheet TC-62 also names 'missing column', covered by X-04. A file with a header and no rows is accepted
    with 0 rows; that case is not covered here, see intent.md P-11.)"""
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    out = tmp_path / "out"
    p = subprocess.run([sys.executable, os.path.join(ROOT, "fixed.py"), "--pings", str(empty), "--out", str(out)],
                       capture_output=True, text=True)
    act = (p.returncode, "input rejected" in p.stderr, out.exists())
    record("TC-62", IMPL, (2, True, False), act)
    assert act == (2, True, False), p.stderr


def test_TC_67_irregular_driver_does_not_affect_regular_driver(record, tmp_path):
    """Given DRV-A with 13 pings exactly 10 s apart (F_INTERVALS_regular) and DRV-B with the same positions but
    one 30 s gap and one 5 s interval (F_INTERVALS_irregular, renamed DRV-B), interleaved in one file by time,
    When the pipeline runs,
    Then interval warnings are per driver: 0 for DRV-A, 2 for DRV-B (pings 7 and 13); DRV-A's km equals its km
    when run alone, 12 x 0.0003 deg = 0.400302 km."""
    reg = list(csv.DictReader(open(fx("F_INTERVALS_regular.csv"))))
    irr = [dict(r, driver_id="DRV-B") for r in csv.DictReader(open(fx("F_INTERVALS_irregular.csv")))]
    both = tmp_path / "two_drivers.csv"
    with open(both, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(reg[0]))
        w.writeheader()
        w.writerows(sorted(reg + irr, key=lambda r: (r["ts_utc"], r["driver_id"])))
    res = fixed.run_file(str(both))
    alone = fixed.run_file(fx("F_INTERVALS_regular.csv"))
    warn = {d: sorted(e["ping_id"] for e in events(res, "INTERVAL_WARNING", d)) for d in ("DRV-A", "DRV-B")}
    exp = ({"DRV-A": [], "DRV-B": ["13", "7"]}, deg_km(0.0036), deg_km(0.0036))
    act = (warn, driver_km(res, "DRV-A"), driver_km(alone, "DRV-A"))
    record("TC-67", IMPL, exp, act)
    assert act[0] == exp[0] and close(act[1], exp[1]) and close(act[2], exp[2])


def test_TC_25_same_timestamp_different_coordinates_no_division_by_zero(record):
    """Given F_DUPLICATES DRV-B: pings 3 and 103 have the same timestamp and different coordinates,
    When the pipeline runs,
    Then there is no division by zero: the pair is deduplicated first (A6) and no segment has dt = 0."""
    res = run("F_DUPLICATES.csv")
    act = (status(res, "DRV-B", 3), status(res, "DRV-B", 103))
    record("TC-25", IMPL, ("ACCEPTED", "DUPLICATE"), act)
    assert act == ("ACCEPTED", "DUPLICATE")


def test_TC_26_spike_does_not_move_the_anchor(record):
    """Given F_NOISE DRV-K: ping 3 is a spike (201 km/h); pings 4-6 continue the real path,
    When the pipeline runs,
    Then ping 3 is dropped, pings 4-6 are kept (measured from ping 2), km = 0.0016 deg = 0.177912 km."""
    res = run("F_NOISE.csv")
    act = [status(res, "DRV-K", i) for i in range(1, 7)] + [driver_km(res, "DRV-K")]
    exp = ["ACCEPTED", "ACCEPTED", "DROPPED_SPEED", "ACCEPTED", "ACCEPTED", "ACCEPTED", deg_km(0.0016)]
    record("TC-26", IMPL, exp, act)
    assert act[:6] == exp[:6] and close(act[6], exp[6])


def test_TC_27_speed_measured_from_last_accepted_not_dropped_ping(record):
    """Given F_NOISE DRV-L: ping 3 is off road and dropped; ping 4 is 181 km/h from ping 3 but
    0.0008 deg in 20 s = 16.0 km/h from ping 2,
    When the pipeline runs,
    Then ping 4's speed is measured from ping 2 and it is kept."""
    res = run("F_NOISE.csv")
    v = res.ping_status[("DRV-L", "4")]["speed_kmh"]
    exp_v = round(0.0008 * DEG_M / 20 * 3.6, 3)
    record("TC-27", IMPL, ("ACCEPTED", exp_v), (status(res, "DRV-L", 4), v))
    assert status(res, "DRV-L", 4) == "ACCEPTED" and abs(v - exp_v) < 0.001


def test_TC_28_stationary_four_hours_identical_coordinates_only_is_zero(record):
    """Given F_STATIONARY DRV-M: 1441 pings over 4 hours, all with IDENTICAL coordinates (0.0080, 0),
    When the pipeline runs,
    Then all pings are kept and km = 0.
    Scope: identical coordinates only; a jittering stationary GPS is NC-01 (not filtered, known limitation)."""
    res = run("F_STATIONARY.csv")
    kept = sum(v["status"] == "ACCEPTED" for v in res.ping_status.values())
    record("TC-28", IMPL, (1441, 0.0), (kept, driver_km(res, "DRV-M")))
    assert kept == 1441 and driver_km(res, "DRV-M") == 0.0


@pytest.mark.xfail(strict=True, reason="jitter not filtered, known limitation")
def test_NC_01_parked_one_hour_with_5m_jitter_is_zero(record):
    """Given F_PARKED_JITTER DRV-P: parked 1 hour at (0.0080, 0) inside Z1, 361 pings, each up to 5 m from that
    point (GPS jitter, seed 1043),
    When the pipeline runs,
    Then a driver who did not move should get 0 km.
    Known limitation: nothing filters jitter, so the zig-zag between pings is counted (the measured value is in
    the recorded 'actual'). Marked xfail(strict=True): if this ever passes, the suite fails and the marker must go."""
    res = run("F_PARKED_JITTER.csv")
    record("NC-01", IMPL, 0.0, driver_km(res, "DRV-P"))
    assert driver_km(res, "DRV-P") == 0.0


# ------------------------------------------------------------------------- D. Duplicates
def test_TC_32_exact_duplicate_counted_once(record):
    """Given F_DUPLICATES DRV-A: ping 3 sent twice (ping 103, same timestamp and coordinates),
    When the pipeline runs,
    Then it counts once: 103 dropped, km = 4 x 0.0004 deg = 0.177912 km, no conflict logged."""
    res = run("F_DUPLICATES.csv")
    act = (status(res, "DRV-A", 103), driver_km(res, "DRV-A"), len(events(res, "DUPLICATE_CONFLICT", "DRV-A")))
    record("TC-32", IMPL, ("DUPLICATE", deg_km(0.0016), 0), act)
    assert act[0] == "DUPLICATE" and close(act[1], deg_km(0.0016)) and act[2] == 0


def test_TC_33_conflict_first_kept_and_logged(record):
    """Given F_DUPLICATES DRV-B: ping 3 (lat 0) then ping 103 (lat 0.0003) with the same timestamp,
    When the pipeline runs,
    Then ping 3 is kept and one DUPLICATE_CONFLICT entry names both coordinates."""
    res = run("F_DUPLICATES.csv")
    ev = events(res, "DUPLICATE_CONFLICT", "DRV-B")
    act = (status(res, "DRV-B", 3), len(ev), "0.0003" in (ev[0]["detail"] if ev else ""))
    record("TC-33", IMPL, ("ACCEPTED", 1, True), act)
    assert act == ("ACCEPTED", 1, True)


def test_TC_34_same_second_different_drivers_not_deduplicated(record):
    """Given F_DUPLICATES DRV-C and DRV-D both sending at 09:00:00Z, 09:00:10Z and 09:00:20Z,
    When the pipeline runs,
    Then no duplicates are reported for them; DRV-C = DRV-D = 0.0008 deg = 0.088956 km."""
    res = run("F_DUPLICATES.csv")
    d = [e for e in events(res, "DUPLICATE_DROPPED") if e["driver_id"] in ("DRV-C", "DRV-D")]
    act = (len(d), driver_km(res, "DRV-C"), driver_km(res, "DRV-D"))
    record("TC-34", IMPL, (0, deg_km(0.0008), deg_km(0.0008)), act)
    assert act[0] == 0 and close(act[1], deg_km(0.0008)) and close(act[2], deg_km(0.0008))


def test_TC_35_half_duplicates_same_as_deduplicated(record):
    """Given F_DUP_HALF_raw (40 pings, 38 of them sent twice, seed 42) and F_DUP_HALF_dedup (each once),
    When the pipeline runs on both,
    Then the daily totals are identical."""
    raw, ded = run("F_DUP_HALF_raw.csv"), run("F_DUP_HALF_dedup.csv")
    n_raw = sum(1 for _ in open(fx("F_DUP_HALF_raw.csv"))) - 1
    record("TC-35", IMPL, ded.daily_km, raw.daily_km)
    assert raw.daily_km == ded.daily_km and n_raw >= 1.8 * 40


def test_TC_36_duplicate_after_later_ping_still_deduplicated(record):
    """Given F_DUPLICATES DRV-E: ping 102 repeats ping 2's timestamp but arrives after ping 4,
    When the pipeline runs,
    Then ping 102 is dropped as a duplicate (file position does not matter)."""
    res = run("F_DUPLICATES.csv")
    record("TC-36", IMPL, "DUPLICATE", status(res, "DRV-E", 102))
    assert status(res, "DRV-E", 102) == "DUPLICATE"


# ------------------------------------------------------------------ E. UTC and daily cut
def test_TC_38_timestamp_without_z_rejected_naming_the_row(record, tmp_path):
    """Given F_INVALID_no_z: line 4 '2026-11-07 09:00:00' and line 7 '2026-11-07T01:00:50' (no Z),
    When the pings are loaded through the CLI,
    Then exit code 2, the error names line 4 and line 7, and no output is written (no run starts)."""
    out = tmp_path / "out"
    p = subprocess.run([sys.executable, os.path.join(ROOT, "fixed.py"), "--pings", fx("F_INVALID_no_z.csv"),
                        "--out", str(out)], capture_output=True, text=True)
    act = (p.returncode, "line 4" in p.stderr, "line 7" in p.stderr, out.exists())
    record("TC-38", IMPL, (2, True, True, False), act)
    assert act == (2, True, True, False)


def test_TC_39_local_midnight_is_15z(record):
    """Given F_DAYCUT DRV-A pings at 14:59:59.999Z, 15:00:00.000Z, 16:59:59.999Z, 17:00:00.000Z on 2026-11-07,
    When the pipeline runs,
    Then 14:59:59.999Z is local 2026-11-07 and 15:00:00.000Z is 00:00 local 2026-11-08 (UTC+9).
    The sheet's pair (16:59:59.999Z, 17:00Z) are both on 2026-11-08 (01:59 and 02:00 local): see P-03."""
    res = run("F_DAYCUT.csv")
    act = [res.ping_status[("DRV-A", str(i))]["local_date"] for i in range(1, 5)]
    exp = ["2026-11-07", "2026-11-08", "2026-11-08", "2026-11-08"]
    record("TC-39", IMPL, exp, act)
    assert act == exp


def test_TC_40_segment_over_midnight_belongs_to_start_day(record):
    """Given F_DAYCUT DRV-B pings at 14:59:45Z, 14:59:55Z, 15:00:05Z, 15:00:15Z, 0.0004 deg apart
    (the sheet's 16:59:55Z-17:00:05Z does not cross the local midnight; corrected to 15:00Z, P-03),
    When the pipeline runs,
    Then the 14:59:55Z -> 15:00:05Z segment counts on 2026-11-07: 11-07 = 0.0008 deg, 11-08 = 0.0004 deg."""
    res = run("F_DAYCUT.csv")
    act = {d: km for (drv, d), km in res.daily_km.items() if drv == "DRV-B"}
    exp = {"2026-11-07": deg_km(0.0008), "2026-11-08": deg_km(0.0004)}
    record("TC-40", IMPL, exp, act)
    assert act.keys() == exp.keys() and all(close(act[k], exp[k]) for k in exp)


@pytest.mark.parametrize("pings", ["fixtures/F_DAYCUT.csv", "data/pings.csv"])
def test_TC_41_output_independent_of_machine_timezone(record, tmp_path, pings):
    """Given the same input,
    When fixed.py runs three times with TZ=Asia/Shanghai (UTC+8), TZ=UTC and TZ=Asia/Tokyo (UTC+9),
    Then every output file is byte-identical."""
    outs = []
    for tz in ("Asia/Shanghai", "UTC", "Asia/Tokyo"):
        out = tmp_path / tz.replace("/", "_")
        env = dict(os.environ, TZ=tz)
        subprocess.run([sys.executable, os.path.join(ROOT, "fixed.py"), "--pings", os.path.join(ROOT, pings),
                        "--out", str(out)], check=True, capture_output=True, env=env)
        outs.append(out)
    names = sorted(os.listdir(outs[0]))
    same = all(filecmp.cmp(outs[0] / n, o / n, shallow=False) for o in outs[1:] for n in names)
    record("TC-41", IMPL, "identical outputs for UTC+8, UTC, UTC+9", f"identical={same} ({pings})")
    assert same


def test_TC_42_three_local_midnights(record):
    """Given F_DAYCUT DRV-E: 3-ping bursts at 14:59:50Z, 15:00:00Z, 15:00:10Z on 11-07, 11-08, 11-09
    (each step 0.0004 deg; the driver waits in place between bursts),
    When the pipeline runs,
    Then 11-07 = 0.0004, 11-08 = 0.0008, 11-09 = 0.0008, 11-10 = 0.0004 deg and the days add to the total."""
    res = run("F_DAYCUT.csv")
    act = {d: km for (drv, d), km in res.daily_km.items() if drv == "DRV-E"}
    exp = {"2026-11-07": deg_km(0.0004), "2026-11-08": deg_km(0.0008), "2026-11-09": deg_km(0.0008),
           "2026-11-10": deg_km(0.0004)}
    record("TC-42", IMPL, exp, act)
    assert act.keys() == exp.keys() and all(close(act[k], exp[k]) for k in exp)
    assert close(sum(act.values()), driver_km(res, "DRV-E"))


# ---------------------------------------------------------------- F. Late and out of order
def test_TC_45_late_ping_placed_by_own_timestamp(record):
    """Given F_LATE DRV-A: the 09:00:30 ping arrives after the 09:01:00 ping,
    When the pipeline runs,
    Then it is kept, placed between 09:00:20 and 09:00:40, and logged as LATE_ARRIVAL."""
    res = run("F_LATE.csv")
    order = [(s["from_ping"], s["to_ping"]) for s in res.segments if s["driver_id"] == "DRV-A"]
    late = [e["ping_id"] for e in events(res, "LATE_ARRIVAL", "DRV-A")]
    act = (status(res, "DRV-A", 4), ("3", "4") in order and ("4", "5") in order, late)
    record("TC-45", IMPL, ("ACCEPTED", True, ["4"]), act)
    assert act == ("ACCEPTED", True, ["4"])


@pytest.mark.parametrize("name", ["pings_clean.csv", "pings.csv"])
def test_TC_46_reversed_file_gives_same_result(record, tmp_path, name):
    """Given data/pings_clean.csv (no faults) or data/pings.csv (54 injected faults), and the same rows in reverse order,
    When the pipeline runs on both,
    Then the daily km are identical.
    Only km is compared. On the faulty file the events legitimately change (reversal changes which duplicate copy
    is first in file order, and almost every ping becomes a late arrival). km stays equal there only because of how
    the dataset was generated: the kept conflicting copies inside Z1 lie along R1's north-south leg (P-07)."""
    with open(os.path.join(DATA, name)) as fh:
        lines = fh.read().splitlines()
    rev = tmp_path / "rev.csv"
    rev.write_text("\n".join([lines[0]] + lines[1:][::-1]) + "\n")
    a, b = run(os.path.join(DATA, name)), fixed.run_file(str(rev))
    record("TC-46", IMPL, {k: round(v, 9) for k, v in a.daily_km.items()}, {k: round(v, 9) for k, v in b.daily_km.items()})
    assert a.daily_km == b.daily_km


def test_TC_47_late_ping_judged_in_timestamp_order(record):
    """Given F_LATE DRV-B: ping 3 arrives last in the file; in file order it would follow ping 6
    (0.0023 deg away, i.e. a jump back in time),
    When the pipeline runs,
    Then it is judged in timestamp order (44 km/h from ping 2) and kept; km covers all 6 pings."""
    res = run("F_LATE.csv")
    rows = sorted((r for r in csv.DictReader(open(fx("F_LATE.csv"))) if r["driver_id"] == "DRV-B"),
                  key=lambda r: r["ts_utc"])
    exp_km = path_inside_km([(float(r["lon"]), float(r["lat"])) for r in rows])
    act = (status(res, "DRV-B", 3), driver_km(res, "DRV-B"))
    record("TC-47", IMPL, ("ACCEPTED", exp_km), act)
    assert act[0] == "ACCEPTED" and close(act[1], exp_km)


def test_TC_48_late_ping_of_one_driver_interleaved_with_another(record):
    """Given F_LATE: DRV-D rows (one of them late) interleaved with DRV-C rows,
    When the pipeline runs,
    Then each driver is ordered on its own: DRV-C = 0.0020 deg, DRV-D = 0.0010 deg."""
    res = run("F_LATE.csv")
    act = (driver_km(res, "DRV-C"), driver_km(res, "DRV-D"))
    record("TC-48", IMPL, (deg_km(0.002), deg_km(0.001)), act)
    assert close(act[0], deg_km(0.002)) and close(act[1], deg_km(0.001))


# ------------------------------------------------------------- G. Multi-driver reconciliation
def test_TC_50_daily_totals_sum_to_overall_total(record):
    """Given the full dataset data/pings.csv,
    When fixed.py runs,
    Then for each driver the daily km add up to the driver's overall total."""
    res = run(os.path.join(DATA, "pings.csv"))
    sums = {}
    for (d, _), km in res.daily_km.items():
        sums[d] = sums.get(d, 0.0) + km
    worst = max(abs(sums.get(d, 0.0) - t) for d, t in res.total_km.items())
    record("TC-50", IMPL, f"max |sum(daily) - total| <= {KM_TOL} km", f"{worst:.3g} km over {len(res.total_km)} drivers")
    assert worst <= KM_TOL


def test_TC_51_day_with_only_one_driver(record):
    """Given F_DAYCUT: only DRV-F has pings on local day 2026-11-12,
    When the pipeline runs,
    Then that day has exactly one row (DRV-F) and other drivers are absent, not errors (A15)."""
    res = run("F_DAYCUT.csv")
    rows = sorted(d for (d, day) in res.daily_km if day == "2026-11-12")
    record("TC-51", IMPL, ["DRV-F"], rows)
    assert rows == ["DRV-F"]


def test_TC_52_rounding_error_within_tolerance(record, tmp_path):
    """Given the full dataset (about 2,500 segments, 15 driver-day rows),
    When daily km are written rounded to 6 dp and summed,
    Then the difference from the unrounded sum is within the A11 tolerance (0.001 km).
    Margin: the worst possible rounding error is 15 rows x 0.0000005 km = 0.0000075 km, so the tolerance is
    about 133x larger. This test records that bound; it is not expected to catch a defect."""
    res = run(os.path.join(DATA, "pings.csv"))
    fixed.write_reports(res, str(tmp_path))
    rounded = sum(float(r["km"]) for r in csv.DictReader(open(tmp_path / "daily_km.csv")))
    exact = sum(res.daily_m.values()) / 1000
    record("TC-52", IMPL, f"|diff| <= 0.001 km ({len(res.segments)} segments)", f"{abs(rounded - exact):.3g} km")
    assert len(res.segments) >= 2000 and abs(rounded - exact) <= 0.001


# --------------------------------------------------------------------- H. QA tool (data side)
def test_TC_59_same_seed_gives_identical_dataset(record, tmp_path):
    """Given generate_data.py with seed 42,
    When it is run twice into two empty directories,
    Then both runs are byte-identical, and pings.csv and ground_truth.csv match the sha256 values pinned
    below (recorded 2026-11-10). The pins are fixed in this file, not read from data/, which run_all.py
    regenerates. If the generator changes on purpose, update the pins and say why."""
    import hashlib
    pinned = {"pings.csv": "8740b276e1bcaf7a68300c0c280c8be03c70685bfcbc56c7905d69372471287a",
              "ground_truth.csv": "8b0f0e3b2a7e7fe12a6b451781dd6081666bdeb3b9a9e71fed53148e7f56a6c4"}
    hashes = []
    for k in (1, 2):
        d = tmp_path / f"run{k}"
        subprocess.run([sys.executable, os.path.join(ROOT, "generate_data.py"), "--seed", "42", "--data-dir", str(d),
                        "--no-fixtures"], check=True, capture_output=True)
        hashes.append({n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in sorted(os.listdir(d))})
    got = {n: hashes[0][n] for n in pinned}
    record("TC-59", IMPL, pinned, f"run1==run2: {hashes[0] == hashes[1]}; run1: {got}")
    assert hashes[0] == hashes[1] and got == pinned


@pytest.mark.parametrize("name,needle", [
    ("F_INVALID_swapped.csv", "swapped"),         # TC-60
    ("F_INVALID_offset.csv", "offset"),           # X-01
    ("F_INVALID_range.csv", "out of range"),      # X-03
    ("F_INVALID_missing_col.csv", "missing"),     # X-04
])
def test_TC_60_and_X_01_X_03_X_04_pipeline_rejects_bad_pings(record, name, needle):
    """Given a bad pings file (swapped lat/lon, UTC offset, out-of-range coordinate or missing column),
    When fixed.py loads it,
    Then it raises InputError naming the problem, and no run starts."""
    tc = {"F_INVALID_swapped.csv": "TC-60", "F_INVALID_offset.csv": "X-01",
          "F_INVALID_range.csv": "X-03", "F_INVALID_missing_col.csv": "X-04"}[name]
    with pytest.raises(fixed.InputError) as ei:
        fixed.run_file(fx(name))
    record(tc, IMPL, f"InputError with '{needle}'", str(ei.value).replace("\n", " | ")[:200])
    assert needle in str(ei.value)


# ------------------------------------------------------- 'Regression Test Cases' tab (RTC-xx)
def test_RTC_01_full_in_zone_route_no_faults(record):
    """Given F_ZONE DRV-A: 20 pings along R1, all inside Z1, exactly every 10 s, no faults,
    When the pipeline runs and DRV-A's total for local day 2026-11-07 is read,
    Then it equals the sum of its 19 segment lengths = 0.0038 deg = 0.422541 km, and no event of any kind
    (warning, duplicate, drop) is logged for DRV-A."""
    res = run("F_ZONE.csv")
    seg_sum = sum(s["length_m"] for s in res.segments if s["driver_id"] == "DRV-A") / 1000
    day_km = res.daily_km.get(("DRV-A", "2026-11-07"), 0.0)
    n_events = sum(e["driver_id"] == "DRV-A" for e in res.events)
    record("RTC-01", IMPL, (deg_km(0.0038), deg_km(0.0038), 0), (day_km, seg_sum, n_events))
    assert close(day_km, deg_km(0.0038)) and close(seg_sum, deg_km(0.0038)) and n_events == 0


def test_RTC_02_each_driver_total_equals_its_own_segments(record):
    """Given F_ZONE DRV-A (01:00Z) and DRV-B (03:00Z), both inside Z1 on the same local day 2026-11-07,
    When the pipeline runs,
    Then both rows are on 2026-11-07, and each total equals the sum of that driver's own segments:
    DRV-A 0.0038 deg = 0.422541 km, DRV-B 0.0018 deg = 0.200151 km."""
    res = run("F_ZONE.csv")
    act, exp = [], []
    for drv, deg in (("DRV-A", 0.0038), ("DRV-B", 0.0018)):
        own = sum(s["inside_m"] for s in res.segments if s["driver_id"] == drv) / 1000
        days = sorted(d for (dd, d) in res.daily_km if dd == drv)
        act.append((days, res.daily_km.get((drv, "2026-11-07"), 0.0), own))
        exp.append((["2026-11-07"], deg_km(deg), deg_km(deg)))
    record("RTC-02", IMPL, exp, act)
    assert all(a[0] == e[0] and close(a[1], e[1]) and close(a[2], e[2]) for a, e in zip(act, exp))


def test_RTC_08_late_ping_placed_by_own_timestamp(record):
    """Given F_LATE DRV-A: the 09:00:30 ping (ping 4) arrives in the file after the 09:01:00 ping (ping 7),
    When the pipeline runs,
    Then ping 4 is kept and placed by its timestamp: accepted order 1,2,3,4,5,6,7 and
    km = 6 x 0.0004 deg = 0.266868 km."""
    res = run("F_LATE.csv")
    segs = [s for s in res.segments if s["driver_id"] == "DRV-A"]
    order = [segs[0]["from_ping"]] + [s["to_ping"] for s in segs]
    exp = (["1", "2", "3", "4", "5", "6", "7"], "ACCEPTED", deg_km(0.0024))
    act = (order, status(res, "DRV-A", 4), driver_km(res, "DRV-A"))
    record("RTC-08", IMPL, exp, act)
    assert act[:2] == exp[:2] and close(act[2], exp[2])


@pytest.mark.parametrize("name", ["pings.csv", "pings_clean.csv"])
def test_RTC_09_daily_totals_sum_to_overall_total(record, name):
    """Given the full dataset (data/pings.csv with faults, and data/pings_clean.csv),
    When the pipeline runs and daily totals are compared with overall totals per driver,
    Then for every driver the daily rows add up to the overall total (within 1 mm), including the
    drivers whose shifts cross local midnight (DRV-03, DRV-07, DRV-10)."""
    res = run(os.path.join(DATA, name))
    sums = {}
    for (d, _), km in res.daily_km.items():
        sums[d] = sums.get(d, 0.0) + km
    bad = {d: round(sums.get(d, 0.0) - t, 9) for d, t in res.total_km.items() if not close(sums.get(d, 0.0), t)}
    two_day = sorted(d for d in res.total_km if sum(1 for (dd, _) in res.daily_km if dd == d) > 1)
    record("RTC-09", IMPL, ({}, ["DRV-03", "DRV-07", "DRV-10"]), (bad, two_day))
    assert bad == {} and {"DRV-03", "DRV-07", "DRV-10"} <= set(two_day)


def test_RTC_03_segment_fully_inside_counts_in_full(record):
    """Given F_ZONE DRV-A segment 1->2 (lon 0.0062 -> 0.0064), more than 10 m from every edge,
    When the pipeline runs,
    Then its inside length equals its full great-circle length."""
    s = next(s for s in run("F_ZONE.csv").segments if s["driver_id"] == "DRV-A" and s["from_ping"] == "1")
    record("RTC-03", IMPL, round(s["length_m"], 6), round(s["inside_m"], 6))
    assert abs(s["inside_m"] - s["length_m"]) < 1e-9


def test_RTC_04_ping_20m_off_road_kept(record):
    """Given F_NOISE DRV-N: ping 3 is 20 m off R1 mid-route, speed valid,
    When the pipeline runs,
    Then ping 3 is kept and included in the distance (km = clipped path through all 6 pings)."""
    res = run("F_NOISE.csv")
    rows = [r for r in csv.DictReader(open(fx("F_NOISE.csv"))) if r["driver_id"] == "DRV-N"]
    exp = path_inside_km([(float(r["lon"]), float(r["lat"])) for r in rows])
    act = (status(res, "DRV-N", 3), driver_km(res, "DRV-N"))
    record("RTC-04", IMPL, ("ACCEPTED", exp), act)
    assert act[0] == "ACCEPTED" and close(act[1], exp) and exp > deg_km(0.002)


def test_RTC_05_conflict_log_once_per_group(record):
    """Given F_DUPLICATES DRV-F: two conflicting groups (ping 2 + 102; ping 4 + 104 + 105),
    When the pipeline runs,
    Then exactly two DUPLICATE_CONFLICT entries are logged, one per group."""
    ev = events(run("F_DUPLICATES.csv"), "DUPLICATE_CONFLICT", "DRV-F")
    record("RTC-05", IMPL, ["2", "4"], [e["ping_id"] for e in ev])
    assert [e["ping_id"] for e in ev] == ["2", "4"]


def test_RTC_06_segment_starting_1630z_in_next_local_day(record):
    """Given F_DAYCUT DRV-D: segment starting 2026-11-07T16:30:00Z (01:30 local on 11-08; the sheet's
    '00:30 local' is wrong, the day is right, P-03),
    When the pipeline runs,
    Then it is counted on local day 2026-11-08."""
    res = run("F_DAYCUT.csv")
    days = sorted(day for (d, day) in res.daily_km if d == "DRV-D")
    record("RTC-06", IMPL, ["2026-11-08"], days)
    assert days == ["2026-11-08"]


def test_RTC_07_timestamps_keep_z_after_load_save_reload(record, tmp_path):
    """Given fixtures/F_BOUNDARY.csv,
    When it is loaded, run, saved (ping_status.csv) and reloaded,
    Then every timestamp is unchanged and still ends in Z."""
    res = fixed.run_file(fx("F_BOUNDARY.csv"))
    fixed.write_reports(res, str(tmp_path))
    before = [p.ts_text for p in fixed.load_pings(fx("F_BOUNDARY.csv"))]
    after = [p.ts_text for p in fixed.load_pings(str(tmp_path / "ping_status.csv"))]
    record("RTC-07", IMPL, before, after)
    assert before == after and all(t.endswith("Z") for t in after)


def test_RTC_10_generated_intervals_are_exactly_10s(record):
    """Given data/pings_clean.csv (no injected faults),
    When intervals between consecutive pings are measured per driver,
    Then every interval is exactly 10 s: no gaps, no extra pings."""
    pings = fixed.load_pings(os.path.join(DATA, "pings_clean.csv"))
    by = {}
    for p in pings:
        by.setdefault(p.driver_id, []).append(p.ts)
    bad = [(d, (b - a).total_seconds()) for d, ts in by.items() for a, b in zip(sorted(ts), sorted(ts)[1:])
           if (b - a).total_seconds() != 10]
    record("RTC-10", IMPL, [], bad[:10])
    assert bad == []


def test_RTC_12_no_duplicate_timestamps_in_clean_data(record):
    """Given data/pings_clean.csv,
    When duplicate ts_utc per driver_id are counted,
    Then there are zero."""
    pings = fixed.load_pings(os.path.join(DATA, "pings_clean.csv"))
    dups = len(pings) - len({(p.driver_id, p.ts) for p in pings})
    record("RTC-12", IMPL, 0, dups)
    assert dups == 0


def test_RTC_14_irregular_intervals_do_not_change_distance(record):
    """Given F_INTERVALS_regular (13 pings every 10 s on a straight stretch) and F_INTERVALS_irregular
    (same positions without pings 5 and 6, and the last ping sent 5 s early),
    When the pipeline runs on both,
    Then the distance is identical, and the irregular file only adds INTERVAL_WARNING events (A9)."""
    a, b = run("F_INTERVALS_regular.csv"), run("F_INTERVALS_irregular.csv")
    warns = [e["detail"] for e in events(b, "INTERVAL_WARNING")]
    record("RTC-14", IMPL, (driver_km(a, "DRV-A"), 2), (driver_km(b, "DRV-A"), len(warns)))
    assert close(driver_km(a, "DRV-A"), driver_km(b, "DRV-A")) and len(warns) == 2

