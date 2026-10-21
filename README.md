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

The BOM Checker still calculates from the Excel files with the unchanged engine. `--data-dir DIR` uses a different data folder (for testing).

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
