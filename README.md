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

Development source includes the reviewed M4C controlled read-only tools and Agent core, the M4D DeepSeek
adapter (local commit `d25ad29`), and the M4E robot/chat interface (local commit `85f8a65`), plus the
the reviewed M4F aggregate narratives, local HTML/JSON report delivery and .eml drafts. These development features are not in
the published v1.0.0 portable package.
No real API was called in implementation/verification. Data access requires session-only historical-cache authorization and returns
UNVERIFIED / Cloud Not Verified evidence. External transmission requires a separate, explicit session consent.
M4C's two P2 follow-ups are fixed in local commit `5b2e75f`; see `M4C_P2_REMEDIATION.md`.
See the M4D, M4E and M4F implementation/test reports for scope, safety boundaries and untested environments.

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

## Inventory analytics (M4B, source reviewed and committed locally)

Click **Analytics…** beside Daily Summary to open the independent historical analysis window. Choose 30/60/90 days, an optional exact Storage Sheet, and/or a partial Material ID. Every source file / original Sheet / exact Material ID remains a separate group. Results always say **HISTORICAL / UNVERIFIED · Not current stock · Cloud Not Verified**, with last-observed timestamps and selectable raw source/version/row/Rack/Level details. This reads retained SQLite snapshots only; it does not load Excel or call an AI provider.

The displayed, adjustable heuristics default to a minimum 30-day observed span, low cumulative absolute change of 0, and a large single change of at least 50% of the previous positive value. Positive stock whose trailing observations remain equal across the minimum span is a **human-review candidate**; it is not confirmed excess stock or low importance. A recent change ends that trailing-unchanged cue. No consumption, reorder amount, demand forecast or days-of-stock estimate is calculated. Existing MIN QTY stock-alert rules remain in Stock Alerts.

Movement is the sum of absolute differences over comparable adjacent snapshot intervals only. Net change is withheld across missing/invalid/duplicate records, missing payloads, pruned history or source interruptions. Missing material records are ABSENT, not 0; missing retained payloads are unknown. Zero-to-positive changes have no percentage. A labelled before-window reference may be included; snapshot dates describe when values were imported, not when actual movements occurred. No new snapshot does not prove unchanged physical stock.

One query runs at a time with at most one replaceable waiting query. Stop or changing filters discards old results. Database failures clear results and invalidate alert verification through the existing failure handler; Refresh Excel is required to re-verify. Results render 200 groups at a time. Queries have a five-second processing budget and refuse, without partial results, more than 400 in-window snapshots, 200,000 historical rows (including reference) or 5,000 source/Sheet/material groups. The row cap counts complete source versions even with a material filter; choose a shorter period when it is exceeded. The version-count and row limits protect memory and limit read-lock duration; filesystem/SQLite lock waits can add latency. No database migration or dependency installation is needed. The P2 Sheet-metadata integrity follow-up is implemented with M4C and has synthetic regressions, pending separate review. Packaged M4B, real Drive, another PC and physical-DPI acceptance remain pending.

## Unattended daily run and schedule draft (M3.2E E1)

Open **Daily Summary… → Schedule draft…** to choose an existing output folder and local daily time. The default-No confirmation explains the constraints, then exports a new Task Scheduler XML file. **This does not register, enable or change a Windows task.** Existing XML files are not overwritten. Actual task activation is a separate user decision and acceptance step.

The draft uses the current logged-in Windows account (`InteractiveToken`, least privilege), no saved password, one daily trigger, no parallel instances, and at most three application-managed attempts 30 seconds apart. Each attempt rechecks both Excel sources; no native RestartOnFailure loop is configured. It requests a delayed run if the scheduled time was missed. A delayed run verifies/generates the current day; it does not recreate the stock state of every missed date. The computer must be available, the user logged in, and the Drive-mounted source files accessible. The draft does not wake the computer and waits on battery power. No guarantee of exact-time delivery is made. Regenerate/review the draft after moving the portable folder or changing executable/data/output paths.

