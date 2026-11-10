# GPS distance QA tool (SYNTHETIC data)

Pay-per-km QA for GPS pings. It counts only distance inside zone Z1 along road R1, after
dedup, noise filtering and the UTC+9 daily cut. **All drivers, coordinates, roads and zones
are SYNTHETIC.** The rules live in [intent.md](intent.md) (assumptions A1-A23, B-01, problems P-01..P-09).

## Run everything from a fresh clone

Requires Python 3.11.

```bash
git clone <repo-url> gps-qa && cd gps-qa
```

```bash
python3.11 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements.txt
```

```bash
.venv/bin/python run_all.py
```

`run_all.py` runs these steps in order and prints a summary (exit 0 when every step did what it should):

| Step | Command it runs | Expected |
|---|---|---|
| 1 | `python generate_data.py --seed 42` | writes data/ and fixtures/ (same bytes every time) |
| 2 | `python fixed.py --pings fixtures/F_BOUNDARY.csv --out out/F_BOUNDARY` then `python qa_check.py ... --ground-truth fixtures/F_BOUNDARY_ground_truth.csv` | PASS against the **hand calculation**; if not, the run stops here |
| 3 | `python fixed.py --pings data/pings.csv --out out/fixed` (and `pings_clean.csv`), `python old_reference.py --pings data/pings.csv --out out/old` | report files |
| 4 | `python qa_check.py --pings data/pings.csv --ground-truth data/ground_truth.csv --report out/fixed/daily_km.csv --events out/fixed/events.csv --out results/qa_fixed` | fixed: exit 0; old: exit 1, by design. `results/qa_old/qa_summary.txt` opens with a `NOTE:` line saying the FAIL is expected (it shows the checker catching the 17 planted bugs) |
| 5 | `python regression_summary.py`, `python before_after.py` | results/regression_summary.*, results/regression_guards.csv, results/before_after.csv |
| 6 | `python -m pytest tests -q --results-csv results/test_results.csv` | 0 failed; see "Expected pytest summary" below |

**Commit before running.** TC-56 copies only files git tracks (`git ls-files`) and runs this README in
the copy. With files uncommitted it fails, and step 6 then reports BAD.

### Expected pytest summary
`116 passed, 28 xfailed, 5 xpassed` (149 tests, measured 2026-11-10 with every file committed in a scratch copy).
- **xfailed 28** = 18 bug-regression tests on old_reference (must fail: `xfail(strict=True)`) + 9 guards
  on old_reference (old's result is only recorded) + NC-01 (known limitation: GPS jitter while parked is
  not filtered, `xfail(strict=True)`).
- **xpassed 5** = guards that old_reference happens to pass (TC-27, TC-35, TC-41, TC-52, TC-71). Guards use
  `xfail(strict=False)`, so this is reported, not failed.
- Any **failed** is a real problem. Any XPASS on a bug-regression test or on NC-01 fails the run (strict).

Use `python run_all.py --no-tests` to skip step 6. Run the groups separately:

```bash
.venv/bin/python -m pytest tests -m functional -q
```

```bash
.venv/bin/python -m pytest tests -m regression -q
```

```bash
.venv/bin/python -m pytest tests -m guard -q
```

```bash
.venv/bin/python -m pytest tests -m checker -q
```

Checker help: `python qa_check.py --help`. Exit codes: 0 pass, 1 check failure, 2 invalid input.

> Speed: the pipelines take well under a second. If the repo (or `.venv`) sits in iCloud Drive,
> the first `import pandas` can wait minutes on file downloads (seen: 2 min 30 s), and the suite
> starts many subprocesses. Clone it outside iCloud for a run of a few minutes.

## Files

| File | What it is |
|---|---|
| `fixed.py` | Corrected pipeline. Core logic is plain Python; pandas only writes the reports. |
| `old_reference.py` | Old pipeline with planted bugs BUG-01..BUG-17, each switchable (`--bugs all\|none\|BUG-xx,...`). |
| `BUGS.md` | Each planted bug: what it does, the rule it breaks, the test that catches it. |
| `qa_check.py` | Checker: per driver per local day vs ground truth (tolerance A11), fault precision/recall, interval summary, input validation. Shares no code with the pipelines. |
| `generate_data.py` | Seed-42 dataset (2,525 pings, 12 drivers, 54 injected faults), clean twin, ground truth (computed independently, Liang-Barsky clipping), fixtures. |
| `data/` | `pings.csv`, `ground_truth.csv` (DAILY_KM rows + FAULT rows), `pings_clean.csv`, `ground_truth_clean.csv`, R1 and Z1. |
| `fixtures/` | F_BOUNDARY (+ hand calculation), F_ZONE, F_NOISE, F_STATIONARY, F_PARKED_JITTER, F_LONG, F_DUPLICATES, F_DUP_HALF_*, F_DAYCUT, F_LATE, F_INTERVALS_*, F_INVALID_* and test geometry. |
| `tests/` | `test_functional.py` (fixed.py), `test_regression.py` (bug regressions: old fails, fixed passes; worst-case guards: fixed must pass; TC-57/58), `test_checker.py` (qa_check.py). Checks live in `regression_checks.py` and `regression_guards.py`. Each test is named by its TC_ID and has Given/When/Then. |
| `results/` | `test_results.csv`, `before_after.csv`, `regression_summary.csv/.md`, `regression_guards.csv`, `qa_*` checker reports. |

## Test IDs
- `TC-xx`: the Test Cases tab (TC-01..TC-60, all covered). `RTC-xx`: the "Regression Test Cases" tab
  (RTC-01..RTC-14, all covered; the tab reuses TC-01..14, see P-04). `NC-xx`: known limitations, kept as
  strict expected failures (NC-01: GPS jitter while parked, P-10).
- `TC-00` (hand-calculation gate) and `TC-61..TC-71` (extra input-validation, `--help`, 149.9 km/h, 10.1 s / 9.99 s intervals, negative coordinates, not-a-duplicate and 08:59:99 tests) are new
  and not in the sheet yet (P-09).
- In `results/test_results.csv`, `result` is the raw outcome on that implementation. Regression tests are
  **meant** to show `FAIL` on `old_reference` and `PASS` on `fixed`.
