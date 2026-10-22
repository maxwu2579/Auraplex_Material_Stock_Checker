# Auraplex Material Stock Checker

A Windows tool that calculates the material requirements of a product from its BOM and compares them with the current Storage inventory.

## Download

Go to [Releases](https://github.com/maxwu2579/Auraplex_Material_Stock_Checker/releases) and download:

```
Auraplex_Material_Stock_Checker_v1.0.0_Portable.zip
```

Extract the ZIP and double-click `Auraplex_Material_Stock_Checker.exe`. No installation and no Python are needed. Keep the extracted folder together; the `.exe` needs the `_internal` folder next to it.

The application is not digitally signed, so Windows may show a "Windows protected your PC" notice on first start. Only run it if you downloaded it from the Releases page above.

## Features

- Product ID search (type part of an ID, pick from the list)
- Production quantity calculation
- BOM vs Storage comparison
- Shortage highlighting
- Exception detection for missing, blank, invalid or duplicated data
- Excel report export
- Google Drive for Desktop support (files are read as ordinary local files)

## Result colours

| Colour | Result | Meaning |
| --- | --- | --- |
| Red | SHORTAGE | Required quantity is greater than the stock recorded in Storage |
| Yellow | EXCEPTION | The source data needs checking before the figure can be relied on |
| White | ENOUGH | Required quantity is covered by the stock recorded in Storage |

Results are always listed red, then yellow, then white.

Exception types: `STOCK_NOT_FOUND`, `BLANK_STOCK`, `INVALID_STOCK`, `DUPLICATE_STOCK`, `DUPLICATE_BOM`, `INVALID_BOM_QTY`, `CODE_TYPE_MISMATCH`, `INVALID_MATERIAL_ID`.

When a material is not found in Storage, or its stock value is blank or not a number, the calculation uses a stock of 0 and marks the row `ASSUMED 0`. Such rows stay yellow, so a shortage caused by missing data is never mixed with a shortage against a real stock figure. Duplicate material IDs are never added together or merged.

## Usage

1. Select the Storage Excel file.
2. Select the BOM Excel file.
3. Search or select the Product ID.
4. Enter the Production Quantity (a positive whole number).
5. Click **CHECK MATERIALS**.
6. Review the results. Select a row to see where its data came from.
7. Click **EXPORT EXCEL** to save a report.

The report is a new `.xlsx` file with two sheets: `Shortage` (all materials, coloured and sorted) and `Exceptions` (only the rows that need checking, with source details).

Notes:

- Required = BOM quantity × Production Quantity. Material IDs are matched exactly (ignoring letter case and surrounding spaces); there is no fuzzy matching.
- The tool reads the files as last saved. Unsaved changes in an open Excel window are not included; a notice appears if a workbook seems to be open in Excel.
- Results support checking. They are not a production approval.

## Inventory Database (M3.1, in development)

The app keeps a local SQLite copy of the Storage and BOM data in `%LOCALAPPDATA%\Auraplex\MaterialStockChecker\inventory.db`, together with the remembered file paths (`settings.json`). The Excel files remain the source of truth and are never written.

- **On start**: the remembered files are checked. Unchanged files are not re-read; changed files are imported in one transaction.
- **Refresh Excel**: checks both files again and updates the result shown.
- **The Inventory Database panel** shows Status, Last Verified, Last Checked and Source File Modified for each file. `Local File Checked` means that at the Last Verified time the database matched one version of the Excel file *on this computer*. It is not a promise that the file is unchanged since then. **`Cloud Not Verified` is always shown beside the status, in every state**: the Google Drive cloud copy is never checked. When the files are not currently verified, an earlier time is labelled `Previously Verified`.
- **A failure always wins over older records.** If this program sees a sync failure, that file shows the failure until this program verifies it again. This also applies when the failure could not be written to the database, which may still hold an older success.
- **CHECK results are bound to the file versions they were calculated from.** After calculating, the program checks that both files are still exactly the versions that were read. It uses the versions verified by the database sync, or re-reads a file directly when its sync did not verify it. If a file changed, the whole CHECK runs again (up to 3 times). If it still cannot be confirmed, the result is shown as `OUTDATED / RECHECK REQUIRED` and cannot be exported. A confirmed result shows `Local Sources Verified <time>`; click it to see the exact versions used.
- **If a file is unavailable or an import fails**, the previous data is kept and labelled `Using Previous Data`. Nothing partial is ever published.
- **If a file changes while it is being synchronised** (Excel saving, Google Drive downloading), the check is retried up to 3 times. If it is still changing, the status is `Source Changed — Refresh Needed`; click Refresh Excel later.
- **If the status cannot be read from the database**, the panel and status bar show `Status Unknown — Database Read Failed`. No earlier status or time is kept on screen, and no stored data is deleted.
- **Each new Storage version is stored as a snapshot.** Differences between versions are *observed changes*, not confirmed consumption.

By default the BOM Checker calculates from Excel with the unchanged engine. `--data-dir DIR` uses a different data folder (for testing).

## Historical cached calculations (M3.2A, in development)

When Excel is unavailable, CHECK fails visibly; it never silently falls back to SQLite. To run a historical estimate:

1. Click **Use Cached Data…** in the top file area.
2. Review both Storage and BOM source paths, database version IDs, source modification times, import times and historical verification times (UTC). The two files synchronise independently and may have different dates. Confirm explicitly; the default answer is No.
3. Choose an existing cached product and Storage sheet, enter a positive production quantity and CHECK.
4. The result remains **CACHED DATA / UNVERIFIED**, with **Cloud Not Verified** visible. This never becomes Local Sources Verified, even if the files happen to be available.
5. Export writes a separate **UNVERIFIED_** report. Both sheets show the warning, cache versions and import dates; the warning repeats on printed pages. Calculation/classification rules and material tables are unchanged.

Both roles need a successful cached version. Missing, unsupported or unreadable databases cannot be used. Selection, calculation and export check the database versions; if they change, the result cannot be exported and you must select/confirm the cache again. No cached calculation writes the database or opens the source Excel files. Changing product, quantity or Storage sheet clears the old result.

**Refresh Excel / Reload Files** leaves cache mode and reads the real files again. A failed refresh never re-enables cache automatically. Browsing a new file also leaves cache mode and clears the cached selections. The opt-in lasts only in the current session; restarting always begins with the normal Excel workflow. Cached calculations do not clear any existing synchronisation failure or claim that inventory is current.

Nothing automatically deletes versions, snapshots or logs. The separate manual maintenance workflow below implements M3.2B. Export still performs synchronous verification; slow disk/cloud I/O can delay the UI.

## Local history maintenance (M3.2B, in development)

Click **Local History…** in the top file area to prepare a read-only cleanup preview. It shows the local database path, cutoff times and exact deletion counts. Choosing **No** leaves the database untouched. Choosing **Yes** creates a recovery backup and applies the matching preview in one transaction; calculation results are cleared and need CHECK again. Maintenance runs on a worker and disables overlapping actions.

| Active database records | Retention |
|---|---|
| Inventory snapshots / old Storage payloads | 12 calendar months, by UTC observation/import time |
| Routine sync logs (`IMPORTED`, `UNCHANGED`) | 90 days, by UTC finish time |
| Failure logs (`FAILED`, `UNAVAILABLE`) | 180 days, by UTC finish time |

Records exactly at the cutoff are kept. Latest/current snapshots, the last snapshot before the retention window and the predecessor payloads required to explain retained differences are protected, even if older. Current Storage/BOM payloads and each role's latest attempt/success records are protected; deleting logs cannot turn an old failure into apparent success or remove the cache's successful provenance. Lightweight source-version headers, BOM history and the material registry are retained to preserve references. An expired Storage payload cannot be reconstructed as an empty workbook. Trend queries explicitly report the retained history boundary and do not claim complete coverage before it.

The database is checked again after confirmation and under the write lock. If anything changed since preview, maintenance is refused and a new preview is required. Backup failure or a deletion error prevents partial cleanup; errors include the backup path when one exists. The source Excel files and Drive settings are never touched.

Recovery backups live in the database folder's `backups` subfolder. A successful `.sqlite3` backup is verified against the preview's logical database snapshot before deletion. **`.partial` files are failed/incomplete backup attempts and must not be used for recovery.** Recovery is manual, with the application closed; the tool does not overwrite a live database automatically.

**Backups contain historical records and are not automatically deleted.** This retention policy limits active SQLite history, not all copies or secure data erasure. A backup-retention policy needs separate approval. Deletion frees SQLite pages for reuse but does not promise a smaller database file or net disk-space savings; no automatic VACUUM is performed. Store the database/backups in the default local user data folder, not a cloud-synchronised directory or unvalidated network share.

## Stock alerts (M3.2C, in development)

Stock alerts are evaluated from the **synchronised** data, not by parsing Excel again. They run automatically in the background after this program has verified both the Storage and the BOM file in the current session (start-up, Refresh Excel, CHECK). The line **Stock Alerts: N active** under the top buttons opens the **Stock Alerts** window. Its banner always says *From synchronised Excel data · Cloud Not Verified · Thresholds and units pending business confirmation*. The CHECK area, M2 rules (including ASSUMED 0) and export are unchanged.

**Minimum-stock column.** On the Storage header row, exactly the headers `MIN QTY` and `MIIN QTY` are recognised (`MIIN QTY` is the confirmed spelling in the AURA Storage workbook; Excel is never changed). There is no fuzzy matching, and the column must lie within A–AD. The original header text, raw value, Sheet and row are kept. If several candidate columns exist, none is chosen: a `THRESHOLD_COLUMN_AMBIGUOUS` data issue asks for confirmation. The business meaning of the threshold, and of its units, is still to be confirmed. Storage has no unit column, so LIVE STOCK and the threshold **of the same row** are compared as a trial only.

| Alert | When | Never means |
|---|---|---|
| `OUT_OF_STOCK` | Unique ID, LIVE STOCK is the valid number 0 (whatever the threshold) | that a production order is short |
| `LOW_STOCK` | Unique ID, valid LIVE STOCK < valid threshold. Equal is not low; threshold 0 never makes LOW. Shows the **threshold shortfall** (threshold − LIVE STOCK). Trial rule, pending business confirmation | a production requirement |
| `BOM_MATERIAL_NOT_IN_STOCK_MASTER` | A valid BOM ID with no exact match in that Storage Sheet. Every product, BOM Sheet, row and raw QTY is listed; quantities are never added | stock 0 or a confirmed shortage |
| `DATA_ISSUE` | Blank or invalid LIVE STOCK, invalid threshold, duplicate Storage ID (rows kept separate), unusable Storage ID, ambiguous threshold column | a converted or merged value |
| `THRESHOLD_NOT_CONFIGURED` | Unique ID with a blank threshold. Other alerts of the same material are still shown | threshold 0 |

A threshold of `0` stays the number 0 and is not interpreted ("no stock needed" / "alert off" are not assumed). Matching uses the checker's exact rule (letter case and surrounding spaces ignored; internal spaces, hyphens, revisions and suffixes kept). Each Storage Sheet is evaluated separately. The window summary counts **distinct missing IDs**, **affected BOM rows** and **affected products** separately.

**One alert per source file.** An alert's identity is its type, issue, **Storage file** (plus the **BOM file** for BOM-coverage alerts), Storage Sheet, and Material ID or row. New versions of the same file de-duplicate: first-seen stays, last-seen moves on. The same Sheet and ID in another file is a different alert. An evaluation can only resolve alerts of its own files. Alerts of a file that is no longer selected stay **active, from another source, not re-checked**: they are hidden by default (*Show other source files*) and never shown as recovered. Switching back to that file continues them.

**When alerts are current.** An evaluation adds, updates or resolves alerts only if, at the moment it writes:
- the newest synchronisation record of both files is a success for the current versions;
- this program itself verified exactly those versions and paths in this session;
- nothing happened since that could change this, such as another selection, a sync, a failure (including one that could not be written to the database) or a database read failure.

Otherwise the attempt is recorded as UNVERIFIED (or FAILED) and no alert changes. The last check is made at the moment of COMMIT: a verification withdrawn at any point before it rolls the whole publication back. A database read failure (including one in the Stock Alerts window) discards this session's verification of both files, so *Re-evaluate* cannot make alerts current again; Refresh Excel (a new successful check of both files) is needed. The line then also says *database read failed*. Until a current, verified evaluation completes, the line says **not re-checked**, and the window starts with **NOT RE-CHECKED IN THIS SESSION** and the reason. This covers start-up, any newer sync or failure, and a late result from an older request. One evaluation runs at a time, with at most one waiting.

**The Stock Alerts window** has two tabs, sharing a **Storage Sheet** filter and a **Material ID contains** filter:
- **Alerts** (type filter, *Show resolved*, *Show other source files*). Each alert shows its raw values, threshold column and header, threshold shortfall, Storage file and version (and BOM file for coverage alerts), and first/last-seen times. The details line adds Rack/Level, full paths and every BOM occurrence. A basis panel names the current files, the last verified evaluation of exactly those files, and the per-Sheet counts.
- **Observed Changes** (change-type filter, 30 / 60 / 90 days). The differences between synchronised versions of the **current Storage file**, read from the stored snapshots (no Excel parsing). They follow the M4A rules: a difference only between single valid records of the same file, and *not comparable* across a source switch. **Observed Change ≠ Actual Consumption**, and never a production-order shortage.

Rows are shown 200 at a time; up to 5,000 alerts and 2,000 observed changes are loaded, and totals are always counted.

**Alert history** is bounded without losing what the window needs. The newest 200 evaluations are kept, plus the latest verified evaluation of every file scope and every evaluation that a stored alert refers to. Resolved alerts are kept for 180 days. Failed attempts are pruned the same way. This is separate from the M3.2B inventory and sync-log retention, which is unchanged.

**One-time database upgrade.** Alerts need schema 3 of the local database. A new database is created at schema 3. An existing database stays as it is (schema 1, or schema 2 from an M3.2C development build), with every other function unchanged, until you choose **Upgrade database…** in the Stock Alerts window. That shows a preview (default *No*), writes a verified backup to the `backups` subfolder, and applies the change in one transaction; existing inventory rows are not rewritten and nothing is deleted. From schema 2, existing alerts are attributed to the files they came from. From schema 1, the current Storage file is read once more afterwards to capture its thresholds: a version imported before the upgrade shows "thresholds not captured", never blank or 0. Older development builds cannot open an upgraded database; keep the backup if you need to go back.

## Inventory History (M4A, in development)

Click **Inventory History…** in the top file area to open a separate, read-only window. It shows what the synchronised Storage versions recorded for one Material ID. Everything in it is a **historical observation**: the banner **HISTORICAL OBSERVATIONS · Not current stock · Cloud Not Verified** is always shown, and the window never uses `Local Sources Verified`. The CHECK area, its rules and export are unchanged.

1. Type part of a Material ID (same matching as the checker: letter case and surrounding spaces ignored). Candidates come from IDs ever stored for Storage. Typing alone does not query; **select one exact ID**. Similar IDs (for example `A-1` and `A-10`) are separate and never merged. IDs stored in numeric cells are not text keys and cannot be selected.
2. Choose a **Storage Sheet** (or all Sheets, each row labelled with its own Sheet) and **30 / 60 / 90 days**. The window start is inclusive.
3. **Records** lists, newest first, every stored row of that ID in each snapshot: snapshot time, Material ID, description, the raw stock value with its data status, Rack, Level, source file, Sheet, row and version. Selecting a row shows the full path. The last snapshot before the window is included and marked **Before window**: it is the recorded state at the window start, not a new observation.
4. **Observed Changes** lists the differences between consecutive Storage versions: before and after times, before and after stock, the change type (quantity, added, removed, blank/invalid status change, duplicate rows changed) and an **observed difference only between two single valid records from the same source file**.

What the window never does:

| Situation | Shown as |
|---|---|
| Blank stock | `(blank)` · `BLANK — not 0` |
| Text or other invalid quantity | the value as read · `INVALID — not converted` |
| Duplicate ID in one Sheet | separate rows · `DUPLICATE ×n — not added`; changes have no difference |
| Same ID in different Sheets or source files | separate rows; never merged |
| Source file switched between versions | `not comparable (source switch)`, with a coverage note |
| ID not in a snapshot | `NOT PRESENT — not 0` |
| Rows removed by Local History maintenance | `NOT RETAINED — values unknown`; nothing is reconstructed |
| History starting inside the window, or cleaned before it | an explicit coverage note; earlier stock is unknown, not 0 |

**Observed Change ≠ Actual Consumption.** Storage is edited irregularly (receipts, corrections, recounts). A snapshot is recorded only when a new Storage version is imported.

Each query reads one consistent, read-only view of the database on a background thread. If another program publishes a new version meanwhile, the result still belongs entirely to the earlier state; query again to see the new one. A newer query always replaces an older one, and closing the window discards pending results. Up to 1,000 records and 1,000 changes are loaded per query and shown 200 at a time (**Show more**); when more exist, the window says how many and asks for a narrower query. If the database cannot be read, the old result is cleared and **QUERY FAILED** is shown; nothing is presented as a successful query. The window does not write the database, the Excel files or Drive settings, and has no charts, forecasts, reorder suggestions or export.

## Daily Stock Summary (M3.2D, in development)

Click **Daily Summary…** (beside the *Stock Alerts* line, top right) to open a separate window. Choose a date (`YYYY-MM-DD`, default today; ◀ / Today / ▶), **Generate**, check the preview, then **Save HTML + JSON…** into a folder you choose. Nothing is sent, scheduled or uploaded; the Excel files, stock and Drive settings are never changed, and the database is only read. CHECK, Stock Alerts and Inventory History are unchanged.

**What the summary contains**
1. *Report information* — report date, time zone, the day's window, generation time, the Storage and BOM file and version (current, and for a past date the version in effect at the end of that day), the latest check and last verified time of each file, whether this session verified them, and the database basis (versions, newest sync records, alert evaluation). **Cloud Not Verified** is always stated.
2. *Stock alerts* — the stored M3.2C alerts (`OUT_OF_STOCK`, `LOW_STOCK`, `BOM_MATERIAL_NOT_IN_STOCK_MASTER`, `DATA_ISSUE`, `THRESHOLD_NOT_CONFIGURED`); no quantity rule is recalculated. Per type: alerts, **distinct Material IDs**, entries without an ID and Storage Sheets; plus the distinct IDs with any alert. One material can have several types, so the per-type counts are never added up as a number of materials. Alert evaluations recorded on that date are listed with their recorded counts.
3. *Observed changes on that date* — quantity changes, added / removed IDs, blank / invalid / duplicate status changes and source-file switches, from the stored snapshots. A change belongs to the date on which this program **observed** it (snapshot time), never to the file's modified time. **Observed Change ≠ Actual Consumption**: no issue quantity or consumption is calculated, and a difference exists only between two single valid records of the same file.
4. *Data limitations* — history coverage and Local History cleanup boundaries, missing or failed synchronisation, threshold columns pending confirmation, blank / text / duplicate stock in the current Storage version, and every field that is **not calculated** (with its reason; never 0). "No observed change" only means nothing was recorded, not that the warehouse had no movement.

**The day.** The computer's local date and time zone. The day's local start (inclusive) and the next day's local start (exclusive) are converted to UTC, so every record belongs to exactly one day, including at midnight and on a daylight-saving day.

**VERIFIED or UNVERIFIED.** A summary is **VERIFIED** only for today, when this program has just checked both Excel files, the alerts were re-checked in this session, the database's current versions are exactly the ones it checked, and the stored alerts come from a verified evaluation of exactly those versions (not an older version of the same file path). Anything else — a past date, no or failed synchronisation, alerts behind the Storage version, verification changed while generating — needs your explicit confirmation (default *No*) and is marked **UNVERIFIED** in the preview, the file names (`UNVERIFIED_…`) and the report. For a past date, the alerts of that day are shown as **not available** (they cannot be reconstructed); the alerts at generation time are listed separately, labelled with their basis and time. Unavailable alerts are never shown as "no alerts", and nothing says stock is normal or sufficient.

**Saving.** One new report folder `Daily_Stock_Summary_<date>_generated_<YYYYMMDD_HHMMSS>` (with `UNVERIFIED_` in front when applicable; ` (2)`, ` (3)`… if the name exists) containing the `.html` and `.json` of the same name, both from the same immutable summary: same report ID, date and version basis; the HTML records the SHA-256 of the JSON. The HTML is self-contained (no online fonts, scripts or images), and every file name, path, description and other original text is HTML-escaped; it can be opened in a browser and printed. The JSON is for later scheduled runs and AI interpretation. Both files are first written and read back in a hidden staging folder `.mrc-daily-….partial`; the report appears only when that folder is renamed to its final name in one step, so a report folder always holds the complete pair. Nothing existing is replaced. Right before that rename, while holding a read lock on the local database (so no program can commit at that moment), the program checks again that the data are exactly those the summary was generated from: a new version, sync record or alert evaluation — also from another copy of the program — refuses the save, as does, for a VERIFIED summary, a change of this program's verification (for example Refresh Excel): generate again. A failed save shows the original error; if a `.partial` staging folder could not be removed, its path is shown — it is not a report and can be deleted. VERIFIED describes the local file versions at that moment only, never later or cloud freshness. Saving requires the local database's default rollback journal; a database switched to WAL (or another journal mode) is refused with an explanation and is not changed — generating and previewing still work.

Generation and saving run in the background, one at a time with at most one waiting request; the newest request always wins, an older result never replaces it, a failed generation clears the preview, and closing the window discards pending results. A database read failure is handled like other alert reads: this session's verification is discarded until Refresh Excel. Preview lists show 200 rows each; the saved files hold up to 5,000 alerts and 2,000 observed changes, with totals always counted.

## Safety

The program reads the selected Storage and BOM workbooks and generates a separate report. It does not modify the source workbooks.

- Workbooks are opened read-only.
- The report is always a new file. A source workbook is rejected as the export target, and an existing file is never overwritten.
- Nothing is uploaded; the tool makes no network connections.

This repository contains no company data. Tests create their own synthetic workbooks in a temporary folder.

## Development

Python 3.10+ with Tkinter, and [openpyxl](https://openpyxl.readthedocs.io/). Windows only.

```powershell
# one-time: creates .venv in the project folder and installs requirements.txt into it
.\Setup.bat

# run from source
& '.\Start M0.bat'

# run the tests
.\.venv\Scripts\python.exe -m unittest discover -v
```

| Path | Purpose |
| --- | --- |
| `app.py` | Entry point |
| `checker/core.py` | Matching, calculation, classification, sorting |
| `checker/reader.py` | Read-only workbook parsing, change detection, cache |
| `checker/report.py`, `checker/report_style.py` | Excel report |
| `checker/ui.py`, `checker/presentation.py` | Tkinter interface |
| `checker/history.py`, `checker/history_ui.py` | M4A read-only Inventory History queries and window |
| `checker/alerts.py`, `checker/alerts_ui.py` | M3.2C stock-alert evaluation, de-duplicated persistence, bounded runner and window |
| `checker/upgrade.py` | Explicit, backed-up local database upgrade (schema 1 or 2 → 3) |
| `checker/daily.py`, `checker/daily_ui.py` | M3.2D Daily Stock Summary: one-view generation, HTML/JSON rendering, safe save, bounded runner and window |
| `tests/` | Automated tests using synthetic workbooks |

A few file-behaviour tests run only when `MRC_TEST_MOUNT_DIR` names a folder on a mounted drive (for example Google Drive for Desktop). They create and delete their own temporary sub-folder there and are skipped otherwise.

## Build

```powershell
.\build_portable.bat -Version <VERSION from app.py>       # release build
.\build_portable.bat -Version 1.1.0.dev0 -AllowDevBuild  # development test build, never a release
.\build_portable.bat -Version 1.1.0.dev0 -AllowDevBuild -ValidateOnly   # check the arguments only
```

There is no default version. The script stops before touching anything if `-Version` is missing or differs from `VERSION` in `app.py`. It also stops if the version is a development or pre-release version (`.devN`, `aN`, `bN`, `rcN`) and `-AllowDevBuild` is not given.

The script uses the project `.venv` only (run `Setup.bat` first), installs PyInstaller into that `.venv` if it is missing, cleans `build\` and `dist\`, builds a windowed one-folder application, adds the end-user guide as `README.txt`, and creates:

```
dist\Auraplex_Material_Stock_Checker\
    Auraplex_Material_Stock_Checker.exe
    _internal\
    README.txt
dist\Auraplex_Material_Stock_Checker_v<version>_Portable.zip
```

`build\` and `dist\` are not committed. The ZIP is published as a Release asset. See `PACKAGING_REPORT.md` and `RELEASE_CHECKLIST.md`.
