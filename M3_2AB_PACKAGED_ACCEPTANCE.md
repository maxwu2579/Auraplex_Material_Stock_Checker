# M3.2A/B packaged acceptance (frozen EXE)

Date: 2026-10-21 (Asia/Singapore). Scope: the uncommitted M3.2A/B working tree on top of `311a69a`, exercised as a frozen PyInstaller application. This was run by Claude Code as a bounded acceptance task. It is not an independent human audit. No production code was changed, no rebuild was made, and nothing was committed, pushed or released.

## Decision

**GO for a local commit of M3.2A/B. This is not a release decision.**

The frozen application passed every cached-mode and retention acceptance check below, driven through its real UI. No P0/P1 defect was reproduced. The remaining items are P2 or test-tooling observations and documented limitations.

## Package and source identity

| Item | Value |
|---|---|
| Package used | Existing isolated build `%TEMP%\MRC_M32B_Package_51f10b568dc14f25abafdefec259a023\dist\MRC_M32B_TEST\MRC_M32B_TEST.exe` (onedir, windowed, built 11:30:19 by the M3.2B stage) |
| EXE SHA256 | `F4FEC282BE0D968DA4A8D8458EE400B12DAE7E36CBDDFAC9E1DF45BAD0789424` |
| Source correspondence | The `PYZ.pyz` code objects of all 15 `checker` modules and the `app` entry script are identical to the current working-tree sources, ignoring file paths and line tables. Evidence: `package_identity.txt`. Version `1.1.0.dev0`. |
| Negative control | The same comparison against a copy with one changed constant in `checker/cached.py` reports `checker.cached DIFFERENT` / `MISMATCH`. Evidence: `package_identity_negative_control.txt`. |
| Rebuild | Not needed and not performed. The project's `build\` and `dist\` were not touched. |

Correction during the run: the first version of the comparator printed `repr()` of `frozenset` constants, whose order is hash-randomised. One run therefore falsely reported `checker.report_style DIFFERENT`; the file was unchanged since 2026-10-07 and had the same SHA256. After sorting `frozenset` members the result was `ALL MATCH` on three consecutive runs, and the negative control was still detected.

## Method

