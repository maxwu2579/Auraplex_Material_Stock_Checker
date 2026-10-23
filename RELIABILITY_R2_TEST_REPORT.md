# Reliability R2 — test report

Date: 2026-10-23. Environment: the project `.venv` (Python 3.12) on Windows 11, with about 2.6 GB free memory before
the final runs.

All tests used synthetic workbooks, temporary folders and temporary SQLite databases. No real company data, real
`%LOCALAPPDATA%`, API, mail client or user-opened window was used. The self-test cases ran `app.py` in separate
processes with a 120 s timeout, with `LOCALAPPDATA`/`APPDATA` pointed at the temporary folder. The self-test window
opened briefly and closed by itself.

## Final runs

| Run | Tests | Result | Time |
| --- | ---: | --- | ---: |
| New: `tests.test_reliability_r2` (three app.py subprocess runs included) | 8 | OK | 9.4 s |
| Directly affected export regressions (one process) | 47 | OK | 39.4 s |
| **Total** | **55** | **OK** | **48.8 s** |

The 47 export regressions:

| Tests | Count |
| --- | ---: |
| `test_export_freshness` (all) | 26 |
| `test_m31.CheckBindingTests`: `test_fresh_check_result_is_exportable`, `test_fresh_check_without_database_is_bound_to_the_re_read_files`, `test_outdated_bom_result_is_marked_and_cannot_be_exported`, `test_outdated_storage_result_is_marked_and_cannot_be_exported`, `test_source_changing_on_every_attempt_ends_outdated_after_bounded_retries` | 5 |
| `test_m21.PresentationTests.test_export_feedback_is_nonmodal_and_complete` | 1 |
| `test_m32a.CacheUiTests`: every test that exports or refuses an export | 11 |
| `test_b1_l10n.DialogLanguageTests.test_export_refusals_and_write_failure_in_three_languages` | 1 |
| `test_m1.UiTests.test_export_writes_new_file_and_never_a_source_workbook` | 1 |
| `test_m2.UiFlowTests`: `test_20_file_update_refreshes_result_and_failure_shows_no_stale_result` and `test_export_excel_from_the_ui_uses_suggested_name_and_never_overwrites` | 2 |

These were selected mechanically as the existing tests that call `write_export`, `export` or `start_export`, plus the
whole freshness module.

`git diff --check` passed, and every changed file stays LF.

As requested, the following were not rerun: the full suite, the 17-module group, the 80/94-test groups, the R1 tests,
`--smoke-test`, screenshots, packaging and performance.

## New tests (`tests/test_reliability_r2.py`)

| # | Test | Requested case |
| --- | --- | --- |
| 1 | `BackgroundExportTests.test_export_runs_in_the_background_with_real_stages_and_the_same_report` | Export button with generation held: the click returns at once, a Tk `after` callback still runs, controls are disabled and nothing is published yet. Status stages are exactly checking → generating → writing → final check → exported. Both sheets' rows equal `build_report` of the same result, the provenance row is present, the success panel is shown and no staging file remains. |
| 2 | `BackgroundExportTests.test_repeated_clicks_and_refresh_start_no_second_task` | While one export runs: a second click, `export()`, `start_export`, `write_export` and Refresh. There is one dialog, one new export thread and no new job; generation ran once and there is one report. |
| 3a | `ChangeDuringExportTests.test_an_input_change_cancels_before_publication` | Quantity changed during generation: the task is cancelled, nothing is published, no staging file remains, the status says cancelled, and there is no success panel or error dialog. |
| 3b | `ChangeDuringExportTests.test_a_change_after_publication_keeps_the_file_but_not_as_the_current_export` | Change right after publication: the file is kept (not deleted), the status says it was published for the earlier result, and there is no success panel. |
| 4 | `ChangeDuringExportTests.test_write_failure_and_closing_never_report_success_or_leave_a_report` | Partial write then `OSError`: an error dialog, no success status or panel, no report or staging file. Closing during generation: the task is cancelled, the worker ends, nothing is published and there is no dialog. |
| 5 | `CachedExportTests.test_cached_export_stays_unverified_and_a_revoked_authorisation_cancels_it` | Cached export in the background is still `UNVERIFIED_…`, with the banners in A1/A8 on both sheets and the cached status. Leaving cache mode during generation (authorisation revoked) cancels the export and publishes nothing. |
| 6a | `SelfTestExitTests.test_a_missing_output_folder_is_created_and_success_exits_0` | A nested missing `OUTPUT_DIR` is created. Exit 0, `passed=true`, report written, nothing created in the fake `%LOCALAPPDATA%`. |
| 6b | `SelfTestExitTests.test_an_unusable_folder_or_result_file_exits_non_zero` | `OUTPUT_DIR` is an existing file: exit 2 with a stderr message, the file is unchanged, and the process ends in under 60 s. `self_test.json` is a folder: the full check runs, then exit 2 with a stderr message, and the window closes within the timeout. |

Source-change refusals during generation and after staging, the final verification, partial-write cleanup and
publication collisions are already covered by the existing freshness tests. Those now run through the background task,
so they were not duplicated.

