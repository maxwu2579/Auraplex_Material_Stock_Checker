# M4A — Test Report

Date: 2026-10-21. Run by Claude Code on the uncommitted M4A working tree (base `d0633fd`). All inputs are synthetic workbooks (`tests/fixtures.py`) and temporary SQLite databases under `TemporaryDirectory`. The real user database, real workbooks and Google Drive settings were not opened or changed. No destructive test touched real data.

## Final results

| Run | Command | Result | Time |
|---|---|---|---|
| Final full suite (once; shared `checker/ui.py` changed) | `.\.venv\Scripts\python.exe -m unittest discover -v` | **285 tests: 280 passed, 5 skipped, 0 failures** | 203.4 s |
| M4A module | `python -m unittest tests.test_m4a` | 23 passed | ~16–19 s |
| Order-dependence check | `python -m unittest tests.test_m32b tests.test_m4a.HistoryWindowTests` | passed (after the fix below) | ~53 s |
| Concurrency test, 3 repeats | `…test_m4a.HistoryQueryTests.test_one_consistent_view_while_another_program_publishes` | 3/3 passed | — |

The 285 tests are the previous 262 plus 23 new M4A tests; earlier tests were not changed or weakened. The 5 skips are the existing mounted-drive tests, which need `MRC_TEST_MOUNT_DIR`; no Drive tests ran. Logs: `%TEMP%\MRC_M4A_full_suite_final.txt` (final) and `%TEMP%\MRC_M4A_full_suite.txt`.

## History of runs (nothing hidden)

1. The first M4A run had 22/23 passing. One test expected a "Before window" row after cleanup. With the retained snapshots inside the window there correctly is none, so the assertion was corrected to check that the removed snapshot is **not** reconstructed.
2. The first full suite gave 283/285. Two subtests of the M4A small-window test failed (960×600: the table was 1 px high). This reproduced reliably after `test_m32b`, which leaves Tk at 150% scaling. It was a **real layout defect** in the new window at 960×600 / 150%, not a flaky test. The window was fixed (see the implementation report). The test now builds a fresh window for each scale (100 / 125 / 150%) and waits, with a time limit, for the tab to be laid out.
3. Visual review then found Treeview stretch columns squeezed at 960 px. This was fixed with minimum column widths, and an assertion was added.
4. After the code was final, one full suite ran: all passed (above).

## Coverage of the required scenarios

