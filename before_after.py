"""before_after.py - old vs fixed vs ground truth, km per driver per local day (SYNTHETIC data).

Every number comes from running old_reference.py and fixed.py on data/pings.csv.
Bug attribution, per row:
  * solo effect: old with ONLY bug b on, minus old with no bugs (which equals fixed);
  * leave-one-out effect: old with all bugs, minus old with all bugs except b.
A bug is named if either effect is larger than 1e-6 km. Bugs whose solo effect is
zero but which matter in combination are marked "(combined)".

    python before_after.py [--pings data/pings.csv] [--ground-truth data/ground_truth.csv]
"""
import argparse
import csv
import os
import sys

import pandas as pd  # reporting only

import fixed
import old_reference as old

HERE = os.path.dirname(os.path.abspath(__file__))
EPS = 1e-6


def daily(res):
    return dict(res.daily_km)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pings", default=os.path.join(HERE, "data", "pings.csv"))
    ap.add_argument("--ground-truth", default=os.path.join(HERE, "data", "ground_truth.csv"))
    ap.add_argument("--out", default=os.path.join(HERE, "results", "before_after.csv"))
    args = ap.parse_args(argv)

    gt = {(r["driver_id"], r["local_date"]): float(r["expected_km"])
          for r in csv.DictReader(open(args.ground_truth, encoding="utf-8")) if r["record_type"] == "DAILY_KM"}
    fx_d = daily(fixed.run_file(args.pings))
    old_all = daily(old.run_file(args.pings))
    with old.only_bugs(set()):
        old_none = daily(old.run_file(args.pings))
    solo, loo = {}, {}
    for b in sorted(old.ALL_BUGS):
        with old.only_bugs({b}):
            solo[b] = daily(old.run_file(args.pings))
        with old.only_bugs(old.ALL_BUGS - {b}):
            loo[b] = daily(old.run_file(args.pings))

    keys = sorted(set(gt) | set(fx_d) | set(old_all))
    rows = []
    for k in keys:
        g, f, o = gt.get(k, 0.0), fx_d.get(k, 0.0), old_all.get(k, 0.0)
        named, effects = [], []
        for b in sorted(old.ALL_BUGS):
            s = solo[b].get(k, 0.0) - old_none.get(k, 0.0)
            l = o - loo[b].get(k, 0.0)
            if abs(s) > EPS or abs(l) > EPS:
                named.append(b if abs(s) > EPS else f"{b} (combined)")
                effects.append(f"{b}: alone {s:+.6f}, in old {l:+.6f}")
        diff = o - f
        rows.append({"label": "SYNTHETIC", "driver_id": k[0], "local_date": k[1],
                     "ground_truth_km": round(g, 6), "fixed_km": round(f, 6), "old_km": round(o, 6),
                     "fixed_minus_ground_truth_km": round(f - g, 6), "old_minus_fixed_km": round(diff, 6),
                     "bugs_responsible": "; ".join(named) if abs(diff) > EPS else "",
                     "bug_effects_km": " | ".join(effects) if abs(diff) > EPS else ""})
    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    df.to_csv(args.out, index=False)
    tot = df[["ground_truth_km", "fixed_km", "old_km"]].sum()
    print(f"before_after: {len(df)} driver-day rows -> {os.path.relpath(args.out, HERE)}")
    print(f"  totals: ground truth {tot.ground_truth_km:.6f} km, fixed {tot.fixed_km:.6f} km, old {tot.old_km:.6f} km")
    print(f"  rows where old differs from fixed: {(df.old_minus_fixed_km.abs() > EPS).sum()}; "
          f"rows where fixed differs from ground truth (> 0.001 km): {(df.fixed_minus_ground_truth_km.abs() > 0.001).sum()}")
    no_bug = df[(df.old_minus_fixed_km.abs() > EPS) & (df.bugs_responsible == "")]
    return 1 if len(no_bug) else 0


if __name__ == "__main__":
    sys.exit(main())
