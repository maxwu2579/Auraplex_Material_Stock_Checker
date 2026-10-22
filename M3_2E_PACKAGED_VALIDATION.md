# M3.2E E1 — Focused packaged validation

2026-10-22, Asia/Singapore. Codex implementation verification; **not an independent audit**. User requested that the unresolved Windows native-restart behavior be retained for later Claude Code investigation and authorized moving forward. This run validates the existing application-managed retry alternative in a temporary EXE, without further production changes.

## Result and boundary

**PASS for the tested packaged entry, timed execution, bounded retry and source-failure safety.** No full M3.2E deployment/release acceptance is claimed. No commit, push, release or later milestone was performed. Windows missed-run catch-up remains unverified; the native-restart cause remains deferred, not fixed or silently dismissed.

## Build

- Existing project virtual environment, Python/PyInstaller 6.22.3; no dependencies installed.
- Same onedir/windowed build approach as the existing script, with all build/spec/dist paths redirected into a new temporary root. The normal build script was not run because it cleans the repository's existing build/dist directories.
- Build completed in approximately 35 seconds. No release ZIP created.
- EXE: `C:\Users\25795\AppData\Local\Temp\MRC_M32E_EXE_899513903e174c8cad49478c7d65fb79\dist\Auraplex_M32E_Test\Auraplex_M32E_Test.exe`
- SHA-256: `39A5ACEC9EA71393E865B853D9E372AE40DB5C3E39DB01A1ACE4E2C7984CE483`
- Archive extraction compared code objects, recursively normalizing filenames, against compiled current source: **app.py plus all 24 checker modules match (25 total)**. Source hashes were checked again after execution. Packaged runtime, rather than source Python, was invoked for every execution below.
- No .py, Excel/CSV, database or log files were found in the runtime distribution. This is a development test bundle, not a complete delivery package or installer.

## Actual Windows executions

Three temporary current-user, least-privilege InteractiveToken tasks were registered with TASK_CREATE; their calendar triggers actually fired at **10:56:16**. No manual Run call was substituted. Actions matched the generated frozen-EXE draft exactly, including `--daily-attempts 3 --daily-retry-delay 30`, and contained no RestartOnFailure element. Test-only overrides were unique task names, near-term trigger start/end boundaries and allowing battery start. No password was stored. Each case had separate synthetic sources, database and report folder.

| Case | Scheduler / application result | Observed completion |
| --- | --- | --- |
| Both sources available | 0 / 0; attempt 1; one complete report | 10:56:17.616 |
| Stock absent, restored during retry delay | 0 / 0; attempt 2; first failure retained, one complete report | 10:56:47.667 |
| Stock remains unavailable | 3 / 3; exactly 3 attempts and 3 failure reasons; no report/partial bundle | 10:57:17.625 |
| Separate EXE invocation with missing application-data folder | Exit 2, missing folder not created; no GUI fallback | Within 15-second bound |
| Separate EXE `--smoke-test` | Exit 0 | Within 15-second bound |

The timed cases ran concurrently in separate data folders, taking approximately one minute after the trigger, rather than waiting for three serial test windows.

## Independent artifact checks within this development validation

The verifier did not use the application reporting or query functions. It used JSON parsing, SHA-256, XML comparison and read-only SQLite queries:

- Report IDs agree with receipts; HTML embeds the correct JSON SHA-256. Both successful reports say VERIFIED as a local-version observation and show Cloud Not Verified.
- All six synthetic source workbook hashes are unchanged. Only synthetic missing-source files were deliberately renamed, and the recovery file restored.
- All three databases pass integrity_check. Scheduled Stock sync record counts match the exact attempt counts, scoped to each synthetic source path; seeded history is excluded from that count.
- Failed case publishes no report and never silently uses retained stock.
- Both original v1.0.0 artifacts retain their pre-run hashes:
  - ZIP: `768759C9961D9027D1A990E678C5581001F151EE2B54AB1C424AB425ED1517D5`
  - EXE: `E232F2074F0F6DFE35EC623C96ED913C4EC570A53B098ABA45F7F74183930E50`
- All three test tasks were deleted and absence checked. Final inventory: **0 matching tasks, 0 test-EXE processes**. No permanent schedule installed.

## Deferred CC investigation and remaining acceptance

Retain `M3_2E_SCHEDULER_VALIDATION.md` and its temporary probe evidence for CC. On this machine neither a minimal task returning 3 nor one returning -2147467259 restarted within a 100-second observation window under PT1M / Count=2. The exact reason is unknown; do not assert that native restart never works. Current draft uses an independently bounded application loop instead, so resolving native restart is not required to execute that tested alternative. Do not reintroduce two multiplying retry loops without a reviewed policy.

Still not executed: actual missed-run catch-up, logoff/sleep/wake/battery transitions, real Google Drive/cloud freshness, real company workbooks, another PC without Python, Windows 10, physical DPI, full GUI interaction/layout, browser/printing and broader package regressions. Running a frozen EXE here confirms bundled entry compatibility but does not establish clean-machine compatibility. No full business suite rerun because no production code changed in this validation; previous focused source run remains 19 passed in 4.932 seconds.

No real workbook/database was opened or upgraded. Existing unrelated changes and audit_test_run.txt remain intact. E1 remains uncommitted pending review; future local commit requires its own authorization. No automatic task installation or company deployment was added.

## Evidence location

`C:\Users\25795\AppData\Local\Temp\MRC_M32E_EXE_899513903e174c8cad49478c7d65fb79\`

`build.log`, `prepare.py`, `source-parity.json`, `plan.json`, per-case draft XML, `run.ps1`, `run-evidence.json`, `verify.py`, `verified.json`, `old-package-hashes.json`, synthetic source/database/receipt/report folders. Evidence is outside the repository and release folders. It is temporary and should not be treated as permanent archival storage.
