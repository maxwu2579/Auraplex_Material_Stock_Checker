# M4F second slice — local report delivery and e-mail drafts: test report

Date: 2026-10-23. Environment: Windows 11, Python 3.12 (project `.venv`), Tk 8.6, source run.

All tests used synthetic workbooks, temporary SQLite databases and folders, and fake keys and API transport. There was no real company data, no real API call, no mail server or client, and nothing was sent.

## Runs

| Run | Scope | Result | Time | Log |
|---|---|---|---|---|
| Development | `tests.test_m4f` after the UI patch | 34 passed | 7.0 s | console |
| Development | `tests.test_m4f_delivery`, iterations | Harness fixes only (see below), then 24 passed | ~9–11 s | console |
| **Final, once** | `python -m unittest tests.test_m4f_delivery tests.test_m4f tests.test_m4e -v` | **94 passed** (24 new + 34 M4F + 36 M4E) | 28.2 s | `%TEMP%\MRC_M4F_DELIVERY_final.txt` |

M4E was included because `assistant.py`, `assistant_ui.py` and `assistant_language.py` are shared assistant modules. `git diff --check` passed.

**Not run:**
- M4D (`providers.py` unchanged this round);
- M3.2D (`daily.py`/`daily_ui.py` byte-identical; only `DailyRunner` is reused);
- M4C (`agent.py` unchanged this round);
- the full suite, packaging, real-environment tests.

**Development fixes were all test-harness issues, not product changes.** The new UI test class first borrowed `setUp` incorrectly (zero-argument `super()`) and was then collected twice through a module-level import. One subtest captured an old session object across re-setup. One test expected a save to complete after closing the assistant, but closing revokes the session, so the save is correctly refused and publishes nothing; the assertion now checks that.

**Two product fixes were found by inspecting the samples:**
- The language code was added to report names, which previously collided within the same second.
- `Content-Language` was being removed by `set_content()`; it is now set last and asserted in a test.

## Requirement → test (`tests/test_m4f_delivery.py`)

| Requirement | Tests |
|---|---|
| Export without AI; status, Observed Change ≠ Actual Consumption, INCOMPLETE_HISTORY kept | `test_local_statistics_export_without_ai_keeps_status_and_unknowns` |
| Unknown stays unknown (zh/en/ms), never 0; canonical JSON keys; three languages differ | `test_unknown_values_render_as_unknown_in_three_languages` |
| AI section separate, escaped, facts unchanged | `test_ai_interpretation_is_a_separate_escaped_section_and_never_changes_facts` |
| Rejected / empty / oversized AI text, digest mismatch, bad basis, extra fields refused | `test_rejected_or_mismatched_inputs_are_refused` |
| No Material IDs, descriptions, Sheet names, paths, source file hashes or content signatures | `test_no_identifiers_paths_or_file_hashes_in_report` |
| Pair published with one report ID; HTML meta SHA-256 = JSON bytes; ` (2)` instead of overwrite | `test_pair_published_once_with_one_report_id_and_never_overwritten` |
| Another program's sync, Local History cleanup marker, Stop/Refresh invalidation during staging refuse | `test_data_change_cleanup_or_session_change_during_staging_refuses` |
| Invalidated session refuses before writing | `test_invalidated_session_refuses_before_writing` |
| No commit possible between final check and rename (`database is locked`) | `test_no_commit_can_happen_inside_the_publication_window` |
| WAL refused, mode unchanged | `test_wal_database_is_refused_and_left_unchanged` |
| Write failure; publish failure plus cleanup failure keeps the original error and names the leftover | `test_write_publish_and_cleanup_failures` |
| Name race: retry re-checks; the other folder is untouched | `test_name_race_retry_checks_again_and_never_touches_the_other_folder` |
| Missing target folder | `test_missing_folder_is_refused` |
| MIME structure, Unicode subject/body, `X-Unsent`, `Content-Language`, exact two attachments (an extra file in the folder is not attached) | `test_mime_structure_unicode_and_exact_attachments` |
| Header injection (CR/LF, tab, U+2028), invalid or too many addresses, empty or long subject | `test_header_injection_and_bad_addresses_are_refused` |
| Saved report changed after saving → draft refused | `test_changed_saved_report_is_refused` |
| Draft has no source data, no workbook (no `PK` zip), body differs by language | `test_draft_contains_no_source_data_and_three_languages_differ` |
| `.eml` never overwrites; bad extension / folder refused; write failure leaves nothing | `test_save_eml_never_overwrites_and_refuses_bad_targets` |
| No network or mail: module has no smtplib/socket/subprocess/webbrowser/startfile/urllib/http.client; patched `socket.connect` never used; fake API never called | `test_nothing_touches_the_network_or_a_mail_server` |
| UI: save without AI, then e-mail preview → `.eml` saved with the exact attachments, no API call | `test_save_without_ai_then_draft` |
| UI: valid AI kept only for these facts, included only when ticked | `test_valid_ai_interpretation_is_included_only_when_ticked` |
| UI: rejected AI reply never kept; checkbox disabled | `test_rejected_ai_reply_is_never_kept` |
| UI: data changed after preview → save refused, preview cleared, no files; after invalidation no folder dialog opens | `test_stale_or_invalidated_report_cannot_be_saved` |
| UI: repeated clicks → one worker thread + busy message; close during a write → no Tk error, nothing delivered, nothing published | `test_repeated_clicks_run_one_task_and_close_drops_late_results` |

