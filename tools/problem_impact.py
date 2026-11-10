"""tools/problem_impact.py - measure each problem group of planted bugs on data/pings.csv (SYNTHETIC).

For every group: old_reference.py with ONLY that group's bugs on, compared with old_reference.py with
no bugs on (which gives the same daily km as fixed.py; checked below and printed). Writes:

  results/problem_impact.csv        one row per group (+ "all 17 bugs"):
      total km change, driver-days off by more than 1 m (counted over the UNION of driver-days in
      both outputs), km over / km under, gross km wrong, worst driver-day
  results/problem_examples.csv      per group, the worst driver-day with its evidence: the qa_check
      daily row (old with only that group on, checked against data/ground_truth.csv), the
      before_after.csv attribution for that driver-day, and the ping_status / events rows that differ
  results/daycut_before_after.csv   before = old with ONLY BUG-14/15 on, after = fixed.py, with the
      ground truth and an "after = ground truth" check per driver per local day, per-driver and per-day
      subtotals and a grand total
  results/problem_qa/<group>/       qa_check output for old with only that group on

    python tools/problem_impact.py
"""
import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import fixed  # noqa: E402
import old_reference as old  # noqa: E402

PINGS = os.path.join(HERE, "data", "pings.csv")
GT = os.path.join(HERE, "data", "ground_truth.csv")
RES = os.path.join(HERE, "results")
ONE_M_KM = 0.001  # "off by more than 1 m" (same size as the A11 tolerance)
GROUPS = [
    ("day_cut", "Day cut", ["BUG-14", "BUG-15"]),
    ("noise", "Noise", ["BUG-04", "BUG-05", "BUG-06", "BUG-07", "BUG-08", "BUG-09"]),
    ("late_pings", "Late pings", ["BUG-17"]),
    ("zone_boundary", "Zone boundary", ["BUG-01", "BUG-02"]),
    ("duplicates", "Duplicates", ["BUG-10", "BUG-11", "BUG-12", "BUG-13"]),
    ("earth_radius", "Earth radius", ["BUG-03"]),
    ("no_z_input", "No-Z input", ["BUG-16"]),
]


def rel(p):
    return os.path.relpath(p, HERE)


def run_old(bugs, pings=PINGS):
    with old.only_bugs(set(bugs)):
        return old.run_file(pings)


def compare(base, on):
    keys = sorted(set(base.daily_km) | set(on.daily_km))
    diffs = {k: on.daily_km.get(k, 0.0) - base.daily_km.get(k, 0.0) for k in keys}
    worst = max(keys, key=lambda k: abs(diffs[k])) if keys else None
    tb, to = sum(base.daily_km.values()), sum(on.daily_km.values())
    return keys, diffs, worst, {
        "baseline_km": round(tb, 6), "group_km": round(to, 6), "total_change_km": round(to - tb, 6),
        "total_change_pct": round((to - tb) / tb * 100, 2) if tb else 0.0,
        "union_driver_days": len(keys),
        "driver_days_off_gt_1m": sum(abs(d) > ONE_M_KM for d in diffs.values()),
        "km_over": round(sum(d for d in diffs.values() if d > 0), 6),
        "km_under": round(-sum(d for d in diffs.values() if d < 0), 6),
        "gross_km_wrong": round(sum(abs(d) for d in diffs.values()), 6),
        "worst_driver_day": f"{worst[0]} {worst[1]}" if worst and abs(diffs[worst]) > 0 else "none",
        "worst_change_km": round(diffs[worst], 6) if worst else 0.0,
    }


def qa_for_group(key, bugs):
    out = os.path.join(HERE, "out", "problem", key)
    qa_dir = os.path.join(RES, "problem_qa", key)
    subprocess.run([sys.executable, os.path.join(HERE, "old_reference.py"), "--pings", PINGS, "--out", out,
                    "--bugs", ",".join(bugs)], check=True, capture_output=True, cwd=HERE)
    p = subprocess.run([sys.executable, os.path.join(HERE, "qa_check.py"), "--pings", rel(PINGS), "--ground-truth", rel(GT),
                        "--report", rel(os.path.join(out, "daily_km.csv")), "--out", rel(qa_dir),
                        "--note", f"old_reference.py with only {', '.join(bugs)} on (problem group '{key}')"],
                       capture_output=True, text=True, cwd=HERE)
    result = next((l for l in p.stdout.splitlines() if l.startswith("RESULT")), "RESULT: ?")
    rows = {(r["driver_id"], r["local_date"]): r for r in csv.DictReader(open(os.path.join(qa_dir, "qa_daily.csv")))}
    return p.returncode, result, rows


