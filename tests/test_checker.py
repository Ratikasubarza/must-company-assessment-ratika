"""Checker validation group: runs qa_check.py as a program (exit codes, report text, CSVs)."""
import csv
import os
import shutil
import subprocess
import sys

import pytest

import fixed
import old_reference
from helpers import DATA, ROOT, fx

pytestmark = pytest.mark.checker
IMPL = "qa_check"
QA = os.path.join(ROOT, "qa_check.py")


def qa(*args):
    return subprocess.run([sys.executable, QA, *args], capture_output=True, text=True)


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    """Pipeline outputs produced once for this module: fixed (faulty + clean data) and old (faulty data)."""
    base = tmp_path_factory.mktemp("pipeline")
    fixed.write_reports(fixed.run_file(os.path.join(DATA, "pings.csv")), str(base / "fixed"))
    fixed.write_reports(fixed.run_file(os.path.join(DATA, "pings_clean.csv")), str(base / "fixed_clean"))
    fixed.write_reports(fixed.run_file(fx("F_INTERVALS_irregular.csv")), str(base / "intervals"))
    fixed.write_reports(old_reference.run_file(os.path.join(DATA, "pings.csv")), str(base / "old"))
    return base


def test_TC_00_checker_matches_hand_calculation_on_F_BOUNDARY(record, tmp_path):
    """Given F_BOUNDARY and its hand-calculated ground truth (0.778364 km, fixtures/F_BOUNDARY_handcalc.md),
    When fixed.py runs and qa_check.py compares, and again with the report changed by +0.002 km,
    Then the checker passes the real report (exit 0) and fails the changed one (exit 1).
    (Step 6 gate, run before the full dataset. TC-00 is not in the sheet.)"""
    fixed.write_reports(fixed.run_file(fx("F_BOUNDARY.csv")), str(tmp_path))
    good = qa("--pings", fx("F_BOUNDARY.csv"), "--ground-truth", fx("F_BOUNDARY_ground_truth.csv"),
              "--report", str(tmp_path / "daily_km.csv"))
    rows = list(csv.DictReader(open(tmp_path / "daily_km.csv")))
    rows[0]["km"] = f"{float(rows[0]['km']) + 0.002:.6f}"
    bad_path = tmp_path / "bad.csv"
    with open(bad_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    bad = qa("--pings", fx("F_BOUNDARY.csv"), "--ground-truth", fx("F_BOUNDARY_ground_truth.csv"),
             "--report", str(bad_path))
    record("TC-00", IMPL, (0, 1), (good.returncode, bad.returncode))
    assert (good.returncode, bad.returncode) == (0, 1)


@pytest.mark.parametrize("case,delta_km,exp_exit", [
    ("plus_0.0009_km_within_tolerance", 0.0009, 0),
    ("plus_0.0011_km_outside_tolerance", 0.0011, 1),
    ("missing_row_read_as_0_km", None, 1),
])
def test_TC_00_checker_tolerance_boundary_on_F_BOUNDARY(record, tmp_path, case, delta_km, exp_exit):
    """Given F_BOUNDARY's hand-calculated ground truth (DRV-A 2026-11-07 = 0.778364 km) and a report that is
    (a) +0.0009 km off, (b) +0.0011 km off, or (c) missing the DRV-A row (header only),
    When qa_check.py compares them with the A11 tolerance (0.001 km),
    Then (a) passes, exit 0; (b) fails, exit 1; (c) reads the missing row as 0 km (A15) and fails, exit 1,
    reporting 'got 0.000000'. (Step 6 gate boundary. TC-00 is not in the sheet.)"""
    fixed.write_reports(fixed.run_file(fx("F_BOUNDARY.csv")), str(tmp_path))
    rows = list(csv.DictReader(open(tmp_path / "daily_km.csv")))
    fields = list(rows[0])
    if delta_km is None:
        rows = []
    else:
        rows[0]["km"] = f"{float(rows[0]['km']) + delta_km:.6f}"
    rep = tmp_path / "report.csv"
    with open(rep, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    p = qa("--pings", fx("F_BOUNDARY.csv"), "--ground-truth", fx("F_BOUNDARY_ground_truth.csv"), "--report", str(rep))
    read_as_zero = "got 0.000000" in p.stdout
    act = (p.returncode, read_as_zero) if delta_km is None else p.returncode
    exp = (exp_exit, True) if delta_km is None else exp_exit
    record("TC-00", IMPL, exp, act)
    assert act == exp, p.stdout


def test_TC_54_clean_dataset_zero_violations(record, outputs, tmp_path):
    """Given data/pings_clean.csv (no injected faults) and fixed.py's output,
    When qa_check.py runs,
    Then exit 0, 0 failed daily rows, 0 fault events, 0 interval violations."""
    p = qa("--pings", os.path.join(DATA, "pings_clean.csv"), "--ground-truth", os.path.join(DATA, "ground_truth_clean.csv"),
           "--report", str(outputs / "fixed_clean" / "daily_km.csv"), "--events", str(outputs / "fixed_clean" / "events.csv"))
    act = (p.returncode, "interval violations: 0" in p.stdout, "TP 0, FP 0, FN 0" in p.stdout)
    record("TC-54", IMPL, (0, True, True), act)
    assert act == (0, True, True), p.stdout


def test_TC_55_each_injected_fault_flagged_with_precision_recall(record, outputs, tmp_path):
    """Given data/pings.csv with 54 injected faults (ground_truth.csv) and fixed.py's output,
    When qa_check.py runs,
    Then every injected fault is matched (no FN), nothing extra is flagged (no FP), and
    precision 1.000 / recall 1.000 is reported; exit 0."""
    out = tmp_path / "qa"
    p = qa("--pings", os.path.join(DATA, "pings.csv"), "--ground-truth", os.path.join(DATA, "ground_truth.csv"),
           "--report", str(outputs / "fixed" / "daily_km.csv"), "--events", str(outputs / "fixed" / "events.csv"),
           "--out", str(out))
    matches = [r["match"] for r in csv.DictReader(open(out / "qa_faults.csv"))]
    line = next(l for l in p.stdout.splitlines() if l.startswith("fault detection"))
    act = (p.returncode, matches.count("FN"), matches.count("FP"), "precision 1.000, recall 1.000" in line)
    record("TC-55", IMPL, (0, 0, 0, True), act + (line,))
    assert act == (0, 0, 0, True), p.stdout


def test_TC_55_checker_fails_old_implementation(record, outputs, tmp_path):
    """Given data/pings.csv and old_reference.py's output (all 17 bugs on), checked with the same --note that
    run_all.py uses for results/qa_old,
    When qa_check.py runs,
    Then it exits 1 and lists daily-km failures (the checker catches the old bugs), and the first line of both
    the printed report and qa_summary.txt is that note, so the FAIL reads as expected. The note changes no check."""
    import run_all
    out = tmp_path / "qa_old"
    p = qa("--pings", os.path.join(DATA, "pings.csv"), "--ground-truth", os.path.join(DATA, "ground_truth.csv"),
           "--report", str(outputs / "old" / "daily_km.csv"), "--events", str(outputs / "old" / "events.csv"),
           "--out", str(out), "--note", run_all.OLD_NOTE)
    n_fail = sum(1 for l in p.stdout.splitlines() if l.strip().startswith("daily km"))
    note = f"NOTE: {run_all.OLD_NOTE}"
    first_out = p.stdout.splitlines()[0] if p.stdout else ""
    first_file = open(out / "qa_summary.txt").readline().rstrip("\n") if (out / "qa_summary.txt").exists() else ""
    act = (p.returncode, n_fail > 0, first_out == note, first_file == note)
    record("TC-55", IMPL, (1, True, True, True), act)
    assert act == (1, True, True, True), p.stdout[:500]


def test_TC_56_fresh_copy_runs_from_readme_command(record, tmp_path):
    """Given a fresh copy of ONLY the files git tracks (`git ls-files`; untracked files are not copied),
    When the README command `python run_all.py --no-tests` runs in it twice,
    Then each run exits 0 and writes results/before_after.csv and results/qa_fixed/qa_summary.txt, and the
    run history keeps BOTH runs: results/history/runs.csv has 2 rows with different run_ids, both overall OK,
    each with its own history folder (qa_fixed/qa_summary.txt and run.log), and results/RUN_ID names the 2nd run.
    Needs a commit first: until fixed.py, run_all.py and the rest are committed, the copy is incomplete
    and this test fails."""
    files = subprocess.run(["git", "ls-files"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split("\n")
    dst = tmp_path / "clone"
    for f in filter(None, files):
        src = os.path.join(ROOT, f)
        if os.path.isfile(src) and not f.startswith("results/"):
            os.makedirs(dst / os.path.dirname(f), exist_ok=True)
            shutil.copy2(src, dst / f)
    runs = [subprocess.run([sys.executable, "run_all.py", "--no-tests"], cwd=dst, capture_output=True, text=True)
            for _ in range(2)]
    res = dst / "results"
    hist = list(csv.DictReader(open(res / "history" / "runs.csv"))) if (res / "history" / "runs.csv").exists() else []
    ids = [h["run_id"] for h in hist]
    folders_ok = all((res / "history" / i / "qa_fixed" / "qa_summary.txt").exists()
                     and (res / "history" / i / "run.log").exists() for i in ids)
    last_id = (res / "RUN_ID").read_text().strip() if (res / "RUN_ID").exists() else ""
    act = ([p.returncode for p in runs], (res / "before_after.csv").exists(), (res / "qa_fixed" / "qa_summary.txt").exists(),
           len(hist), len(set(ids)), [h["overall"] for h in hist], folders_ok, bool(ids) and last_id == ids[-1])
    exp = ([0, 0], True, True, 2, 2, ["OK", "OK"], True, True)
    record("TC-56", IMPL, exp, act)
    assert act == exp, runs[-1].stdout[-2000:] + runs[-1].stderr[-2000:]


@pytest.mark.parametrize("name,tc,needle", [
    ("F_INVALID_swapped.csv", "TC-60", "swapped"),
    ("F_INVALID_offset.csv", "X-01", "offset"),
    ("F_INVALID_no_z.csv", "X-02", "no Z"),
    ("F_INVALID_range.csv", "X-03", "out of range"),
    ("F_INVALID_missing_col.csv", "X-04", "missing column"),
    ("F_INVALID_bad_second.csv", "X-11", "not a valid date/time"),
])
def test_TC_60_and_X_01_to_X_04_X_11_checker_rejects_bad_input(record, name, tc, needle):
    """Given a bad pings file (swapped lat/lon, UTC offset, no Z, out-of-range coordinate, missing column),
    When qa_check.py validates its inputs,
    Then it exits 2 with an INPUT ERROR naming the problem (X-01..X-04 are repo-only tests, not sheet cases; P-09)."""
    p = qa("--pings", fx(name), "--ground-truth", fx("F_BOUNDARY_ground_truth.csv"),
           "--report", fx("F_BOUNDARY_ground_truth.csv"))
    record(tc, IMPL, f"exit 2, '{needle}'", f"exit {p.returncode}: {p.stderr.strip()[:160]}")
    assert p.returncode == 2 and needle in p.stderr


def test_TC_62_checker_rejects_empty_pings_file(record, tmp_path):
    """Given an empty pings file (0 bytes),
    When qa_check.py validates its inputs,
    Then it exits 2 with an INPUT ERROR and reports no comparison (no partial result)."""
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    report = tmp_path / "daily_km.csv"  # a valid report, so only the pings file can cause the rejection
    report.write_text("label,driver_id,local_date,km\nSYNTHETIC,DRV-A,2026-11-07,0.778364\n")
    p = qa("--pings", str(empty), "--ground-truth", fx("F_BOUNDARY_ground_truth.csv"), "--report", str(report))
    act = (p.returncode, "INPUT ERROR: pings" in p.stderr, "RESULT" in p.stdout)
    record("TC-62", IMPL, (2, True, False), act)
    assert act == (2, True, False), p.stderr


def test_X_05_checker_help(record):
    """Given qa_check.py,
    When it is run with --help,
    Then it exits 0 and prints usage with every option (X-05 is a repo-only test, not a sheet case; P-09)."""
    p = qa("--help")
    opts = ["--pings", "--ground-truth", "--report", "--events", "--route", "--tolerance-km", "--out"]
    act = (p.returncode, all(o in p.stdout for o in opts))
    record("X-05", IMPL, (0, True), act)
    assert act == (0, True)


def test_RTC_11_injected_gap_in_violation_list(record, outputs):
    """Given data/pings.csv with 8 INTERVAL_GAP faults recorded in ground_truth.csv,
    When qa_check.py runs,
    Then each gap is in the violation list and matches ground truth (no 'not in ground truth' failure)."""
    gt = sorted((r["driver_id"], r["ping_id"]) for r in csv.DictReader(open(os.path.join(DATA, "ground_truth.csv")))
                if r["fault_type"] == "INTERVAL_GAP")
    p = qa("--pings", os.path.join(DATA, "pings.csv"), "--ground-truth", os.path.join(DATA, "ground_truth.csv"),
           "--report", str(outputs / "fixed" / "daily_km.csv"))
    listed = sorted(tuple(l.split()[2:5:2]) for l in p.stdout.splitlines() if l.strip().startswith("GAP driver"))
    listed = [(d, pid.rstrip(":")) for d, pid in listed]
    record("RTC-11", IMPL, gt, listed)
    assert listed == gt and p.returncode == 0


def test_RTC_13_interval_summary_per_driver(record, outputs, tmp_path):
    """Given F_INTERVALS_irregular: one 30 s gap and one 5 s short interval for DRV-A,
    When qa_check.py runs,
    Then qa_intervals.csv lists DRV-A with gaps 1 and short 1."""
    gt = tmp_path / "gt.csv"
    gt.write_text("label,record_type,driver_id,local_date,expected_km,fault_type,ping_id,ref_ping_id,ts_utc,detail\n"
                  "SYNTHETIC,FAULT,DRV-A,,,INTERVAL_GAP,7,,,30 s gap\n")
    qa("--pings", fx("F_INTERVALS_irregular.csv"), "--ground-truth", str(gt),
       "--report", str(outputs / "intervals" / "daily_km.csv"), "--out", str(tmp_path / "qa"))
    row = next(csv.DictReader(open(tmp_path / "qa" / "qa_intervals.csv")))
    act = (row["driver_id"], row["gaps"], row["short"])
    record("RTC-13", IMPL, ("DRV-A", "1", "1"), act)
    assert act == ("DRV-A", "1", "1")
