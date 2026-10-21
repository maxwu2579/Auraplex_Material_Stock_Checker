# M3.1 P1 Export Freshness Fix

Date: 2026-10-20

This is an implementation and regression report, not an independent acceptance audit. The earlier audit's NO-GO decision is preserved as historical evidence; this report does not replace independent re-review.

Latest validation after the cleanup follow-up below: **205 tests, 200 passed, 5 skipped, 0 failures**.

## Scope and result

The remaining P1 was a source save after CHECK: a result calculated with Storage stock 100 could still be exported after Storage changed to 0, before Refresh. Application exports now compare both selected local source versions with the CHECK binding, fail closed on any mismatch or read failure, and require a new CHECK after failure.

Changed production files: `checker/binding.py`, `checker/report.py`, and `checker/ui.py`. Added `tests/test_export_freshness.py` with 23 regression tests. Existing uncommitted M3.1 changes were preserved. No commit, push, release, M3.2, or M4 work was performed.

## Export contract

1. The UI checks both selected source paths before showing the save dialog. If the CHECK result or background-job identity changes while that dialog is open, the original export request is refused.
2. The actual `write_export()` path independently calls `save_verified_report()`, which requires a valid CHECK binding and rechecks both source paths. A direct call cannot bypass version validation by relying on an enabled button.
3. Comparisons use the complete existing fingerprint: resolved path, size, file times, file-system identity, and workbook ZIP-part signature. Selected paths and the in-memory workbook fingerprints must agree with the calculation binding. A matching filename or material name alone is insufficient.
4. Each verification performs two fixed passes over Storage and BOM, so Storage changing while BOM is inspected is also checked. A later matching observation cannot erase an earlier mismatch or error. There is no source retry loop or fallback to cached inventory/SQLite during export verification.
5. The report is generated in a private `.mrc-export-*.xlsx` staging file in the selected output directory. After generation, both sources are checked again immediately before publication. On failure the staging file is removed, the old result is marked `OUTDATED / RECHECK REQUIRED`, its export button is disabled, previous export feedback is hidden, and no new final report is published.
6. On Windows, publication uses a same-directory `os.rename`, which refuses an existing destination. A competing report creation gets a new numbered name, with at most ten publication attempts. Existing source workbooks and reports are never overwritten. POSIX uses a no-overwrite hard-link publication; that branch was not executed on this Windows host.
7. Both existing report sheets retain the M2 tables. Visible row 8 records the completed pre-generation local export-verification time and `Cloud Not Verified`, with a point-in-time limitation. Comments on the Storage/BOM path cells C5/C6 retain the CHECK verification time, export verification time, source path, exact file metadata, content signature, and full-fingerprint version ID. The final post-generation check is an additional publication gate; its later time is not backdated into the saved report.
8. The original raw `build_report()` / `save_report()` formatting API remains available for existing calculation/report tests and does not claim local-source verification. Every user-facing application export uses the guarded `save_verified_report()` boundary.

## Tests and evidence

Final command: `.\.venv\Scripts\python.exe -m unittest discover -v`.

**202 tests: 197 passed, 5 skipped, 0 failures, 83.918 seconds.** The five skips require `MRC_TEST_MOUNT_DIR`; real Google Drive cloud freshness was not tested. Full output: `%TEMP%\MRC_P1_full_tests_final.txt`.

The new 23 tests cover:

- External Storage and BOM saves after CHECK; direct writer refusal and UI refusal before a save dialog.
- Source changes and a new CHECK while a save dialog is open.
- A different selected path with identical file bytes.
- Missing, permission-denied, invalid/replaced sources, and temporary verification failure with later successful observations.
- Changed workbook content even when metadata observations are made identical by injection.
- Storage changing during the BOM fingerprint pass; bounded verification work.
- Changes during report construction and after staging save; no final report or leftover staging file.
- Partial writes, concurrent target creation, bounded target collisions, and protection of existing output.
- A mismatched in-memory workbook, refusal to revive an invalidated binding without CHECK, and successful export after a new CHECK.
- M2 table payload equality, source hash/mtime preservation, unchanged SQLite file, provenance retention, no source reparse, and no database read during export.
- Direct export while CHECK is busy.
- A synthetic workbook containing 101 MiB of media: export did not call the source parser or read media content. This targeted test passed in 1.346 seconds including setup/CHECK/export on this host; it is not a real Drive performance guarantee.

An initial complete run caught an M2.1 success-message regression. The existing message was restored; the final complete suite above passes without changing the original tests.

The complete suite includes prior P0 binding/failure/cloud-warning tests, packaging version safeguards, transaction rollback and snapshot-history tests, Excel/SQLite parity, duplicate/invalid stock preservation, frozen M2 report table payload checks, and the existing Tk geometry/scaling simulations.

## Isolated Windows package

Built the final source with the existing project PyInstaller 6.22.3 in `%TEMP%`, without changing project `build` or `dist`, installing dependencies, or running the release build script.