| Requirement | Test(s) | What is asserted |
|---|---|---|
| Normal history query | `test_normal_records_and_quantity_change_with_source_details` | Newest-first rows; raw and exact values; Rack/Level; Sheet, row, file and version; one `QUANTITY_CHANGED` of `-10` with exact before/after times; "not consumption" note; incomplete coverage noted |
| Blank, text, invalid quantities | `test_blank_text_and_invalid_quantities_are_shown_as_read` | `None` / `'abc'` / `'0+10'` kept; no value; displayed `(blank)`, `BLANK — not 0`, `INVALID — not converted`; changes are `VALIDITY_CHANGED` with no difference |
| Duplicate IDs | `test_duplicates_are_separate_rows_never_added` | Separate rows with `duplicates=2`; no summed value (no 3 or 4); `DUPLICATE_CHANGED` with no difference; raw sides listed `1 \| 3` |
| Sheet isolation and filter | `test_sheets_are_isolated_and_filterable` | Same ID in two Sheets: separate, not duplicates; filter returns one Sheet; per-Sheet changes; unknown Sheet shown as "not in this Storage version" |
| Source-file isolation / switch | `test_source_switch_is_never_a_comparable_difference` | Rows keep their own file; `QUANTITY_CHANGED` across a switch has no difference and shows `not comparable (source switch)`; switch listed in coverage |
| 30/60/90 boundaries | `test_30_60_90_day_boundaries_are_inclusive` | A snapshot exactly at `now − days` is inside; 1 ms later it becomes the Before-window row; changes follow; unsupported ranges refused |
| Insufficient history / no results | `test_empty_database_and_unknown_material_invent_nothing`, boundary test | Empty database: no rows, explicit note; unknown ID: `NOT PRESENT`, no value; "no snapshot in window" note |
| After cleanup | `test_cleanup_boundary_and_removed_payload_are_reported_not_filled` | Real `RetentionService` preview + apply; `retained_from` reported; window not fully covered; removed snapshot not reconstructed; removed payload → `NOT_RETAINED`, no value |
| Database unavailable | `test_unavailable_foreign_or_corrupt_database_is_refused_and_never_created`; UI `test_database_failure_clears_previous_result` | Missing, garbage and foreign databases → `HistoryReadError`; missing file not created; inputs byte/mtime unchanged; UI clears the old result and shows `QUERY FAILED` with Cloud Not Verified |
| Rapid queries | `test_older_query_cannot_overwrite_newer_result` | Held 30-day query released after the 90-day result → window keeps 90 days |
| Window closed during a query | `test_closing_during_query_never_touches_destroyed_widgets`, `test_main_app_close_closes_history` | Late response stays unapplied; no Tk callback exceptions; app close closes the window |
| Another process publishes during a query | `test_one_consistent_view_while_another_program_publishes` | A separate `InventorySync` publishes during the query; its commit is still waiting at the second checkpoint; the result has only the old state; afterwards it succeeds and a new query shows both versions with `-50` |
| Search | `test_search_is_partial_exact_first_and_never_merges_similar_ids`, `test_numeric_cell_ids_are_not_searchable_keys`, `test_typing_alone_does_not_query_and_selection_is_exact` | Exact → prefix → contains; `_` / `%` literal; limit flag; `A-1` history excludes `A-10` / `XA-1`; numeric-cell IDs not offered; typing alone does not query |
| Bounded loading | `test_cap_reports_totals_instead_of_silently_dropping`, `test_rows_render_in_batches` | Cap reports totals and `truncated`; 451 rows render as 200 + 200 + 51 with **Show more** |
| Labels | `test_query_flow_and_permanent_historical_labels` | Banner has HISTORICAL OBSERVATIONS and Cloud Not Verified; caveat present; **no `Local Sources Verified` anywhere in the window**; CHECK state untouched; one window instance |
| Read-only | `test_queries_never_write_database_or_workbooks`, query-flow test | Database and workbook SHA-256 + mtime unchanged by queries, search and the window |
| 960×600 / 1280×720 | `test_small_windows_keep_controls_and_tables_usable`, `test_entry_button_fits_main_window` | Fresh window per scale 100/125/150%; both tables > 60 px; banner, caveats, search, Sheet, Range, Query, coverage and status inside the window; no column below its minimum width; main heading buttons fit at 960/1280 and 100/150%; main table > 60 px; Cloud Not Verified visible |

Measured margins:
- At 100%, the Records table is 189 px at 960×600 and 305 px at 1280×720.
- In the real 1.5× font case (fonts created after a 150% scaling), it is 86 px at 960×600 (compact mode on) and 187 px at 1280×720.

## Visual check (source, not EXE)

A synthetic temporary database with duplicates, blank and text quantities, two Sheets and a source switch was opened in a DPI-unaware Python process with the app's real styles. The window was captured at 960×600 and 1280×720 (Records and Observed Changes), and the main window at 960×600.
- At 960×600: all controls, the coverage notes, the full Data Status column, the paging line and the status were visible.
- At 1280×720: correct, but the right and bottom edges were off-screen, because this 300% display has a logical work area of about 1280×680.

Screenshots are in the Claude Code session scratchpad, not in the project.

## Not executed (no pass claimed)

- The frozen / packaged EXE with M4A (no build was made).
- Real Google Drive files or cloud freshness; another PC; native per-monitor high-DPI rendering; Windows 10.
- Real user data of any kind.
- Codex / independent review.
