"""generate_data.py - SYNTHETIC dataset, ground truth and test fixtures.

    python generate_data.py --seed 42

Writes:
  data/pings.csv, data/ground_truth.csv              faulty dataset + expected km + fault list
  data/pings_clean.csv, data/ground_truth_clean.csv  same drivers, no injected faults
  fixtures/F_*.csv, fixtures/*.json                  hand-designed fixtures for the test cases

Ground truth is computed here independently of fixed.py: the generator knows
which pings are real and which are injected faults. Inside-zone length uses
Liang-Barsky clipping against the zone's bounding rectangle (Z1 is an
axis-aligned rectangle; this is asserted). fixed.py uses general polygon clipping instead.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
from datetime import datetime, timedelta, timezone

LABEL = "SYNTHETIC"
R = 6_371_000.0
HERE = os.path.dirname(os.path.abspath(__file__))
DEG_M = R * math.pi / 180  # metres per degree along the equator or a meridian
PING_COLUMNS = ["label", "driver_id", "ping_id", "ts_utc", "lon", "lat"]
GT_COLUMNS = ["label", "record_type", "driver_id", "local_date", "expected_km",
              "fault_type", "ping_id", "ref_ping_id", "ts_utc", "detail"]


# ------------------------------------------------------------------ geometry (independent)
def hav(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def zone_rect(zone_pts):
    lons = sorted({p[0] for p in zone_pts})
    lats = sorted({p[1] for p in zone_pts})
    assert len(lons) == 2 and len(lats) == 2, "generator ground truth needs an axis-aligned rectangle zone"
    return lons[0], lons[1], lats[0], lats[1]


def clipped_m(a, b, rect):
    """Liang-Barsky clip of a->b to the rectangle (boundary inclusive), measured with haversine."""
    xmin, xmax, ymin, ymax = rect
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if p == 0:
            if q < 0:
                return 0.0
        else:
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
    if t1 <= t0:
        return 0.0
    return hav(x0 + dx * t0, y0 + dy * t0, x0 + dx * t1, y0 + dy * t1)


def dist_to_route_m(lon, lat, route):
    """Planar distance in metres (equator-scale; fine for this tiny equatorial area)."""
    k = math.cos(math.radians(lat))
    best = math.inf
    for (ax, ay), (bx, by) in zip(route, route[1:]):
        ux, uy = (bx - ax) * k, by - ay
        wx, wy = (lon - ax) * k, lat - ay
        L2 = ux * ux + uy * uy
        t = 0 if L2 == 0 else max(0, min(1, (wx * ux + wy * uy) / L2))
        best = min(best, math.hypot(wx - t * ux, wy - t * uy) * DEG_M)
    return best


class RoutePath:
    """Position along an axis-aligned polyline by arc length in degrees."""

    def __init__(self, pts):
        self.pts = pts
        self.lens = [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(pts, pts[1:])]
        for (a, b) in zip(pts, pts[1:]):
            assert a[0] == b[0] or a[1] == b[1], "route segments must be axis-aligned"
        self.length = sum(self.lens)

    def at(self, s):
        s = min(max(s, 0.0), self.length)
        for (a, b), L in zip(zip(self.pts, self.pts[1:]), self.lens):
            if s <= L:
                f = 0 if L == 0 else s / L
                return (round(a[0] + (b[0] - a[0]) * f, 7), round(a[1] + (b[1] - a[1]) * f, 7))
            s -= L
        return tuple(self.pts[-1])


def reflect(s, L):
    """Triangle wave: bounce between 0 and L."""
    period = 2 * L
    s = s % period
    return s if s <= L else period - s


def iso(ts: datetime) -> str:
    if ts.microsecond:
        return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def local_day(ts: datetime) -> str:
    return (ts + timedelta(hours=9)).date().isoformat()


def write_csv(path, columns, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def fmt(x):
    return f"{x:.9f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


# ------------------------------------------------------------------------------ dataset
T0 = datetime(2026, 11, 7, tzinfo=timezone.utc)
SHIFTS = [  # (driver, start UTC). Comments give the reason for each start time.
    ("DRV-01", T0 + timedelta(hours=0, minutes=10)),
    ("DRV-02", T0 + timedelta(hours=2, minutes=30)),
    ("DRV-03", T0 + timedelta(hours=14, minutes=40)),   # crosses 15:00Z = 00:00 local
    ("DRV-04", T0 + timedelta(hours=23, minutes=45)),   # crosses 00:00Z (UTC date change, not a local cut)
    ("DRV-05", T0 + timedelta(days=1, hours=1)),
    ("DRV-06", T0 + timedelta(days=1, hours=5, minutes=15)),
    ("DRV-07", T0 + timedelta(days=1, hours=14, minutes=50)),  # crosses local midnight
    ("DRV-08", T0 + timedelta(days=1, hours=9)),
    ("DRV-09", T0 + timedelta(days=2, hours=3)),
    ("DRV-10", T0 + timedelta(days=2, hours=14, minutes=45)),  # crosses local midnight
    ("DRV-11", T0 + timedelta(days=2, hours=23, minutes=50)),  # crosses 00:00Z
    ("DRV-12", T0 + timedelta(hours=6)),                       # always clean (no faults)
]
FAULT_PLAN = {"OFFROAD_NOISE": 10, "SPEED_SPIKE": 8, "INTERVAL_GAP": 8,
              "DUPLICATE_EXACT": 10, "DUPLICATE_CONFLICT": 8, "LATE_PING": 10}


def build_dataset(seed, route_pts, zone_pts, faulty):
    rng = random.Random(seed)
    path = RoutePath(route_pts)
    rect = zone_rect(zone_pts)

    drivers = {}
    for drv, start in SHIFTS:
        n = rng.randint(190, 230)
        step = round(rng.uniform(0.0003, 0.0012), 7)
        s0 = rng.uniform(0, path.length)
        direction = rng.choice((1, -1))
        start = start + timedelta(seconds=10 * rng.randint(0, 5))
        pts = []
        for i in range(n):
            lon, lat = path.at(reflect(s0 + direction * step * i, path.length))
            pts.append({"driver_id": drv, "idx": i, "ping_id": str(i + 1),
                        "ts": start + timedelta(seconds=10 * i), "lon": lon, "lat": lat,
                        "s": reflect(s0 + direction * step * i, path.length)})
        drivers[drv] = pts

    faults = []
    removed, replaced = set(), set()      # (driver, idx)
    used = {d: set() for d in drivers}    # indices with a fault (kept 4 apart)

    def pick(drv_pool):
        for _ in range(1000):
            drv = rng.choice(drv_pool)
            n = len(drivers[drv])
            i = rng.randint(5, n - 7)
            if all(abs(i - j) >= 4 for j in used[drv]):
                used[drv].add(i)
                return drv, i
        raise RuntimeError("could not place fault")

    pool = [d for d, _ in SHIFTS if d != "DRV-12"]
    file_ops = []  # duplicates and late moves, applied when building file order
    if faulty:
        for ftype, count in FAULT_PLAN.items():
            for _ in range(count):
                drv, i = pick(pool)
                pts = drivers[drv]
                p = pts[i]
                if ftype == "INTERVAL_GAP":
                    k = rng.choice((1, 2))
                    for j in range(i, i + k):
                        removed.add((drv, j))
                    nxt = pts[i + k]
                    used[drv].update(range(i, i + k + 1))
                    faults.append({"fault_type": ftype, "driver_id": drv, "ping_id": nxt["ping_id"],
                                   "ts_utc": iso(nxt["ts"]),
                                   "detail": f"pings {','.join(pts[j]['ping_id'] for j in range(i, i + k))} "
                                             f"removed; interval {10 * (k + 1)} s"})
                elif ftype == "OFFROAD_NOISE":
                    for _ in range(100):
                        off = rng.uniform(150, 300) / DEG_M
                        ang = rng.uniform(0, 2 * math.pi)
                        lon = round(p["lon"] + off * math.cos(ang), 7)
                        lat = round(p["lat"] + off * math.sin(ang), 7)
                        d = dist_to_route_m(lon, lat, route_pts)
                        if d > 120:
                            break
                    else:
                        raise RuntimeError("no off-road point")
                    p["lon"], p["lat"] = lon, lat
                    replaced.add((drv, i))
                    faults.append({"fault_type": ftype, "driver_id": drv, "ping_id": p["ping_id"],
                                   "ts_utc": iso(p["ts"]), "detail": f"{d:.1f} m off route"})
                elif ftype == "SPEED_SPIKE":
                    prev = pts[i - 1]
                    for _ in range(100):
                        jump = rng.uniform(0.005, 0.009) * rng.choice((1, -1))
                        lon, lat = path.at(reflect(p["s"] + jump, path.length))
                        v = hav(prev["lon"], prev["lat"], lon, lat) / 10 * 3.6
                        v_next = hav(lon, lat, pts[i + 1]["lon"], pts[i + 1]["lat"]) / 10 * 3.6
                        if v > 170 and v_next > 170:
                            break
                    else:
                        raise RuntimeError("no spike")
                    p["lon"], p["lat"] = lon, lat
                    replaced.add((drv, i))
                    faults.append({"fault_type": ftype, "driver_id": drv, "ping_id": p["ping_id"],
                                   "ts_utc": iso(p["ts"]), "detail": f"{v:.1f} km/h from ping {prev['ping_id']}"})
                elif ftype in ("DUPLICATE_EXACT", "DUPLICATE_CONFLICT"):
                    file_ops.append((ftype, drv, i, rng.randint(1, 4)))
                elif ftype == "LATE_PING":
                    file_ops.append((ftype, drv, i, rng.randint(2, 5)))

    # ---- ground truth from the real pings only
    daily = {}
    for drv, pts in drivers.items():
        real = [p for p in pts if (drv, p["idx"]) not in removed and (drv, p["idx"]) not in replaced]
        for a, b in zip(real, real[1:]):
            day = local_day(a["ts"])
            daily[(drv, day)] = daily.get((drv, day), 0.0) + clipped_m((a["lon"], a["lat"]), (b["lon"], b["lat"]), rect)

    # ---- file rows: per-driver arrival order, then merge drivers by arrival time
    per_driver_rows = {}
    for drv, pts in drivers.items():
        rows = [dict(p) for p in pts if (drv, p["idx"]) not in removed]
        per_driver_rows[drv] = rows
    next_id = {d: 10001 for d in drivers}
    for ftype, drv, i, shift in file_ops:
        rows = per_driver_rows[drv]
        pos = next(k for k, r in enumerate(rows) if r["idx"] == i and not r.get("dup_of"))
        orig = rows[pos]
        if ftype == "LATE_PING":
            rows.pop(pos)
            rows.insert(min(pos + shift, len(rows)), orig)
            faults.append({"fault_type": ftype, "driver_id": drv, "ping_id": orig["ping_id"],
                           "ts_utc": iso(orig["ts"]), "detail": f"arrives {shift} rows late"})
            continue
        dup = dict(orig)
        dup["ping_id"] = str(next_id[drv])
        next_id[drv] += 1
        dup["dup_of"] = orig["ping_id"]
        if ftype == "DUPLICATE_CONFLICT":
            dup["lat"] = round(orig["lat"] + rng.choice((1, -1)) * rng.uniform(0.0002, 0.0004), 7)
        rows.insert(min(pos + shift + 1, len(rows)), dup)
        faults.append({"fault_type": ftype, "driver_id": drv, "ping_id": dup["ping_id"],
                       "ref_ping_id": orig["ping_id"], "ts_utc": iso(orig["ts"]),
                       "detail": "identical coordinates" if ftype == "DUPLICATE_EXACT" else
                       f"conflicting lat {dup['lat']} vs {orig['lat']}"})
    merged = []
    for drv, rows in per_driver_rows.items():
        latest = None
        for k, r in enumerate(rows):
            latest = r["ts"] if latest is None or r["ts"] > latest else latest
            merged.append((latest, drv, k, r))
    merged.sort(key=lambda t: (t[0], t[1], t[2]))
    out_rows = [{"label": LABEL, "driver_id": r["driver_id"], "ping_id": r["ping_id"], "ts_utc": iso(r["ts"]),
                 "lon": fmt(r["lon"]), "lat": fmt(r["lat"])} for _, _, _, r in merged]

    gt = [{"label": LABEL, "record_type": "DAILY_KM", "driver_id": d, "local_date": day,
           "expected_km": f"{m / 1000:.6f}"} for (d, day), m in sorted(daily.items())]
    for f in sorted(faults, key=lambda f: (f["fault_type"], f["driver_id"], int(f["ping_id"]))):
        gt.append({"label": LABEL, "record_type": "FAULT", **f})
    return out_rows, gt


# ----------------------------------------------------------------------------- fixtures
def _rows(driver, start, coords, step_s=10, ids=None):
    out = []
    for k, (lon, lat) in enumerate(coords):
        ts = start + timedelta(seconds=step_s * k) if not isinstance(step_s, list) else start + timedelta(seconds=step_s[k])
        out.append({"label": LABEL, "driver_id": driver, "ping_id": str(ids[k] if ids else k + 1),
                    "ts_utc": iso(ts), "lon": fmt(lon), "lat": fmt(lat)})
    return out


def on_eq(lons):
    return [(round(x, 9), 0.0) for x in lons]


def build_fixtures(fx_dir, seed):
    d7 = datetime(2026, 11, 7, tzinfo=timezone.utc)
    files = {}

    # ---- A/B: zone (TC-01..06, TC-10, TC-11, TC-15)
    z = []
    z += _rows("DRV-A", d7 + timedelta(hours=1), on_eq([0.0062 + 0.0002 * i for i in range(20)]))      # TC-01
    z += _rows("DRV-B", d7 + timedelta(hours=3), on_eq([0.0080 + 0.0002 * i for i in range(10)]))      # TC-02
    z += _rows("DRV-C", d7 + timedelta(hours=4), [(0.0110 + 0.0008 * i, 0.005) for i in range(10)])    # TC-03
    z += _rows("DRV-D", d7 + timedelta(hours=5), [(0.0080, 0.0)])                                      # TC-04
    z += _rows("DRV-E", d7 + timedelta(hours=6), [(0.0080, 0.0)] * 361)                                # TC-05
    z += _rows("DRV-F", d7 + timedelta(hours=8), on_eq([0.0080, 0.0090, 0.0100]) +                     # TC-06
               [(0.01, 0.0010), (0.01, 0.0025), (0.01, 0.0035), (0.01, 0.0045), (0.0110, 0.005), (0.0120, 0.005)])
    z += _rows("DRV-G", d7 + timedelta(hours=9),                                                       # TC-10
               [(0.0045, 0.0), (0.0055, 0.0), (0.0100, 0.0035), (0.0100, 0.0045)], step_s=[0, 10, 30, 40])
    z += _rows("DRV-H", d7 + timedelta(hours=10), on_eq(                                               # TC-11
        [0.0040, 0.0052, 0.0064, 0.0076, 0.0068, 0.0056, 0.0044, 0.0050, 0.0062, 0.0074]))
    z += _rows("DRV-I", d7 + timedelta(hours=11), on_eq([0.0050, 0.0065, 0.0080]))                     # TC-15
    z += _rows("DRV-J", d7 + timedelta(hours=12), on_eq([0.0062 + 0.0004 * i for i in range(5)]),       # TC-67
               step_s=[0, 10, 20.1, 30.09, 40.09])          # intervals 10, 10.1, 9.99, 10 s
    z += _rows("DRV-K", d7 + timedelta(hours=13), [(-0.0004, 0.0), (0.0, 0.0), (0.0004, 0.0)])        # TC-68 lon < 0
    z += _rows("DRV-L", d7 + timedelta(hours=14),                                                     # TC-68 lat < 0
               [(0.0070, 0.0), (0.0074, -0.0004), (0.0078, 0.0), (0.0082, 0.0)])
    files["F_ZONE.csv"] = z

    # ---- C: noise
    n = []
    a = on_eq([0.0062 + 0.0004 * i for i in range(10)])
    a[4] = (a[4][0], round(150 / DEG_M, 9))                                                            # TC-16/29
    n += _rows("DRV-A", d7 + timedelta(hours=1), a)
    b = on_eq([0.0062 + 0.0004 * i for i in range(10)])
    b[2] = (b[2][0], round(99 / DEG_M, 9))                                                             # TC-17
    b[5] = (b[5][0], round(101 / DEG_M, 9))
    n += _rows("DRV-B", d7 + timedelta(hours=2), b)
    c = on_eq([0.0062 + 0.0004 * i for i in range(8)])
    c[3] = (c[3][0], round(100 / DEG_M, 9))                                                            # TC-18
    n += _rows("DRV-C", d7 + timedelta(hours=3), c)
    n += _rows("DRV-D", d7 + timedelta(hours=4), [(0.0020, 0.0060)] +                                  # TC-19
               on_eq([0.0020, 0.0024, 0.0028, 0.0032]))
    n += _rows("DRV-E", d7 + timedelta(hours=5), [(0.001 + 0.0005 * i, 0.004) for i in range(7)])      # TC-20
    n += _rows("DRV-F", d7 + timedelta(hours=6), [(0.007 + 0.0004 * i, -0.004) for i in range(6)])     # TC-21 noise
    n += _rows("DRV-G", d7 + timedelta(hours=6), on_eq([0.0062 + 0.0004 * i for i in range(6)]))       # TC-21 valid
    jump160 = round(160 / 3.6 * 10 / DEG_M, 9)
    n += _rows("DRV-H", d7 + timedelta(hours=7), on_eq(                                                # TC-22/30
        [0.0056, 0.0060, 0.0060 + jump160, 0.0064, 0.0068, 0.0072]))
    # smallest 9-dp step whose speed is >= 150 km/h; it rounds to 150.000 (A12), so it must be kept
    jump150 = math.ceil(150 / 3.6 * 10 / DEG_M * 1e9) / 1e9
    n += _rows("DRV-I", d7 + timedelta(hours=8), on_eq(                                                # TC-23
        [0.0056, 0.0060, 0.0060 + jump150, 0.0099, 0.0100]))
    n += _rows("DRV-K", d7 + timedelta(hours=10), on_eq([0.0060, 0.0064]) + [(0.0100, 0.0035)] +       # TC-26
               on_eq([0.0068, 0.0072, 0.0076]))
    n += _rows("DRV-L", d7 + timedelta(hours=11), on_eq([0.0060, 0.0064]) + [(0.0068, 0.0045)] +       # TC-27/31
               on_eq([0.0072, 0.0076]))
    nn = on_eq([0.0062 + 0.0004 * i for i in range(6)])
    nn[2] = (nn[2][0], round(20 / DEG_M, 9))                                                           # RTC-04
    n += _rows("DRV-N", d7 + timedelta(hours=12), nn)
    jump1499 = round(149.9 / 3.6 * 10 / DEG_M, 9)                                                      # TC-66
    n += _rows("DRV-O", d7 + timedelta(hours=13), on_eq([0.0056, 0.0060, 0.0060 + jump1499, 0.0099, 0.0100]))
    files["F_NOISE.csv"] = n
    files["F_STATIONARY.csv"] = _rows("DRV-M", d7 + timedelta(hours=1), [(0.0080, 0.0)] * 1441)        # TC-28
    # NC-01: parked 1 h at (0.0080, 0) with GPS jitter up to 5 m. Own RNG so no other fixture changes.
    jrng = random.Random(seed + 1001)
    jit = []
    for _ in range(361):
        r, ang = 5.0 * math.sqrt(jrng.random()), jrng.uniform(0, 2 * math.pi)
        jit.append((round(0.0080 + r * math.cos(ang) / DEG_M, 9), round(r * math.sin(ang) / DEG_M, 9)))
    files["F_PARKED_JITTER.csv"] = _rows("DRV-P", d7 + timedelta(hours=2), jit)
    files["F_LONG.csv"] = _rows("DRV-J", d7 + timedelta(hours=8),                                      # TC-24
                                on_eq([0.05, 0.05 + round(100000 / DEG_M, 9)]), step_s=[0, 7200])

    # ---- D: duplicates (row order matters, so rows are listed explicitly)
    dup = []
    A = _rows("DRV-A", d7 + timedelta(hours=1), on_eq([0.0062 + 0.0004 * i for i in range(5)]))         # TC-32
    dup += A[:3] + [dict(A[2], ping_id="103")] + A[3:]
    B = _rows("DRV-B", d7 + timedelta(hours=2), on_eq([0.0062 + 0.0004 * i for i in range(5)]))         # TC-33/25
    dup += B[:3] + [dict(B[2], ping_id="103", lat="0.0003")] + B[3:]
    C = _rows("DRV-C", d7 + timedelta(hours=9), on_eq([0.0062, 0.0066, 0.0070]))                        # TC-34
    D = _rows("DRV-D", d7 + timedelta(hours=9), on_eq([0.0080, 0.0084, 0.0088]))
    for rc, rd in zip(C, D):
        dup += [rc, rd]
    E = _rows("DRV-E", d7 + timedelta(hours=3), on_eq([0.0062 + 0.0004 * i for i in range(6)]))         # TC-36/37
    dup += E[:4] + [dict(E[1], ping_id="102", lat="0.0004")] + E[4:]
    F = _rows("DRV-F", d7 + timedelta(hours=4), on_eq([0.0062 + 0.0004 * i for i in range(6)]))         # RTC-05
    dup += (F[:2] + [dict(F[1], ping_id="102", lat="0.0002")] + F[2:4] +
            [dict(F[3], ping_id="104", lat="0.0002"), dict(F[3], ping_id="105", lat="-0.0002")] + F[4:])
    G = _rows("DRV-G", d7 + timedelta(hours=8), on_eq([0.0070, 0.0070, 0.0074]))     # TC-69 new ts, same coords
    H = _rows("DRV-H", d7 + timedelta(hours=8), on_eq([0.0070, 0.0074, 0.0078]))     # TC-70 new ts, new coords
    dup += G + H
    files["F_DUPLICATES.csv"] = dup

    rng = random.Random(seed)                                                                          # TC-35
    base = _rows("DRV-A", d7 + timedelta(hours=1), on_eq([0.0040 + 0.0002 * i for i in range(40)]))
    raw = []
    for k, r in enumerate(base):
        raw.append(r)
        if rng.random() < 0.95:
            raw.append(dict(r, ping_id=str(1000 + k)))
    files["F_DUP_HALF_dedup.csv"] = base
    files["F_DUP_HALF_raw.csv"] = raw

    # ---- E: UTC and daily cut. Local midnight (UTC+9) is 15:00Z.
    dc = []
    dc += _rows("DRV-A", d7, on_eq([0.0070, 0.0071, 0.0072, 0.0073]),                                  # TC-39
                step_s=[14 * 3600 + 59 * 60 + 59.999, 15 * 3600, 16 * 3600 + 59 * 60 + 59.999, 17 * 3600])
    dc += _rows("DRV-B", d7 + timedelta(hours=14, minutes=59, seconds=45),                             # TC-40
                on_eq([0.0062, 0.0066, 0.0070, 0.0074]))
    dc += _rows("DRV-C", d7 + timedelta(hours=17), on_eq([0.0070, 0.0074, 0.0078]))                    # TC-43
    dc += _rows("DRV-D", d7 + timedelta(hours=16, minutes=30), on_eq([0.0070, 0.0074]))                # RTC-06
    e = []
    for day, lons in enumerate(([0.0070, 0.0074, 0.0078], [0.0078, 0.0074, 0.0070], [0.0070, 0.0074, 0.0078])):
        e += _rows("DRV-E", d7 + timedelta(days=day, hours=14, minutes=59, seconds=50), on_eq(lons),   # TC-42
                   ids=[day * 3 + 1, day * 3 + 2, day * 3 + 3])
    dc += e
    dc += _rows("DRV-F", d7 + timedelta(days=5, hours=2), on_eq([0.0070, 0.0074, 0.0078]))             # TC-51
    dc += _rows("DRV-G", d7 + timedelta(hours=23, minutes=59, seconds=55), on_eq([0.0070, 0.0074, 0.0078]))  # 00:00Z
    files["F_DAYCUT.csv"] = dc

    # ---- F: late and out-of-order
    late = []
    A = _rows("DRV-A", d7 + timedelta(hours=9), on_eq([0.0062 + 0.0004 * i for i in range(7)]))         # TC-45/49
    late += A[:3] + A[4:] + [A[3]]   # 09:00:30 ping arrives after the 09:01:00 ping
    B = _rows("DRV-B", d7 + timedelta(hours=10), on_eq([0.0060, 0.0071, 0.0082, 0.0093]) +             # TC-47
              [(0.01, 0.0004), (0.01, 0.0015)])
    late += B[:2] + B[3:] + [B[2]]
    C = _rows("DRV-C", d7 + timedelta(hours=11), on_eq([0.0062 + 0.0004 * i for i in range(6)]))        # TC-48
    D = _rows("DRV-D", d7 + timedelta(hours=11), on_eq([0.0080 + 0.0002 * i for i in range(6)]))
    late += [C[0], D[0], C[1], D[2], C[2], D[1], C[3], D[3], C[4], D[5], C[5], D[4]]
    files["F_LATE.csv"] = late

    # ---- I: intervals (A9)
    reg = on_eq([0.0062 + 0.0003 * i for i in range(13)])
    files["F_INTERVALS_regular.csv"] = _rows("DRV-A", d7 + timedelta(hours=1), reg)
    # same positions minus pings 5 and 6 (one 30 s gap); last ping sent 5 s early (one short interval)
    keep = [k for k in range(13) if k not in (4, 5)]
    irr_pts = [reg[k] for k in keep]
    irr_secs = [10 * k for k in keep]
    irr_secs[-1] -= 5
    irr_ids = [k + 1 for k in keep]
    files["F_INTERVALS_irregular.csv"] = _rows("DRV-A", d7 + timedelta(hours=1), irr_pts, step_s=irr_secs, ids=irr_ids)

    # ---- invalid input (each file is rejected as a whole)
    with open(os.path.join(fx_dir, "F_BOUNDARY.csv"), newline="", encoding="utf-8") as fh:
        bnd = list(csv.DictReader(fh))
    for r in bnd:
        r["label"] = LABEL
    files["F_INVALID_no_z.csv"] = [dict(r) for r in bnd]
    files["F_INVALID_no_z.csv"][2]["ts_utc"] = "2026-11-07 09:00:00"
    files["F_INVALID_no_z.csv"][5]["ts_utc"] = "2026-11-07T01:00:50"
    files["F_INVALID_offset.csv"] = [dict(r) for r in bnd]
    files["F_INVALID_offset.csv"][3]["ts_utc"] = "2026-11-07T10:00:30+09:00"
    files["F_INVALID_swapped.csv"] = [dict(r, lon=r["lat"], lat=r["lon"]) for r in bnd]
    files["F_INVALID_range.csv"] = [dict(r) for r in bnd]
    files["F_INVALID_range.csv"][4]["lat"] = "91.0"
    files["F_INVALID_range.csv"][6]["lon"] = "-181.5"
    # TC-71: the TC-69 and TC-70 drivers both send a ping stamped 08:59:99 (second 99 does not exist)
    bad = "2026-11-07T08:59:99Z"
    files["F_INVALID_bad_second.csv"] = [G[0], dict(G[1], ts_utc=bad), H[0], dict(H[1], ts_utc=bad)]

    for name, rows in files.items():
        write_csv(os.path.join(fx_dir, name), PING_COLUMNS, rows)
    write_csv(os.path.join(fx_dir, "F_INVALID_missing_col.csv"), ["label", "driver_id", "ping_id", "ts_utc", "lon"],
              [{k: v for k, v in r.items() if k != "lat"} for r in bnd])

    with open(os.path.join(HERE, "data", "zone_Z1.json"), encoding="utf-8") as fh:
        z1 = json.load(fh)
    geo = {
        "zone_Z1_swapped.json": {"label": LABEL, "name": "Z1 with lat/lon swapped (TC-13)",
                                 "coordinates": [[p[1], p[0]] for p in z1["coordinates"]]},
        "route_LONG.json": {"label": LABEL, "name": "LONG (TC-24)", "coordinates": [[0.0, 0.0], [1.0, 0.0]]},
        "zone_LONG.json": {"label": LABEL, "name": "LONG zone (TC-24)",
                           "coordinates": [[0.0, -0.01], [1.0, -0.01], [1.0, 0.01], [0.0, 0.01], [0.0, -0.01]]},
    }
    for name, doc in geo.items():
        with open(os.path.join(fx_dir, name), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
    return sorted(files) + ["F_INVALID_missing_col.csv"] + sorted(geo)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate the SYNTHETIC dataset, ground truth and fixtures.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--fixtures-dir", default=os.path.join(HERE, "fixtures"))
    ap.add_argument("--no-fixtures", action="store_true", help="only write the dataset")
    args = ap.parse_args(argv)

    with open(os.path.join(HERE, "data", "route_R1.json"), encoding="utf-8") as fh:
        route = [tuple(p) for p in json.load(fh)["coordinates"]]
    with open(os.path.join(HERE, "data", "zone_Z1.json"), encoding="utf-8") as fh:
        zone = [tuple(p) for p in json.load(fh)["coordinates"]]

    for faulty, suffix in ((True, ""), (False, "_clean")):
        rows, gt = build_dataset(args.seed, route, zone, faulty)
        write_csv(os.path.join(args.data_dir, f"pings{suffix}.csv"), PING_COLUMNS, rows)
        write_csv(os.path.join(args.data_dir, f"ground_truth{suffix}.csv"), GT_COLUMNS, gt)
        n_f = sum(r["record_type"] == "FAULT" for r in gt)
        print(f"pings{suffix}.csv: {len(rows)} rows, {len({r['driver_id'] for r in rows})} drivers; "
              f"ground_truth{suffix}.csv: {len(gt) - n_f} driver-days, {n_f} faults")
    if not args.no_fixtures:
        names = build_fixtures(args.fixtures_dir, args.seed)
        print(f"fixtures: {len(names)} files in {os.path.relpath(args.fixtures_dir, HERE)}")


if __name__ == "__main__":
    main()