Scratch folder: `C:\Users\25795\AppData\Local\Temp\MRC_P1_Frozen_aa2d8905dac6477fb6abcb77182bedf5`.

Final frozen self-test: `smoke-final/self_test.json` in that folder. Verified `passed=true`, `frozen=true`, `result_verified=true`, `cloud_notice="Cloud Not Verified"`, `refresh_unchanged=true`, successful report/provenance generation, and unchanged synthetic source hashes. The synthetic result included SHORTAGE and EXCEPTION rows, including invalid stock and duplicate IDs.

## Protected assets

A pre-edit SHA-256 baseline covered 974 existing Python and distribution files. Only `binding.py`, `report.py`, and `ui.py` changed among those files.

All **951 existing distribution files** retained their baseline hashes. The M2 calculation engine, reader, service, report styles, presentation code, SQLite synchronization/query/schema modules, and original M3.1 tests retained their baseline hashes. No real company Storage/BOM workbooks were opened or modified; all fault injection used temporary synthetic workbooks.

`git diff --check` passed. Nothing was staged or committed.

## Remaining limits and handoff

- A finite sequence of local file observations cannot prevent a save immediately after the last observation, or prove that Google Drive has delivered its newest cloud version. The report explicitly limits its claim to observed local versions at the recorded verification time. Fingerprints are invalidation signatures, not cryptographic proof of source authenticity.
- There is no continuous file watcher. The UI retains the historical CHECK timestamp until another action detects a change; every export independently checks sources and invalidates the result on a detected mismatch.
- Export retains the existing synchronous UI call. Validation reads ZIP directory metadata rather than parsing source rows or reading images. Real cloud-placeholder hydration, provider stalls, remote I/O timeouts, physical high-DPI displays, and another PC were not tested.
- Cleanup is attempted after ordinary exceptions. If the OS refuses deletion, the original error is preserved and the UI reports the staging-file path. A process kill or power failure can also leave a staging file; crash durability was not added.
- Existing Google Drive tests remain skipped. No cloud-freshness or real-workbook parity claim is made.

The P1 has been addressed and the available regression/build checks pass. Independent acceptance re-audit should confirm the export boundaries and fault-injection cases before issuing a new GO decision for a local Git commit.

## Follow-up: cleanup failure must not mask a source-version failure

The subsequent static review found an additional P1 edge: the final source check can reject a changed workbook, but an `os.unlink()` failure in `finally` could replace that verification exception. The UI would then show only a write error and leave its earlier CHECK binding marked current.

This was reproduced with synthetic workbooks before the follow-up fix. Three added fault-injection tests initially produced two assertion failures and one exception: the UI retained `result_current=True`, the writer raised `PermissionError` instead of `ExportVerificationError`, and an original disk-full error was lost.

The writer now preserves the original exception type and attaches cleanup failure details rather than replacing it. The UI therefore still marks changed-source results `OUTDATED / RECHECK REQUIRED`, disables export, hides previous success feedback, and displays the cleanup error and staging path. Disk-write failures also retain their original cause. A file the OS refuses to delete can remain; it is an unpublished staging file and must not be used as a successful report. There is no attempt to delete source workbooks or unrelated files.

The export-specific suite now has **26 tests**, all passing. The final full suite was **205 tests, 200 passed, 5 skipped, 0 failures, 65.130 seconds**. Output: `%TEMP%\MRC_P1_cleanup_full_tests.txt`. `git diff --check` passed. Rechecking 960 protected files, including the 951 original distribution files, found no changed hashes. No commit, push, release, or dependency installation occurred.

The final follow-up code was also rebuilt in the same isolated scratch folder with PyInstaller. `smoke-cleanup/self_test.json` confirms `passed=true`, `frozen=true`, `result_verified=true`, successful export with provenance, `Cloud Not Verified`, unchanged-refresh snapshot behavior, and unchanged synthetic input hashes. Project/release build directories were not used.

### Remaining P2 investigation / Claude Code handoff

Google Drive I/O responsiveness remains unverified. Export still runs synchronously on the Tk main thread. A normal button export performs three verification requests (before the dialog, before staging, before publication), each with four ZIP-directory probes. These avoid workbook parsing and media reads but cannot guarantee that a cloud provider will return promptly.

Relevant entry points are `CheckerApp.export()`, `_verify_export_sources()`, `write_export()`, `binding.verify_export()`, and `report.save_verified_report()`.

Suggested next investigation: inject delayed fingerprints and observe Tk timer responsiveness, then measure on a real mounted Drive/placeholder file. If background export is needed, keep dialogs and widget updates on the Tk thread, run validation/staging/publication on a worker, serialize CHECK/Refresh/export, and reject completion events whose job/result/binding identity changed. Preserve both source checks and the no-overwrite publication contract. The existing `_start()` clears the current CHECK result, so it must not be reused unchanged for export. No such worker refactor or cloud validation was performed in this follow-up.