For development or a separately approved scheduled action:

```powershell
.\.venv\Scripts\python.exe app.py --daily-run 'C:\Reports\Auraplex' --data-dir 'C:\LocalData\Auraplex'
# Optional CLI retries; default is one attempt; generated schedule drafts explicitly request 3 attempts / 30 seconds:
.\.venv\Scripts\python.exe app.py --daily-run 'C:\Reports\Auraplex' --daily-attempts 2 --daily-retry-delay 5
```

Use the real configured data folder, normally `%LOCALAPPDATA%\Auraplex\MaterialStockChecker`; the example paths are placeholders, not defaults or a recommendation to relocate existing data. Both folders must exist. First open the GUI, select/load both Excel sources and explicitly upgrade the database to schema 3 if required. Background runs never create a missing database or perform a schema upgrade. The M3.2E packaged CLI passed focused temporary EXE checks; clean-machine and other-PC acceptance remains pending.

Each process acquires a per-data-folder OS lock, checks both remembered Excel sources itself, evaluates alerts with a new per-run authorization, then calls the existing guarded daily generator/saver. It creates no GUI or modal dialogs. Source failure/unverified evaluation means **no cached report**; retries are bounded to 1–3 attempts with a 0–30-second delay. Cloud Not Verified remains in reports. The normal rollback-journal saving requirement still applies; WAL is not changed automatically.

Exit codes: `0` saved, `2` configuration/upgrade/journal-mode requirement, `3` sources not verified, `4` database/evaluation error, `5` generation/save/log error, `6` another run already owns the folder. `daily-runs.json` records UTC completion, code/reason, attempts/errors and any published report path; this feature keeps the latest 200 receipts plus the last success. It never prunes the inventory database. A corrupt receipt file is preserved and reported; if a report was already saved but logging fails, the failure outcome retains that report's path. `daily-run.lock` is an OS lock sentinel; its presence alone does not mean a run is active. A duplicate process returns code 6 without modifying the active run's log.

Task Scheduler behavior references: [StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-startwhenavailable-settingstype-element), [MultipleInstancesPolicy](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-multipleinstancespolicy-settingstype-element). Temporary actual timed recovery on attempt 2 and exhaustion after attempt 3 passed in source and packaged modes. Native automatic restart was not observed; its cause is retained for later CC investigation. See `M3_2E_SCHEDULER_VALIDATION.md`. Missed-run, clean-machine and other-PC acceptance remain unexecuted. No Email, AI, automatic task registration or company-PC deployment is included in E1.

## AI provider adapter (M4D, reviewed and committed locally)

`checker.providers.create_provider()` constructs the default DeepSeek adapter without accessing credentials
or making a request. The existing Agent `Provider` protocol remains the replacement boundary; no other
provider is silently selected. The adapter defaults to `deepseek-flash` with thinking disabled, using the
official fixed HTTPS `/chat/completions` endpoint and normal function-call messages. Model availability
has not been verified against a real account. Tools remain locally validated even when the model emits JSON.

The trusted host must display `provider.disclosure` and obtain consent to `provider.policy` before
calling `authorize_outbound(policy=provider.policy, accepted=True)`. Declining or restarting leaves outbound
access disabled. `revoke_outbound()` cancels the current outbound session. Cache consent is a separate
requirement; a model cannot grant either consent. `preview(messages, tools)` returns the exact JSON body
without accessing the key or network. No consent is saved in settings or SQLite.

The `inventory-routing-v2` policy sends the question, fixed tools, candidate IDs/original Sheets and tool
outcomes. Numerical evidence, descriptions, locations, full paths, hashes and database provenance remain
local. The host renders numerical answers from the unchanged tool evidence. Full results are projected
through a field allowlist; they are never sent wholesale. Common path/credential/email patterns in free text
or identifiers refuse the request. This is not general secret detection: questions and candidate identifiers
can themselves be company-sensitive. Approval of the actual outbound scope is required before live use.

