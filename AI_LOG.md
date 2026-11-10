# AI_LOG.md

A record of each prompt given to the AI assistant (Claude Code), what its output got wrong,
and what was changed. Newest entry at the bottom.

## Entry 1 - 2026-11-08 - "Build it from the beginning, run it, and fix what's wrong"

**Prompt (summary; full text kept by the user):** build a GPS distance QA tool from scratch,
following the Test Cases sheet and intent.md: a seed-42 synthetic dataset of 2,000+ pings with
ground truth; fixtures; old_reference.py with BUG-01..17 plus BUGS.md; fixed.py; qa_check.py;
a pytest suite in three groups; before/after report; hand-check F_BOUNDARY first; never force a
pass; README, AI_LOG and results.

**What the AI found wrong in the inputs** (not silently changed; recorded as P-xx in intent.md):
- intent.md A7 said both "clipped" and "No clipping" (P-01). Resolved to clipping, which the brief, the AC sheet and TC-08/09/10/15 require.
- intent.md had no tolerance, though the brief refers to "the tolerance in intent.md" (P-02). Added A11 (0.001 km).
- TC-39/40 and RTC-06 put local midnight at 17:00Z; for UTC+9 it is 15:00Z (P-03).
- The "Regression Test Cases" tab reuses TC-01..14 for different tests (P-04). Renamed RTC-xx.
- TC-04, TC-12, TC-24 and TC-46 each clash with a rule or with R1's geometry (P-05, P-06, P-07).

**What the AI's own output got wrong during the build, and the fix:**
1. *Fixture rounding.* The first F_NOISE fixture rounded coordinates to 7 dp, so the "exactly
   150 km/h" ping came out at 150.001 km/h. fixed.py correctly dropped it and TC-23 failed on
   fixed.py. Checking the evidence (ping 3 speed 150.001 km/h, lon written as 0.0097472) showed the
   fixture was wrong, not fixed.py. Fix: fixtures keep 9 dp, and the 150 km/h step is the smallest
   9-dp value with speed >= 150 (150.0000257 km/h, rounds to 150.000 under A12). The test was not
   loosened.
2. *Masked bugs in old_reference.py (caught at design time, before code was written).* The first
   bug list hid BUG-08 (strict `>=` at 150 km/h) behind a units bug, and BUG-04 (strict at 100 m)
   behind a "km vs m" bug: with all bugs on, their tests would have passed on the old code. BUG-05 and BUG-09 were redesigned (logged-but-not-dropped
   noise; dropping the wrong ping of a fast pair) so that every regression test fails on the old code.
   TC-57 now checks this: each bug alone, all bugs on, no bugs on.
3. *BUG-15 hidden by BUG-14.* With every bug on, "segment crossing midnight" never happens on
   F_DAYCUT, because the old code uses UTC dates and those never change at 15:00Z. TC-53 was moved to
   the full dataset, which has shifts crossing 00:00Z (DRV-04, DRV-11).
4. *Old error message.* old_reference.py with every bug off did not name the row for a missing Z,
   so TC-44 would have failed on the baseline for the wrong reason. Fixed so that "old with no bugs"
   passes every check.
5. *Results CSV leaked the absolute local path* (the iCloud folder) in error messages. Paths in
   results/test_results.csv are now relative.
6. *Interval fixture.* The first irregular-interval fixture added an extra ping, which gives two
   short intervals, not the "one gap and one short interval" RTC-13 asks for. The last ping is now
   sent 5 s early instead.

**Environment note:** the first `import pandas` from the venv inside iCloud Drive took 2 min 30 s
(0% CPU, waiting on file downloads); the second took 0.5 s. The full test run therefore took about
10 minutes here. Moving the repo out of iCloud Drive, or keeping the venv outside it, should fix this.

## Entry 2 - 2026-11-08 - "Add cases for 149.9 km/h, then run_all, and list all results"

**What the AI found:** fixed.py keeps the 149.9 km/h ping (all 5 kept, 0.444780 km). old_reference.py with
only BUG-03 on reads the same step as about 150.07 km/h and drops it. Recorded as TC-66 and noted in BUGS.md.
**Got wrong:** a background `run_all.py` from before the change was still running and would have produced
stale results. It was stopped, and `out/` and `results/` were deleted before re-running.

## Entry 3 - 2026-11-08 - "Scenario A: 10.1 s / 9.99 s and negative coordinate; Scenario D: new timestamp with same / different coordinates; both send 08:59:99"

**Interpretation stated before building:** "10.1 and 9.99" read as ping intervals in seconds. TC-67..TC-71 added.
**Got wrong:** an impossible time (second 99) produced Python's raw "second must be in 0..59". The message now
says "is not a valid date/time" in fixed.py and qa_check.py.

## Entry 4 - 2026-11-08 - "08:59:99 is not a right time, what's the result? Add regression tests for worst cases"

**Got wrong:** the first check of old_reference on the new cases reported TC-66 and TC-67 failing "with every
single bug". That was not evidence of bugs: those tests read outputs old_reference does not produce (speed
values, interval warnings). Retracted. Added 14 "regression guards" instead (must pass on fixed.py; old
recorded only), so the strict "bug tests fail on old" rule (TC-57) stays intact.

## Entry 5 - 2026-11-10 - User review: stale results, doc claims, tests that cannot fail, circular tests

**Found by the user, confirmed by re-measuring:**
- P-07 claimed reversing data/pings.csv changes km; measured difference is 0.0 (events change instead).
- Docstring numbers were wrong: TC-31 (500 m / 40 km/h vs 355.8 m / 16.0 km/h), TC-10 (633.92 vs 633.91 m, and
  0.472926 vs 0.472916 km, which the AI found while fixing), TC-68 (62.902 vs 62.901 m).
- README linked results/SUMMARY.md, which `rm -rf results` before the re-run had deleted.
- TC-00, TC-46, TC-05/28, TC-52, TC-59 and TC-56 could not fail or were circular.

**Got wrong while fixing:** two of the AI's own deliberate breaks were ineffective (a TC-52 mutation pattern
that did not match, and a TC-59 generator change that drew the same random values). Both were redone;
TC-59 then failed as it should. TC-52 does not fail even with 3-dp rounding (error 0.000292 km), which
confirms the user's point that it cannot catch a defect.
**Found:** parked jitter of 5 m adds 1.655136 km per hour (P-10, NC-01).

## Entry 6 - 2026-11-10 - "Check all the fail steps, debug and fix, make sure no scenario or case is missing on re-run"

**Audit result:** all TC-01..TC-60 covered, but RTC-01, RTC-02, RTC-08 and RTC-09 had no test; regression
guards were missing from the regression summary; AI_LOG had only Entry 1; README had no guard command and
no expected pytest summary. All fixed. TC-56 fails until the files are committed (needs the user's decision).

## Entry 7 - 2026-11-10 - "Check whether old_reference should be present before commit; label it"

**Checked:** old_reference.py is required by the brief (Step 2, Step 5) and 14 files use it. A real run left
data/ and fixtures/ byte-identical (sha256 before = after); it writes only its 4 report files to `--out`.
**Unclear output found:** results/qa_old/qa_summary.txt said `RESULT: FAIL` with no note that this is intended.
**Changed:** qa_check.py has a `--note` option (one line at the top of the report; no check changes);
run_all.py step 4c passes a note saying the FAIL is expected. TC-55 now asserts the note is the first line,
and fails on a copy of qa_check.py that ignores `--note`.
