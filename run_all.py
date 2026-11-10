"""run_all.py - runs everything, in the order intent.md / the brief requires (SYNTHETIC data).

    python run_all.py              # full run including the pytest suite
    python run_all.py --no-tests   # data, pipelines, checker, reports only

Steps:
 1. generate the dataset and fixtures (seed 42)
 2. Step 6 gate: fixed.py + qa_check.py on F_BOUNDARY vs the HAND calculation; stop if it fails
 3. fixed.py and old_reference.py on data/pings.csv (and fixed.py on pings_clean.csv)
 4. qa_check.py on each output (fixed must pass; old is expected to fail)
 5. results/regression_summary.{csv,md} and results/before_after.csv
 6. pytest -> results/test_results.csv
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
OLD_NOTE = ("old_reference.py is EXPECTED to FAIL this check: it contains the 17 planted bugs in BUGS.md, "
            "and this report shows the checker catching them. It is not a defect in fixed.py or qa_check.py.")


def step(title, args, expect=(0,)):
    print(f"\n=== {title}\n$ {' '.join(os.path.relpath(a, HERE) if os.path.isabs(a) else a for a in args)}", flush=True)
    rc = subprocess.run(args, cwd=HERE).returncode
    ok = rc in expect
    print(f"--- exit {rc} ({'as expected' if ok else 'UNEXPECTED'})", flush=True)
    return ok, rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-tests", action="store_true", help="skip the pytest suite")
    args = ap.parse_args(argv)
    os.chdir(HERE)
    results = []

    def run(title, cmd, expect=(0,)):
        ok, rc = step(title, cmd, expect)
        results.append((title, rc, ok))
        return ok

    run("1. generate data (seed 42)", [PY, "generate_data.py", "--seed", "42"])
    if not run("2a. fixed.py on F_BOUNDARY", [PY, "fixed.py", "--pings", "fixtures/F_BOUNDARY.csv", "--out", "out/F_BOUNDARY"]) \
            or not run("2b. GATE: qa_check vs hand calculation (F_BOUNDARY)",
                       [PY, "qa_check.py", "--pings", "fixtures/F_BOUNDARY.csv",
                        "--ground-truth", "fixtures/F_BOUNDARY_ground_truth.csv",
                        "--report", "out/F_BOUNDARY/daily_km.csv", "--out", "results/qa_F_BOUNDARY"]):
        print("\nSTOP: the checker does not match the hand calculation; not running on the full dataset.")
        return 1
    run("3a. fixed.py on data/pings.csv", [PY, "fixed.py", "--pings", "data/pings.csv", "--out", "out/fixed"])
    run("3b. fixed.py on data/pings_clean.csv", [PY, "fixed.py", "--pings", "data/pings_clean.csv", "--out", "out/fixed_clean"])
    run("3c. old_reference.py on data/pings.csv", [PY, "old_reference.py", "--pings", "data/pings.csv", "--out", "out/old"])
    run("4a. qa_check: fixed, faulty dataset (expect PASS)",
        [PY, "qa_check.py", "--pings", "data/pings.csv", "--ground-truth", "data/ground_truth.csv",
         "--report", "out/fixed/daily_km.csv", "--events", "out/fixed/events.csv", "--out", "results/qa_fixed"])
    run("4b. qa_check: fixed, clean dataset (expect PASS)",
        [PY, "qa_check.py", "--pings", "data/pings_clean.csv", "--ground-truth", "data/ground_truth_clean.csv",
         "--report", "out/fixed_clean/daily_km.csv", "--events", "out/fixed_clean/events.csv",
         "--out", "results/qa_fixed_clean"])
    run("4c. qa_check: old, faulty dataset (expect FAIL, exit 1)",
        [PY, "qa_check.py", "--pings", "data/pings.csv", "--ground-truth", "data/ground_truth.csv",
         "--report", "out/old/daily_km.csv", "--events", "out/old/events.csv", "--out", "results/qa_old",
         "--note", OLD_NOTE], expect=(1,))
    run("5a. regression summary", [PY, "regression_summary.py"])
    run("5b. before / after", [PY, "before_after.py"])
    if not args.no_tests:
        run("6. pytest", [PY, "-m", "pytest", "tests", "-q", "--results-csv", "results/test_results.csv"])

    print("\n=== SUMMARY")
    for title, rc, ok in results:
        print(f"  {'OK ' if ok else 'BAD'}  exit {rc}  {title}")
    return 0 if all(ok for _, _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
