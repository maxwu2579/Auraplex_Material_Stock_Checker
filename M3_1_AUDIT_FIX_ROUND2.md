# M3.1 Audit Fix, Round 2

Date: 2026-10-14. Responds to `M3_1_FINAL_CODEX_AUDIT.md` (NO-GO).

**Scope.** It covers the three remaining P0 findings only. Nothing was committed, pushed or published. M3.2 and M4 were not started.

**Frozen code.** `checker/core.py`, `checker/reader.py`, `checker/service.py`, `checker/report*.py` and `checker/presentation.py` have no working-tree diff. The calculation rules, the SHORTAGE / EXCEPTION / ENOUGH classifications, the duplicate and invalid-stock handling, and the report calculation are unchanged. There is no cached-data fallback. Source workbooks are only read.

## Results

| Check | Result |
| --- | --- |
| Full suite `python -m unittest discover -v` | **179 tests: 174 passed, 5 skipped, 0 failed** (the skips are the Drive-mount tests) |
| New round-2 tests | 17, all passing; each one fails when its fix is reverted (mutation check) |
| Earlier P0-1 / P1-1 / round-1 race tests | All still pass |
| `app.py --self-test` from source | Passed |
| Packaged EXE (PyInstaller 6.22.3, built in the session scratchpad) `--self-test` | Passed. `frozen=true`, `result_verified=true`, `cloud_notice="Cloud Not Verified"`, export written, Refresh UNCHANGED with no new snapshot, input SHA-256 unchanged. Project `dist\` v1.0.0 ZIP hash unchanged. |

## P0-A: CHECK results bound to source versions

**Root cause.** `CheckerApp._start` ran the CHECK action first: it read both workbooks and calculated. The database sync ran afterwards. The sync could retry and import a newer file, but the result calculated from the older file was published anyway. The panel then said the database matched the local file, which made the old result look as if it belonged to the new file.

**Solution: the consistency protocol** (`checker/binding.py`, `checker/ui.py`)

1. **Read.** `ReadOnlyCache.read` (unchanged) fingerprints each workbook before parsing and again after, and rejects it if they differ. So `WorkbookData.fingerprint` identifies the exact version parsed: path, size, mtime, ctime, device, inode, and the ZIP CRC/size of every `xl/` part.
2. **Calculate.** `check_materials` runs on those two versions (`V_stock`, `V_bom`).
3. **Synchronise after the calculation.** `InventorySync.sync_all` verifies or imports each file. Its final pass re-confirms every verified file after both roles are done.
4. **Confirm.** For each role, the confirmed version `C` is:
   - the `observed` fingerprint of a verified sync (IMPORTED / UNCHANGED), or
   - when that role's sync did not verify (no database, database error, source unavailable or still changing), a direct re-fingerprint taken after the calculation.

   A file that cannot be read gives `C = None`.
5. **Publish** only if `C == V` for both roles. A sync retry that verified a different (newer) version does not match, so it can never validate the earlier calculation.
6. **Retry.** On a mismatch, the whole read → calculate → sync → confirm workflow repeats, at most `CHECK_ATTEMPTS = 3` times. The changed file is re-parsed and the unchanged one comes from the cache.
7. **Outdated.** If the result still cannot be confirmed, it is shown as `OUTDATED / RECHECK REQUIRED · <Storage|BOM> changed`:
   - red label in the results toolbar, status-bar message, and an extra summary line
   - Export button disabled; `export()` and `write_export()` refuse with an error and write nothing
   - the previous valid result is never reused: every job starts by clearing it
8. **Verified results.** A confirmed result shows `Local Sources Verified HH:MM:SS`. Its tooltip or popup (`SourceBinding.describe()`) lists, for each file:
   - path, saved time, size, content signature, and confirmation time
   - whether it was confirmed by the sync or re-read directly
   - that the cloud copy is not verified

**Why a failed sync does not block CHECK.** The database is a mirror, and a database problem must never stop the Excel checker (existing tests require this). When a role's sync did not verify, the result is still bound to the local file by the direct re-read. The database failure is shown separately in the panel. "Cloud Not Verified" and "result version mismatch" stay distinct: the first is permanent and says nothing about the result; the second makes the result OUTDATED.

**What happens when a source changes during CHECK:**

- It changes after the calculation and the sync imports the new version: confirmed ≠ calculated, so CHECK reruns on the new version (attempt 2), and only that result is shown.
- It changes during the sync's own retry, which then imports the newer file: the same rule applies.
- It changes in every attempt: after 3 attempts the last result is shown as OUTDATED and cannot be exported. Both the sync and CHECK retries are bounded.
- It changes after the final confirmation: this cannot be detected, because no finite check can prevent it. The result therefore states which version was confirmed and when, not that the file is still unchanged.

## P0-B: failed sync records cannot restore success

**Root cause.** `_record_failure` can return `recorded=False` when SQLite cannot store the failure row. `_show_inventory` built the panel only from the freshness query. Its newest stored run was the older IMPORTED/UNCHANGED, so the panel went back to `Local File Checked` with the old time, even though this attempt had failed.

**Solution** (`checker/queries.py: with_known_failures`, `checker/ui.py`)

- The in-memory `SyncResult` is authoritative for this program's own attempts. `CheckerApp.sync_failures` keeps the latest failed result per role.
- That failure is overlaid on whatever SQLite returns: Source Unavailable, Source Changed or Sync Failed, with the attempt's error and check time, and `unrecorded=True` when it was not written.
- A role's override is cleared only when this program verifies that role again. That makes it fail-closed for later jobs (for example a BOM-only load) and for startup.
- The stored data and the Last Verified time stay as stored. When the status is not currently verified, the time is labelled `Previously Verified` (panel) or `Previously Verified (historical)` (details).
- The status bar now shows the current database state in every outcome, including read/check failures.
- The details text says when a failure "could not be written to the database".
- Stale jobs still cannot overwrite anything, because every event carries its job id (round 1).

**What happens when a sync failure cannot be logged:**

- **Panel.** The file shows `Source File Unavailable · Using Previous Data` (or `Sync Failed` / `Source Changed`). The overall status becomes `Using Previous Data` (or the failure, if there is no earlier data). The time is labelled `Previously Verified`.
- **Status bar.** It shows `Inventory Database: Using Previous Data — Cloud Not Verified`.
- **Error dialog.** It adds "本次失败未能写入数据库记录".
- **Stored data.** Data, snapshots and versions are unchanged; this is checked table by table in the test.

## P0-C: cloud limitation always visible

**Root cause.** Only the success state's text was qualified, via `status_text()`. Every other state showed the cloud limitation only in a tooltip or the details window.

**Solution**

- A separate, permanent label `Cloud Not Verified` (amber) sits beside the status in the Inventory Database heading. It is never hidden or shortened in any state.
- When space is short, the times shrink to a compact form, then the "Inventory Database" title gives way. The status and the cloud label always stay.
- The heading row adds no height, so the result table keeps its room.
- The status bar adds `— Cloud Not Verified` to every database state.
- Tested states: Local File Checked, Using Previous Data, Source File Unavailable, Source Changed, Sync Failed, Status Unknown, Not Synced, Syncing, and Database Unavailable.
- Tested sizes: 960×600, 1280×720 and 1366×728, each at Tk scaling 100 / 125 / 150 %. In every case the cloud label is mapped, within the window, left of Refresh Excel, not covering the status, and the table is over 60 px tall.

## Modified files (round 2)

| File | Change |
| --- | --- |
| `checker/binding.py` (new) | `SourceBinding`, `bind()`, `CHECK_ATTEMPTS`, `OUTDATED` |
| `checker/ui.py` | CHECK verify / retry loop in `_start`, result-state label, export guard, `sync_failures` overlay, permanent cloud label, historical time label, status bar in every outcome |
| `checker/queries.py` | `with_known_failures()`, `RoleFreshness.unrecorded`, `status_text()` qualifies every state |
| `app.py` | Self-test also requires `result_verified` and the visible cloud label |
| `tests/test_m31.py` | `UiBase` helper base; 17 new tests (below); success assertions now also require the visible cloud label |
| `README.md`, `M3_1_TEST_REPORT.md`, `M3_1_REMAINING_ISSUES.md`, this file | Documentation |

`checker/sync.py`, `checker/inventory_db.py`, `checker/appdata.py` and `build_portable.ps1` are unchanged in this round.

**Existing test changes**

- `VERIFIED_STATUS` is now `Status: Local File Checked`.
- Each former check of the combined text now calls `assert_verified`, which also requires the cloud label to be packed and, when the window is shown, mapped and within bounds. This is stricter than before.
- The P0-1 test no longer forbids "Cloud Not Verified" in the Unknown state. Round 2 requires it there, so the test asserts it instead.

## New tests (round 2)

| # | Requirement | Test |
| --- | --- | --- |
| 1 | Old Storage, then new Storage synchronised | `CheckBindingTests.test_check_with_old_storage_then_new_storage_synchronised_is_recalculated` |
| 2 | Old BOM, then new BOM synchronised | `…test_check_with_old_bom_then_new_bom_synchronised_is_recalculated` |
| 3 | Source change during a sync retry | `…test_source_change_during_a_sync_retry_does_not_validate_the_earlier_calculation` |
| 4 | No stale result published as verified | `…test_source_changing_on_every_attempt_ends_outdated_after_bounded_retries`, plus a check in every binding test that only current results were rendered |
| 5 | Outdated results cannot be exported | `…test_outdated_storage_result_is_marked_and_cannot_be_exported`, `…test_outdated_bom_result_is_marked_and_cannot_be_exported`, `…test_fresh_check_without_database_is_bound_to_the_re_read_files` |
| 6 | Fresh results exportable | `…test_fresh_check_result_is_exportable`, `…test_fresh_check_without_database_is_bound_to_the_re_read_files` |
| 7 | Failure-log write failure with old success in SQLite | `FailureOverrideTests.test_unrecorded_failure_with_old_success_still_in_sqlite` (the audit's reproduction) |
| 8 | Current failure overrides historical success | `…test_current_failure_overrides_success_records_read_by_later_jobs`, `…test_failure_during_startup_sync_is_not_hidden_by_old_success` |
| 9 | Partial Storage/BOM failure | `…test_sqlite_write_failure_while_recording_a_partial_failure` (a real SQLite write error; BOM imports independently) |
| 10 | Cloud limitation in all states | `CloudNoticeTests` (2) |
| 11 | Old jobs cannot overwrite newer results | `CheckBindingTests.test_an_older_check_job_cannot_overwrite_a_newer_result` (plus the round-1 status test) |
| 12 | P0-1 / P1-1 still effective | `InventoryUiTests.test_status_read_failure_*`, `PackagingVersionTests`, all `SourceRaceTests` |
| — | Binding unit tests | `BindingUnitTests` (2) |

Rollback, snapshots, read-only sources and UI responsiveness are covered by the existing tests, which still pass:

- `test_database_write_failure_rolls_back_the_whole_import`
- `test_source_files_are_never_modified`
- snapshot counts in the refresh and self-test runs
- `test_background_sync_keeps_the_ui_responsive_and_touches_tk_only_on_the_main_thread`

## Remaining limitations

- **Freshness is time-bound.** A verified CHECK result or database status means "this local version, confirmed at this time". A save after the final confirmation cannot be detected. Export writes the in-memory result for the confirmed versions; it does not re-read the files at export time.
- **Google Drive's cloud copy is never checked** (no Drive API in M3.1). The label says so permanently.
- **Unrecorded failures live in memory only.** They last until this program verifies the role again. A success by another program instance is not shown until this program re-syncs that role (fail-closed). A restart rechecks all files anyway.
- **Database failures do not block CHECK.** A role whose sync failed for a database reason is bound by a direct re-read, so CHECK keeps working. The panel shows the database failure.
- **An OUTDATED result's rows stay visible** for inspection, clearly marked and not exportable.
- **Worst-case CHECK time** grows with retries: up to 3 CHECK attempts, each with up to 3 sync attempts per file.
- **Layout was verified by Tk geometry at simulated scaling**, not on real 125/150 % displays.
- **Not run:** a real Google Drive mount, the real company workbooks, a second PC.
- **P2 items from the audit are unchanged:** retention, and no encryption or ACL hardening.

## Ready for another independent audit?

Yes. All three remaining P0 findings have deterministic regression tests that fail without the fixes. The full suite and both self-tests pass, and the frozen code and the release artifacts are untouched.