## Samples

`%TEMP%\MRC_M4F_DELIVERY_samples\` contains a zh report without AI, en and ms reports with AI, and three `.eml` drafts. Checks done:
- All three drafts were parsed: Subject is UTF-8 encoded, `X-Unsent: 1`, `Content-Language` zh-CN/en/ms, and there are exactly the two attachments.
- The en HTML report was screenshotted in headless Chrome: status banner, statistics, "unknown" values and comparison limits are visible.

## Not executed

- Real company data, real DeepSeek API, real mail clients (Outlook, Thunderbird, …).
- Network, cloud-synchronised or slow target folders; crash or power-loss behaviour.
- Packaged EXE, Windows 10, another PC, physical DPI, manual operation of the real window.
- The full test suite.

## P1-DL1 regression round — 2026-10-23

New class `DeliveryRaceTests` (4 tests) uses a real save held at `report_delivery._checkpoint('staged')`:

| Case | Test |
|---|---|
| DAILY save finishes after a WEEKLY preview was built: the DAILY report is published and kept on disk but not attached; the e-mail button and the handler both refuse | `test_daily_save_finishing_after_a_weekly_preview_is_not_attached_to_it` |
| Same-period (WEEKLY → WEEKLY) regeneration during a save is a different preview | `test_same_period_regeneration_during_a_save_is_a_different_preview` |
| An old save refused at its final check (another program synced) does not clear the newer preview | `test_old_job_failure_never_clears_a_newer_preview` |
| Language switch, ticking the AI box and a different AI text each detach the saved report; returning to exactly the saved presentation re-attaches it; a save with AI is a new report | `test_language_switch_or_ai_choice_change_detaches_the_saved_report` |

Runs actually executed:
- **Development:** `DeliveryRaceTests` was run three times. Two failures were test expectations, not product faults:
  - the button state is refreshed by the 75 ms poll, so the helper now waits for it;
  - after switching to Malay, the refusal message is correctly in Malay.
  The third run passed 4 tests in 4.5 s.
- **Full module once:** 32 tests passed, but the race class had been collected twice through a leftover module-level loop variable; that variable is now deleted.
- **Final, once:** `python -m unittest tests.test_m4f_delivery -v` → **28 passed in 8.58 s** (4 new and 24 existing save/draft tests). Log: `%TEMP%\MRC_M4F_DL1_final.txt`. `git diff --check` passed.

Not re-run this round, as requested: the 94-test combined run (`tests.test_m4f`, `tests.test_m4e`), the full suite and packaging. No real API, real data or mail client was used.
