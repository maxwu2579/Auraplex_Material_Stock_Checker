# B1 「浅蓝工作台」 UI port and interface language: test report

## Subsequent narrow counter-layout repair

2026-10-23: Codex repaired P2-B1-1 at the user's request. The last-trial counters now wrap to the available card width rather than clipping the ENOUGH number. `tests.test_b1_ui.LastTrialLayoutTests` adds two tests: 100% and 150% Tk font scaling, each exercising 960×600 and 1280×720, including six-digit display totals. **2 passed in 7.409 seconds**. This update does not turn the incomplete concentrated run below into a completed full regression. See `B1_UI_CODEX_REVIEW.md` for the preceding independent audit and the bounded repair.

## Round 2 — dialogs, status bar and remembered language (2026-10-23)

Same environment and rules as below: synthetic workbooks, temporary folders and temporary SQLite only. No real data, API, network or mail, and the user's window was not touched. Free memory was checked before each GUI run (about 1.7 GB).

| Run | Scope | Result | Time | Log |
|---|---|---|---|---|
| New tests, first version | `tests.test_b1_l10n` (13) | 13 OK | 9.5 s | `%TEMP%\MRC_B1_L10N_dev1.txt` |
| **New tests, final** | `tests.test_b1_l10n` (14, with `ChineseWordingTests` added) | **14 OK** | **9.9 s** | `%TEMP%\MRC_B1_L10N_new.txt` |
| **Directly affected regressions, once** | `test_b1_ui` (16, incl. Codex's 2); `test_export_freshness.ExportFreshnessTests` (26); `test_m31.CheckBindingTests` (9) and `FailureOverrideTests` (4) — whole classes because their shared helpers carry adapted assertions; plus the 11 individual tests that pin adapted dialog text or exact English status text (listed below) | **66 OK** | **107.3 s** | `%TEMP%\MRC_B1_L10N_regression.txt` |
| Start-up path | `app.py --smoke-test` (no data folder, so no preference file) | PASS | 1 s | console |

**Totals this round: 80 tests run, 80 passed, 117.2 s of test time**, plus the smoke start. `git diff --check` passed. Every test passed on its first run; there were no development failures this round.

The 11 individual regression tests:
- `test_m1.UiTests.test_reload_loads_good_file_when_other_path_is_bad_then_recovers`
- `test_m2.UiFlowTests.test_11_product_id_must_be_selected_before_calculation`
- `test_ui.TkWorkflowTests.test_nonexistent_product_and_invalid_quantity_block_check`
- `test_m21.PresentationTests.test_export_feedback_is_nonmodal_and_complete`
- `test_m31.CloudNoticeTests.test_status_bar_carries_the_cloud_limitation_in_failure_states`
- `test_m31.InventoryUiTests`:
  - `test_first_run_selection_is_remembered_and_reopening_uses_the_database`
  - `test_manual_refresh_synchronises_changes_and_recalculates`
  - `test_startup_with_unavailable_source_warns_and_keeps_previous_data`
  - `test_status_read_failure_clears_the_previous_success_state`
- `test_m32a.CacheUiTests`:
  - `test_external_import_blocks_direct_and_button_exports_until_new_consent`
  - `test_offline_explicit_check_and_report_are_always_unverified`

**Not rerun, as instructed:** the full suite, the 17-module set, the earlier 94 checks, other business suites. No business module changed.

### New tests (`tests/test_b1_l10n.py`, 14)

| Requirement | Test |
|---|---|
| Invalid quantity / ambiguous or unknown product / files not loaded, in zh/en/ms. Translated title; the original rule detail ("Production Quantity 必须是正整数。") kept; recovery step present; no result. | `test_input_problems_in_three_languages_keep_detail_and_recovery` |
| Read failure names only the failing file in each language, keeps the error, says how to recover; the other file stays loaded; the status shows the failure | `test_read_failure_names_the_file_keeps_the_error_and_says_how_to_recover` |
| Export: no result; write failure (path + detail + recovery, result state unchanged); outdated (`OUTDATED` title untranslated); nothing written | `test_export_refusals_and_write_failure_in_three_languages` |
| zh equals the former Chinese wording; codes and details pass through in every language | `test_former_chinese_text_is_kept` |
| The status is one stored message re-rendered (zh, ms, en); English is exactly the original string; the stored message is unchanged | `test_status_is_structured_and_rerendered_not_string_replaced` |
| The database suffix keeps Cloud Not Verified and the state snapshot of its moment (a later state change is not folded in) | `test_database_suffix_keeps_cloud_not_verified_and_the_state_snapshot` |
| Switch during a running CHECK: the running text in the new language, then the finished result; never the old running text afterwards | `test_switching_during_a_running_check_shows_the_running_then_the_finished_job` |
| A failed job stays a failure in every language and is never shown as success | `test_a_failed_job_is_never_rendered_as_success` |
| Preference file missing / invalid JSON / bad encoding / unsupported value / non-object / empty → English with a problem note | `test_missing_corrupt_and_invalid_files_give_english` |
| Atomic save; a failed replace keeps the old file and leaves no temporary file; an unsupported language is refused | `test_save_is_atomic_and_a_failure_keeps_the_old_file` |
| Restored at start (page title and status in Malay) with no job; a switch saves; `settings.json` is byte-identical and the folder holds only the two files | `test_the_last_choice_is_restored_without_extra_work_and_settings_stay_untouched` |
| Corrupt file: English, note shown, file not rewritten until a choice is made, CHECK works; a later choice saves and clears the note | `test_corrupt_file_starts_in_english_and_says_so` |
| Write failure: the language applies for the session; result, status, permissions kept; no dialog; a later save clears the note | `test_a_write_failure_keeps_the_session_language_and_everything_else` |
| An unreadable location never blocks start or CHECK | `test_an_unreadable_location_never_blocks_start` |

### Adapted existing assertions (10 lines in 5 files)

These tests ran in the English interface and pinned the former Chinese dialog wording, which English now replaces with English text. Each assertion now checks the same fact in the English message:

| File | Assertions |
|---|---|
| `test_export_freshness` | 1 |
| `test_m1` | 1 (role name) |
| `test_m2` | 2 |
| `test_ui` | 1 |
| `test_m31` | 5 |

The Chinese wording itself is now pinned in `ChineseWordingTests`. The quantity assertions (`正整数`) needed no change, because the rule's own detail is kept in every language. No refusal count, state or flow assertion changed.

### Not verified this round

- No new screenshots: this round changed no layout. The longer zh/ms status texts are cut at the status cell, with the full text in its tooltip, as before.
- Real dialogs were not viewed on screen; their texts are covered by the tests above.
- Real `%LOCALAPPDATA%` was never written; the restore path was tested only with temporary folders.
- The earlier display, DPI, docking and packaging limits below still apply.

Date: 2026-10-23. Environment: Windows 11 Home, Python 3.12 (project `.venv`), Tk 8.6, source run.

**Display.** The physical screen is **1280 × 720** at 96 DPI, and the work area is 1280 × 672 because of the taskbar. This limits what the screenshots can show; see "Not verified".

All runs used synthetic workbooks (`tests.fixtures`), temporary SQLite databases and temporary folders. There was no real company data, real API, network or mail, and the user's open test window was not touched.

## Runs

| Run | Scope | Result | Time | Log |
|---|---|---|---|---|
| Development 1 | `test_ui, m1, m2, m21, export_freshness, m31, m32a, m32b` | 232 run: 17 failures (all layout: entries moved to pages, a narrower top bar), 5 skipped | 351 s | `%TEMP%\MRC_B1_dev_run1.txt` |
| Development 2 | `test_b1_ui` | 14 run: 3 failures (test expected the exact label; the label also carries a prefix) → fixed, then 14 OK | 16 s / 19 s | `%TEMP%\MRC_B1_dev_b1.txt` |
| Development 3 | The 7 failing or adapted layout tests | 7 OK | 23.5 s | console |
| **Final concentrated run — stopped by the system** | `test_b1_ui, ui, m1, m2, m21, export_freshness, m31, m32a, m32b, m32c, m32c_remediation, m32c_rereview, m32d, m32e, m4a, m4b, m4e` | **Incomplete.** Claude Code stopped it for low system memory (not a test failure) while the session was idle, during `test_m4a.HistoryWindowTests.test_rows_render_in_batches`. Completed before the stop: 380 tests — **374 ok, 5 skipped, 1 FAIL** (below). Not reached: the rest of `test_m4a`, all of `test_m4b` and `test_m4e`. There is no final summary line or total time. | — | `%TEMP%\MRC_B1_final.txt` (partial) |
| Fix check | `test_m32c_rereview.ReadFailureUiTests` (4) + `test_b1_ui` (14) | **18 OK** | 24.8 s | `%TEMP%\MRC_B1_fix_run.txt` |

Completed tests per module in the stopped run:

| Module | Tests |
|---|---|
| b1_ui | 14 |
| ui | 7 |
| m1 | 27 |
| m2 | 35 |
| m21 | 11 |
| export_freshness | 26 |
| m31 | 69 |
| m32a | 26 |
| m32b | 31 |
| m32c | 24 |
| m32c_remediation | 17 |
| m32c_rereview | 9 |
| m32d | 45 |
| m32e | 19 |
| m4a | 20 of the module |

**The one FAIL was a real product defect, now fixed.** In `test_m32c_rereview.ReadFailureUiTests.test_delayed_background_status_read_failure_invalidates`:
- A home-page alert read had started before a database read failure and finished after it.
- Its success callback (`alert_read_ok`) then cleared the newer "database read failed" flag.
- Fix: `home_ui` now records the alert gate generation when a read starts. A successful read is accepted only if the generation is unchanged; otherwise it is discarded and requested again. A failed read always fails closed.
- The failing class and all B1 tests pass after the fix (fix check above).

**The final run was not restarted.** After the fix, the full 17-module set was not run again: memory was short, and an automatic restart was not allowed. To complete the verification, rerun:

```
.venv\Scripts\python.exe -m unittest tests.test_m4a tests.test_m4b tests.test_m4e tests.test_m32c_rereview tests.test_b1_ui
```

Running the whole 17-module set again would also cover the generation-guard change.

**Not run this round** (business code unchanged):
- `test_checker`, `test_m4c`, `test_m4d`, `test_m4f`, `test_m4f_delivery`;
- the full suite;
- `tests/verify_real.py` and `app.py --self-test` (they need real files).

`git diff --check` passed.

## New tests (`tests/test_b1_ui.py`, 14)

| Requirement | Test |
|---|---|
| Every key in all three languages, with identical placeholders | `test_every_key_has_three_languages_with_the_same_placeholders` |
| Codes, OUTDATED, UNVERIFIED and Cloud Not Verified untranslated; unknown state text never guessed | `test_codes_and_the_cloud_limitation_are_never_translated` |
| Switching zh→ms→en→zh after CHECK + filter + row selection keeps everything, reads nothing and invalidates nothing; Cloud Not Verified, Material IDs, result codes and file names stay unchanged; en restores the exact old status text | `test_switching_keeps_every_input_result_filter_and_permission_and_reads_nothing` |
| A CHECK running during a switch completes and is current | `test_a_running_check_finishes_normally_across_a_switch` |
| Without a database, the Cloud Not Verified chip stays in every language | `test_without_a_database_the_cloud_limitation_stays_visible_in_every_language` |
| A result withdrawn by the existing invalidation is never restored by language or navigation; counts `—`; Open result disabled | `test_an_invalidated_result_is_never_restored_by_language_or_navigation` |
| An outdated binding stays OUTDATED and not exportable on both pages, in all languages | `test_an_outdated_result_stays_outdated_and_not_exportable` |
| Alert tiles show "unknown", never 0, without a database, without an evaluation, or after a read failure (table cleared) | `test_alert_counts_are_unknown_never_zero_when_not_known` |
| Tiles partition the stored rows (sum = total); overlap note; tile filter and Show all | `test_home_tiles_group_stored_rows_and_state_the_overlap` |
| History, Analytics, Stock Alerts (two entries) and Daily entries open the real functions; exactly one page is shown; navigation keeps the result | `test_every_entry_opens_the_existing_function` |
| Settings file buttons use `browse`; a cancelled dialog changes nothing | `test_settings_file_buttons_and_cache_entry_use_the_existing_handlers` |
| AI reports entry opens the assistant on its report tab; the interface switch does not change the assistant's language or session | `test_ai_reports_entry_opens_the_assistant_report_tab_and_keeps_its_session` |
| Forced dock at 1280: CHECK, EXPORT, Refresh, status, Cloud chip and robot visible; sidebar collapses; switching back to a window keeps the draft and the result | `test_docked_assistant_keeps_check_export_status_and_robot_visible` |
| Sidebar collapse is the user's choice; it survives resizing and changes nothing else | `test_sidebar_collapse_is_a_user_choice_and_changes_nothing_else` |

## Adapted existing tests (5)

The behaviour each test checks is unchanged; only where the entry is found changed.

| Test | Old assumption | Now |
|---|---|---|
| `test_m21.FreshWindowLayoutTests` | Result table on the single screen | `show_page('check')` after `render_result` (a direct `render_result` does not switch pages; a user CHECK does) |
| `test_m32b…test_maintenance_controls_fit_small_windows_and_scaling` | Cache and Local History in the header | Local History checked on Settings, Use Cached Data on the check page |
| `test_m4a…test_entry_button_fits_main_window` | History, Local History and cache in the header | Each checked on its page (Materials & history, Settings, check) |
| `test_m32c…test_alert_window_and_entry_fit_small_windows` | Alert line in the header | Checked on the Alerts page; table height checked on the check page |
| `test_m32d…test_entry_and_window_fit_small_windows` | Daily link no wider than the header button row | Daily entry inside the window on the Daily page. The width comparison to the old header row was removed because that row no longer exists. |

All other assertions, including every text-pinning one, run unchanged.

## Screenshot evidence

Screenshots were taken of the real `CheckerApp` window with `PrintWindow` (Windows GDI via ctypes; no PIL installed, nothing installed). The harness:
- runs in its own process for each font scale; Tk fonts are resolved when widgets are created, so the scaling is set first;
- uses synthetic workbooks with zero, low, blank, text and duplicate stock, a missing threshold and a BOM material missing from Storage;
- uses a temporary database, a real sync, a real alert evaluation and a real CHECK.

Harness: `C:\Users\25795\AppData\Local\Temp\claude\C--Users-25795-OneDrive-Desktop-Projects-ChatGPT----MaterialRequirementChecker-M0\51264213-da27-4c2a-a667-1c2fa9b66312\scratchpad\b1_harness.py`.

**Final sweep:** 69 PNGs plus `metrics*.json` (window size, table heights, visibility of the key controls per shot), in `%TEMP%\MRC_B1_shots\final\`:

| Folder | Content |
|---|---|
| `s100\`, `s150\` | Pages home, check and settings × zh/en/ms × 960×600, 1280×720 and 1366×768, at 100 % and 150 % |
| `nodb\` | No database, zh/en, 1280×720 and 960×600 |
| `assistant\` | Separate assistant window plus the main window |
| `dock\`, `dock150\` | Docked assistant, forced (see "Not verified"), zh/ms at 100 % and en at 150 % |

Development shots are in `dev1`–`dev5`.

**What was checked by viewing the images.**
- B1 sidebar, top bar and cards; slim sidebar below 1100 px.
- Cloud Not Verified chip visible on every page, in every language and with or without a database.
- Language buttons, translated labels, codes untranslated.
- Home: quick check, last trial card with counts and basis, tiles with real counts (12 alerts across 9 materials, with the overlap note), alert table, data sources.
- Check page: filter counts, row colours unchanged, CHECK, EXPORT, Use Cached Data, Reload Files.
- 150 %: the home page and the file overview scroll; nothing is cut.
- No database: tiles read "unknown" (two columns at 960 px).
- Docked: CHECK, EXPORT, Refresh and status remain visible beside the assistant.

**Defects found by viewing and fixed:**
- wrap width inside cards;
- the alert table collapsing at 960×600 (now a scrolling page);
- times running under Refresh at 150 %;
- the status text overlapping "Verification Required";
- "unknown" cut off in narrow tiles;
- a duplicated "not production approval" line.

**Metrics.** In every shot, the controls required for the page were mapped and inside the window: CHECK, EXPORT, Reload (check page); home CHECK and Open Stock Alerts (home); Refresh, status, Cloud chip, robot and language buttons (all pages). In no-database mode, Refresh and the database status do not exist, as in v1.

**Shot timing.** The final sweep was taken before these last changes:
- 2/4 tile columns: shown separately in `dev5\home_en_960x600_100_nodb.png`;
- the `?` on the alert badge;
- the removal of a wrong "opens in its own window" note from the Settings cache card;
- the read-generation guard and the render split: no visual effect.

A screenshot is evidence of layout and text, not of every state. The tests above cover the states.

## Not verified

**Physical display: 1280 × 720.**
- "1280×720" gives a 1280 × 701 client area, and the bottom of the window frame lies off screen in the capture.
- "1366×768" is clamped by Windows to 1284 × 701, so a true 1366 × 768 window was **not** verified.
- The same clamp applied to the existing 1366×728 test sizes.
- The 960 × 600 shots are complete.

**Font scaling.** The 150 % checks use Tk scaling (`tk scaling`), not the Windows display setting. Physical DPI / per-monitor DPI, Windows 10 and another PC were not checked.

**Assistant docking.** Docking requires a window ≥ 1440 px × scale, which this screen cannot produce.
- Docking was shown and tested only by forcing the mode (`_wanted_mode` patched).
- The real switch between dock and window at that width was not observed.
- The separate assistant window is a normal window and can overlap the main window. It is not topmost, so the main window can be brought forward; its placement was not changed.

**Not executed in this round:**
- manual operation of the real window by a person;
- a packaged EXE;
- real Storage/BOM files and the Google Drive copy;
- real AI / API and mail clients.

**Incomplete:** the final test run (see "Runs").

**Interface-language gaps, listed explicitly.**
- Separate windows remain English: Stock Alerts, History, Analytics, Daily Summary, and the assistant (own selector).
- As of round 1, all of these remained in their earlier text: dialog bodies, the cleanup / upgrade / cache dialogs, status-bar messages, the result-state label, the alert entry line, detail popups and most tooltips.
- The language was not remembered between starts.
- **Updated in round 2:**
  - Now translated: the main-window error dialogs (file reading, input, CHECK, export) and all status-bar messages.
  - Now remembered: the interface language.
  - Still untranslated: the cleanup / upgrade / cache dialogs, the result-state label, the alert entry line, detail popups, most tooltips and lower-layer error details.