`checker.credentials.WindowsKeyStore` provides save/load/delete through the current user's Windows Credential
Manager. It has no plaintext settings/file, environment-variable or command-line key fallback. M4E provides
interactive key controls in development source; no actual company key was read or stored in verification. Other software
running as the same Windows user can access the user's vault. Python/network buffers cannot guarantee that
all in-memory key copies are erased.

Defaults: ten attempted requests per consent session, 1,024 output tokens per request, 64 KiB request and
256 KiB response limits. Failed attempts consume the request allowance. There are no automatic retries,
redirects, environment proxies or provider switches. Errors distinguish missing/invalid keys, quota, rate
limits, timeout, cancellation and malformed responses. These are resource limits, not a currency budget;
already-sent requests may still incur charges after cancellation.

Run on a host worker. HTTPS cancellation closes the socket, and late replies are discarded. OS DNS may
outlive the caller timeout; the transport keeps its one-worker lock until DNS exits, refuses overlapping
work and checks cancellation before sending. Reuse one adapter/transport in the host instead of creating
one for every click. Stock CHECK, local tools and deterministic statistics do not require an AI provider.
M4E development source wires the GUI to this adapter. Scheduled daily tasks do not use AI.
AI reports/Email remain M4F. No real API, packaged EXE or second-PC validation has been performed for M4D/E.

Account reminders: after outbound consent, the adapter also uses DeepSeek's fixed `GET /user/balance`
endpoint before the first chat request, then at most once every five minutes during active use (including
failed checks). This separate request sends the key, not inventory/question data. No timer/network job is
started while idle. `request_balance_refresh()` makes the next authorized chat request recheck after a
top-up; it does not reset the application's request allowance. Balance requests have a small separate
share of the same overall caller time budget. A slow cancelled balance worker can temporarily leave the
transport BUSY until cleanup; local tools remain usable.

Low-balance thresholds default to USD 1.00 and CNY 5.00, independently configurable in ProviderConfig.
Currencies are never added or converted. Provider-reported insufficient funds or HTTP 402 produces
QUOTA_EXHAUSTED and refuses chat; failed/malformed checks produce QUOTA_UNKNOWN, never an invented zero
or remaining-token percentage. These are labelled observations with a check time, not guarantees that
the shared account balance stays unchanged. Failed rechecks invalidate older healthy observations.

`quota_status()` is a local state read; `take_notifications()` drains deduplicated notices for the trusted
chat host. Session requests nearing 80%/reaching the local cap and replies hitting their output limit have
different codes from account exhaustion. Last-request Token usage is recorded only if the API supplies
valid counts; it never represents Tokens remaining. Chinese/English/Malay notice templates are available
in `checker.quota.notice_text`. M4E shows these notices and the balance-check state in chat.
Quota data is not sent back to the model or stored in SQLite.

## Inventory assistant (M4E, development source)

Click the blue robot at the bottom right to open/collapse the assistant. Small windows use a separate
chat window; sufficiently wide windows use a side panel while keeping the checker usable. Chat,
Local tools, Settings and Evidence are separate tabs. This is not included in the published v1.0.0 EXE.

1. For AI chat, save your key in **Settings**, enter a question and click **Send**. No separate
   historical-data or API-permission dialog is required. Send intentionally uses DeepSeek and the
   existing bounded inventory tool projections; a visible notice describes this. Opening the assistant,
   loading local data, and saving a key do not themselves make API requests.
2. For offline tools, click **Load recorded data**, then choose a tool and Run. Select an actual
   candidate for stock/BOM/history queries. Similar IDs and Sheets remain separate. All assistant data
   remains **UNVERIFIED / Cloud Not Verified**, independent of main CHECK cached-mode permission.
3. Enter sends; Shift+Enter adds a line. Failed questions remain in the input. Material search results
   do not switch away from Chat; use Local tools to select ambiguous candidates.
