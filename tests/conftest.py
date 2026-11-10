"""Pytest setup: shared `record` fixture and the results/test_results.csv writer.

Run with `--results-csv results/test_results.csv` to write one row per test:
TC_ID, implementation, result, expected, actual (+ group, test for traceability).
`result` is the raw outcome of the assertion on that implementation: a regression
test on old_reference.py is EXPECTED to show FAIL (it is marked xfail(strict=True),
so pytest itself stays green and an unexpected PASS on old breaks the run).
"""
import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402  (adds the repo root to sys.path)

_ROWS = []


def pytest_addoption(parser):
    parser.addoption("--results-csv", default=None, help="write per-test results to this CSV")


def pytest_configure(config):
    for m in ("functional: runs on fixed.py", "regression: must fail on old_reference.py and pass on fixed.py",
              "checker: validates qa_check.py", "meta: suite-level checks (TC-57, TC-58)",
              "guard: worst-case regression guards; must pass on fixed.py, outcome on old is recorded"):
        config.addinivalue_line("markers", m)


@pytest.fixture
def record(request):
    """record(tc_id, implementation, expected, actual) - stored with the test report."""
    def _record(tc_id, implementation, expected, actual):
        request.node.user_properties.append(("tc", (tc_id, implementation, expected, actual)))
    return _record


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when != "call" and not (rep.when == "setup" and rep.outcome != "passed"):
        return
    recs = [v for k, v in item.user_properties if k == "tc"]
    if hasattr(rep, "wasxfail"):
        result = "FAIL" if rep.outcome == "skipped" else "PASS"   # xfailed = assertion failed
    else:
        result = "PASS" if rep.outcome == "passed" else "FAIL"
    group = next((m.name for m in item.iter_markers()
                  if m.name in ("functional", "regression", "guard", "checker", "meta")), "")
    for tc, impl, exp, act in recs or [(item.name, "", "", "")]:
        _ROWS.append({"TC_ID": tc, "implementation": impl, "result": result, "expected": _fmt(exp),
                      "actual": _fmt(act), "group": group, "test": item.name})


def _fmt(v):
    s = repr(v) if not isinstance(v, str) else v
    s = s.replace(helpers.ROOT + os.sep, "").replace("\n", " | ")
    return s if len(s) <= 300 else s[:297] + "..."


def pytest_sessionfinish(session, exitstatus):
    path = session.config.getoption("--results-csv")
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    order = {"functional": 0, "regression": 1, "guard": 2, "checker": 3, "meta": 4}
    rows = sorted(_ROWS, key=lambda r: (r["TC_ID"], order.get(r["group"], 9), r["implementation"], r["test"]))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["TC_ID", "implementation", "result", "expected", "actual", "group", "test"],
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
