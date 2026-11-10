"""run_all.py - runs everything, in the order intent.md / the brief requires (SYNTHETIC data).

    python run_all.py              # full run including the pytest suite
    python run_all.py --no-tests   # data, pipelines, checker, reports only

Steps:
 1. generate the dataset and fixtures (seed 42)
 2. Step 6 gate: fixed.py + qa_check.py on F_BOUNDARY vs the HAND calculation; stop if it fails
 3. fixed.py and old_reference.py on data/pings.csv (and fixed.py on pings_clean.csv)
 4. qa_check.py on each output (fixed must pass; old is expected to fail)
 5. results/regression_summary.{csv,md}, results/before_after.csv, results/problem_impact.csv
    (+ problem_examples.csv, daycut_before_after.csv) and results/limitations.csv
 6. pytest -> results/test_results.csv

Run history: every run, including a run stopped by the gate, is kept in
results/history/<run_id>/ (a copy of that run's results plus run.log and run_info.txt), and
gets one row in results/history/runs.csv. results/ itself holds only the latest run: it is
cleared at the start of each run (history/ is never touched). Results found in results/ that
were never archived are archived first as `unarchived_<time>`, so nothing is lost.
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
RESULTS = os.path.join(HERE, "results")
HISTORY = os.path.join(RESULTS, "history")
RUNS_CSV = os.path.join(HISTORY, "runs.csv")
RUN_ID_FILE = os.path.join(RESULTS, "RUN_ID")
OLD_NOTE = ("old_reference.py is EXPECTED to FAIL this check: it contains the 17 planted bugs in BUGS.md, "
            "and this report shows the checker catching them. It is not a defect in fixed.py or qa_check.py.")
RUN_FIELDS = ["run_id", "started", "finished", "git_branch", "git_commit", "git_dirty", "overall", "bad_steps",
              "pytest", "qa_F_BOUNDARY", "qa_fixed", "qa_fixed_clean", "qa_old", "bugs_caught_alone",
              "guards_pass_on_fixed", "note"]


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _results_content():
    """Files in results/ outside history/ and the RUN_ID marker."""
    out = []
    for root, dirs, files in os.walk(RESULTS):
        if os.path.abspath(root).startswith(HISTORY):
            continue
        out += [os.path.join(root, f) for f in files if os.path.join(root, f) != RUN_ID_FILE]
    return out


def _qa_result(name):
    p = os.path.join(RESULTS, name, "qa_summary.txt")
    if not os.path.exists(p):
        return "not run"
    m = re.search(r"^RESULT: (\w+)", open(p, encoding="utf-8").read(), re.M)
    return m.group(1) if m else "unknown"


def _md_value(pattern):
    p = os.path.join(RESULTS, "regression_summary.md")
    if not os.path.exists(p):
        return "not run"
    m = re.search(pattern, open(p, encoding="utf-8").read())
    return m.group(1) if m else "not reported"


def scrub(text):
    """Remove machine-specific paths and the user name before a log is stored in history."""
    import getpass
    import tempfile
    tmp = tempfile.gettempdir()
    pairs = [(HERE + os.sep, ""), (HERE, "."), (os.path.realpath(tmp), "<tmp>"), (tmp, "<tmp>"),
             (os.path.expanduser("~"), "~")]
    for old, new in pairs:
        if old and old not in (os.sep,):
            text = text.replace(old, new)
    user = getpass.getuser()
    return text.replace(user, "<user>") if len(user) >= 3 else text


def git_state():
    """Branch, commit and dirty flag of the code and data a run uses. results/ is excluded: it holds the
    run's own outputs, which every run rewrites."""
    if not _git("rev-parse", "HEAD"):
        return {"git_branch": "n/a", "git_commit": "n/a", "git_dirty": "n/a"}
    dirty = _git("status", "--porcelain", "--untracked-files=no", "--", ".", ":(exclude)results")
    return {"git_branch": _git("branch", "--show-current") or "n/a",
            "git_commit": _git("rev-parse", "--short", "HEAD") or "n/a",
            "git_dirty": "yes" if dirty else "no"}


