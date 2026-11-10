"""Regression guards: worst-case and edge scenarios that must keep PASSING on fixed.py.

Unlike the bug checks in regression_checks.py, a guard is not tied to a planted bug,
so it is not required to fail on old_reference.py. It runs on both: on fixed.py it
must pass (any future change that breaks a worst case fails the suite); on
old_reference.py the outcome is only recorded. Guards compare only outputs both
implementations produce (ping status, km, duplicate events, input rejection).

Covered: every 'Worst' case in the Test Cases tab that runs a pipeline (TC-19, 25, 26,
27, 35, 41, 46, 52; TC-34 is already a bug check) plus the added edge cases TC-66..TC-71.
"""
from __future__ import annotations

import csv
import filecmp
import os
import subprocess
import sys
import tempfile

from helpers import DATA, ROOT, deg_km, driver_km, fx, path_inside_km, status
from regression_checks import Check

GUARDS: list[Check] = []


def guard(tc_id):
    def deco(f):
        GUARDS.append(Check(tc_id, "guard_" + f.__name__, (), f))
        return f
    return deco


def _statuses(res, driver, ids):
    return [status(res, driver, i) for i in ids]


@guard("TC-19")
def first_valid_ping_is_speed_anchor(impl):
    """Given F_NOISE DRV-D: first ping 667 m off road, then 4 on-road pings,
    When the pipeline runs,
    Then ping 1 is dropped as off-road and pings 2-5 are kept (ping 2 is the anchor)."""
    res = impl.run_file(fx("F_NOISE.csv"))
    return ["DROPPED_OFFROAD"] + ["ACCEPTED"] * 4, _statuses(res, "DRV-D", range(1, 6))


@guard("TC-25")
def same_timestamp_different_coordinates_no_crash(impl):
    """Given F_DUPLICATES DRV-B: pings 3 and 103 share a timestamp with different coordinates,
    When the pipeline runs,
    Then it does not crash (no division by zero), ping 3 is kept and 103 is a duplicate."""
    res = impl.run_file(fx("F_DUPLICATES.csv"))
    return ["ACCEPTED", "DUPLICATE"], _statuses(res, "DRV-B", (3, 103))


@guard("TC-26")
def spike_does_not_move_anchor(impl):
    """Given F_NOISE DRV-K: ping 3 is a 201 km/h spike, pings 4-6 continue the real path,
    When the pipeline runs,
    Then only ping 3 is dropped and km = 0.0016 deg = 0.177912 km."""
    res = impl.run_file(fx("F_NOISE.csv"))
    return ((["ACCEPTED"] * 2 + ["DROPPED_SPEED"] + ["ACCEPTED"] * 3, deg_km(0.0016)),
            (_statuses(res, "DRV-K", range(1, 7)), driver_km(res, "DRV-K")))


@guard("TC-27")
def valid_ping_after_dropped_noise_is_kept(impl):
    """Given F_NOISE DRV-L: ping 3 off road, pings 4 and 5 valid when measured from ping 2,
    When the pipeline runs,
    Then pings 4 and 5 are kept."""
    res = impl.run_file(fx("F_NOISE.csv"))
    return ["ACCEPTED", "ACCEPTED"], _statuses(res, "DRV-L", (4, 5))


@guard("TC-35")
def half_duplicates_same_as_deduplicated(impl):
    """Given F_DUP_HALF_raw (most rows sent twice) and F_DUP_HALF_dedup,
    When the pipeline runs on both,
    Then the daily km are identical."""
    a = impl.run_file(fx("F_DUP_HALF_dedup.csv")).daily_km
    b = impl.run_file(fx("F_DUP_HALF_raw.csv")).daily_km
    return a, b


@guard("TC-41")
def output_independent_of_machine_timezone(impl):
    """Given F_DAYCUT,
    When the implementation's CLI runs with TZ=Asia/Shanghai (UTC+8), UTC and Asia/Tokyo (UTC+9),
    Then daily_km.csv is byte-identical in all three runs."""
    script = os.path.join(ROOT, os.path.basename(impl.__file__))
    with tempfile.TemporaryDirectory() as tmp:
        outs = []
        for tz in ("Asia/Shanghai", "UTC", "Asia/Tokyo"):
            out = os.path.join(tmp, tz.replace("/", "_"))
            subprocess.run([sys.executable, script, "--pings", fx("F_DAYCUT.csv"), "--out", out],
                           check=True, capture_output=True, env=dict(os.environ, TZ=tz))
            outs.append(os.path.join(out, "daily_km.csv"))
        return True, all(filecmp.cmp(outs[0], o, shallow=False) for o in outs[1:])


@guard("TC-46")
def reversed_file_same_result(impl):
    """Given data/pings_clean.csv and the same rows reversed,
    When the pipeline runs on both,
    Then the daily km are identical."""
    with open(os.path.join(DATA, "pings_clean.csv")) as fh:
        lines = fh.read().splitlines()
    with tempfile.TemporaryDirectory() as tmp:
        rev = os.path.join(tmp, "rev.csv")
        with open(rev, "w") as fh:
            fh.write("\n".join([lines[0]] + lines[1:][::-1]) + "\n")
        return impl.run_file(os.path.join(DATA, "pings_clean.csv")).daily_km, impl.run_file(rev).daily_km


