"""qa_check.py - QA checker for the GPS distance pipeline (SYNTHETIC data).

Compares a pipeline's daily report with ground_truth.csv per driver per local
day (tolerance A11), scores fault detection (precision / recall) against the
injected-fault list, and builds its own ping-interval summary from the pings file.

It does not import fixed.py or old_reference.py: all checks are written separately here.

Exit codes: 0 = all checks pass, 1 = one or more check failures, 2 = invalid input.

Example:
    python qa_check.py --pings data/pings.csv --ground-truth data/ground_truth.csv \\
        --report out/fixed/daily_km.csv --events out/fixed/events.csv --out results/qa_fixed
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from datetime import datetime, timezone

TOLERANCE_KM = 0.001  # A11
R = 6_371_000.0
OFFROAD_M = 100.0
PING_COLUMNS = ("driver_id", "ping_id", "ts_utc", "lon", "lat")
REPORT_COLUMNS = ("driver_id", "local_date", "km")
GT_COLUMNS = ("record_type", "driver_id", "local_date", "expected_km", "fault_type", "ping_id", "ref_ping_id")
EVENT_COLUMNS = ("event_type", "driver_id", "ping_id")
FAULT_TO_EVENT = {
    "OFFROAD_NOISE": "DROPPED_OFFROAD",
    "SPEED_SPIKE": "DROPPED_SPEED",
    "DUPLICATE_EXACT": "DUPLICATE_DROPPED",
    "DUPLICATE_CONFLICT": "DUPLICATE_DROPPED",
    "LATE_PING": "LATE_ARRIVAL",
    "INTERVAL_GAP": "INTERVAL_WARNING",
}
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
OFFSET_RE = re.compile(r"[+-]\d{2}:?\d{2}$")
HERE = os.path.dirname(os.path.abspath(__file__))


class CheckerInputError(Exception):
    pass


def _read_csv(path, required, what):
    if not os.path.exists(path):
        raise CheckerInputError(f"{what} {path}: file not found")
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in required if c not in (rd.fieldnames or [])]
        if missing:
            raise CheckerInputError(f"{what} {path}: missing column(s) {', '.join(missing)}")
        return [(rd.line_num, r) for r in rd]


def _ts(text):
    s = (text or "").strip()
    if not s.endswith("Z"):
        if OFFSET_RE.search(s):
            raise ValueError(f"timestamp {text!r} has a UTC offset (only Z is accepted)")
        raise ValueError(f"timestamp {text!r} has no Z suffix")
    if not TS_RE.match(s):
        raise ValueError(f"timestamp {text!r} is malformed")
    try:
        base = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:  # e.g. second 99, month 13, 31 November
        raise ValueError(f"timestamp {text!r} is not a valid date/time")
    return base.replace(tzinfo=timezone.utc).timestamp() + (float("0" + s[19:-1]) if len(s) > 20 else 0.0)


def _route_dist_m(lon, lat, route):
    k = math.cos(math.radians(lat))
    m_per_deg = R * math.pi / 180
    best = math.inf
    for (ax, ay), (bx, by) in zip(route, route[1:]):
        ux, uy, wx, wy = (bx - ax) * k, by - ay, (lon - ax) * k, lat - ay
        L2 = ux * ux + uy * uy
        t = 0 if L2 == 0 else max(0, min(1, (wx * ux + wy * uy) / L2))
        best = min(best, math.hypot(wx - t * ux, wy - t * uy) * m_per_deg)
    return best


def validate_pings(path, route):
    rows = _read_csv(path, PING_COLUMNS, "pings")
    errors, pings = [], []
    for line, r in rows:
        probs = []
        try:
            t = _ts(r["ts_utc"])
        except ValueError as exc:
            probs.append(str(exc))
            t = None
        coords = []
        for name, lo, hi in (("lon", -180, 180), ("lat", -90, 90)):
            try:
                v = float(r[name])
                if not math.isfinite(v) or not lo <= v <= hi:
                    raise ValueError
                coords.append(v)
            except (TypeError, ValueError):
                probs.append(f"{name} {r[name]!r} out of range [{lo}, {hi}] or not a number")
        if not (r["driver_id"] or "").strip() or not (r["ping_id"] or "").strip():
            probs.append("empty driver_id or ping_id")
        if probs:
            errors.append(f"line {line}: " + "; ".join(probs))
        else:
            pings.append({"driver_id": r["driver_id"].strip(), "ping_id": r["ping_id"].strip(),
                          "t": t, "lon": coords[0], "lat": coords[1]})
    if errors:
        raise CheckerInputError(f"pings {path}: {len(errors)} invalid row(s):\n  " + "\n  ".join(errors[:30]))
    if pings:
        near = sum(_route_dist_m(p["lon"], p["lat"], route) <= OFFROAD_M for p in pings) / len(pings)
        near_sw = sum(_route_dist_m(p["lat"], p["lon"], route) <= OFFROAD_M for p in pings) / len(pings)
        if near < 0.5 and near_sw >= 0.5:
            raise CheckerInputError(f"pings {path}: lat/lon look swapped ({near:.0%} of pings near the route "
                                    f"as given, {near_sw:.0%} after swapping)")
    return pings


def interval_summary(pings):
    """Per driver: deduplicate on (driver, ts), sort, classify each interval against 10 s."""
    by = {}
    for p in pings:
        by.setdefault(p["driver_id"], {}).setdefault(p["t"], p)
    summary, gaps = [], []
    for drv in sorted(by):
        seq = sorted(by[drv].values(), key=lambda p: p["t"])
        reg = gap = short = 0
        for a, b in zip(seq, seq[1:]):
            dt = round(b["t"] - a["t"], 6)
            if dt == 10:
                reg += 1
            elif dt > 10:
                gap += 1
                gaps.append((drv, b["ping_id"], dt))
            else:
                short += 1
        summary.append({"driver_id": drv, "pings": len(seq), "intervals": max(0, len(seq) - 1),
                        "regular_10s": reg, "gaps": gap, "short": short})
    return summary, gaps


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="QA checker: compares a pipeline daily report with ground truth per driver per "
                    f"local day (tolerance {TOLERANCE_KM} km, A11), scores fault detection and "
                    "summarises ping intervals. Exit 0 = pass, 1 = check failure, 2 = invalid input.")
    ap.add_argument("--pings", required=True, help="pings CSV the pipeline was run on (validated)")
    ap.add_argument("--ground-truth", required=True, help="ground_truth.csv (DAILY_KM and FAULT rows)")
    ap.add_argument("--report", required=True, help="pipeline daily_km.csv (driver_id, local_date, km)")
    ap.add_argument("--events", help="pipeline events.csv; enables fault-detection scoring")
    ap.add_argument("--route", default=os.path.join(HERE, "data", "route_R1.json"),
                    help="route JSON used for the lat/lon swap check")
    ap.add_argument("--tolerance-km", type=float, default=TOLERANCE_KM)
    ap.add_argument("--out", help="directory for qa_daily.csv, qa_faults.csv, qa_intervals.csv, qa_summary.txt")
    ap.add_argument("--note", help="one line printed at the top of the report and qa_summary.txt "
                                   "(e.g. that a FAIL is the expected outcome); does not change any check")
    args = ap.parse_args(argv)

    try:
        with open(args.route, encoding="utf-8") as fh:
            route = [tuple(map(float, p)) for p in json.load(fh)["coordinates"]]
        pings = validate_pings(args.pings, route)
        gt_rows = _read_csv(args.ground_truth, GT_COLUMNS, "ground truth")
        rep_rows = _read_csv(args.report, REPORT_COLUMNS, "report")
        ev_rows = _read_csv(args.events, EVENT_COLUMNS, "events") if args.events else None
        expected, faults = {}, []
        for line, r in gt_rows:
            if r["record_type"] == "DAILY_KM":
                expected[(r["driver_id"], r["local_date"])] = float(r["expected_km"])
            elif r["record_type"] == "FAULT":
                faults.append(r)
            else:
                raise CheckerInputError(f"ground truth line {line}: unknown record_type {r['record_type']!r}")
        actual = {}
        for line, r in rep_rows:
            try:
                km = float(r["km"])
            except ValueError:
                raise CheckerInputError(f"report line {line}: km {r['km']!r} is not a number")
            if not math.isfinite(km):
                raise CheckerInputError(f"report line {line}: km is {r['km']!r}")
            key = (r["driver_id"], r["local_date"])
            if key in actual:
                raise CheckerInputError(f"report line {line}: duplicate row for {key}")
            actual[key] = km
    except (CheckerInputError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"INPUT ERROR: {exc}", file=sys.stderr)
        return 2

    failures = []
    daily_rows = []
    for key in sorted(set(expected) | set(actual)):
        exp, act = expected.get(key, 0.0), actual.get(key, 0.0)  # A15: absent row = 0 km
        diff = act - exp
        ok = abs(diff) <= args.tolerance_km + 1e-12
        daily_rows.append({"driver_id": key[0], "local_date": key[1], "expected_km": f"{exp:.6f}",
                           "actual_km": f"{act:.6f}", "diff_km": f"{diff:+.6f}", "result": "PASS" if ok else "FAIL"})
        if not ok:
            failures.append(f"daily km {key[0]} {key[1]}: expected {exp:.6f}, got {act:.6f} (diff {diff:+.6f})")

    fault_rows, scores = [], {}
    if ev_rows is not None:
        exp_set = {(FAULT_TO_EVENT[f["fault_type"]], f["driver_id"], f["ping_id"]) for f in faults}
        exp_set |= {("DUPLICATE_CONFLICT", f["driver_id"], f["ref_ping_id"]) for f in faults
                    if f["fault_type"] == "DUPLICATE_CONFLICT"}
        scored_types = set(FAULT_TO_EVENT.values()) | {"DUPLICATE_CONFLICT"}
        got_set = {(r["event_type"], r["driver_id"], r["ping_id"]) for _, r in ev_rows if r["event_type"] in scored_types}
        for et in sorted(scored_types):
            e = {x for x in exp_set if x[0] == et}
            g = {x for x in got_set if x[0] == et}
            tp, fp, fn = len(e & g), len(g - e), len(e - g)
            scores[et] = (tp, fp, fn)
        for x in sorted(exp_set | got_set):
            status = "TP" if x in exp_set and x in got_set else ("FN" if x in exp_set else "FP")
            fault_rows.append({"event_type": x[0], "driver_id": x[1], "ping_id": x[2], "match": status})
            if status != "TP":
                failures.append(f"fault detection {status}: {x[0]} driver {x[1]} ping {x[2]}")

    interval_rows, gaps = interval_summary(pings)
    gt_gaps = {(f["driver_id"], f["ping_id"]) for f in faults if f["fault_type"] == "INTERVAL_GAP"}
    found_gaps = {(d, p) for d, p, _ in gaps}
    if faults or found_gaps:  # ground truth must describe every gap present in the pings file
        for d, p in sorted(found_gaps - gt_gaps):
            failures.append(f"interval gap at driver {d} ping {p} is not in ground truth")
        for d, p in sorted(gt_gaps - found_gaps):
            failures.append(f"ground truth gap at driver {d} ping {p} not found in pings")

    tp = sum(s[0] for s in scores.values())
    fp = sum(s[1] for s in scores.values())
    fn = sum(s[2] for s in scores.values())
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    lines = ([f"NOTE: {args.note}"] if args.note else []) + [
        "QA CHECK (SYNTHETIC data)",
        f"pings: {args.pings} ({len(pings)} rows)   report: {args.report}",
        f"daily rows compared: {len(daily_rows)}   tolerance: {args.tolerance_km} km   "
        f"failed: {sum(r['result'] == 'FAIL' for r in daily_rows)}",
    ]
    if ev_rows is not None:
        lines.append(f"fault detection: injected {len(faults)}, TP {tp}, FP {fp}, FN {fn}, "
                     f"precision {precision:.3f}, recall {recall:.3f}")
        for et, (a, b, c) in sorted(scores.items()):
            lines.append(f"  {et:20s} TP {a:3d}  FP {b:3d}  FN {c:3d}")
    lines.append("interval summary (violations = gaps + short intervals):")
    for r in interval_rows:
        lines.append(f"  {r['driver_id']:8s} pings {r['pings']:5d}  regular {r['regular_10s']:5d}  "
                     f"gaps {r['gaps']:3d}  short {r['short']:3d}")
    lines.append(f"interval violations: {len(gaps) + sum(r['short'] for r in interval_rows)}")
    for d, p, dt in gaps:
        lines.append(f"  GAP driver {d} ping {p}: {dt:g} s")
    lines.append(f"RESULT: {'PASS' if not failures else 'FAIL'} ({len(failures)} failure(s))")
    lines += ["  " + f for f in failures[:100]]
    text = "\n".join(lines)
    print(text)

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        for name, rows in (("qa_daily.csv", daily_rows), ("qa_faults.csv", fault_rows),
                           ("qa_intervals.csv", interval_rows)):
            with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8") as fh:
                if rows:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
                    w.writeheader()
                    w.writerows(rows)
        with open(os.path.join(args.out, "qa_summary.txt"), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