def record_history(run_id, log_text, started, finished, step_results, note="", git=None):
    """Copy results/ (latest run) into results/history/<run_id>/ and append one row to runs.csv."""
    log_text = scrub(log_text)
    dest = os.path.join(HISTORY, run_id)
    os.makedirs(dest, exist_ok=True)
    for src in _results_content():
        rel = os.path.relpath(src, RESULTS)
        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
        shutil.copy2(src, os.path.join(dest, rel))
    with open(os.path.join(dest, "run.log"), "w", encoding="utf-8") as fh:
        fh.write(log_text)
    pytest_lines = re.findall(r"^\d+ (?:passed|failed).*$", log_text, re.M)
    bad = [t for t, _, ok in step_results if not ok]
    row = {
        "run_id": run_id, "started": started, "finished": finished,
        **(git or git_state()),
        "overall": "OK" if step_results and not bad else "BAD",
        "bad_steps": "; ".join(bad),
        "pytest": pytest_lines[-1] if pytest_lines else "not run",
        "qa_F_BOUNDARY": _qa_result("qa_F_BOUNDARY"), "qa_fixed": _qa_result("qa_fixed"),
        "qa_fixed_clean": _qa_result("qa_fixed_clean"), "qa_old": _qa_result("qa_old"),
        "bugs_caught_alone": _md_value(r"only that bug switched on: \*\*(\d+/\d+)\*\*"),
        "guards_pass_on_fixed": _md_value(r"Guards passing on fixed.py: \*\*(\d+/\d+)\*\*"),
        "note": note,
    }
    with open(os.path.join(dest, "run_info.txt"), "w", encoding="utf-8") as fh:
        fh.write("".join(f"{k}: {v}\n" for k, v in row.items()))
        fh.write("steps:\n" + "".join(f"  {'OK ' if ok else 'BAD'}  exit {rc}  {t}\n" for t, rc, ok in step_results))
    new = not os.path.exists(RUNS_CSV)
    with open(RUNS_CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow(row)
    return dest


def prepare_results(log):
    """Archive results that were never recorded, then clear results/ except history/."""
    leftover = _results_content()
    archived = os.path.exists(RUN_ID_FILE) and os.path.isdir(
        os.path.join(HISTORY, open(RUN_ID_FILE).read().strip()))
    if leftover and not archived:
        latest = max(os.path.getmtime(p) for p in leftover)
        rid = "unarchived_" + datetime.fromtimestamp(latest, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stamp = datetime.fromtimestamp(latest, timezone.utc).isoformat(timespec="seconds")
        record_history(rid, "(no log: these results were found in results/ before this run and never archived)\n",
                       "unknown", stamp, [], note="archived automatically before a new run cleared results/")
        log.append(f"archived unrecorded results to results/history/{rid}\n")
        print(f"archived unrecorded results to results/history/{rid}", flush=True)
    for name in os.listdir(RESULTS) if os.path.isdir(RESULTS) else []:
        p = os.path.join(RESULTS, name)
        if p == HISTORY:
            continue
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    os.makedirs(RESULTS, exist_ok=True)


def step(title, args, log, expect=(0,)):
    shown = ["python" if a == PY else os.path.relpath(a, HERE) if os.path.isabs(a) else a for a in args]
    head = f"\n=== {title}\n$ {' '.join(shown)}\n"
    print(head, end="", flush=True)
    log.append(head)
    proc = subprocess.Popen(args, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:  # stream to the console and keep for run.log
        print(line, end="", flush=True)
        log.append(line)
    rc = proc.wait()
    ok = rc in expect
    tail = f"--- exit {rc} ({'as expected' if ok else 'UNEXPECTED'})\n"
    print(tail, end="", flush=True)
    log.append(tail)
    return ok, rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-tests", action="store_true", help="skip the pytest suite")
    args = ap.parse_args(argv)
    os.chdir(HERE)
    started_dt = datetime.now(timezone.utc)
    git_at_start = git_state()  # before anything is regenerated
    run_id = started_dt.strftime("%Y%m%dT%H%M%SZ")
    log, results = [], []
    prepare_results(log)

    def run(title, cmd, expect=(0,)):
        ok, rc = step(title, cmd, log, expect)
        results.append((title, rc, ok))
        return ok

    try:
        run("1. generate data (seed 42)", [PY, "generate_data.py", "--seed", "42"])
        if not run("2a. fixed.py on F_BOUNDARY", [PY, "fixed.py", "--pings", "fixtures/F_BOUNDARY.csv", "--out", "out/F_BOUNDARY"]) \
                or not run("2b. GATE: qa_check vs hand calculation (F_BOUNDARY)",
                           [PY, "qa_check.py", "--pings", "fixtures/F_BOUNDARY.csv",
                            "--ground-truth", "fixtures/F_BOUNDARY_ground_truth.csv",
                            "--report", "out/F_BOUNDARY/daily_km.csv", "--out", "results/qa_F_BOUNDARY"]):
            msg = "\nSTOP: the checker does not match the hand calculation; not running on the full dataset.\n"
            print(msg, end="")
            log.append(msg)
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
        run("5c. problem impact per bug group + day-cut before/after", [PY, "tools/problem_impact.py"])
        run("5d. limitations (what fixed.py does not handle)", [PY, "tools/limitations.py"])
        if not args.no_tests:
            run("6. pytest", [PY, "-m", "pytest", "tests", "-q", "--results-csv", "results/test_results.csv"])

        summary = "\n=== SUMMARY\n" + "".join(f"  {'OK ' if ok else 'BAD'}  exit {rc}  {t}\n" for t, rc, ok in results)
        print(summary, end="")
        log.append(summary)
        return 0 if all(ok for _, _, ok in results) else 1
    finally:
        finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
        dest = record_history(run_id, "".join(log), started_dt.isoformat(timespec="seconds"), finished, results, git=git_at_start,
                              note="--no-tests" if args.no_tests else "")
        with open(RUN_ID_FILE, "w") as fh:
            fh.write(run_id + "\n")
        print(f"run history: {os.path.relpath(dest, HERE)} (row added to results/history/runs.csv)")


if __name__ == "__main__":
    sys.exit(main())