def ping_diffs(base, on, driver, limit=3):
    out = []
    for k, st in on.ping_status.items():
        if k[0] != driver:
            continue
        b = base.ping_status.get(k)
        fields = [f for f in ("status", "in_zone", "local_date") if b is None or st.get(f) != b.get(f)]
        if fields:
            out.append(f"ping {k[1]} " + ", ".join(f"{f}: {b.get(f) if b else '-'} -> {st.get(f)}" for f in fields))
    return out[:limit]


def event_diffs(base, on, driver):
    def count(res):
        c = {}
        for e in res.events:
            if e["driver_id"] == driver:
                c[e["event_type"]] = c.get(e["event_type"], 0) + 1
        return c
    cb, co = count(base), count(on)
    return "; ".join(f"{t}: {cb.get(t, 0)} -> {co.get(t, 0)}" for t in sorted(set(cb) | set(co))
                     if cb.get(t, 0) != co.get(t, 0)) or "no change"


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main():
    base = run_old([])
    fx = fixed.run_file(PINGS)
    same = set(base.daily_km) == set(fx.daily_km) and all(abs(base.daily_km[k] - fx.daily_km[k]) < 1e-9 for k in fx.daily_km)
    print(f"baseline check: old_reference with no bugs == fixed.py daily km: {same}")
    ba = {(r["driver_id"], r["local_date"]): r["bugs_responsible"]
          for r in csv.DictReader(open(os.path.join(RES, "before_after.csv")))} \
        if os.path.exists(os.path.join(RES, "before_after.csv")) else {}

    impact, examples = [], []
    for key, name, bugs in GROUPS + [("all_bugs", "All 17 bugs", sorted(old.ALL_BUGS))]:
        on = run_old(bugs)
        keys, diffs, worst, m = compare(base, on)
        missing = {d: on.total_km[d] - sum(v for (dd, _), v in on.daily_km.items() if dd == d) for d in on.total_km}
        missing = {d: v for d, v in missing.items() if abs(v) > 1e-9}
        m["km_in_totals_not_in_daily"] = round(sum(missing.values()), 6)
        m["drivers_missing_from_daily"] = "; ".join(f"{d} {v:.6f}" for d, v in sorted(missing.items())) or "none"
        impact.append({"group": key, "problem": name, "bugs": " ".join(bugs), **m})
        print(f"{key:14s} change {m['total_change_km']:+.6f} km ({m['total_change_pct']:+.2f}%), "
              f"off >1 m: {m['driver_days_off_gt_1m']}/{m['union_driver_days']} (union), over {m['km_over']:.6f}, "
              f"under {m['km_under']:.6f}, gross {m['gross_km_wrong']:.6f}, worst {m['worst_driver_day']} "
              f"{m['worst_change_km']:+.6f}")
        if key == "all_bugs":
            continue
        rc, result, qa_rows = qa_for_group(key, bugs)
        ex = {"group": key, "bugs": " ".join(bugs), "qa_check_exit": rc, "qa_check_result": result}
        if worst is not None and abs(diffs[worst]) > 0:
            q = qa_rows.get(worst, {})
            ex.update({"driver_id": worst[0], "local_date": worst[1],
                       "baseline_km": round(base.daily_km.get(worst, 0.0), 6), "group_km": round(on.daily_km.get(worst, 0.0), 6),
                       "qa_check_row": f"expected {q.get('expected_km')} actual {q.get('actual_km')} diff {q.get('diff_km')} {q.get('result')}",
                       "before_after_bugs_responsible": ba.get(worst, "(row not in before_after.csv)"),
                       "ping_status_changes": " | ".join(ping_diffs(base, on, worst[0])) or "no status change",
                       "event_changes": event_diffs(base, on, worst[0])})
        else:
            ex.update({"driver_id": "", "local_date": "", "baseline_km": "", "group_km": "", "qa_check_row": "",
                       "before_after_bugs_responsible": "", "ping_status_changes": "", "event_changes": ""})
        examples.append(ex)

    # No-Z input has no effect on data/pings.csv (every timestamp ends in Z): show its effect on the fixture.
    fx_noz = os.path.join(HERE, "fixtures", "F_INVALID_no_z.csv")
    codes = {}
    for label, bugs in (("BUG-16 on", "BUG-16"), ("no bugs", "none")):
        with tempfile.TemporaryDirectory() as tmp:
            p = subprocess.run([sys.executable, os.path.join(HERE, "old_reference.py"), "--pings", fx_noz, "--out", tmp,
                                "--bugs", bugs], capture_output=True, text=True, cwd=HERE)
            codes[label] = p.returncode
    for ex in examples:
        if ex["group"] == "no_z_input":
            ex["ping_status_changes"] = (f"fixtures/F_INVALID_no_z.csv: old_reference exit {codes['BUG-16 on']} with BUG-16 on "
                                         f"(file accepted), exit {codes['no bugs']} with no bugs (rejected)")
    print(f"no_z_input on fixtures/F_INVALID_no_z.csv: exit {codes['BUG-16 on']} with BUG-16 on, "
          f"exit {codes['no bugs']} with no bugs")
    write_csv(os.path.join(RES, "problem_impact.csv"), impact)
    write_csv(os.path.join(RES, "problem_examples.csv"), examples)

    # Day-cut fix: before = old with ONLY BUG-14/15 on; after = fixed.py; checked against ground truth.
    before = run_old(["BUG-14", "BUG-15"])
    gt = {(r["driver_id"], r["local_date"]): float(r["expected_km"])
          for r in csv.DictReader(open(GT)) if r["record_type"] == "DAILY_KM"}
    keys = sorted(set(before.daily_km) | set(fx.daily_km) | set(gt))  # absent row = 0 km (A15)
    get = lambda d, k: d.get(k, 0.0)
    rows, matches = [], 0
    for k in keys:
        b, a, g = get(before.daily_km, k), get(fx.daily_km, k), get(gt, k)
        ok = round(a, 6) == round(g, 6)
        matches += ok
        rows.append({"row_type": "DRIVER_DAY", "driver_id": k[0], "local_date": k[1], "before_km": round(b, 6),
                     "after_km": round(a, 6), "ground_truth_km": round(g, 6), "change_km": round(a - b, 6) + 0.0,
                     "after_equals_ground_truth": "yes" if ok else "NO"})
    for kind, idx in (("DRIVER_SUBTOTAL", 0), ("DAY_SUBTOTAL", 1)):
        for v in sorted({k[idx] for k in keys}):
            ks = [k for k in keys if k[idx] == v]
            b = sum(get(before.daily_km, k) for k in ks)
            a = sum(get(fx.daily_km, k) for k in ks)
            g = sum(get(gt, k) for k in ks)
            ok = all(round(get(fx.daily_km, k), 6) == round(get(gt, k), 6) for k in ks)
            rows.append({"row_type": kind, "driver_id": v if idx == 0 else "", "local_date": v if idx == 1 else "",
                         "before_km": round(b, 6), "after_km": round(a, 6), "ground_truth_km": round(g, 6),
                         "change_km": round(a - b, 6) + 0.0, "after_equals_ground_truth": "yes" if ok else "NO"})
    tb, ta, tg = sum(before.daily_km.values()), sum(fx.daily_km.values()), sum(gt.values())
    rows.append({"row_type": "TOTAL", "driver_id": "", "local_date": "", "before_km": round(tb, 6),
                 "after_km": round(ta, 6), "ground_truth_km": round(tg, 6), "change_km": round(ta - tb, 6) + 0.0,
                 "after_equals_ground_truth": "yes" if matches == len(keys) else "NO"})
    write_csv(os.path.join(RES, "daycut_before_after.csv"), rows)
    changed = sum(abs(r["change_km"]) > ONE_M_KM for r in rows if r["row_type"] == "DRIVER_DAY")
    print(f"day-cut before/after (old with only BUG-14/15 -> fixed.py): total {tb:.6f} -> {ta:.6f} km "
          f"(ground truth {tg:.6f}); after = ground truth on {matches}/{len(keys)} driver-days (union, absent = 0); "
          f"changed >1 m: {changed}/{len(keys)}")
    ctx_b, ctx_a = run_old(sorted(old.ALL_BUGS)), run_old(sorted(old.ALL_BUGS - {"BUG-14", "BUG-15"}))
    print(f"context: with the other 15 bugs also on, removing BUG-14/15 moves the total "
          f"{sum(ctx_b.daily_km.values()):.6f} -> {sum(ctx_a.daily_km.values()):.6f} km")
    print("wrote results/problem_impact.csv, results/problem_examples.csv, results/daycut_before_after.csv")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
