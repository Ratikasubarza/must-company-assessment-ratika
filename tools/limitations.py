"""tools/limitations.py - measure what fixed.py deliberately does NOT handle (SYNTHETIC data).

Each item builds a small SYNTHETIC input (temporary files, nothing added to fixtures/ or the
pytest suite), runs fixed.py on it, and records the measured number. Writes results/limitations.csv.

    python tools/limitations.py
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import fixed  # noqa: E402
from generate_data import clipped_m, hav  # noqa: E402  (independent Liang-Barsky + haversine)

DEG_M = fixed.R_EARTH_M * 3.141592653589793 / 180
T0 = datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc)
TMP = tempfile.mkdtemp(prefix="limitations_")
ROWS = []


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def pings_file(name, rows):
    """rows: (driver, ping_id, datetime, lon, lat)"""
    p = os.path.join(TMP, name)
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["label", "driver_id", "ping_id", "ts_utc", "lon", "lat"])
        for d, i, t, lon, lat in rows:
            w.writerow(["SYNTHETIC", d, i, iso(t), f"{lon:.9f}", f"{lat:.9f}"])
    return p


def track(lons_lats, start=T0, step=10, driver="DRV-L"):
    return [(driver, str(k + 1), start + timedelta(seconds=step * k), lo, la) for k, (lo, la) in enumerate(lons_lats)]


def add(lid, name, scenario, value, unit, compare, consequence):
    ROWS.append({"id": lid, "limitation": name, "scenario": scenario, "measured": value, "unit": unit,
                 "compared_with": compare, "consequence": consequence})
    print(f"{lid} {name}: {value} {unit} ({compare})")


def km(res, d="DRV-L"):
    return round(res.total_km.get(d, 0.0), 6)


def main():
    # L01 parked jitter
    r = fixed.run_file(os.path.join(HERE, "fixtures", "F_PARKED_JITTER.csv"))
    add("L01", "Parked GPS jitter is counted as distance",
        "fixtures/F_PARKED_JITTER.csv: parked 1 h inside Z1, 361 pings, each within 5 m of one point",
        km(r, "DRV-P"), "km", "true distance 0 km", "advertiser billed, driver paid for not moving")

    # L02 zig-zag inside the 100 m corridor
    pts = [(0.0062 + 0.0004 * k, 0.0008 if k % 2 == 0 else -0.0008) for k in range(10)]
    r = fixed.run_file(pings_file("l02.csv", track(pts)))
    kept = sum(v["status"] == "ACCEPTED" for v in r.ping_status.values())
    along = round(0.0036 * DEG_M / 1000, 6)
    add("L02", "Zig-zag inside the 100 m corridor is counted in full",
        f"10 pings 0.0004 deg apart along R1 inside Z1, alternating 89 m either side of the road; {kept}/10 kept",
        km(r), "km", f"along-road distance {along} km (+{round((km(r) / along - 1) * 100, 1)}%)",
        "no filter for lateral wander within 100 m")

    # L03 3-hour gap bridged as a straight line
    rows = [("DRV-L", "1", T0, 0.0070, 0.0), ("DRV-L", "2", T0 + timedelta(hours=3), 0.0100, 0.0025)]
    r = fixed.run_file(pings_file("l03.csv", rows))
    v = r.ping_status[("DRV-L", "2")]["speed_kmh"]
    road = round((0.0030 + 0.0025) * DEG_M / 1000, 6)
    add("L03", "A 3-hour gap is bridged as one straight segment",
        f"ping at (0.0070, 0), next ping 3 h later at (0.0100, 0.0025); implied speed {v} km/h, so accepted",
        km(r), "km", f"shortest along-road route {road} km; real route in 3 h unknown",
        "unknown real distance replaced by a straight chord; no gap limit")

    # L04 spike on the first ping
    pts = [(0.0200, 0.005)] + [(0.0062 + 0.0004 * k, 0.0) for k in range(10)]
    r = fixed.run_file(pings_file("l04.csv", track(pts)))
    dropped = sum(v["status"] == "DROPPED_SPEED" for v in r.ping_status.values())
    clean = round(0.0036 * DEG_M / 1000, 6)
    add("L04", "A spike on the first ping becomes the speed anchor",
        f"first ping on R1's far end (0.0200, 0.005), then 10 normal pings inside Z1; {dropped} valid pings dropped as too fast",
        km(r), "km", f"{clean} km without the spike", "valid pings lost until the time gap makes the spike look reachable (A21)")

    # L05 duplicate whose kept copy is noise
    good = [(0.0090, 0.0), (0.0095, 0.0), (0.0100, 0.0), (0.0100, 0.0005), (0.0100, 0.0010)]
    rows = track(good)
    noisy = ("DRV-L", "103", rows[2][2], 0.0100, -0.0015)          # same timestamp as ping 3, 167 m off road
    r = fixed.run_file(pings_file("l05.csv", rows[:2] + [noisy, rows[2]] + rows[3:]))
    r_ok = fixed.run_file(pings_file("l05_ok.csv", rows))
    add("L05", "A duplicate whose first copy is noise loses the good copy",
        "ping 3 sent twice at the same second: first copy 167 m off road, second copy on R1 (corner); "
        f"status first copy {r.ping_status[('DRV-L', '103')]['status']}, good copy {r.ping_status[('DRV-L', '3')]['status']}",
        km(r), "km", f"{km(r_ok)} km if the good copy were kept", "A6 keeps the first copy, A3 then drops it; the corner is cut")

    # L06 midnight-crossing segments go to the start day (full dataset)
    r = fixed.run_file(os.path.join(HERE, "data", "pings.csv"))
    ts = {k: fixed.parse_ts_utc(v["ts_utc"]) for k, v in r.ping_status.items()}
    n, total_m, after_m = 0, 0.0, 0.0
    for s in r.segments:
        a, b = ts[(s["driver_id"], s["from_ping"])], ts[(s["driver_id"], s["to_ping"])]
        if fixed.local_date(a) != fixed.local_date(b):
            midnight = datetime.fromisoformat(fixed.local_date(b)).replace(tzinfo=timezone.utc) - timedelta(hours=9)
            n += 1
            total_m += s["inside_m"]
            after_m += s["inside_m"] * (b - midnight).total_seconds() / (b - a).total_seconds()
    # In data/pings.csv pings sit on a 10 s grid, so crossing segments END exactly at 15:00:00Z (share 0).
    # F_DAYCUT DRV-B has a segment that really straddles midnight: 14:59:55Z -> 15:00:05Z.
    rb = fixed.run_file(os.path.join(HERE, "fixtures", "F_DAYCUT.csv"))
    tsb = {k: fixed.parse_ts_utc(v["ts_utc"]) for k, v in rb.ping_status.items()}
    seg = next(s for s in rb.segments if s["driver_id"] == "DRV-B"
               and fixed.local_date(tsb[("DRV-B", s["from_ping"])]) != fixed.local_date(tsb[("DRV-B", s["to_ping"])]))
    a, b = tsb[("DRV-B", seg["from_ping"])], tsb[("DRV-B", seg["to_ping"])]
    midnight = datetime.fromisoformat(fixed.local_date(b)).replace(tzinfo=timezone.utc) - timedelta(hours=9)
    straddle = seg["inside_m"] * (b - midnight).total_seconds() / (b - a).total_seconds() / 1000
    add("L06", "A segment crossing local midnight goes wholly to the start day",
        f"fixtures/F_DAYCUT.csv DRV-B segment {a.strftime('%H:%M:%S')}Z -> {b.strftime('%H:%M:%S')}Z "
        f"({seg['inside_m'] / 1000:.6f} km inside Z1) is booked on {fixed.local_date(a)}. "
        f"In data/pings.csv {n} segments cross 00:00 UTC+9 ({total_m / 1000:.6f} km inside Z1) but all end exactly at "
        f"15:00:00Z, so their after-midnight share is {after_m / 1000:.6f} km",
        round(straddle, 6), "km", "time-proportional share driven after midnight but booked on the previous day (A8)",
        "by design under A8; the 10 s grid in data/pings.csv hides it")

    # L07 (0,0) lies on R1
    route = fixed.load_route()
    d00 = fixed.distance_to_route_m(0.0, 0.0, route)
    near = [(0.0004, 0.0), (0.0008, 0.0), (0.0, 0.0), (0.0012, 0.0)]
    r1 = fixed.run_file(pings_file("l07a.csv", track(near)))
    far = [(0.0070, 0.0), (0.0074, 0.0), (0.0, 0.0), (0.0078, 0.0)]
    r2 = fixed.run_file(pings_file("l07b.csv", track(far)))
    add("L07", "A (0,0) 'null island' ping lies on R1 and is never off-road",
        f"distance of (0,0) to R1 = {d00} m; near R1's start the (0,0) ping is {r1.ping_status[('DRV-L', '3')]['status']}; "
        f"inside Z1 it is {r2.ping_status[('DRV-L', '3')]['status']} only by the speed filter",
        d00, "m off road", "any real GPS null fix would be kept if speed allows", "R1 starts at (0,0); real routes rarely do")

    # L08 everything sits at lat 0
    shift = 60.0
    geo = {}
    for name in ("route_R1", "zone_Z1"):
        doc = json.load(open(os.path.join(HERE, "data", f"{name}.json")))
        doc["coordinates"] = [[x, y + shift] for x, y in doc["coordinates"]]
        geo[name] = os.path.join(TMP, f"{name}_lat60.json")
        json.dump(doc, open(geo[name], "w"))
    bnd = list(csv.DictReader(open(os.path.join(HERE, "fixtures", "F_BOUNDARY.csv"))))
    rows = [("DRV-A", r_["ping_id"], fixed.parse_ts_utc(r_["ts_utc"]), float(r_["lon"]), float(r_["lat"]) + shift) for r_ in bnd]
    r60 = fixed.run_file(pings_file("l08.csv", rows), geo["route_R1"], geo["zone_Z1"])
    rect = (0.006, 0.012, shift - 0.003, shift + 0.003)
    pts = [(x[3], x[4]) for x in rows]
    indep = sum(clipped_m(a, b, rect) for a, b in zip(pts, pts[1:])) / 1000
    r0 = fixed.run_file(os.path.join(HERE, "fixtures", "F_BOUNDARY.csv"))
    add("L08", "All geometry and tests sit at latitude 0",
        f"F_BOUNDARY, R1 and Z1 moved to lat 60 N: fixed.py {km(r60, 'DRV-A')} km vs independent "
        f"Liang-Barsky + haversine {indep:.6f} km (at lat 0: {km(r0, 'DRV-A')} km)",
        round(abs(km(r60, 'DRV-A') - indep), 6), "km difference", "fixed.py vs independent calculation at lat 60",
        "longitude scaling (cos lat) is never exercised by the test suite; only this measurement covers it")

    # L09 one bad row rejects the whole file
    src = list(csv.DictReader(open(os.path.join(HERE, "data", "pings.csv"))))
    src[100]["ts_utc"] = src[100]["ts_utc"].rstrip("Z")
    p = os.path.join(TMP, "l09.csv")
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(src[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(src)
    full = fixed.run_file(os.path.join(HERE, "data", "pings.csv"))
    try:
        fixed.run_file(p)
        outcome = "accepted"
    except fixed.InputError as exc:
        outcome = f"rejected ({len(exc.errors)} problem)"
    add("L09", "One bad row rejects the whole file",
        f"data/pings.csv with the Z removed from 1 of {len(src)} rows: {outcome}, no output",
        round(sum(full.total_km.values()), 6), "km withheld", f"{len(src)} rows and 12 drivers held back by 1 row (A17)",
        "safe (no wrong pay) but nobody is paid until the file is fixed")

    # L10 late pings after the daily cut
    rows3 = [r_ for r_ in src if r_["driver_id"] == "DRV-03"]
    cut = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)
    day1 = [r_ for r_ in rows3 if fixed.parse_ts_utc(r_["ts_utc"]) < cut]
    late = day1[-6:]  # the last minute before the cut arrives after the report is published
    mk = lambda rs: pings_file(f"l10_{len(rs)}.csv", [("DRV-03", x["ping_id"], fixed.parse_ts_utc(x["ts_utc"]), float(x["lon"]), float(x["lat"])) for x in rs])
    published = fixed.run_file(mk([x for x in rows3 if x not in late])).daily_km.get(("DRV-03", "2026-11-07"), 0.0)
    final = fixed.run_file(mk(rows3)).daily_km.get(("DRV-03", "2026-11-07"), 0.0)
    add("L10", "Late pings after the daily cut change a day already reported",
        f"DRV-03, local day 2026-11-07: its last 6 pings before 15:00Z arrive after the report is published; "
        f"published {published:.6f} km, after re-run {final:.6f} km",
        round(final - published, 6), "km", "no restatement or versioning of a published day",
        "batch re-run silently changes a closed day")

    # L11 the checker needs generator ground truth
    gt = os.path.join(TMP, "gt_empty.csv")
    open(gt, "w").write("label,record_type,driver_id,local_date,expected_km,fault_type,ping_id,ref_ping_id,ts_utc,detail\n")
    out = os.path.join(TMP, "fixed_out")
    fixed.write_reports(full, out)
    q = subprocess.run([sys.executable, os.path.join(HERE, "qa_check.py"), "--pings", os.path.join(HERE, "data", "pings.csv"),
                        "--ground-truth", gt, "--report", os.path.join(out, "daily_km.csv")], capture_output=True, text=True)
    failed = next(l for l in q.stdout.splitlines() if l.startswith("daily rows compared"))
    add("L11", "qa_check can only judge km against generator ground truth",
        f"correct fixed.py output for data/pings.csv checked against a ground truth with no DAILY_KM rows: exit {q.returncode}; {failed}",
        q.returncode, "exit code", "on real data there is no ground truth, so km cannot be verified this way",
        "real-data QA needs another oracle (e.g. a second implementation or invariants)")

    path = os.path.join(HERE, "results", "limitations.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ROWS[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(ROWS)
    print(f"wrote results/limitations.csv ({len(ROWS)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