4. Stop, close, Refresh, source changes and read failures still cancel work and invalidate old data
   bindings and report grants. The next deliberate Send binds the newly recorded snapshot without
   another dialog; it does not claim the cloud is current. Changed data during a query is rejected,
   with no automatic network retry. Consecutive sends on the same valid session do not reset quota.
   Report-specific AI approval and main CHECK cached calculations retain their existing protections.
   **Recheck balance on next Send** only arms the next send; it does not contact the API itself.

Replies/warnings support Chinese, English and Malay. Mixed precedence is English > Malay > Chinese;
explicit reply-language instructions override automatic routing. Known identifiers, source labels, quotes
and fixed technical tokens do not determine language. Shared/unknown words use the previous reply language
(first turn English) with a visible notice. The language selector overrides the heuristic. Detection is
lexical and can be wrong for unusual phrasing; it is not a general multilingual classifier. Existing main
windows and canonical evidence/status codes are not fully translated. Original descriptions and IDs are
never translated. Numerical explanations come from deterministic local templates and the existing tools;
model prose is discarded rather than accepted as stock evidence.

Ambiguous AI searches expose candidates in Local tools; choose one and run the requested local action.
Each AI Send is a bounded independent question; conversational pronouns are not inferred from prior turns.
Include the ID/Sheet again or use a selected local candidate. Quick questions insert drafts and never send
automatically. Source versions, hashes, import/observation times and recorded sync attempts appear in
answers/Evidence, with an explicit warning that historical success logs do not prove present freshness.
Missing data is unknown; blank stock is not zero; duplicates are not added. M2's existing row-level
assumptions are explicitly labelled in estimates. No chat export, inventory write or Email tool is provided.

Quota warnings are deterministic and deduplicated in the selected reply language. The persistent status
strip shows consent, balance observation/check-due state, usage when supplied and canonical warning codes.
Low credit, exhausted credit, unknown balance, local request cap and output limit remain distinct.
Historical records and prior chat replies never become verified inventory merely because AI succeeds.

Only one assistant worker runs at a time; all Tk updates/dialogs run on the UI thread. Display limits:
80 transcript entries / 160k characters, 80k characters per answer and 200k displayed evidence characters,
with truncation marked. Tools retain M4C's bounded result/query limits; host Sheet metadata is capped at
200 Storage Sheets and 200 product Sheets. Conversation, candidate permissions and consent are not saved.
Draft text survives collapse, but unsaved key input is cleared. Reopening/restarting requires new permissions.
No new dependency, database migration or release artifact is introduced. See
`M4E_IMPLEMENTATION_REPORT.md` and `M4E_TEST_REPORT.md` for verification details and delivery limits.

## AI history narratives (M4F first slice, development source)

Quality issue counts are separated by Storage/BOM; an unsynchronised source shows unknown, not zero.
Weekly comparison requires a retained snapshot or successful Storage check in each period, as well as history coverage.
Per-period sync attempt/success counts are shown. A failed check alone is not an observation; successful UNCHANGED
checks permit zero recorded changes. Observation frequency may differ, so these comparisons do not measure consumption.

The **AI reports** tab builds daily and weekly previews locally from retained SQLite history. Weekly comparison
uses observed change-event counts; missing or pruned history stays unknown. Alert counts are stored observations,
not re-checked in this view, and categories may overlap. Observed change does not prove consumption.

The exact outbound DeepSeek request is shown before each report send, with a separate one-report confirmation
that defaults to No. The request contains aggregate date windows and category counts, recorded sync outcomes and
times, history coverage, and data-quality counts. It excludes Material IDs, descriptions, individual stock/BOM
quantities, Sheet names, local paths, file hashes and database rows. A separate balance recheck may occur under
the existing API consent if due. Local and AI results remain **UNVERIFIED / Cloud Not Verified**. A small
keyword check (Chinese, English, Malay) discards AI replies that state counts (digits, or number words attached to
counted items) or plainly claim that stock is sufficient/production-ready, cloud-verified, actually consumed, or
that a purchase should be made; negated sentences ("not actual consumption") pass. A discarded reply is reported
and the local counts stay. The check is keyword-based and cannot guarantee that every reply is correct. The
preview is shown in the assistant's current language (canonical codes stay visible) and is re-rendered from the
same facts after a language switch; the AI is asked to reply in that language. This slice has no purchasing advice or email
delivery, and it is not part of the published v1.0.0 EXE. It used only synthetic SQLite/workbooks and a fake API;
no real API, company data, packaged EXE or live Drive was tested. See `M4F_IMPLEMENTATION_REPORT.md` and
`M4F_TEST_REPORT.md`.

