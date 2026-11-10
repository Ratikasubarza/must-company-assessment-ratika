"""Test helpers: paths and an independent expected-value calculator (SYNTHETIC data).

Expected distances in the tests are written as degrees of travel along the
equator or the meridian lon 0.010, times DEG_M. Haversine is exact on those lines.
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FX = os.path.join(ROOT, "fixtures")
DATA = os.path.join(ROOT, "data")
R = 6_371_000.0
DEG_M = R * math.pi / 180          # 111194.92664 m per degree
Z1 = (0.006, 0.012, -0.003, 0.003)  # lon_min, lon_max, lat_min, lat_max
KM_TOL = 1e-6                       # 1 mm: fixtures are exact, so unit tests are stricter than A11


def fx(name):
    return os.path.join(FX, name)


def hav(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def clip_m(a, b, rect=Z1):
    """Liang-Barsky clip to an axis-aligned rectangle, boundary inclusive."""
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
            t0, t1 = (max(t0, r), t1) if p < 0 else (t0, min(t1, r))
    return 0.0 if t1 <= t0 else hav(x0 + dx * t0, y0 + dy * t0, x0 + dx * t1, y0 + dy * t1)


def path_inside_km(points, rect=Z1):
    return sum(clip_m(a, b, rect) for a, b in zip(points, points[1:])) / 1000


def deg_km(deg):
    return deg * DEG_M / 1000


def driver_km(res, driver):
    return res.total_km.get(driver, 0.0)


def status(res, driver, ping_id):
    return res.ping_status[(driver, str(ping_id))]["status"]
