# M3.2C — Test Report

Date: 2026-10-21. Run by Claude Code on the uncommitted working tree (base `d0633fd` + M4A + M3.2C). Automated tests use only synthetic workbooks (`tests/fixtures.py`) and temporary databases. Real-data checks were read-only, against temporary databases that were deleted afterwards.

> **Status after remediation (2026-10-21).** The figures below are the first M3.2C implementation run. After the Codex-review repair, the final full suite is **326 tests: 321 passed, 5 skipped, 0 failures (141.0 s)**: these 309 plus 17 new regression tests in `tests/test_m32c_remediation.py`. The existing `tests/test_m32c.py` was adapted to the concrete authorization API and schema 3 without weakening assertions (one bounded-history expectation now also keeps the referenced provenance row). Details, mutation evidence and real-data re-validation: `M3_2C_REMEDIATION_REPORT.md`.

## Final results

| Run | Command | Result | Time |
|---|---|---|---|
| **Final full suite** (once; shared core changed) | `.\.venv\Scripts\python.exe -m unittest discover -v` | **309 tests: 304 passed, 5 skipped, 0 failures** | 253.8 s |
| M3.2C module, 3 consecutive runs | `python -m unittest tests.test_m32c` | 24/24, three times | ~8–10 s each |
| Affected modules after the reader/sync/schema change | `tests.test_checker test_m1 test_m2 test_m21 test_m31 test_m32a test_m32b test_m4a` | 252 run, 247 passed, 5 skipped | 187 s |
| UI-affected modules after integration | `tests.test_m31 test_m32a test_m32b test_m4a test_ui` | 156 passed (after the fix below) | 152 s |

309 = the previous 285 + 24 new. No existing test was changed or weakened. The 5 skips are the mounted-drive tests (`MRC_TEST_MOUNT_DIR` not set); no Drive test ran. Log: `%TEMP%\MRC_M32C_full_suite.txt`.

## What went wrong during development (nothing hidden)

1. **Alerts label in the Inventory Database panel.** The first placement broke 3 M3.1 layout subtests at 960 px: the verification time lost its guaranteed visible space. The label was moved under the top buttons, the panel code was restored exactly, and the M3.1 tests pass unchanged.
2. **First M3.2C run: 23/24.** The OUT_OF_STOCK detail lacked the row's threshold status, so a "stock 0 / threshold 0" alert could not show that the 0 was kept. This was a real gap and was fixed in `alerts.py`. One assertion in the duplicate-row test was then too crude: it matched the "3" in a row number, not a summed value. It was rewritten to check the per-row values exactly.
3. **Line endings.** A helper script rewrote `cached.py`, `retention.py` and `history.py` with CRLF line endings, which `git diff --check` reported. They were restored to LF byte-wise, with no content change, and `git diff --check` passes.
4. **Test-design race.** The "version published between read and write" test was first designed with a racy background publisher. It now publishes deterministically at the write connection.

## Coverage of the required checks (`tests/test_m32c.py`)