All evidence is in `%TEMP%\MRC_M32AB_PackagedAcceptance_4f828e45e37a491db42afa7cd2411e7a\`, called `ACC` below. The harness scripts are copied to `ACC\harness\`.

- **System under test:** the unmodified frozen EXE, launched with `--data-dir ACC\<case>\appdata`. That is a temporary application-data folder holding synthetic workbooks and synthetic databases only.
- **Driver:** `w32.py` plus `drive_cached.py` / `drive_retention.py`, run as a separate process from the project `.venv` Python. They use only `ctypes` and `sqlite3`, plus `openpyxl` to read the produced report. They never import `checker` or `app`.
  - Tk buttons are pressed with real mouse/keyboard input (`SendInput`).
  - Native MessageBox, Save As and confirmation dialogs are read with `WM_GETTEXT` and answered with their button IDs.
  - A screenshot of the window or dialog is taken at every step with `PrintWindow`.
  - The app is DPI-unaware (it is bitmap-scaled at 300% on this display). The driver thread therefore runs DPI-unaware, so coordinates are logical pixels.
  - The CHECK/EXPORT row moves when the layout compacts, so it is located on every click from the colour of the primary `CHECK MATERIALS` button.
- **Imports through the frozen app:** `MRC_M32B_TEST.exe --self-test <storage> <bom> <outdir> --data-dir <appdata>` established the initial synthetic imports. Every self-test in this run reported `passed=true`, `frozen=true`, `errors=[]` and `Cloud Not Verified`.
- **Fixture generation, not the system under test:**
  - Synthetic workbooks were written with `tests/fixtures.py`.
  - For retention, backdated history (2024-07-01 … 2025-11-01, plus a 2025-01-15 `UNAVAILABLE` attempt) was generated with the project's own `InventorySync` and a fixed clock (`seed_retention.py`). The app has no way to import with a past clock.
  - The current-day import, CHECK, preview, cleanup and export were all performed by the frozen EXE.
- **Independent verification:** all database checks use stdlib `sqlite3` in read-only URI mode:
  - a logical digest over all `sqlite_master` objects and every table's rows in rowid order;
  - `PRAGMA integrity_check` and `PRAGMA foreign_key_check`;
  - table-level comparisons.

  The application's own `retention._digest` was not used.

Commands (from the repo root, with `PY=.venv\Scripts\python.exe` and `EXE` as above):

```
PY scratch\compare_pyz.py EXE .                                    # identity, 3x
EXE --self-test ACC\cached\sources\storage.xlsx ACC\cached\sources\bom.xlsx ACC\cached\selftest --data-dir ACC\cached\appdata
(rename ACC\cached\sources -> sources_offline)
PY scratch\drive_cached.py scratch EXE ACC\cached <repo>           # 44.5 s
PY scratch\seed_retention.py ACC\retention <repo>
EXE --self-test ACC\retention\sources\storage.xlsx ACC\retention\sources\bom.xlsx ACC\retention\selftest --data-dir ACC\retention\appdata
PY scratch\drive_retention.py scratch EXE ACC\retention            # 38.4 s
sha256sum dist\Auraplex_Material_Stock_Checker_v1.0.0_Portable.zip dist\Auraplex_Material_Stock_Checker\Auraplex_Material_Stock_Checker.exe
git diff --check
```

Each frozen `--self-test` took about 4 s. The whole session, including harness development and the failed attempts listed below, took about 25 minutes.

## M3.2A cached workflow — frozen EXE (`ACC\cached\evidence\cached_results.json`)

| # | Check | Result |
|---|---|---|
| 1 | Restart with both remembered synthetic sources unavailable: the `读取/检查失败` dialog names both files; two `UNAVAILABLE` sync runs are recorded; status shows `Using Previous Data` and `Cloud Not Verified`; the product list is empty | PASS |
| 2 | No silent fallback: CHECK is refused (`请先成功读取库存与 BOM 文件`) | PASS |
| 3 | The cache preview shows `CACHED DATA / UNVERIFIED`, `Cloud Not Verified`, both paths, version IDs, and modified, imported and verified UTC times. The default button is No | PASS |
| 4 | After declining, CHECK is still refused | PASS |
| 5 | After explicit Yes: the mode line shows `CACHED DATA / UNVERIFIED`; the product is typed and selected; CHECK shows 3 rows (EXCEPTION 2, ENOUGH 1), identical to the Excel self-test; the result label is `CACHED DATA / UNVERIFIED`; no error dialog; no new `sync_runs` rows | PASS |
| 6 | Export: the Save dialog proposes `UNVERIFIED_Material_Check_PRODUCT-1_QTY1_…`. The published report has sheets `Shortage` and `Exceptions`; both start with `UNVERIFIED · Cached Material Requirement & Stock Report`, and `Cloud Not Verified` is present. The status line reads `CACHED DATA / UNVERIFIED report exported · Cloud Not Verified` | PASS |
| 7 | A separate frozen EXE process (`--self-test` with a changed synthetic Storage file, same `--data-dir`) publishes a new database version while session 1 stays open. Result: exit 0, `passed=true`, stock `IMPORTED`, 4 source versions in total | done |
| 8 | Stale cache export in session 1 is refused before any Save dialog with `OUTDATED / RECHECK REQUIRED` / "Cached Storage/BOM versions changed…". No new file is written; EXPORT is disabled; the label is `OUTDATED / RECHECK REQUIRED`; the mode line shows `Reselect required` | PASS |
| 9 | A new CHECK cannot restore the expired consent (`缓存授权已失效…`) | PASS |
| 10 | Clean close (exit 0). `settings.json` contains only `version` and `paths`: no consent is persisted | PASS |
| 11 | Restart (sources unavailable again): normal Excel mode with no cached label; CHECK is refused; EXPORT is refused (`没有可导出的结果`); exit 0 | PASS |
| 12 | Offline synthetic source hashes are unchanged; database `integrity_check` = `ok` | PASS |

Not exercised in the frozen app: a database change during staging, after the Save dialog. The source tests cover it (M3.2A implementation report and earlier ad hoc review). This run exercised the pre-dialog and preflight refusal path.

## M3.2B retention workflow — frozen EXE (`ACC\retention\evidence\retention_results.json`)

Seeded state: 5 stock snapshots (2024-07-01, 2025-07-01, 2025-10-01, 2025-11-01, and the 2026-10-21 import made by the frozen app), 16 sync runs, and current sources `stock=6`, `bom=2`.

| # | Check | Result |
|---|---|---|
| 1 | Start with available sources (no dialog), then an Excel CHECK showing `Local Sources Verified` | PASS |
| 2 | **Preview → No:** the dialog shows cutoffs (snapshots before 2025-10-21 06:55 UTC; routine logs 90 days; failure logs 180 days) and counts: 2 snapshots, 1 payload, 4 stock rows, 1 sheet, 3 quality issues, 1 change, 6 logs. The default button is No. The logical digest is unchanged and no `backups` folder exists | PASS |
| 3 | **Preview → Yes:** the counts are identical to the declined preview. The completion dialog shows `Local history cleanup completed` and the path of the recovery backup | PASS |
| 4 | Deleted snapshots `{1, 2}`, all older than the cutoff. The latest/current snapshot (5) is kept. The **baseline** (snapshot 3, 2025-10-01, the last one before the cutoff) is kept. Snapshot 4 is kept | PASS |
| 5 | `current_sources` unchanged; all `source_versions` headers kept; the current stock payload is kept. Only version 1's payload was removed (payload versions `[1,3,4,5,6]` → `[3,4,5,6]`). BOM tables and the `materials` registry are byte-identical | PASS |
| 6 | Deleted logs `1–6`: routine runs older than 90 days and the 2025-01-15 `UNAVAILABLE` run older than 180 days. Each role's latest attempt and latest success are kept. The BOM's 2024 `IMPORTED` log was removed; its current-version provenance is the kept recent `UNCHANGED` run for version 2, as documented. `history_retained_from` is recorded | PASS |
| 7 | `integrity_check` = `ok` and `foreign_key_check` is empty, on a post-cleanup copy and on the live database at the end | PASS |
| 8 | The backup `appdata\backups\inventory_before_cleanup_<hex>.sqlite3` exists with no `.partial` file. Its integrity is `ok` and its **logical digest equals the pre-cleanup digest** | PASS |
| 9 | **Recovery rehearsal:** the backup was copied with the SQLite backup API into a separate `ACC\retention\restore\restored.db`. It has integrity `ok`, a logical digest equal to pre-cleanup, and 5 snapshots. The published database's SHA256 is unchanged across the restore: it was never written for recovery | PASS |
| 10 | After maintenance the old result is cleared and EXPORT is refused (`没有可导出的结果`). A new CHECK then succeeds and a normal verified export is written (`Material_Check_PRODUCT-1_QTY1_…xlsx`, no UNVERIFIED prefix) | PASS |
| 11 | Clean exit (0); synthetic source workbook hashes unchanged | PASS |

## Attempts that did not count (all harness defects, kept for traceability)

| Folder | What happened |
|---|---|
| `ACC\cached_run1_driver_defect` | Setting the Save-dialog filename with `WM_SETTEXT` did not take effect, so the app saved under its proposed name in the dialog's default folder, `C:\Users\25795\OneDrive\文档\`. The synthetic report (13 KB) was written at 14:43:20 and moved within about one minute to `cached_run1_driver_defect\stray_from_onedrive_documents\`. No other file was placed there. **OneDrive may already have synced it**: it contains only synthetic data and temporary paths. If you want it gone completely, check OneDrive's web recycle bin. The driver now types the path, reads it back and cancels the dialog if it does not match exactly. |
| `cached_run2_driver_race` | The driver picked up the app's transient `.mrc-export-*.xlsx` staging file before publication. The app published correctly. |
| `cached_run3_publisher_outdir` | The independent publisher's `--self-test` output folder did not exist, and the process hung until the driver's 120 s timeout (see P2-1). |
| `cached_run4_layout_shift` | Fixed click coordinates missed after the export-feedback bar compacted the layout. The driver now locates the row on screen. |
| `retention_run1_comparator`, `retention_run2_comparator` | The driver compared preview text including the evaluation time, giving a false `confirm_preview_same_counts=false`. The counts were identical in the log; all other checks passed in both runs. |

In every attempt the application behaved as specified up to the point where the driver failed.

## Findings

- **P0 / P1:** none reproduced.
- **P2-1 (test tooling, pre-existing, not M3.2):** `--self-test` does not exit if `OUTPUT_DIR` does not exist. `finish()` writes `self_test.json` without a guard, and the exception handler calls `finish()` again, so the self-test window stays open. This was observed once and is consistent with `app.py`; creating the folder avoids it. It does not affect normal use.
- **P2-2 (known, not re-assessed):** export verification and writing remain synchronous on the Tk thread.
- **Observation:** the frozen app is DPI-unaware and bitmap-scaled on this 300% display. The layout is usable at 1248×624 logical pixels; text is softer than native. This is not new in M3.2 and no physical-DPI claim is made.

## Limitations

- One machine and one display. There was no second PC, no real Google Drive or cloud freshness check, and no Drive settings were changed.
- The real user database (`%LOCALAPPDATA%\Auraplex\MaterialStockChecker\inventory.db`, last modified 10:43 today, before this session) and the real workbooks were not opened.
- Backdated retention history was generated with source `InventorySync` (fixture data). The retention preview, decision, backup, deletion and post-maintenance flow ran in the frozen EXE.
- The driver used real mouse and keyboard input on the interactive desktop for about 1.5 minutes per final run.
- Cached reconstruction after a cleanup and multi-sheet Storage selection were not exercised in the frozen app; source tests cover them.
- Point-in-time checks only. This does not prove every interleaving.
- Importing `tests.fixtures` / `checker.sync` for fixture generation may have refreshed git-ignored `__pycache__` files. `git status` is unchanged.

## Repository and protected artefacts

- `git status`: identical to the start of the task. The only new file is this report. `git diff --check` passes.
- Protected v1.0.0 hashes, before and after, are unchanged:
  - ZIP `768759C9961D9027D1A990E678C5581001F151EE2B54AB1C424AB425ED1517D5`
  - EXE `E232F2074F0F6DFE35EC623C96ED913C4EC570A53B098ABA45F7F74183930E50`
- No application process was left running.
- No full test suite was rerun, because no code changed. The last full suite is still 262 tests / 257 passed / 5 skipped (M3.2B report).
