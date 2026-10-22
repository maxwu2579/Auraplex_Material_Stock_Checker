# M3.2C — Thresholds, Stock Alerts and Explicit Database Upgrade

Date: 2026-10-21 (Asia/Singapore). Base: local commit `d0633fd` plus the uncommitted, Codex-accepted M4A working tree. Implementation by Claude Code; not an independent acceptance. Nothing was committed, pushed or released. M3.2D was not started. Codex review is pending.

> **Status after remediation (2026-10-21).** Codex review `M3_2C_CODEX_REVIEW.md` returned NO-GO with three P1 defects and two P2 items. They are repaired in the working tree; see `M3_2C_REMEDIATION_REPORT.md`. Statements below that the remediation changed are marked *[superseded]*. Current behaviour:
> - **Schema 3.** It adds the source scope of alerts and evaluations. Upgrades from schema 1 or 2 are explicit and backed up; schema-2 alerts are attributed to their files.
> - **Alert identity** includes the Storage file, plus the BOM file for coverage alerts. There is no cross-file de-duplication or recovery.
> - **Verification** is bound to concrete versions, paths, sync records and a session generation, and is re-checked under the write lock.
> - **The UI** shows "not re-checked" until a current, verified evaluation of this session completes.
> - **Pruning** keeps provenance.
> - **Observed Changes** tab, Sheet and material filters, threshold shortfall and per-alert source detail are added.
>
> Full suite after remediation: **326 tests, 321 passed, 5 skipped**.

## Instructions and decisions

- The **supplementary M3.2C instruction** governs. The *original* M3.2C instruction it refers to ("sync freshness, concurrency cap, de-duplication, delivery requirements") was **not available** in the session or the repository. The user chose to proceed with these stated defaults:
  - **Freshness:** alerts are bound to explicit Storage/BOM versions and Sheet scope. A failed or unverified sync never resolves an alert.
  - **Concurrency:** one evaluation running plus one latest pending.
  - **De-duplication:** by (type, subtype, Storage Sheet, ID or row), with first-seen and last-seen; nothing merged. *[superseded: the identity now also includes the Storage file, and the BOM file for coverage alerts; see the remediation report]*
  - **Delivery:** README plus the two reports.
