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

## Entry 8 - 2026-11-10 - "Is the 8 Nov data still there? Every run should be stored to keep a history of fails and bugs"

**Found:** the 8 Nov results were still on disk (only left out of the commit), but run_all.py overwrote
results/ on every run, so the next run would have erased them. No history was kept.
**Changed:** run_all.py now saves every run (including gate-stopped and --no-tests runs) to
results/history/<run_id>/ with run.log and run_info.txt, and appends a row to results/history/runs.csv.
results/ is cleared at the start of a run (history kept); never-archived results are archived first as
`unarchived_<time>`. The 8 Nov run was archived as 20261108T115954Z from its own files and log (times are
file modification times). TC-56 now runs the README command twice and checks both runs are in history;
it fails on the previous run_all.py (0 history rows) and passes on the new one.
**Choice stated:** history lives in results/history/, not data/, because step 1 regenerates data/.

## Entry 9 - 2026-11-10 - "Finish the write-up: privacy, problem impact, ranking section, directive.md, consistency check"

**Prompt (summary):** remove local paths from logs and scripts; mark the 8 Nov history row's git fields n/a;
measure each bug group's impact (tools/problem_impact.py) and every left-out limitation (tools/limitations.py),
both run by run_all.py; add "Ranking and choice" to intent.md with the user's reason inserted verbatim (numbers
checked only); write directive.md; cross-check numbers across the documents.

**What the AI's output got wrong or nearly missed:**
- `.gitignore` had `*.log`, so every results/history/*/run.log would have been left out of git without notice.
  Added an exception for history logs.
- run_all.py printed the interpreter path relative to the repo; from a copy outside the repo this produced
  a relative path running through the home folder and user name. Pytest failure output also carried the temp folder with the user name. Logs are now
  scrubbed before they are stored, and the interpreter prints as `python`.
- directive.md's own completion criterion quoted the home-folder path prefix it was meant to forbid, so the privacy grep hit it. Reworded.
- tools/limitations.py first reported L06 (midnight-crossing segment) as 0.0 km. The cause was real: in
  data/pings.csv every crossing segment ends exactly at 15:00:00Z. A straddling segment from fixtures/F_DAYCUT.csv
  was added so the limitation gets a real number (0.022239 km).
- The first cross-document check merged CSV fields into wrong numbers (a comma in the number pattern); fixed and re-run.
- "about 150.07 km/h" (BUGS.md, Entry 2) and "+112 m" (BUGS.md) had been calculated, not measured. Both were
  measured this time: 150.0679 km/h and 100,112.023 m vs 100,000.000 m.
- The 8 Nov row's git_dirty was also set to n/a (the request named only branch and commit).

**Number check on the user's ranking text:** all numbers match the measurements except the claim that noise is
"the only problem that makes the advertiser pay more overall" (late pings, duplicates and Earth radius also raise
the total). "Close second" was flagged as not supported by gross km wrong. The text itself was not changed.

**Run history:** run 20261110T134354Z is recorded as BAD (`1 failed, 115 passed, 28 xfailed, 5 xpassed`): TC-56
copies only committed files and tools/ was not yet committed. A scratch clone with everything committed gives
`116 passed, 28 xfailed, 5 xpassed`.

## Entry 10 - 2026-11-10 - "Fix the wrong claim, redo the day-cut before/after, fix the directive links"

**Number check of the ranking text in intent.md** (moved here from intent.md on request; all values from
`python tools/problem_impact.py` and related commands on data/pings.csv):
- "10 of 17 driver-days are wrong": `day_cut … off >1 m: 10/17 (union)`. Matches.
- "about 10 km of the 53.8 km land on the wrong day": over 9.997299 km, under 10.084599 km; baseline 53.802292 km. Matches.
- "The total barely moves": -0.087300 km (-0.16%). Matches.
- "DRV-03 on 2026-11-08" shows 0 km with the day-cut bugs (correct 1.161358 km). Matches.
- "every shift that runs past 15:00Z": DRV-03, 04, 07, 10 and 11 are exactly the 10 wrong driver-days. Matches.
- "a single line, the UTC date used instead of UTC+9": BUG-14 alone makes 10/17 driver-days wrong; BUG-15 alone 1/15. Matches.
- First version of the third paragraph: "the only problem that makes the advertiser pay more overall" did not
  match (late pings +1.325634 km, duplicates +0.070231 km, Earth radius +0.060271 km also raise the total), and
  "close second" was not supported (gross km wrong 2.269227 vs 20.081898). The user replaced the paragraph.
- Replacement paragraph: "the problem that adds the most to what the advertiser pays overall (+2.27 km, +4.2%)":
  noise +2.269227 km (+4.22%) is the largest total increase of any group. "5 driver-days, compared with 10":
  5/15 vs 10/17. "mainly one party": over 2.269227, under 0. All match.

**Changed:**
- Day-cut before/after now compares old_reference with only BUG-14/15 on against fixed.py, with ground truth.
  Measured: total 53.714992 -> 53.802292 km (ground truth 53.802293 summed from six-decimal rows); after = ground
  truth on 17/17 driver-days (union, absent = 0). The earlier all-bugs comparison is kept as one line of context
  (58.872196 -> 58.959594 km).
- The day cut's -0.087300 km total change was measured, not inferred: a new problem_impact.csv column
  (km in driver totals but missing from every daily report) gives exactly DRV-11 0.087300 km; every other group gives 0.
- directive.md now links qa_check.py, data/pings.csv, data/ground_truth.csv, fixed.py#L74-L76 and #L399, and
  tests/regression_checks.py#L198-L205 (TC-43) and #L208-L218 (TC-53); all 25 links checked to resolve after commit.

**Found while checking (the AI's own earlier mistake):** run_all.py measured git_dirty at the END of a run,
after rewriting results/. Once results/ is committed, every run would have reported git_dirty = yes because of
its own outputs. git state is now taken at the start of the run, excluding results/. A simulated
commit-then-run in a scratch clone gave git_dirty = no and overall OK on two consecutive runs.
