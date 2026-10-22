# M3.2D — Daily Stock Summary: test report

Date: 2026-10-22. Environment: Windows 11 Home, Python 3.12.10 (project `.venv`), Tk 8.6, source run (no EXE). All executions used synthetic workbooks and temporary SQLite databases (`tempfile.TemporaryDirectory`); no real company workbook or user database was opened.

## Runs

| Run | Command | Result | Log |
|---|---|---|---|
| Development (affected only) | `python -m unittest tests.test_m32d` (repeated while developing) | final: 35 passed | console |
| Related regression, final code | `python -m unittest tests.test_m32c tests.test_m32c_remediation tests.test_m32c_rereview tests.test_m4a tests.test_m32d` | **108 passed**, 30.97 s | `%TEMP%\MRC_M32D_related.txt` |
| Full suite, final code (shared `alerts.py` and main `ui.py` changed) | `python -m unittest discover -s tests -t .` | **370 tests: 365 passed, 5 skipped** (mounted-drive tests, `MRC_TEST_MOUNT_DIR` not set), 139.84 s | `%TEMP%\MRC_M32D_full_suite.txt` |
| After a statement reorder in `ui.py` (no behaviour change) | `python -m unittest tests.test_m32d tests.test_m32c.AlertUiTests` | 39 passed, 9.01 s | `%TEMP%\MRC_M32D_after_reorder.txt` |

`git diff --check` passed. Published v1.0.0 artefacts re-hashed and unchanged: ZIP `768759C9961D9027D1A990E678C5581001F151EE2B54AB1C424AB425ED1517D5`, EXE `E232F2074F0F6DFE35EC623C96ED913C4EC570A53B098ABA45F7F74183930E50`.

One intermediate related-regression run failed in a new M3.2D layout assertion (title width under the process's DPI scaling left by earlier UI tests). The assertion was corrected to the intended property (the link row is no wider than the existing button row), and the related regression and full suite above were run after that fix.

## Required scenarios → tests (`tests/test_m32d.py`)

| Scenario | Test(s) |
|---|---|
| Alerts present; per-type vs distinct materials | `test_verified_summary_counts_types_and_distinct_materials_separately` (A is OUT_OF_STOCK and LOW_STOCK: 3 alerts, 2 distinct IDs) |
| No alerts, never "stock normal" | `test_no_alerts_is_never_called_normal_stock` |
| No change on the day | `test_no_change_on_the_day_means_no_record_not_no_movement` |
| Quantity / blank / invalid / duplicate / source switch | `test_observed_quantity_change_has_a_difference_but_no_consumption`, `test_blank_invalid_and_duplicate_states_are_reported_not_converted`, `test_source_switch_is_listed_and_not_comparable` |
| Midnight and date boundaries | `test_midnight_belongs_to_exactly_one_day` (00:00:00.000 and 23:59:59.999 local belong to the day, next 00:00:00.000 does not), `test_daylight_saving_day_has_its_real_length` (23-hour day), `test_future_date_is_refused` |
| Cleanup boundary | `test_cleanup_boundary_is_stated_not_reconstructed` (REMOVED / PARTLY_REMOVED / COVERED) |
| Historical date never uses current alerts as that day | `test_historical_date_never_presents_current_alerts_as_that_day` |
| Sync failure / unverified report | `test_sync_failure_makes_the_summary_unverified_and_lists_it`, `test_unverified_session_never_produces_a_verified_summary`, `test_unverified_files_are_marked` |
| Alert evaluation behind the Storage version (same path) | `test_alert_evaluation_of_an_older_version_of_the_same_path_is_not_current`, `test_session_verified_an_older_version_than_the_database` |
| Source/verification change during generation or saving | `test_verification_changed_during_generation`, `test_changed_data_or_verification_refuses_saving`, `test_verification_withdrawn_while_saving_publishes_nothing` |
| Database failure | `test_database_read_failures_produce_no_summary` (missing file not created; read error), `test_database_failure_while_saving`, `test_read_failure_discards_the_session_verification` (UI) |
| Save failure | `test_failed_publication_leaves_no_complete_looking_report` (HTML publish fails after JSON → JSON removed; staging failure; no `.partial` left) |
| HTML special characters / raw text | `test_raw_text_is_escaped_and_the_page_is_self_contained` (`<script>`, `<img onerror>`, quotes, `&`, hostile Sheet name; tag allow-list; no http/src/href/@import/url()) |
| HTML/JSON consistency, no overwrite | `test_html_and_json_come_from_one_summary` (JSON == summary data, HTML SHA-256 meta == JSON bytes, same report ID; second save → ` (2)`, first file unchanged) |
| Read-only | `test_saving_reads_nothing_new_and_writes_no_source_or_database` (workbook hashes/mtimes and logical DB digest unchanged), `test_schema_1_database_still_summarises_without_upgrading` |
| Bounded worker | `test_one_task_and_one_newest_waiting_request` (20 requests → 1 thread, only first and last run), `test_nothing_is_delivered_after_close` |
| Rapid date switching, repeated clicks, newest wins, failure clears preview | `test_newest_request_wins_and_failure_clears_the_preview` |
| Explicit confirmation (default No), UNVERIFIED in preview and file names | `test_unverified_needs_explicit_confirmation`, `test_worker_detected_problem_asks_before_generating_unverified` |
| Verified flow, out-of-date after Refresh | `test_verified_generate_preview_save_and_out_of_date` |
| Window close during generation | `test_closing_during_generation_updates_nothing` (no Tk callback error, nothing delivered, reopen gives a new window) |
| Compact layout | `test_entry_and_window_fit_small_windows` (main window 960×600; summary window 760×480 / 960×600 / 1280×720) |

## Sample output check

`%TEMP%\MRC_M32D_evidence\` was generated by a script from purely synthetic data (see `README.txt` there). The verified preview text was read and checked by hand: type/distinct counts, raw values (`(blank) (BLANK — not 0)`, `approx 8 (INVALID — not converted)`, duplicate `20 | 4`), observed differences only for quantity changes, the synthetic UNAVAILABLE check listed in sync notes, and threshold/raw-data limitations. The past-date and unverified samples carry `UNVERIFIED_` names and the UNVERIFIED banner.

## Not executed

- Visual inspection of the HTML in a browser and printing; screenshots of the window.
- Frozen EXE/portable build, real Google Drive, a second PC, Windows 10, physical high-DPI displays (DPI only through Tk scaling in existing tests).
- Large-volume or slow-disk performance; real DST time zone on Windows.
- Mounted-drive tests (5 skipped; `MRC_TEST_MOUNT_DIR` not set).
