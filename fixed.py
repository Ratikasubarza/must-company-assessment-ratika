"""fixed.py - corrected GPS distance pipeline. SYNTHETIC data only.

Rules come from intent.md (A1-A23, B-01). Core logic is plain Python; pandas is
used only to write the report files.

Pipeline order (intent.md): validate -> A6 dedup -> stable sort by ts_utc ->
interval warnings (A9/A16) -> A3 off-road filter -> A4 speed filter ->
A7 clipping -> A8 local-day assignment.

CLI:
    python fixed.py --pings data/pings.csv --out out/fixed
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

LABEL = "SYNTHETIC"
R_EARTH_M = 6_371_000.0          # A10
NOMINAL_INTERVAL_S = 10.0        # A9
MAX_OFFROAD_M = 100.0            # A3 (inclusive)
MAX_SPEED_KMH = 150.0            # A4 (inclusive)
COMPARE_DECIMALS = 3             # A12: mm and 0.001 km/h
LOCAL_OFFSET = timedelta(hours=9)  # A8
GEOM_EPS_DEG = 1e-12             # A14: on-edge tolerance in degrees (~0.1 micrometre)
REQUIRED_COLUMNS = ("driver_id", "ping_id", "ts_utc", "lon", "lat")
DEFAULT_ROUTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "route_R1.json")
DEFAULT_ZONE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "zone_Z1.json")

_TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$")
_OFFSET_RE = re.compile(r"(?:[+-]\d{2}:?\d{2})$")


class InputError(Exception):
    """Input file rejected. No run starts and no output is written."""

    def __init__(self, source: str, errors: list[str]):
        self.source = source
        self.errors = list(errors)
        shown = "\n".join("  " + e for e in self.errors[:50])
        more = f"\n  ... and {len(self.errors) - 50} more" if len(self.errors) > 50 else ""
        super().__init__(f"{source}: input rejected, {len(self.errors)} problem(s):\n{shown}{more}")


# --------------------------------------------------------------------------- time
def parse_ts_utc(text: str) -> datetime:
    """Parse 'YYYY-MM-DDTHH:MM:SS[.ffffff]Z' into an aware UTC datetime.

    Never consults the machine time zone (TC-41). Raises ValueError with a reason.
    """
    s = text.strip()
    if not s.endswith("Z"):
        if _OFFSET_RE.search(s):
            raise ValueError(f"timestamp {text!r} has a UTC offset; only the Z suffix is allowed")
        raise ValueError(f"timestamp {text!r} has no Z suffix")
    m = _TS_RE.match(s)
    if not m:
        raise ValueError(f"timestamp {text!r} is not in the form YYYY-MM-DDTHH:MM:SS[.ffffff]Z")
    y, mo, d, h, mi, se, frac = m.groups()
    micro = int((frac or "0").ljust(6, "0"))
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(se), micro, tzinfo=timezone.utc)
    except ValueError as exc:  # e.g. second 99, month 13, 31 November
        raise ValueError(f"timestamp {text!r} is not a valid date/time ({exc})")


def local_date(ts: datetime) -> str:
    """Local calendar day in UTC+9 (A8)."""
    return (ts + LOCAL_OFFSET).date().isoformat()


# ----------------------------------------------------------------------- geometry
def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH_M * math.asin(min(1.0, math.sqrt(a)))


def distance_to_route_m(lon: float, lat: float, route: list[tuple[float, float]]) -> float:
    """Shortest distance from a point to the route polyline (A13).

    Local equirectangular projection centred on the point's latitude.
    """
    k = math.cos(math.radians(lat))
    px, py = math.radians(lon) * k * R_EARTH_M, math.radians(lat) * R_EARTH_M
    best = math.inf
    for (alon, alat), (blon, blat) in zip(route, route[1:]):
        ax, ay = math.radians(alon) * k * R_EARTH_M, math.radians(alat) * R_EARTH_M
        bx, by = math.radians(blon) * k * R_EARTH_M, math.radians(blat) * R_EARTH_M
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def _on_segment(px, py, ax, ay, bx, by, eps=GEOM_EPS_DEG) -> bool:
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy)
    if L == 0:
        return math.hypot(px - ax, py - ay) <= eps
    if abs(dx * (py - ay) - dy * (px - ax)) / L > eps:
        return False
    t = ((px - ax) * dx + (py - ay) * dy) / (L * L)
    return -eps / L <= t <= 1 + eps / L


def in_zone(lon: float, lat: float, zone: list[tuple[float, float]]) -> bool:
    """Point in polygon; a point on an edge or vertex counts as inside (B-01, covers)."""
    for (ax, ay), (bx, by) in zip(zone, zone[1:]):
        if _on_segment(lon, lat, ax, ay, bx, by):
            return True
    inside = False
    for (ax, ay), (bx, by) in zip(zone, zone[1:]):
        if (ay > lat) != (by > lat):
            x_cross = ax + (lat - ay) * (bx - ax) / (by - ay)
            if lon < x_cross:
                inside = not inside
    return inside


def inside_length_m(a: tuple[float, float], b: tuple[float, float], zone) -> float:
    """Length of segment a->b that lies inside the zone (A7 clipping, A14).

    The segment is split at every crossing with a zone edge; each piece is kept
    if its midpoint is inside (boundary counts). Pieces are measured with haversine.
    """
    (ax, ay), (bx, by) = a, b
    rx, ry = bx - ax, by - ay
    rr = rx * rx + ry * ry
    if rr == 0:
        return 0.0
    ts = {0.0, 1.0}
    for (cx, cy), (dx, dy) in zip(zone, zone[1:]):
        sx, sy = dx - cx, dy - cy
        denom = rx * sy - ry * sx
        qx, qy = cx - ax, cy - ay
        if abs(denom) > 1e-12 * math.sqrt(rr) * math.hypot(sx, sy):
            t = (qx * sy - qy * sx) / denom
            u = (qx * ry - qy * rx) / denom
            if -1e-12 <= t <= 1 + 1e-12 and -1e-12 <= u <= 1 + 1e-12:
                ts.add(min(1.0, max(0.0, t)))
        elif abs(qx * ry - qy * rx) <= GEOM_EPS_DEG * math.sqrt(rr):
            # collinear with this edge: split at the edge end points
            for ex, ey in ((cx, cy), (dx, dy)):
                t = ((ex - ax) * rx + (ey - ay) * ry) / rr
                if 0.0 < t < 1.0:
                    ts.add(t)
    cuts = sorted(ts)
    total = 0.0
    for t0, t1 in zip(cuts, cuts[1:]):
        if t1 - t0 <= 1e-15:
            continue
        tm = (t0 + t1) / 2
        if in_zone(ax + rx * tm, ay + ry * tm, zone):
            total += haversine_m(ax + rx * t0, ay + ry * t0, ax + rx * t1, ay + ry * t1)
    return total


# ------------------------------------------------------------------------ loading
@dataclass
class Ping:
    line: int            # 1-based line number in the source file (header = line 1)
    driver_id: str
    ping_id: str
    ts_text: str
    ts: datetime
    lon: float
    lat: float


def _check_coord(name: str, value: str, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} {value!r} is not a number")
    if not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f"{name} {value!r} is out of range [{lo}, {hi}]")
    return v


def _load_coords(path: str, what: str) -> list[tuple[float, float]]:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(path, [f"cannot read {what}: {exc}"])
    errors = []
    if doc.get("label") != LABEL:
        errors.append(f"{what} file must carry label {LABEL!r}")
    pts = []
    for i, pt in enumerate(doc.get("coordinates") or []):
        try:
            lon = _check_coord("lon", pt[0], -180, 180)
            lat = _check_coord("lat", pt[1], -90, 90)
            pts.append((lon, lat))
        except (ValueError, IndexError, TypeError) as exc:
            errors.append(f"{what} vertex {i}: {exc}")
    if errors:
        raise InputError(path, errors)
    return pts


def load_route(path: str = DEFAULT_ROUTE) -> list[tuple[float, float]]:
    pts = _load_coords(path, "route")
    if len(pts) < 2:
        raise InputError(path, ["route needs at least 2 points"])
    return pts


def _route_touches_zone(route, zone) -> bool:
    if any(in_zone(lon, lat, zone) for lon, lat in route):
        return True
    return any(inside_length_m(a, b, zone) > 0 for a, b in zip(route, route[1:]))


def load_zone(path: str = DEFAULT_ZONE, route=None) -> list[tuple[float, float]]:
    """Load a polygon ring as [lon, lat]. Rejects a zone that looks lat/lon swapped (A18)."""
    pts = _load_coords(path, "zone")
    if len(set(pts)) < 3:
        raise InputError(path, ["zone needs at least 3 distinct vertices"])
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    if route is not None and not _route_touches_zone(route, pts):
        swapped = [(lat, lon) for lon, lat in pts]
        if _route_touches_zone(route, swapped):
            raise InputError(path, ["zone coordinates look swapped (lat, lon instead of lon, lat): "
                                    "the route does not touch the zone, but it touches the swapped zone"])
    return pts


def load_pings(path: str, route=None) -> list[Ping]:
    """Read and validate a pings CSV. Any invalid row rejects the whole file (A17)."""
    try:
        fh = open(path, newline="", encoding="utf-8")
    except OSError as exc:
        raise InputError(path, [f"cannot open: {exc}"])
    with fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise InputError(path, [f"missing required column(s): {', '.join(missing)}"])
        errors: list[str] = []
        pings: list[Ping] = []
        for row in reader:
            line = reader.line_num
            problems = []
            driver = (row.get("driver_id") or "").strip()
            pid = (row.get("ping_id") or "").strip()
            if not driver:
                problems.append("driver_id is empty")
            if not pid:
                problems.append("ping_id is empty")
            ts = None
            try:
                ts = parse_ts_utc(row.get("ts_utc") or "")
            except ValueError as exc:
                problems.append(str(exc))
            lon = lat = None
            try:
                lon = _check_coord("lon", row.get("lon"), -180, 180)
            except ValueError as exc:
                problems.append(str(exc))
            try:
                lat = _check_coord("lat", row.get("lat"), -90, 90)
            except ValueError as exc:
                problems.append(str(exc))
            if problems:
                errors.append(f"line {line} (driver {driver or '?'}, ping {pid or '?'}): " + "; ".join(problems))
            else:
                pings.append(Ping(line, driver, pid, row["ts_utc"].strip(), ts, lon, lat))
    if errors:
        raise InputError(path, errors)
    if route is not None and pings:
        _check_not_swapped(path, pings, route)
    return pings


def _check_not_swapped(path, pings, route):
    n = len(pings)
    near = sum(distance_to_route_m(p.lon, p.lat, route) <= MAX_OFFROAD_M for p in pings) / n
    near_sw = sum(distance_to_route_m(p.lat, p.lon, route) <= MAX_OFFROAD_M for p in pings) / n
    if near < 0.5 and near_sw >= 0.5:
        raise InputError(path, [f"lat/lon look swapped: {near:.0%} of pings are within {MAX_OFFROAD_M:.0f} m "
                                f"of the route as given, {near_sw:.0%} after swapping lat and lon"])


# ----------------------------------------------------------------------- pipeline
@dataclass
class Result:
    daily_m: dict = field(default_factory=dict)      # (driver, local_date) -> metres inside Z1
    total_m: dict = field(default_factory=dict)      # driver -> metres inside Z1
    events: list = field(default_factory=list)       # dicts
    ping_status: dict = field(default_factory=dict)  # (driver, ping_id) -> status dict
    segments: list = field(default_factory=list)     # dicts

    @property
    def daily_km(self):
        return {k: v / 1000 for k, v in self.daily_m.items()}

    @property
    def total_km(self):
        return {k: v / 1000 for k, v in self.total_m.items()}


def _event(res: Result, etype: str, p: Ping, detail: str):
    res.events.append({"event_type": etype, "driver_id": p.driver_id, "ping_id": p.ping_id,
                       "ts_utc": p.ts_text, "detail": detail})


def run(pings: list[Ping], route, zone) -> Result:
    res = Result()
    by_driver: dict[str, list[Ping]] = {}
    for p in pings:  # file order
        by_driver.setdefault(p.driver_id, []).append(p)

    for driver in sorted(by_driver):
        rows = by_driver[driver]
        res.total_m[driver] = 0.0

        # A6: dedup on (driver_id, ts instant); keep first in file order.
        first: dict[datetime, Ping] = {}
        groups: dict[datetime, list[Ping]] = {}
        kept: list[Ping] = []
        for p in rows:
            if p.ts in first:
                groups[p.ts].append(p)
                k = first[p.ts]
                same = (p.lon, p.lat) == (k.lon, k.lat)
                _event(res, "DUPLICATE_DROPPED", p,
                       f"duplicate of ping {k.ping_id}" + ("" if same else
                       f"; conflicting coordinates ({p.lon}, {p.lat}) vs kept ({k.lon}, {k.lat})"))
                res.ping_status[(driver, p.ping_id)] = _status(p, "DUPLICATE", zone)
            else:
                first[p.ts] = p
                groups[p.ts] = [p]
                kept.append(p)
        for ts, grp in groups.items():
            k = grp[0]
            conflicting = [q for q in grp[1:] if (q.lon, q.lat) != (k.lon, k.lat)]
            if conflicting:  # one log entry per conflicting group
                _event(res, "DUPLICATE_CONFLICT", k,
                       f"kept ping {k.ping_id} ({k.lon}, {k.lat}); dropped " +
                       ", ".join(f"{q.ping_id} ({q.lon}, {q.lat})" for q in conflicting))

        # A20: late arrival (info only): ts earlier than a ping already seen in file order.
        latest = None
        for p in kept:
            if latest is not None and p.ts < latest.ts:
                _event(res, "LATE_ARRIVAL", p, f"arrived after ping {latest.ping_id} ({latest.ts_text})")
            if latest is None or p.ts > latest.ts:
                latest = p

        # Sort by timestamp (stable).
        ordered = sorted(kept, key=lambda q: q.ts)

        # A9/A16: interval warnings on deduplicated, sorted pings.
        for prev, cur in zip(ordered, ordered[1:]):
            dt = (cur.ts - prev.ts).total_seconds()
            if dt != NOMINAL_INTERVAL_S:
                kind = "gap" if dt > NOMINAL_INTERVAL_S else "short"
                _event(res, "INTERVAL_WARNING", cur, f"interval {dt:g} s after ping {prev.ping_id} ({kind})")

        # A3 then A4.
        accepted: list[Ping] = []
        anchor = None
        for p in ordered:
            st = _status(p, "ACCEPTED", zone)
            d = distance_to_route_m(p.lon, p.lat, route)
            st["offroad_m"] = round(d, 3)
            if round(d, COMPARE_DECIMALS) > MAX_OFFROAD_M:
                st["status"] = "DROPPED_OFFROAD"
                _event(res, "DROPPED_OFFROAD", p, f"{d:.3f} m from route")
            elif anchor is not None:
                dt = (p.ts - anchor.ts).total_seconds()
                v = haversine_m(anchor.lon, anchor.lat, p.lon, p.lat) / dt * 3.6
                st["speed_kmh"] = round(v, 3)
                if round(v, COMPARE_DECIMALS) > MAX_SPEED_KMH:
                    st["status"] = "DROPPED_SPEED"
                    _event(res, "DROPPED_SPEED", p, f"{v:.3f} km/h from ping {anchor.ping_id}")
            if st["status"] == "ACCEPTED":
                accepted.append(p)
                anchor = p
            res.ping_status[(driver, p.ping_id)] = st

        # A7 clipping, A8 day of the starting ping.
        for a, b in zip(accepted, accepted[1:]):
            inside = inside_length_m((a.lon, a.lat), (b.lon, b.lat), zone)
            day = local_date(a.ts)
            res.segments.append({"driver_id": driver, "from_ping": a.ping_id, "to_ping": b.ping_id,
                                 "local_date": day, "length_m": haversine_m(a.lon, a.lat, b.lon, b.lat),
                                 "inside_m": inside})
            res.daily_m[(driver, day)] = res.daily_m.get((driver, day), 0.0) + inside
            res.total_m[driver] += inside
    return res


def _status(p: Ping, status: str, zone) -> dict:
    return {"driver_id": p.driver_id, "ping_id": p.ping_id, "ts_utc": p.ts_text, "lon": p.lon,
            "lat": p.lat, "status": status, "in_zone": in_zone(p.lon, p.lat, zone),
            "local_date": local_date(p.ts), "offroad_m": None, "speed_kmh": None}


def run_file(pings_path: str, route_path: str = DEFAULT_ROUTE, zone_path: str = DEFAULT_ZONE) -> Result:
    route = load_route(route_path)
    zone = load_zone(zone_path, route)
    return run(load_pings(pings_path, route), route, zone)


# ---------------------------------------------------------------------- reporting
def write_reports(res: Result, out_dir: str) -> None:
    import pandas as pd  # reporting only

    os.makedirs(out_dir, exist_ok=True)
    daily = pd.DataFrame(
        [{"label": LABEL, "driver_id": d, "local_date": day, "km": round(m / 1000, 6)}
         for (d, day), m in sorted(res.daily_m.items())],
        columns=["label", "driver_id", "local_date", "km"])
    daily.to_csv(os.path.join(out_dir, "daily_km.csv"), index=False)
    totals = pd.DataFrame(
        [{"label": LABEL, "driver_id": d, "km": round(m / 1000, 6)} for d, m in sorted(res.total_m.items())],
        columns=["label", "driver_id", "km"])
    totals.to_csv(os.path.join(out_dir, "driver_totals.csv"), index=False)
    ev = pd.DataFrame(res.events, columns=["event_type", "driver_id", "ping_id", "ts_utc", "detail"])
    ev.insert(0, "label", LABEL)
    ev.sort_values(["driver_id", "ts_utc", "event_type", "ping_id"], kind="stable").to_csv(
        os.path.join(out_dir, "events.csv"), index=False)
    st = pd.DataFrame(list(res.ping_status.values()))
    if not st.empty:
        st.insert(0, "label", LABEL)
        st.sort_values(["driver_id", "ts_utc", "ping_id"], kind="stable").to_csv(
            os.path.join(out_dir, "ping_status.csv"), index=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fixed GPS distance pipeline (SYNTHETIC data). "
                                             "Writes daily_km.csv, driver_totals.csv, events.csv, ping_status.csv.")
    ap.add_argument("--pings", required=True, help="pings CSV (driver_id, ping_id, ts_utc, lon, lat)")
    ap.add_argument("--route", default=DEFAULT_ROUTE, help="route JSON (default: data/route_R1.json)")
    ap.add_argument("--zone", default=DEFAULT_ZONE, help="zone JSON (default: data/zone_Z1.json)")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args(argv)
    try:
        res = run_file(args.pings, args.route, args.zone)
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    write_reports(res, args.out)
    print(f"fixed: {len(res.daily_m)} driver-day rows, {len(res.events)} events -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