@guard("TC-52")
def rounding_error_within_tolerance(impl):
    """Given the full dataset (about 2,500 segments),
    When daily km are written rounded to 6 dp and summed,
    Then the sum is within 0.001 km of the unrounded sum.
    Margin: worst-case rounding error is rows x 0.0000005 km (15 rows on fixed.py = 0.0000075 km), so the
    tolerance is about 133x larger. This records the bound; it is not expected to catch a defect."""
    import fixed  # report writer is shared; only the numbers come from impl
    res = impl.run_file(os.path.join(DATA, "pings.csv"))
    with tempfile.TemporaryDirectory() as tmp:
        fixed.write_reports(res, tmp)
        rounded = sum(float(r["km"]) for r in csv.DictReader(open(os.path.join(tmp, "daily_km.csv"))))
    return True, abs(rounded - sum(res.daily_m.values()) / 1000) <= 0.001


@guard("TC-66")
def speed_149_9_kmh_kept(impl):
    """Given F_NOISE DRV-O: ping 3 is 149.9 km/h from ping 2,
    When the pipeline runs,
    Then all 5 pings are kept and km = 0.0040 deg = 0.444780 km."""
    res = impl.run_file(fx("F_NOISE.csv"))
    return (["ACCEPTED"] * 5, deg_km(0.0040)), (_statuses(res, "DRV-O", range(1, 6)), driver_km(res, "DRV-O"))


@guard("TC-67")
def intervals_10_1s_and_9_99s_do_not_change_distance(impl):
    """Given F_ZONE DRV-J: intervals 10, 10.1, 9.99, 10 s inside Z1,
    When the pipeline runs,
    Then all 5 pings are kept and km = 0.0016 deg = 0.177912 km (as with exact 10 s)."""
    res = impl.run_file(fx("F_ZONE.csv"))
    return (["ACCEPTED"] * 5, deg_km(0.0016)), (_statuses(res, "DRV-J", range(1, 6)), driver_km(res, "DRV-J"))


@guard("TC-68")
def negative_coordinates(impl):
    """Given F_ZONE DRV-K (negative longitude, outside Z1) and DRV-L (negative latitude, inside Z1),
    When the pipeline runs,
    Then every ping is kept, DRV-K = 0 km, DRV-L = 0.170281 km."""
    res = impl.run_file(fx("F_ZONE.csv"))
    exp_l = path_inside_km([(0.0070, 0.0), (0.0074, -0.0004), (0.0078, 0.0), (0.0082, 0.0)])
    return ((["ACCEPTED"] * 3, ["ACCEPTED"] * 4, 0.0, exp_l),
            (_statuses(res, "DRV-K", (1, 2, 3)), _statuses(res, "DRV-L", (1, 2, 3, 4)),
             driver_km(res, "DRV-K"), driver_km(res, "DRV-L")))


def _no_dup(res, driver):
    return sum(e["driver_id"] == driver and e["event_type"].startswith("DUPLICATE") for e in res.events)


@guard("TC-69")
def new_timestamp_same_coordinates_not_duplicate(impl):
    """Given F_DUPLICATES DRV-G: two pings at the same coordinates, 10 s apart, then a move,
    When the pipeline runs,
    Then no duplicate is reported, all 3 are kept, km = 0.0004 deg."""
    res = impl.run_file(fx("F_DUPLICATES.csv"))
    return ((["ACCEPTED"] * 3, 0, deg_km(0.0004)),
            (_statuses(res, "DRV-G", (1, 2, 3)), _no_dup(res, "DRV-G"), driver_km(res, "DRV-G")))


@guard("TC-70")
def new_timestamp_new_coordinates_not_duplicate(impl):
    """Given F_DUPLICATES DRV-H: three pings 10 s apart at different coordinates,
    When the pipeline runs,
    Then no duplicate is reported, all 3 are kept, km = 0.0008 deg."""
    res = impl.run_file(fx("F_DUPLICATES.csv"))
    return ((["ACCEPTED"] * 3, 0, deg_km(0.0008)),
            (_statuses(res, "DRV-H", (1, 2, 3)), _no_dup(res, "DRV-H"), driver_km(res, "DRV-H")))


@guard("TC-71")
def impossible_time_08_59_99_rejected(impl):
    """Given F_INVALID_bad_second: two drivers send a ping stamped 08:59:99Z (line 3 and line 5),
    When the pings are loaded,
    Then the file is rejected with an error naming line 3, and no result is produced."""
    try:
        impl.run_file(fx("F_INVALID_bad_second.csv"))
    except Exception as exc:
        return True, "line 3" in str(exc)
    return True, "accepted (no error)"