## Adapted existing tests (3 lines)

These tests clicked Export and asserted immediately, or expected two exports from two instant clicks. They now wait
for the background task with their existing `finish()` helper. No assertion was removed or weakened.

- `test_export_freshness.test_change_while_save_dialog_is_open_is_caught_at_write_boundary`: waits, then the same
  refusal is asserted.
- `test_m1.UiTests.test_export_writes_new_file_and_never_a_source_workbook`: waits before opening the report.
- `test_m2.UiFlowTests.test_export_excel_from_the_ui_uses_suggested_name_and_never_overwrites`: waits between the two
  clicks. A second click during an export is now refused by design; that is test 2 above.

## Mutation checks (development only, not counted above)

- **Cancellation boundaries disabled** (`report._step` never cancels): 3 of the 4 change, close and cache tests failed.
- **One-export guard removed:** the repeated-click test failed.
- **`HEAD`'s `app.py` with an unusable `OUTPUT_DIR`:** the process was still running when the 30 s timeout killed it.
  The current version exits 2 at once.

## Remediation after `RELIABILITY_R2_CODEX_REVIEW.md` (P1-R2-1, P2-R2-2)

The final run took place once, after the fixes were finalised.

| Run | Tests | Result | Time |
| --- | ---: | --- | ---: |
| R2 export tests: `BackgroundExportTests` 2, `ChangeDuringExportTests` 3, `PublicationBoundaryTests` 3, `CachedExportTests` 2 | 10 | OK | 17.0 s |

What was not rerun, and why:

- **`SelfTestExitTests` (2 subprocess tests):** `app.py` changed only in a comment and a docstring; `py_compile`
  passed.
- **The 47 export regressions, the full suite and unrelated modules:** not rerun, as instructed. The shared change is
  confined to the publication step of `report._stage_report`. It is active only when a `Cancellation` is passed, and
  only the main window passes one.

`git diff --check` passed, and every changed file stays LF.

### New and changed tests (`tests/test_reliability_r2.py`)

The R2 file now has 12 tests: 10 export tests and 2 self-test tests.

| Test | Boundary covered |
| --- | --- |
| `PublicationBoundaryTests.test_cancellation_after_the_final_check_but_before_publication_wins` (new) | **Normal mode.** The worker is held after the real final `verify_export`, before the publication lock, while the target does not exist. The Tk thread changes the quantity, and the cancel returns at once (< 1 s, the lock is free). Result: nothing published, no staging file, `published` is `None`, status "cancelled", no dialog. |
| `PublicationBoundaryTests.test_a_publication_under_way_wins_and_the_cancellation_waits_for_it` (new) | **The reviewed race.** The worker is held inside the boundary, just before the real rename. A concurrent `cancel()` stays blocked (still alive after 0.3 s) until the rename completes, then returns `False`. The report stays published (`published` = target), status "published for the earlier result", not accepted. |
| `PublicationBoundaryTests.test_a_cancelled_export_reports_a_staging_file_it_could_not_remove` (new) | **P2.** Cancellation during generation, with removal of this task's `.mrc-export-` file failing (synthetic `PermissionError`). Exactly one leftover. The dialog contains the leftover path, the reason, the original "cancelled before the report was published" error and "current result was not changed"; the status contains the cancelled text and the path. No report, no success panel, the result is not restored. The test removes only its own synthetic leftover. |
| `CachedExportTests.test_revoking_cache_authorisation_after_the_final_check_prevents_publication` (new) | **Cache mode.** The worker is held after the real final `cached.verify`. Leaving cache mode (revoking authorisation) cancels the export; no `UNVERIFIED_` report is published and the status says "cancelled". |
| `ChangeDuringExportTests.test_a_change_after_publication_keeps_the_file_but_not_as_the_current_export` (changed) | **Publication first.** The hold moved from inside the rename (now inside the lock) to the staging-file cleanup after publication. Cancellation then returns `False` immediately. Assertions are unchanged: the file is kept and shown as late, not accepted. |

### Mutation checks (development only)

- **Old, unserialised check-then-rename restored** in `Cancellation.publishing`: the "publication under way" test
  failed, because the concurrent cancel was not blocked.
- **Stale branch dropping `cleanup_warning`:** the leftover test errored, because no dialog was shown at all.

The publication-first and cancellation-first outcomes above are deterministic. They are forced with events and holds,
not timing.

## Not verified

- A genuinely read-only folder (Windows ACL) or a full disk.
- Very large real reports, with how long each uninterruptible stage takes.
- Closing the real program during an export, where the non-daemon worker delays process exit. This is covered only at
  thread level.
- **The 180 s self-test timer is a Tk callback, not a hard deadline.** It was never exercised with a blocked Tk callback
  or a stuck non-daemon worker; exit within 180 s is not guaranteed in those cases.
- **Slow renames.** A rename on a slow network or synced folder, during which a Tk-thread cancel would wait.
- Packaged or frozen `--self-test`, other PCs, physical DPI and screenshots.
- Real data, Drive or API.