| Requirement | Test(s) | Asserted |
|---|---|---|
| `MIIN QTY` and `MIN QTY` only; no fuzzy matching | `test_miin_qty_and_min_qty_are_the_only_recognised_headers` | Both headers (and trimmed / lower-case forms) → `FOUND`, column P, original spelling kept, raw values and cell types. `MIN. QTY`, `MINIMUM QTY`, `MIN  QTY`, `MINQTY`, `MIN QTY (PCS)` → `NOT_FOUND`. |
| Several candidates → no automatic choice | `test_several_candidates_are_never_chosen_automatically` | `AMBIGUOUS`, candidates listed, no value read, reader note |
| M2 unchanged | `test_m2_check_is_identical_with_and_without_a_threshold_column` | Every M2 row (category, data status, required, stock, shortage, exceptions incl. ASSUMED 0) is identical with and without the column |
| Excel↔database parity | `test_excel_and_database_reconstruction_stay_identical` and the existing M3.1 parity test | Reconstructed Storage Sheets equal the Excel read, thresholds included |
| No automatic migration; schema 1 keeps working | `test_new_databases_are_schema_2_and_schema_1_is_never_migrated_automatically` | New database is v2; opening a v1 database leaves it byte-identical. Sync, history, cache, retention preview and reconstruction (`NOT_CAPTURED`) work on v1. Alerts report "upgrade required". |
| Explicit upgrade, backup, add-only | `test_preview_is_read_only_and_apply_backs_up_then_adds_only` | Preview does not change the file; the backup's logical digest equals the pre-upgrade database; existing rows unchanged, new columns empty; integrity ok; schema SQL identical to a new database; a second upgrade is refused |
| Rollback / refusal | `test_refused_or_failed_upgrade_leaves_schema_1_intact` | Change after preview → refused, unchanged. Failure before COMMIT → rolled back, still v1, error names the backup. Missing database → refused, not created. |
| Threshold capture from the same version | `test_thresholds_are_captured_once_from_the_same_file_version`, `test_capture_refuses_a_different_row_layout` | `NOT_CAPTURED` blocks threshold alerts; the unchanged sync captures from the caller's parse (no extra parse) exactly once; a mismatched row layout writes nothing |
| Retention and cache on schema 2 | `test_retention_and_cache_work_on_schema_2_with_alert_tables` | Preview, apply and backup digest include alert tables; alerts survive cleanup; cache still loads |
| OUT / LOW / THRESHOLD / DATA_ISSUE rules | `test_alert_classification_rules` | OUT {A (0, blank threshold), D (0/0)}. LOW {B (3<5)}; C 5=5 not low; D 0/0 not low. THRESHOLD_NOT_CONFIGURED {A}, shown together with OUT. BLANK_STOCK, INVALID_STOCK (text), INVALID_THRESHOLD (text, negative, formula), DUPLICATE_STOCK_ID, UNUSABLE_STOCK_ID (numeric-cell ID). Nothing else inferred. |
| Raw values; 0 ≠ blank | `test_raw_values_are_kept_and_zero_threshold_is_not_interpreted` | `['int','0']` stock and threshold kept with status VALID / value 0; text kept as text; duplicate rows listed with values 1 and 2, never 3 |
| BOM coverage across all product Sheets | `test_bom_coverage_checks_every_product_and_counts_distinct_ids_rows_and_products` | Three product Sheets checked. `X 1` ≠ `X1`; `h` matches `H`. Occurrences per product/row with raw QTY (not summed). Counts: 3 distinct IDs, 4 BOM rows, 3 products. Numeric-cell BOM IDs excluded and counted. A duplicated Storage ID is a DATA_ISSUE, not "not found". |
| De-duplication; resolution only when verified | `test_persistence_deduplicates_and_only_verified_evaluations_resolve` | Repeated runs create no duplicates and keep first-seen. An unverified run changes nothing even after the data changed. The next verified run resolves exactly one alert. Versions are recorded. |
| Read failure / failed sync never resolves | `test_read_failure_or_failed_sync_never_resolves` | After an `UNAVAILABLE` sync: UNVERIFIED, nothing resolved. Injected database error: FAILED evaluation recorded with message; active alerts unchanged. |
| Version published concurrently | `test_version_published_between_read_and_write_writes_nothing` | Another `InventorySync` publishes between the read view and the write → `AlertStale`; no evaluation or alert row written |
| Bounded history | `test_alert_history_is_bounded` | Evaluations pruned to the limit; resolved alerts removed after the retention days |
| Sheet isolation | `test_sheets_are_evaluated_separately` | An ID only in Sheet One is "not in stock master" for Sheet Two, not merged |
| Concurrency cap | `test_one_running_and_one_latest_pending`, `test_nothing_is_delivered_after_close` | 11 requests → 1 thread; only the first and the newest pending run. Nothing is delivered after close; new requests are refused. |
| Automatic trigger and labels (UI) | `test_evaluated_automatically_after_both_files_are_verified` | One verified file is not enough. After both files: "Stock Alerts: 2 active". Window banner has Cloud Not Verified and "pending business confirmation"; no `Local Sources Verified`; basis names `MIIN QTY`; CHECK state untouched. |
| Failed refresh (UI) | `test_failed_refresh_keeps_alerts_and_marks_them_not_rechecked` | Label "not re-checked"; stored alerts unchanged; session not verified |
| Upgrade flow (UI) | `test_schema_1_database_needs_explicit_upgrade` | v1 → "upgrade required"; declined preview leaves the file byte-identical; accepted → backup, v2, refresh captures `FOUND` thresholds, alerts evaluated |
| 960×600 / 1280×720 | `test_alert_window_and_entry_fit_small_windows` + the existing M3.1/M3.2/M4A layout tests | Alerts line inside the main window at 960×600; main table > 60 px; alert table > 60 px with banner, Re-evaluate and status inside the window at both sizes |

## Real-data checks (read-only)

Commands (scratch scripts outside the repository):
- `real_inspect.py`: aggregate inspection.
- `real_alerts.py`: fresh-v2 and upgraded-v1 temporary databases, sync, evaluation, record.
- `real_crosscheck.py`: independent recount from reader rows.

Results are in `M3_2C_IMPLEMENTATION_REPORT.md`:
- all baseline facts reproduced;
- alerts: OUT 494, LOW 133, not in master 133 IDs / 373 rows / 11 products, DATA_ISSUE 112, THRESHOLD_NOT_CONFIGURED 417;
- the independent recount matches exactly;
- fresh and upgraded paths are identical;
- the workbooks are unchanged and the temporary databases were removed.

## Visual check (source, not EXE)

A synthetic temporary dataset was opened in a DPI-unaware Python process, and the main window and the Stock Alerts window were captured at 960×600. Both are readable: the alerts line is under the top buttons, the Inventory Database panel and the CHECK row are unchanged, and the alert table, basis, filter, buttons, details and status are visible. Screenshots are in the session scratchpad only.

## Not executed (no pass claimed)

- Packaged / frozen EXE with M3.2C.
- Upgrade of the user's real database (intentionally not done).
- Real Google Drive or cloud freshness; another PC; native high-DPI; Windows 10.
- Notifications or daily summaries (M3.2D, not started).
- Codex / independent review.
