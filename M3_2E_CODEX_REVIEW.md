# M3.2E E1 — Codex implementation review

Date: 2026-10-22. Scope: current uncommitted E1 diff after the retry follow-up and temporary packaged validation. Reviewed `app.py`, `checker/jobs.py`, `checker/scheduling.py`, `checker/daily_ui.py`, `tests/test_m32e.py`, README, roadmap and evidence reports. This review did not alter production code or rerun tests.

## Decision

**No P0 or P1 finding in the reviewed scope. GO for a local Git commit after the owner chooses to commit. NO-GO for a release, unattended company deployment, or claiming missed-run acceptance.** The Windows native-restart anomaly is retained for CC investigation as a deferred P2. The shipped schedule draft no longer depends on native restart; the explicit application-managed alternative has focused source tests and actual temporary EXE evidence.

## Findings

| Severity | Finding | Disposition |
| --- | --- | --- |
| P0/P1 | None found in the reviewed diff and evidence. | — |
| P2 | Task Scheduler did not restart a minimal task after either exit code 3 or -2147467259 within the bounded PT1M observation. Cause unknown; TaskScheduler Operational history was disabled. | Deferred to CC as requested. The product draft uses three application-managed attempts at 30-second intervals and omits RestartOnFailure, so this anomaly is not a dependency of the tested flow. Do not claim the native issue is fixed. |
| P2 / acceptance | StartWhenAvailable, sleep/logoff behavior, clean-machine compatibility, other PC and real Drive freshness were not exercised. | Keep as deployment acceptance items. No release claim. |

## Review basis

- The headless CLI branches before importing Tk. Exit status maps to the `jobs.run` outcome; frozen CLI tests confirmed normal launch, missing-data refusal (exit 2 without creating the directory), and the GUI smoke branch.
- Each scheduled attempt syncs both remembered Excel paths again, then creates new authorization and calls the existing guarded alert/report flow. Failures do not produce a cache-backed report. The data-directory OS lock prevents overlapping retry loops. The receipt keeps each failure and any published report path.
- Retry count and delay are bounded to at most 3 and 30 seconds, validated before file access. Schedule XML uses current-user InteractiveToken and least privilege, absolute paths, quoted arguments, no password and IgnoreNew. It does not install or change tasks. The generated action matches the actual temporary task action used in the packaged test.
- Frozen code-object comparison matched `app.py` and 24 checker modules to current source. Actual timed EXE cases passed normal run, recovery on attempt 2, exhaustion after attempt 3 with no report, missing configuration refusal and GUI smoke. All named temporary tasks/processes were removed; source hashes and old published artifact hashes were unchanged.
- The most recent focused source regression was 19 passed in 4.932 seconds. The full suite was intentionally not rerun under the user's time constraint; M2 rules and M3.2C/D core modules are outside the production code changes in the latest retry follow-up. `git diff --check` passes.

## Remaining limits

This is a local-commit review, not a release acceptance. No commit, push, release, real-company workbook/database, Google Drive cloud-freshness verification, second-PC test, missed-run test, logoff/sleep/battery test or physical-DPI test was performed. Native restart diagnosis remains open for CC. E1 changes are still uncommitted; `audit_test_run.txt` remains an existing untracked file and must remain excluded from any commit.