- **Storage approach (user's choice):** an explicit in-app upgrade from schema 1 to 2, with preview, a default *No* and a verified backup first. Never automatic.
- **Units (user's choice):** there is no unit column. The same row's LIVE STOCK and threshold are compared as a trial. Every LOW_STOCK says the threshold meaning and units are pending business confirmation.
- **Trigger (user's choice):** automatic after each sync that verifies both files in the session, plus a manual **Re-evaluate** button.
- **File paths:** the two desktop workbooks the user named, `LOCATION MAP AURA - MASTER.xlsx` and `MASTER BOM LIST- AURA.xlsx` (on the OneDrive desktop, not Google Drive), were used only for read-only validation. No path is hard-coded; files are still chosen by the user.

## Behaviour

**Threshold recognition** (`checker/reader.py`, `checker/core.py`):
- On the first Storage header row, a column whose header normalises to exactly `MIN QTY` or `MIIN QTY` is the threshold column.
- No other spelling is accepted: `MIN. QTY`, `MINIMUM QTY`, `MIN  QTY` and `MIN QTY (PCS)` are all rejected by test.
- Storage rows are now read up to column AD; BOM stays at 18 columns.
- With exactly one candidate, state is `FOUND`. Each row keeps its raw threshold value and cell type, and the original header text and column letter are kept.
- With several candidates, state is `AMBIGUOUS`: no values are read and a reader note asks for confirmation. With none, state is `NOT_FOUND`.
- The new `Material` / `StockSheet` fields are optional and ignored by `check_materials`. M2 results are identical with and without the column (tested).

**Schema 2** (`checker/inventory_db.py`) *[superseded: now schema 3, see the remediation report]*:
- `UPGRADE_TO_2` adds 4 nullable columns to `stock_sheets` and 3 to `stock_records`, plus the `alert_evaluations` and `stock_alerts` tables.
- New databases get the same statements in their creation transaction, so both paths end with identical schema SQL (tested).
- `initialise()` now accepts schema 1 *unchanged*; it never migrates it.
- `retention`, `cached` and `history` accept schemas 1 and 2. Retention validates and digests the table set of each version; alert tables are covered by its preview, backup and digest but never pruned by it.

**Sync** (`checker/sync.py`):
- On schema 2, a new Storage import also stores the thresholds, in the same publish transaction.
- On schema 1, writes are exactly as before.
- `capture_thresholds()` runs once on the UNCHANGED path, for a current version imported before thresholds existed. It reuses the caller's parse (in the app, the parse it already holds, so no extra Excel read). It writes only `NULL` threshold fields, and only if all of these hold:
  - the fingerprint and content signature match the version;
  - Sheet names and header rows match;
  - every row number and Material ID matches;
  - the file is unchanged before COMMIT.

  Otherwise it writes nothing and returns quietly; thresholds stay "not captured". It never fails the sync.

**Upgrade** (`checker/upgrade.py`):
- `preview()` is read-only and refuses a missing, foreign, damaged or already-upgraded database.
- `apply()` re-checks the preview under a read transaction, then writes `backups/inventory_before_upgrade_<hex>.sqlite3`. That backup is published only if its integrity is ok and its logical digest equals the preview's.
- It then re-checks under the write lock and applies the statements, `user_version = 2` and `schema_info` entries in one transaction, validating before COMMIT.
- Any failure rolls back; the database stays schema 1.

**Alerts** (`checker/alerts.py`):
- `evaluate()` reads one consistent view of the current Storage and BOM versions. It refuses incomplete payloads, and evaluates each Storage Sheet separately:
  - **OUT_OF_STOCK:** unique ID with valid LIVE STOCK of 0, regardless of threshold.
  - **LOW_STOCK:** unique ID with valid stock below a valid threshold. Equal is not low, and a 0 threshold can never give LOW.
  - **BOM_MATERIAL_NOT_IN_STOCK_MASTER:** one per (Sheet, ID), with every product, BOM Sheet, row and raw QTY listed and nothing summed.
  - **DATA_ISSUE:**
    - blank stock;
    - invalid stock;
    - invalid threshold (text, negative, formula, error or boolean);
    - duplicate Storage ID, with every row's raw values;
    - unusable Storage ID, such as a numeric-cell code;
    - ambiguous threshold column.
  - **THRESHOLD_NOT_CONFIGURED:** blank threshold; it does not hide the row's other alerts.
- Every alert carries raw values as stored, the threshold header and column, the row, and the threshold status.
- The summary counts, per Sheet: each type, data-issue subtypes, distinct missing IDs, missing BOM rows and products, and the threshold state. It also counts BOM rows without a usable ID.
- `AlertService.run()` records an evaluation. It upserts and resolves alerts only when the evaluation is **COMPLETED**: both roles Local File Checked in the database *and* verified by this program in the session.
  - Under the write lock it re-checks that the evaluated versions are still current; otherwise `AlertStale`, nothing is written, and the runner re-evaluates once.
  - `UNVERIFIED` and `FAILED` evaluations are recorded but change no alert.
  - History is bounded: 200 evaluations, and resolved alerts for 180 days.
  - A resolved alert that reappears starts a new episode.
- `AlertRunner` (no Tk) allows one running evaluation and one pending request (the newest replaces it), and delivers nothing after `close()`.

**UI** (`checker/ui.py`, `checker/alerts_ui.py`):
- A clickable **Stock Alerts: N active** line sits under the three top buttons. It also shows *not re-checked*, *upgrade required*, *not evaluated* or *evaluating…*.
- The Inventory Database panel and the CHECK area are unchanged. A first version placed the label in the panel; three M3.1 layout tests failed because the verification time lost its guaranteed space. The label was moved, and those tests now pass unchanged.
- Evaluation is requested after any job whose sync leaves both roles verified in this session. A request made while a job runs waits until it ends. Local History and Upgrade previews refuse while an evaluation is writing.
- The **Stock Alerts** window shows:
  - the permanent banner (synchronised data · Cloud Not Verified · thresholds and units pending business confirmation) and a caveat line;
  - a basis panel: the verified evaluation number, the Storage/BOM versions and file times, Sheet scope, threshold column state, and all counts. A newer UNVERIFIED or FAILED attempt is stated first, saying the alerts were not updated by it;
  - a type filter and *Show resolved*;
  - a table rendered 200 rows at a time;
  - details for the selected alert (rows or BOM occurrences, versions, times);
  - **Re-evaluate**, and **Upgrade database…** on schema 1.

  The window reads on one background thread at a time (plus one pending refresh). Columns never shrink below their normal width.
- Upgrade errors have their own branch: they never clear loaded files. After a successful upgrade the app runs Refresh Excel, which captures thresholds and then evaluates.

## Changed and new files

| File | Change |
|---|---|
| `checker/core.py` | +2 optional `Material` fields and +4 optional `StockSheet` fields (defaults keep earlier behaviour) |
| `checker/reader.py` | Threshold header recognition; Storage scan to AD |
| `checker/inventory_db.py` | Schema 2 statements, table sets, `schema_version()`, schema 1 accepted unchanged |
| `checker/sync.py` | Threshold storage on schema 2; guarded one-time capture |
| `checker/queries.py` | Reconstruction includes thresholds (Excel↔database parity kept) |
| `checker/retention.py`, `checker/cached.py`, `checker/history.py` | Accept schema 1 and 2 (retention: per-version table set) |
| `checker/upgrade.py`, `checker/alerts.py`, `checker/alerts_ui.py` | New |
| `checker/ui.py` | Alerts line, runner, upgrade job, deferral and serialisation |
| `tests/test_m32c.py` | 24 new tests |
| `README.md` | M3.2C section and file table |

Unchanged: `check_materials`, matching and classification (`core.py` logic), report and export, M3.1 sync freshness and its protections, M3.2A cache consent and UNVERIFIED rules, M3.2B retention policy and transactions, the M4A query logic, and the schema-1 write path. No dependency was installed.

## Real-data validation (read-only, temporary databases)

Both workbooks were opened read-only by the project reader (no save, no VBA, no external links, formulas not evaluated). Their fingerprints were identical before and after every run. Temporary databases under `%TEMP%` were deleted afterwards. Nothing was copied into the repository. **The user's real local database was not opened, upgraded or cleaned.** It was created by schema-1 builds; a stat-only check shows `inventory.db` last modified 2026-10-21 10:43, before this work.

| Item | Result |
|---|---|
| Storage file | 197,693,909 bytes, modified 2026-09-30 00:18:59 UTC, SHA256 `ee16d7a8…9323b` |
| BOM file | 121,657,329 bytes, modified 2026-09-08 08:32:19 UTC, SHA256 `88a1aa66…0d40` |
| Storage Sheet | `AURA STOCK MAP-V2-K`, header row 13. Threshold `FOUND`: column P `MIIN QTY`, the only candidate. Header has no unit column. |
| Baseline facts (all reproduced) | 885 rows · 873 distinct IDs · 12 duplicated IDs (24 rows) · LIVE STOCK 785 valid (516 are 0), 54 blank, 46 invalid · MIIN QTY 323 positive, 137 zero, 425 blank · BOM 11 Sheets, 882 rows, 496 distinct IDs · 133 IDs / 373 BOM rows not in Storage |
| Alerts | **OUT_OF_STOCK 494** · **LOW_STOCK 133** · **NOT IN STOCK MASTER 133 distinct IDs / 373 BOM rows / 11 products** · **DATA_ISSUE 112** (BLANK_STOCK 54, INVALID_STOCK 46, DUPLICATE_STOCK_ID 12) · **THRESHOLD_NOT_CONFIGURED 417**. Total 1,289 alerts. |
| Reconciliation | Checked independently from the reader's raw rows, without the alerts module. 516 zero rows = 494 unique + 22 inside duplicated IDs. 425 blank thresholds = 417 unique + 8 inside duplicated IDs. Of the 133 LOW_STOCK, 117 have stock 0 and so also appear as OUT_OF_STOCK. 151 rows have stock equal to threshold and are not low. 117 rows have stock 0 and threshold 0: OUT_OF_STOCK only. 0 invalid thresholds. |
| Upgrade path | Schema-1 temp database → upgrade (0.42 s, verified backup) → threshold capture through the unchanged sync with the same in-memory parse (no extra Excel parse) → identical counts to the fresh schema-2 path |
| Time | Both workbooks parsed once (1.6 s together); evaluation 0.04–0.07 s; recording 0.14–0.24 s |

These figures describe the current files only; the tests do not hard-code them.

## Known issues and limitations (for review)

1. **Missing original instruction:** M3.2C was built against the supplement plus the defaults the user approved. Requirements that existed only in the original may be unmet; please compare.
2. **Duplicated IDs** get only a DATA_ISSUE listing each row's raw values. Their zero stock (22 rows) and blank thresholds (8 rows) do not create OUT_OF_STOCK or THRESHOLD_NOT_CONFIGURED, because an ambiguous ID cannot be assessed. This is a business choice to confirm.
3. **Stock 0 below a positive threshold** shows both OUT_OF_STOCK and LOW_STOCK (117 materials). That is two facts, not a merge. Whether to show one, both or a combined label needs business confirmation.
4. **Multi-Sheet Storage:** coverage is evaluated per Sheet. An ID present only in another Sheet is "not in stock master" for this Sheet, because Sheets are never merged. The real file has one Sheet.
5. **Threshold capture** updates threshold fields of an already-imported version from NULL to the value, once, under strict identity checks. The ambiguity reader note is not added afterwards to that version's stored notes, but the candidates are stored per Sheet.
6. **Threshold columns beyond AD** are not seen; the state is then `NOT_FOUND`.
7. **Manual Re-evaluate during maintenance:** if it is clicked while a Local History or Upgrade confirmation dialog is open, the later apply is refused safely ("changed after preview") and must be previewed again.
8. **Older development builds** refuse a schema-2 or schema-3 database (newer schema). The published v1.0.0 does not use a database. The upgrade keeps a backup.
9. **Not done:** frozen EXE build or run, real Google Drive, another PC, native high-DPI, and Windows 10. Visual checks ran from source in a DPI-unaware process at 960×600 only (1280×720 is checked by tests). No notification or daily summary (M3.2D). The M4A Codex P2 finding (unbounded history workers) is not addressed here.
10. The real user database was not opened here; as a schema-1 database it stays usable unchanged until the user explicitly upgrades it in the app.

Verification details: `M3_2C_TEST_REPORT.md`.
