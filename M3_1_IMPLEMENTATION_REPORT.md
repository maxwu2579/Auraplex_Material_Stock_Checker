# M3.1 Implementation Report — Automatic Excel-to-SQLite Synchronization

Date: 2026-10-14. Not committed, not released.

## Architecture

The Google Drive Excel files remain the source of truth. SQLite is a local, read-only mirror that also keeps history. **The BOM Checker engine is unchanged.** CHECK still reads Excel through `checker.reader` and calculates with `checker.core.check_materials`. The database runs alongside the engine; it does not replace it.

| File | Role |
| --- | --- |
| `checker/appdata.py` | `%LOCALAPPDATA%\Auraplex\MaterialStockChecker`; `Settings` (remembered paths, atomic JSON write) |
| `checker/inventory_db.py` | Schema v1 (`PRAGMA user_version`), lossless value codec, connection, schema creation in one transaction. Refuses a newer or foreign database and never deletes one |
| `checker/sync.py` | `InventorySync`: change detection, settle wait, revalidation, atomic publish, snapshots, data-quality records |
| `checker/queries.py` | Read API for M3.2/M4: `open_readonly`, `freshness`, `current_stock`, `list_products`, `bom_lines`, `data_quality(_summary)`, `snapshots`, `stock_history`, `observed_changes`, `observed_change_summary(days)`, `load_workbook_data` (parity rebuild) |
| `checker/ui.py` | Inventory Database panel, Refresh Excel, startup sync, remembered paths. The database is opt-in: `CheckerApp(root)` behaves exactly as v1.0.0 |
| `app.py` | Opens the local data (a failure leaves the checker usable), `--data-dir`, extended `--self-test`. VERSION is `1.1.0.dev0` |

Unchanged: `core.py`, `reader.py`, `report.py`, `report_style.py`, `service.py`, `presentation.py`, and every existing test file.

## Schema (v1)

- `schema_info`
- `source_versions`: one immutable row per imported workbook version (path, size, mtime, content signature, file SHA-256, notes, counts)
- `current_sources`: the published version per role
- `sync_runs`: every check, with outcome `IMPORTED` / `UNCHANGED` / `UNAVAILABLE` / `FAILED`, plus error and `~$` owner files
- `materials`: identity registry of text keys; no quantities and no merging
- `stock_sheets`, `stock_records`: every row as read. Raw code, quantity, description, rack and level are stored as (kind, text); cell types are kept; `material_key` is set only for usable text codes; `numeric_code` is a flag only; `qty_status` is VALID / BLANK / INVALID; `qty_value` (exact decimal) is set only when VALID
- `bom_products`, `bom_lines`: the same, for BOM data
- `inventory_snapshots`: one per imported Storage version, with counts and `has_differences` (NULL = baseline, 0 = a new version with no differences)
- `inventory_changes`: QUANTITY_CHANGED (`observed_net_change`), ADDED, REMOVED, VALIDITY_CHANGED, DUPLICATE_CHANGED
- `data_quality_issues`: DUPLICATE_STOCK, BLANK_STOCK, INVALID_STOCK, NUMERIC_MATERIAL_ID, INVALID_MATERIAL_ID, DUPLICATE_BOM, INVALID_BOM_QTY

## Change detection

1. If the file is missing or inaccessible: `UNAVAILABLE`, nothing is parsed.
2. Otherwise, the ZIP central-directory signature (CRC and size of each `xl/` part, the same signature the cache already uses) is compared with the published version from the same path. If they match: `UNCHANGED`. No parse, no hash, no snapshot. This took about 8 ms on the real files.
3. Otherwise:
   - If the file was modified less than 2 s ago, wait and re-fingerprint.
   - Parse with the unchanged reader, which checks the fingerprint before and after.
   - Re-fingerprint, then SHA-256 the file.
   - In one `BEGIN IMMEDIATE` transaction, insert all rows, the snapshot and the pointer. Re-fingerprint again before COMMIT; any difference means ROLLBACK.
   - Inside the transaction, also re-check whether another program instance already published the same version.

## UI behaviour

- **Startup**: restores remembered paths, then loads and syncs them in the background worker. The UI stays responsive; Tk is updated only from `_poll` on the main thread.
- **First run**: the user selects the files. Only a file that loaded successfully is remembered.
- **Every worker read** (select, CHECK, Reload, Refresh) also syncs, reusing the same parse from the shared cache. The database therefore never lags behind what the checker shows.
- **Refresh Excel**: if a result is shown, it re-runs the same check (and syncs). Otherwise it reloads both files without forcing a re-parse.
- **Panel** (a compact two-line section in the existing notice row, with Refresh Excel beside Reload Files):
  - Line 1: "Inventory Database", Status, Last Checked, Last Successful Sync. The overall sync time is the *older* of the two files.
  - Line 2: one entry per file with its state and Source File Modified, shortened to fit (the full text is in the tooltip).
  - Clicking it shows details, the last error, and a note that "Up to Date" means *matches the local file*, not the Google Drive cloud copy.
- **Placement**: the panel was first placed in the scrollable file overview. A screenshot showed it hidden below the fold at 1280×720, so it moved to the always-visible notice row. That row is already as tall as its buttons, so the section adds little height.
- **Short windows**: the per-file line is hidden (the overall status still shows any failure). The notice sentence becomes one ellipsized line with its full text in the tooltip. This keeps M2.1's guarantee of a usable table (over 60 px) at 960×600 up to 150% font scaling.
- **Failure**: an error dialog when the Excel read failed, with the database note appended; a warning when Excel was fine but the database update failed. The panel shows `Sync Failed · Using Previous Data` or `Source File Unavailable · Using Previous Data`. The last-success time is preserved.

## Data integrity decisions

- Duplicates are stored as separate rows and flagged, never merged.
- Numeric-cell IDs never become keys.
- Invalid or blank stock is kept raw with no trusted value.
- A net change is computed only between two single, valid values. Anything else is an "interruption" in the series.
- "Observed net change" is never called consumption; `OBSERVED_CHANGE_CAVEAT` is returned with every summary.
