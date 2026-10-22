# M3.2E E1 — Actual Windows scheduler validation

2026-10-22, Asia/Singapore. Codex implementation validation, not an independent review. **Initial native retry failed the observation window; the replacement application-managed retry passed actual timed recovery/exhaustion checks.** Complete deployment acceptance remains pending. Initial validation changed no production code; the user-authorized follow-up changed the schedule draft, dialog explanation and CLI help only.

## Actual executions

Two uniquely named temporary tasks were registered through Task Scheduler COM with TASK_CREATE (no overwrite), current-user InteractiveToken and least privilege. They invoked the actual project `pythonw.exe` and `app.py --daily-run`, using separate synthetic workbooks, schema-3 databases and report folders. No manual task Run call was used: both calendar triggers fired at **10:41:39**.

| Check | Observed result |
| --- | --- |
| Normal timed execution | PASS: scheduler result 0; one successful receipt and one complete HTML/JSON report bundle |
| Report consistency | PASS: VERIFIED local observation, matching report IDs, HTML SHA-256 matches JSON bytes, visible Cloud Not Verified; database integrity_check = ok |
| Source unavailable after prior successful import | PASS: receipt code 3 at 10:41:42.776; scheduler also reported 3; no cached fallback and no report |
| Automatic scheduler retry after recovery | **FAIL within bounded observation / cause unresolved**: source restored at 10:41:44; configured PT1M, Count=2; no second receipt or task start observed before 10:43:56 |
| Source content protection | PASS: SHA-256 of all four synthetic source workbooks unchanged (the unavailable synthetic file was deliberately renamed and restored) |
| Cleanup | PASS: both exact task names deleted and absence checked at 10:43:56; no permanent task installed |

Task names: `_MRC_M32E_uvnv84gw_normal` and `_MRC_M32E_uvnv84gw_retry`. Registered at 10:41:19. The test harness deliberately used a **one-minute** retry interval, battery start allowed, a two-minute execution limit and a four-minute trigger end boundary. Product XML remains unchanged: five-minute retries, ten-minute execution limit and no battery start. This is not a successful test of the production five-minute retry timing.

## Finding: native retry cannot yet be relied upon (P1 deployment gate)

The application correctly returned a source error and Windows recorded exit code 3, but the restored source was not processed by an automatic restart in the observation window. Registered XML read-back confirmed RestartOnFailure Count=2 / Interval=PT1M. Root cause is **not established**; this bounded test does not prove retries can never occur. Task Scheduler Operational history was disabled; it was not enabled or otherwise modified. In-process bounded retry tests previously passed, but those do not establish native scheduler restart behavior.

Next focused work: reproduce with a minimal nonzero-exit task and the application under the same account/settings, compare scheduler behavior, then choose and validate an explicit bounded retry mechanism. Do not claim automatic retry acceptance based solely on XML values. Avoid rerunning unrelated business tests for that investigation.

## Limits

- Missed-run catch-up, logoff, sleep/wake, battery conditions and production five-minute retry timing were not tested. Microsoft documents a default ten-minute delay for StartWhenAvailable queued tasks; no extra long wait was performed: [TaskSettings.StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable).
- Actual registration/first execution passed on this machine in source-Python mode only; no new EXE, Windows 10, second PC, real Google Drive, cloud freshness or real company workbook acceptance is claimed.
- No full test suite rerun: this was a bounded OS integration check with no production code changes. All test data and evidence remain outside the repository. No real inventory database/workbook was opened. No commit, push, release or later milestone started.

## Evidence

`C:\Users\25795\AppData\Local\Temp\MRC_M32E_actual_uvnv84gw\`

- `plan.json`, generated task XML, `validate.ps1`: exact fixtures, test overrides and registration/cleanup logic.
- `scheduler-evidence.json`: registration, failed-run receipt, restoration, timeout, source hashes and cleanup confirmation.
- `verify_outputs.py`, `verified-outputs.json`: separate read-only output/hash/database validation.
- Each case retains its `appdata/daily-runs.json` and synthetic source files; only the normal case contains a report.

**Initial decision:** keep E1 uncommitted pending retry investigation. The follow-up below addresses that gate.

## Follow-up: explicit bounded application retry (10:49–10:52)

Two minimal Python tasks wrote start times and failed once using exit 3 and exit -2147467259 respectively. Under PT1M / Count=2, each started only once during 100 seconds after the trigger. Both were removed. The observation reproduces independently of application imports and source parsing; **the precise Windows cause remains unknown**. No universal Windows behavior is asserted.

The draft now adds `--daily-attempts 3 --daily-retry-delay 30` and omits RestartOnFailure, avoiding multiplied retry loops. The existing process lock covers attempts/delays; each attempt rechecks both sources, creates fresh authorization and retains failure reasons. CLI defaults remain one attempt. The dialog states the retry policy. No business, schema or calculation code changed. Regenerate old XML drafts; installed tasks are not silently edited. Persistent source failure stops after three attempts and waits for the next daily trigger. Individual filesystem calls can still block; the existing ten-minute task limit is unchanged.

Two actual calendar-triggered application tasks used the final generated action: command, arguments and working directory were independently compared against the final draft. Test-only overrides allowed battery start, set near-term start/end boundaries and unique names; no native restart loop was present.

| Scenario | Observed result |
| --- | --- |
| Initially missing source restored during delay | PASS: trigger 10:50:52, restored about 10:51:02, finished 10:51:23; code 0, attempts 2, one retained failure, one VERIFIED local-observation report with Cloud Not Verified |
| Source remains unavailable | PASS: trigger 10:50:52, finished 10:51:53; code 3, attempts 3, three failure reasons, no report or partial bundle |
| Integrity | PASS: synthetic source hashes unchanged, both database integrity checks ok, HTML/JSON hash and report ID match; actions match final draft |
| Cleanup | PASS: all four follow-up tasks removed; zero tasks with this test prefix remained |
| Focused regression | PASS: `python -m unittest tests.test_m32e -q`: 19 tests in 4.932 seconds, including recovery, exhaustion, CLI/process lock, XML and UI; no full suite rerun |

Evidence in the same temporary root: `probe_exit.py`, `probe.ps1`, `probe-evidence.json`, `prepare_bounded.py`, `bounded.ps1`, `bounded-evidence.json`, `verify_bounded.py`, `bounded-verification.json`. An initial harness setting COM RestartCount=0 generated invalid XML and was rejected before registration. The corrected harness removes RestartOnFailure entirely, as does the product draft. This was a harness error.

**Current decision:** retry gate addressed through a tested alternative; E1 remains uncommitted for review. Missed-run/logoff/battery/packaged/real-Drive/other-PC acceptance remains unexecuted. No independent or full deployment acceptance is claimed. No real workbook/database, unrelated task, published package, commit, push or release was changed.
