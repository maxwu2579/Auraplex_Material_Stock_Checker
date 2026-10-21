# M3.1 Test Report

Date: 2026-10-14. Python 3.12.10, project `.venv`.

## Automated tests

`python -m unittest discover -v`: **149 tests. 144 passed, 5 skipped** (the existing Drive-mount tests: no Google Drive mount exists on this PC). All 110 pre-existing tests pass with their files unmodified. The new `tests/test_m31.py` has 39 tests, all passing.

Required cases are covered by:

- initial sync
- reopen with unchanged files (no parse, no snapshot)
- re-saved file with identical content
- changed content with the same size and mtime
- Storage update (−3 recorded as an observed change)
- a new version with no differences
- BOM update
- manual Refresh (unchanged and changed)
- missing Drive source and missing drive letter
- corrupted, truncated and invalid-structure workbooks
- source changing during import, at the final revalidation, and while still being written
- transaction rollback on database write failure (Storage and BOM)
- a failure that cannot even be recorded
- duplicate publication by two program instances
- duplicate IDs, invalid stock values, numeric vs text IDs
- codec round-trip
- 30/60/90-day history windows
- freshness timestamps
- default location, schema version, and refusal of newer, foreign or garbage databases (files left untouched)
- read-only query connection
- settings
- first-run selection remembered, failed selection not remembered
- startup with an unavailable source
- database failure shown as a warning only
- background sync responsiveness, and Tk touched only on the main thread
- database unavailable, with the checker still working
- no local data means v1.0.0 behaviour
- small-window layout at 1280×720, 1366×728 and 960×600 for 100/125/150% scaling, in either test order (an earlier test leaves the process DPI-aware): actions, status and Refresh Excel visible, table over 60 px
- **Excel-vs-database parity** of `check_materials` and the report payload

## Real-data verification (read-only, database in the scratchpad)

| Check | Result |
| --- | --- |
| First import, Storage / BOM | 0.42 s / 0.28 s |
| Unchanged re-check, including after reopening | 6–9 ms per file |
| Parity: 11 products × 1 sheet × 3 quantities | 33 / 33 identical; report payload identical (5 sampled) |
| Rows | 885 Storage rows, 882 BOM rows; database size 0.65 MB |
| Source SHA-256, size and mtime before and after | Unchanged |

## Packaged EXE (isolated build in `C:\Temp\AMSC_M31`, rebuilt after the final layout change and then deleted; v1.0.0 `dist\` untouched)

`sqlite3.dll` is bundled. `--smoke-test --data-dir` exited with code 0 and created the database. Three `--self-test` runs used synthetic workbooks, with Python environment variables removed. The process was frozen and modules loaded from `_internal`.

| Run | Startup sync | Result | Refresh Excel |
| --- | --- | --- | --- |
| 1 | No remembered paths | 3 / 8 / 2 | UNCHANGED, no new snapshot |
| 2 (reopen) | Both UNCHANGED | Same | UNCHANGED |
| 3 (after a Storage edit) | Storage IMPORTED, snapshot 2 | 2 / 8 / 3 | UNCHANGED |

The files recorded as current in the database match the files on disk by SHA-256.

## Visual check

Synthetic preview screenshots were taken (DPI-aware full-screen capture) at 1280×720 and 960 wide, in the Up to Date and Source File Unavailable states.

- The first placement hid the panel below the fold; this was fixed (see the implementation report).
- In the final layout, the status, both file lines (ellipsized at 960), Refresh Excel, the actions and the table are all visible.

## Audit remediation (rounds 1 and 2)

`python -m unittest discover -v` after round 2: **179 tests. 174 passed, 5 skipped** (the same Drive-mount tests), 0 failed. Round 1 added 13 tests (149 → 162) and round 2 added 17 (162 → 179). Details are in `M3_1_AUDIT_FIX_ROUND2.md`.

| Area | Tests |
| --- | --- |
| Round 1, P0-1 status read failure | `test_status_read_failure_clears_the_previous_success_state`, `test_status_unknown_when_the_whole_sync_fails_unexpectedly` |
| Round 1, P0-2 sync races | `SourceRaceTests` (8): windows A and B, retries, bound, cross-role change, another instance |
| Round 1, P1-1 packaging | `PackagingVersionTests` |
| Round 2, P0-A CHECK ↔ versions | `CheckBindingTests` (9), `BindingUnitTests` (2) |
| Round 2, P0-B unrecorded failures | `FailureOverrideTests` (4) |
| Round 2, P0-C cloud notice | `CloudNoticeTests` (2): 9 states × 960×600 / 1280×720 / 1366×728 × 100 / 125 / 150 % |

Mutation check: with each round-2 fix reverted in turn, every corresponding new test failed. The fixes were then restored and checked by SHA-256.

Packaged EXE, round 2: built with PyInstaller 6.22.3 inside the session scratchpad (project `build\` and `dist\` untouched; the v1.0.0 ZIP hash was unchanged). `--self-test` on synthetic workbooks gave:

- `frozen=true`, modules from `_internal`
- `passed=true`, `result_verified=true`, `cloud_notice="Cloud Not Verified"`
- export written
- Refresh: UNCHANGED, no new snapshot
- input workbooks unchanged by SHA-256

## Not executed

- Google Drive mount tests (no mount on this PC)
- a person clicking through the UI
- a second PC
