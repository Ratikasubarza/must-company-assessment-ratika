"""Regression group: each test must FAIL on old_reference.py and PASS on fixed.py.

The test functions are generated from tests/regression_checks.py, so the pytest
suite, TC-57/TC-58 and regression_summary.py all use the same checks.
Docstrings (Given / When / Then) come from the check functions.
"""
import pytest

import fixed
import old_reference
from regression_checks import CHECKS, checks_for_bug
from regression_guards import GUARDS

IMPLS = {"fixed": fixed, "old_reference": old_reference}


def _make(chk):
    @pytest.mark.regression
    @pytest.mark.parametrize("impl_name", [
        pytest.param("old_reference", marks=pytest.mark.xfail(
            strict=True, reason=f"old_reference.py has {', '.join(chk.bugs)}")),
        "fixed",
    ])
    def _test(impl_name, record):
        expected, actual, ok = chk.evaluate(IMPLS[impl_name])
        record(chk.tc_id, impl_name, expected, actual)
        assert ok, f"{chk.tc_id} on {impl_name}: expected {expected!r}, got {actual!r}"

    _test.__name__ = chk.test_name
    _test.__doc__ = chk.doc
    return _test


for _chk in CHECKS:
    globals()[_chk.test_name] = _make(_chk)


def _make_guard(chk):
    @pytest.mark.guard
    @pytest.mark.parametrize("impl_name", [
        pytest.param("old_reference", marks=pytest.mark.xfail(
            strict=False, reason="guard: outcome on old_reference.py is recorded, not required")),
        "fixed",
    ])
    def _test(impl_name, record):
        expected, actual, ok = chk.evaluate(IMPLS[impl_name])
        record(chk.tc_id, impl_name, expected, actual)
        assert ok, f"{chk.tc_id} on {impl_name}: expected {expected!r}, got {actual!r}"

    _test.__name__ = chk.test_name
    _test.__doc__ = chk.doc
    return _test


for _g in GUARDS:
    globals()[_g.test_name] = _make_guard(_g)


@pytest.mark.meta
def test_TC_57_each_documented_bug_fails_its_regression_test(record):
    """Given old_reference.py with exactly ONE planted bug switched on (repeated for BUG-01..BUG-17),
    When that bug's regression checks run,
    Then at least one of them fails for every bug; and with no bugs on, all checks pass."""
    with old_reference.only_bugs(set()):
        baseline_fail = [c.test_name for c in CHECKS if not c.evaluate(old_reference)[2]]
    not_caught = []
    for b in sorted(old_reference.ALL_BUGS):
        mapped = checks_for_bug(b)
        with old_reference.only_bugs({b}):
            if not mapped or all(c.evaluate(old_reference)[2] for c in mapped):
                not_caught.append(b)
    all_on_pass = [c.test_name for c in CHECKS if c.evaluate(old_reference)[2]]
    record("TC-57", "old_reference",
           "17 bugs caught alone; 0 checks pass with all bugs on; 0 fail with no bugs",
           f"{17 - len(not_caught)} bugs caught alone (missed {not_caught}); "
           f"{len(all_on_pass)} pass with all bugs on {all_on_pass}; {len(baseline_fail)} fail with no bugs {baseline_fail}")
    assert not not_caught and not all_on_pass and not baseline_fail


@pytest.mark.meta
def test_TC_58_fixed_passes_all_regression_checks(record):
    """Given fixed.py,
    When every regression check and every regression guard runs,
    Then all pass: 0 failures."""
    allc = CHECKS + GUARDS
    failed = [c.test_name for c in allc if not c.evaluate(fixed)[2]]
    record("TC-58", "fixed", f"0 of {len(allc)} fail", f"{len(failed)} of {len(allc)} fail {failed}")
    assert not failed
