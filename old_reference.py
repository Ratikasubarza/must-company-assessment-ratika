"""old_reference.py - the OLD pipeline, with planted bugs BUG-01..BUG-17 (see BUGS.md).

SYNTHETIC data only. Do not use for pay.

Every bug sits behind `if bug("BUG-xx")` so it can be switched on or off by
itself. That lets the regression suite show that each bug, alone, makes its own
regression test fail. By default ALL bugs are on: that is "the old implementation".

    with only_bugs({"BUG-05"}):
        res = old_reference.run_file("fixtures/F_NOISE.csv")

CLI:
    python old_reference.py --pings data/pings.csv --out out/old [--bugs BUG-01,BUG-05 | --bugs none]
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

from fixed import Result, write_reports  # report container + writer only; no pipeline logic

ALL_BUGS = frozenset(f"BUG-{i:02d}" for i in range(1, 18))
_ACTIVE = set(ALL_BUGS)
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROUTE = os.path.join(HERE, "data", "route_R1.json")
DEFAULT_ZONE = os.path.join(HERE, "data", "zone_Z1.json")


def bug(bug_id: str) -> bool:
    return bug_id in _ACTIVE


@contextlib.contextmanager
def only_bugs(bugs):
    """Run with exactly this set of bugs enabled."""
    global _ACTIVE
    saved = _ACTIVE
    _ACTIVE = set(bugs)
    try:
        yield
    finally:
        _ACTIVE = saved


class OldInputError(Exception):
    pass


# ------------------------------------------------------------------------- helpers
def earth_radius():
    return 6_378_137.0 if bug("BUG-03") else 6_371_000.0   # BUG-03: equatorial radius


def hav(lon1, lat1, lon2, lat2):
    R = earth_radius()
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


def parse_ts(s):
    s = s.strip()
    if s.endswith("Z"):
        return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
    if bug("BUG-16"):
        # BUG-16: timestamps without Z are accepted and silently treated as UTC
        return datetime.fromisoformat(s.replace(" ", "T")).replace(tzinfo=timezone.utc)
    raise ValueError(f"timestamp {s!r} must end in Z")


def day_of(ts):
    if bug("BUG-14"):
        return ts.date().isoformat()                    # BUG-14: UTC date, not UTC+9
    return (ts + timedelta(hours=9)).date().isoformat()


def dist_to_route(lon, lat, route):
    R = 6_371_000.0
    k = math.cos(math.radians(lat))
    best = math.inf
    for (ax, ay), (bx, by) in zip(route, route[1:]):
        ux, uy, wx, wy = (bx - ax) * k, by - ay, (lon - ax) * k, lat - ay
        L2 = ux * ux + uy * uy
        t = 0 if L2 == 0 else max(0, min(1, (wx * ux + wy * uy) / L2))
        best = min(best, math.radians(math.hypot(wx - t * ux, wy - t * uy)) * R)
    return best


def _on_edge(x, y, ax, ay, bx, by):
    cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
    if abs(cross) > 1e-15:
        return False
    return min(ax, bx) - 1e-12 <= x <= max(ax, bx) + 1e-12 and min(ay, by) - 1e-12 <= y <= max(ay, by) + 1e-12


def in_zone(lon, lat, zone):
    edges = list(zip(zone, zone[1:]))
    if any(_on_edge(lon, lat, ax, ay, bx, by) for (ax, ay), (bx, by) in edges):
        return not bug("BUG-01")                       # BUG-01: boundary counted as outside
    inside = False
    for (ax, ay), (bx, by) in edges:
        if (ay > lat) != (by > lat) and lon < ax + (lat - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def zone_length(a, b, zone):
    if bug("BUG-02"):
        # BUG-02: no clipping - the whole segment counts if its start ping is inside
        return hav(a[0], a[1], b[0], b[1]) if in_zone(a[0], a[1], zone) else 0.0
    (ax, ay), (bx, by) = a, b
    rx, ry = bx - ax, by - ay
    if rx == 0 and ry == 0:
        return 0.0
    ts = [0.0, 1.0]
    for (cx, cy), (dx, dy) in zip(zone, zone[1:]):
        sx, sy = dx - cx, dy - cy
        den = rx * sy - ry * sx
        if den == 0:
            continue
        t = ((cx - ax) * sy - (cy - ay) * sx) / den
        u = ((cx - ax) * ry - (cy - ay) * rx) / den
        if 0 <= t <= 1 and 0 <= u <= 1:
            ts.append(t)
    ts.sort()
    total = 0.0
    for t0, t1 in zip(ts, ts[1:]):
        if t1 > t0 and in_zone(ax + rx * (t0 + t1) / 2, ay + ry * (t0 + t1) / 2, zone):
            total += hav(ax + rx * t0, ay + ry * t0, ax + rx * t1, ay + ry * t1)
    return total


# --------------------------------------------------------------------------- loading
def _coords(path):
    with open(path, encoding="utf-8") as fh:
        return [tuple(map(float, p)) for p in json.load(fh)["coordinates"]]


def load_pings(path):
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            try:
                ts = parse_ts(row["ts_utc"])
            except ValueError as exc:
                raise ValueError(f"{path}: line {rd.line_num}: {exc}")
            out.append({"driver_id": row["driver_id"], "ping_id": row["ping_id"], "ts_text": row["ts_utc"],
                        "ts": ts, "lon": float(row["lon"]), "lat": float(row["lat"])})
    return out


# -------------------------------------------------------------------------- pipeline
def _ev(res, et, p, detail=""):
    res.events.append({"event_type": et, "driver_id": p["driver_id"], "ping_id": p["ping_id"],
                       "ts_utc": p["ts_text"], "detail": detail})


def run(pings, route, zone):
    res = Result()

    # dedup
    kept = []
    if bug("BUG-12"):
        # BUG-12: only compares each row with the row directly before it in the file
        prev = None
        for p in pings:
            same_key = prev is not None and prev["ts"] == p["ts"] and (
                bug("BUG-11") or prev["driver_id"] == p["driver_id"])
            if same_key:
                _dup(res, kept, prev, p)
            else:
                kept.append(p)
            prev = p
    else:
        seen = {}
        for p in pings:
            key = p["ts"] if bug("BUG-11") else (p["driver_id"], p["ts"])  # BUG-11: key ignores driver
            if key in seen:
                seen[key] = _dup(res, kept, seen[key], p)
            else:
                seen[key] = p
                kept.append(p)

    drivers = {}
    for p in kept:
        drivers.setdefault(p["driver_id"], []).append(p)
    for p in pings:
        res.total_m.setdefault(p["driver_id"], 0.0)

    for drv in sorted(drivers):
        seq = drivers[drv] if bug("BUG-17") else sorted(drivers[drv], key=lambda q: q["ts"])  # BUG-17: no sort

        accepted = []
        anchor = None
        for p in seq:
            st = {"driver_id": drv, "ping_id": p["ping_id"], "ts_utc": p["ts_text"], "lon": p["lon"],
                  "lat": p["lat"], "status": "ACCEPTED", "in_zone": in_zone(p["lon"], p["lat"], zone),
                  "local_date": day_of(p["ts"]), "offroad_m": None, "speed_kmh": None}
            d = dist_to_route(p["lon"], p["lat"], route)
            offroad = d >= 100.0 if bug("BUG-04") else round(d, 3) > 100.0   # BUG-04: 100 m itself dropped
            if offroad:
                _ev(res, "DROPPED_OFFROAD", p, f"{d:.3f} m")
                if not bug("BUG-05"):                     # BUG-05: logged as noise but still used
                    st["status"] = "DROPPED_OFFROAD"
                    res.ping_status[(drv, p["ping_id"])] = st
                    if bug("BUG-07"):
                        anchor = p                         # BUG-07: dropped ping becomes the anchor
                    continue
            if anchor is not None:
                dt = 10.0 if bug("BUG-06") else (p["ts"] - anchor["ts"]).total_seconds()  # BUG-06
                v = 0.0 if dt <= 0 else hav(anchor["lon"], anchor["lat"], p["lon"], p["lat"]) / dt * 3.6
                too_fast = v >= 150.0 if bug("BUG-08") else round(v, 3) > 150.0  # BUG-08: 150 itself dropped
                if too_fast:
                    if bug("BUG-09") and accepted and accepted[-1] is anchor:
                        # BUG-09: drops the earlier ping of the fast pair, keeps the spike
                        dropped = accepted.pop()
                        res.ping_status[(drv, dropped["ping_id"])]["status"] = "DROPPED_SPEED"
                        _ev(res, "DROPPED_SPEED", dropped, f"{v:.3f} km/h")
                    else:
                        st["status"] = "DROPPED_SPEED"
                        _ev(res, "DROPPED_SPEED", p, f"{v:.3f} km/h")
                        res.ping_status[(drv, p["ping_id"])] = st
                        if bug("BUG-07"):
                            anchor = p
                        continue
            accepted.append(p)
            anchor = p
            res.ping_status[(drv, p["ping_id"])] = st

        for a, b in zip(accepted, accepted[1:]):
            inside = zone_length((a["lon"], a["lat"]), (b["lon"], b["lat"]), zone)
            d0, d1 = day_of(a["ts"]), day_of(b["ts"])
            res.segments.append({"driver_id": drv, "from_ping": a["ping_id"], "to_ping": b["ping_id"],
                                 "local_date": d0, "length_m": hav(a["lon"], a["lat"], b["lon"], b["lat"]),
                                 "inside_m": inside})
            res.total_m[drv] += inside
            if bug("BUG-15") and d0 != d1:
                continue                                   # BUG-15: segment over midnight left out of the daily report
            res.daily_m[(drv, d0)] = res.daily_m.get((drv, d0), 0.0) + inside
    return res


def _dup(res, kept, first, p):
    conflict = (first["lon"], first["lat"]) != (p["lon"], p["lat"])
    if bug("BUG-10"):
        # BUG-10: keeps the LAST occurrence instead of the first
        kept[kept.index(first)] = p
        rep = p
        _ev(res, "DUPLICATE_DROPPED", first, f"replaced by ping {p['ping_id']}")
        res.ping_status[(first["driver_id"], first["ping_id"])] = {"driver_id": first["driver_id"],
                                                                   "ping_id": first["ping_id"], "status": "DUPLICATE"}
    else:
        rep = first
        _ev(res, "DUPLICATE_DROPPED", p, f"duplicate of ping {first['ping_id']}")
        res.ping_status[(p["driver_id"], p["ping_id"])] = {"driver_id": p["driver_id"], "ping_id": p["ping_id"],
                                                           "status": "DUPLICATE"}
    if conflict and not bug("BUG-13"):                    # BUG-13: conflicting coordinates not logged
        _ev(res, "DUPLICATE_CONFLICT", first, f"conflict with ping {p['ping_id']}")
    return rep


def run_file(pings_path, route_path=DEFAULT_ROUTE, zone_path=DEFAULT_ZONE):
    route, zone = _coords(route_path), _coords(zone_path)
    if zone[0] != zone[-1]:
        zone.append(zone[0])
    return run(load_pings(pings_path), route, zone)


def main(argv=None):
    ap = argparse.ArgumentParser(description="OLD pipeline with planted bugs (SYNTHETIC data).")
    ap.add_argument("--pings", required=True)
    ap.add_argument("--route", default=DEFAULT_ROUTE)
    ap.add_argument("--zone", default=DEFAULT_ZONE)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bugs", default="all", help="'all' (default), 'none', or a comma list like BUG-01,BUG-05")
    args = ap.parse_args(argv)
    bugs = ALL_BUGS if args.bugs == "all" else set() if args.bugs == "none" else set(args.bugs.split(","))
    with only_bugs(bugs):
        try:
            res = run_file(args.pings, args.route, args.zone)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    write_reports(res, args.out)
    print(f"old ({len(bugs)} bugs on): {len(res.daily_m)} driver-day rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