## Report files and e-mail drafts (M4F second slice, development source)

**Done.** On the assistant's **AI reports** tab, below the preview:
- **Save report (HTML + JSON)…** saves the shown daily/weekly preview into a folder you choose, as one new report
  folder `UNVERIFIED_AI_Report_<DAILY|WEEKLY>_<EN|ZH|MS>_<time>UTC` holding an `.html` and a `.json` with the same
  report ID (the HTML records the SHA-256 of the JSON). No AI call is needed.
- **Include the AI interpretation** can be ticked only while an AI reply exists that was accepted for exactly the
  facts on screen (same data basis, same digest, same session). It is saved as a separate, UNVERIFIED section in the
  reply's language and never changes a statistic. Rejected, failed, cancelled or out-of-date replies are never kept.
- **E-mail draft (.eml)…** needs a report saved from the current preview. It shows a preview: To (optional),
  Subject, the body and the two attachments. **Save .eml draft…** then writes a new `.eml` file. The draft attaches
  exactly that saved report, re-read and checked against the hashes recorded when it was saved; nothing else in the
  folder is attached.

What the files contain:
- The same aggregate facts as the AI request: report type, windows, generation time, data-basis digest, history
  coverage, sync outcomes, data-quality counts, observation counts and comparison limits.
- UNVERIFIED, Cloud Not Verified and Observed Change ≠ Actual Consumption; unknown stays "unknown", never 0.
- No Material IDs, descriptions, Sheet names, local paths, source-file hashes, stock rows or workbooks.
- Chinese, English or Malay, following the current preview (or the AI reply's language when it is included).

When a report can be saved:
- Saving re-checks itself in the background, not only through the button state. Right before one no-overwrite
  rename of a staged folder, it holds a database read lock (rollback journal only; a WAL database is refused) and
  then the assistant session lock.
- The data basis must be unchanged and the session must still hold the same local-data authorisation. After
  Refresh, a sync by any program, Local History cleanup, Stop, Disconnect, closing the assistant or a new permission,
  the save is refused and asks you to build the report again.
- Nothing existing is replaced; a failure leaves no complete-looking report; a leftover `.mrc-report-….partial`
  staging folder is named in the message.

**Never done here:** no SMTP, no mail credentials, no sending, no mail program is opened, no scheduled sending. The
`.eml` is a local draft; mail programs may open it differently (an `X-Unsent: 1` header is set for those that
support draft mode). Purchasing suggestions, real sending, automatic notifications and RAG remain later work, so
M4F as a whole is not complete.

**Verified this round:** synthetic workbooks and temporary databases, fake API transport, `tests.test_m4f_delivery`
(see `M4F_DELIVERY_TEST_REPORT.md`). **Not executed:** real company data, real API, real mail clients, network or
cloud-synchronised target folders, packaged EXE, other PCs, physical DPI.

## Safety

The program reads the selected Storage and BOM workbooks and generates a separate report. It does not modify the source workbooks.

- Workbooks are opened read-only.
- The report is always a new file. A source workbook is rejected as the export target, and an existing file is never overwritten.
- The checker and local tools work offline. Optional AI requests require separate explicit session consent;
  their disclosed question/identifier scope is described above. Workbooks and full database contents are not uploaded.

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

### History window interface languages (2026-10-23, source slice)

Inventory History follows the main Chinese / EN / BM selector, including already-open windows, without restarting queries or changing selected data. Titles, controls, headings, loading/failure feedback and coverage framing are translated. Raw source values, status codes and original query/detail notes are preserved; several row-level explanations remain English. Alerts, analytics, daily and maintenance dialogs are not covered by this slice. This source change is uncommitted and awaits independent review; see HISTORY_L10N_IMPLEMENTATION_REPORT.md for focused checks and the Tk finalizer warning observed during testing.

### Stock Alerts interface languages (2026-10-23, source slice)

The open Stock Alerts window now follows the main Chinese / EN / BM selector without reloading or re-evaluating. Controls, headings, rules, session-verification/failure framing and counts are translated; source values, canonical codes and original evaluation/row details remain unchanged. Eight directly relevant tests passed; see ALERTS_L10N_IMPLEMENTATION_REPORT.md. Analytics, Daily Summary and maintenance dialogs remain pending. These localisation changes are uncommitted and await review.

### Analytics and Daily Summary interface languages (2026-10-23)

These windows now follow the main Chinese / EN / BM selector, including open windows, pending work, failures and stale states. Daily preview labels are translated from the same immutable summary; saved HTML/JSON keep the original English report format, as disclosed in the window. Original data, status codes and raw detail/reason text are preserved. Eight new and six directly affected checks passed in about 20 seconds; no full suite. See ANALYSIS_DAILY_L10N_IMPLEMENTATION_REPORT.md. This combined secondary-window localisation work remains uncommitted and awaits independent review. Maintenance/cache/upgrade dialog bodies and some original detail narratives/tooltips remain open.

### Current localisation completion status (2026-10-23; supersedes earlier step statuses)

History, Alerts, Analytics and Daily Summary follow the main Chinese / EN / BM selector; cache, retention and database-upgrade consent/preview framing is now translated too. Source values/canonical codes and original data-bearing narratives/diagnostics remain verbatim. Daily saved HTML/JSON remain English, as stated in the window. Closure/consent and Tk-object lifetime findings were reproduced and repaired; 16 distinct targeted tests have passing results in this final step. This is author source self-review, not independent/packaged acceptance. The combined patch passed independent Claude review and is included in the user-authorised local localisation commit. See SECONDARY_WINDOWS_L10N_CLAUDE_REVIEW.md and SECONDARY_WINDOWS_L10N_REVIEW.md. Four non-blocking P3 observations remain; real API and packaged acceptance are still pending.

### Readable answers and reports (2026-10-23, source, awaiting review)

Chat answers, the AI-report preview, saved AI reports and the Daily Stock Summary now open with a short business summary; details stay one click away.
- **Default view.** The answer first, one data-status line (data time, UNVERIFIED / VERIFIED, Cloud Not Verified, failed sync), and only the limits that apply.
- **Chat details.** Use the **Details** button / Evidence tab for every returned row, the data basis (paths, versions, SHA-256, sync attempts) and the original JSON.
- **Reports.** Use **Show details** for the full figures with canonical codes. Saved HTML puts the summary first with collapsible sections; JSON still holds the complete data.
- **Stock values.** Blank is shown as "not recorded yet (not 0)", text as "quantity to be confirmed" with the original value, duplicates as separate unmerged records, and a missing ID as "not found in the stock list (not zero stock)".
- **Long lists.** A shortened list says "Showing X of Y".
- **Source switches.** Switching the stock source file (for example to `storage_test.xlsx`) is stated in the summary. The resulting record differences are listed separately as "differences caused by switching the source file" and are not counted as comparable changes; a first import is a baseline, not stock received. Summary + switch counts equal the recorded totals.
- **Alerts.** Alert entries and distinct material IDs are shown separately and never added across categories. Unknown stays unknown, and missing or partial history never produces a "no change" conclusion.
- **AI facts format.** The AI report facts are now format `mrc-ai-aggregate-report/2`: the same aggregate counts, with the same-source / source-switch split and distinct-ID counts added (no identifiers). VERIFIED in the daily summary only means this session checked the local files at generation time. See READABILITY_REPORT.md. Not committed.
