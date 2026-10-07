# Packaging Report — v1.0.0

Date: 2026-10-07. Packaging and publishing only; no calculation, matching, classification, sorting, Product ID, file-handling or report logic was changed.

## Build

| Item | Value |
| --- | --- |
| Python | 3.12.10 (64-bit), project `.venv` |
| PyInstaller | 6.22.3, installed into the project `.venv` only |
| openpyxl | 3.1.5 |
| Build mode | `--onedir --windowed` |
| Build script | `build_portable.bat` → `build_portable.ps1` |
| EXE | `dist\Auraplex_Material_Stock_Checker\Auraplex_Material_Stock_Checker.exe` |
| ZIP | `dist\Auraplex_Material_Stock_Checker_v1.0.0_Portable.zip` |
| ZIP size | 11,920,934 bytes (11.4 MB); 28 MB extracted |
| ZIP SHA-256 | `768759c9961d9027d1a990e678c5581001f151ee2b54ab1c424ab425ed1517d5` |
| Digital signature | None (`NotSigned`) |

ZIP contents: `Auraplex_Material_Stock_Checker.exe`, `_internal\` (Python runtime, Tcl/Tk, openpyxl, application modules) and `README.txt` (copy of `PORTABLE_USER_GUIDE.txt`). No source files, tests, scripts, workbooks or development reports.

## Changes made for packaging

| File | Change |
| --- | --- |
| `app.py` | Added `--self-test STORAGE BOM OUTPUT_DIR`, a packaging check that drives one load / search / check / export with caller-supplied synthetic workbooks and writes `self_test.json`. Not used in normal operation |
| `checker/ui.py` | Two placeholder texts that named real workbook files were replaced with generic wording |
| `tests/test_m2.py`, `tests/test_m21.py`, `tests/visual_preview.py` | Product and workbook names in synthetic fixtures replaced with invented ones. Two report-payload digests were re-derived after confirming the payload equals the earlier baseline once the one renamed sheet name is substituted back |
| `.gitignore` | Extended: environments, build output, workbooks, test artifacts, internal records |
| New | `build_portable.bat`, `build_portable.ps1`, `PORTABLE_USER_GUIDE.txt`, `README.md` (rewritten), `RELEASE_NOTES_v1.0.0.md`, this report, `RELEASE_CHECKLIST.md` |

## Pre-build verification

| Check | Result |
| --- | --- |
| Full test suite before any change | PASS — 110 tests (105 run, 5 mount tests skipped) |
| Full test suite after the changes above | PASS — 110 tests (105 run, 5 skipped) |
| Launcher smoke test (`launch.ps1 -SmokeTest`) | PASS |

## Packaged EXE smoke test

The ZIP was extracted to `C:\Temp\Auraplex_Material_Stock_Checker_Test`, outside the repository and outside any synced folder. The EXE was started with the working directory set to that folder and with all `PYTHON*` and virtual-environment variables removed. Input workbooks were small synthetic files written into the test folder.

| Check | Result |
| --- | --- |
| EXE launches (`--smoke-test`) | PASS, exit code 0 |
| Normal start: main window appears, is visible and responding, closes cleanly | PASS |
| UI renders | PASS — window image captured and inspected |
| Runs from the packaged files only | PASS — the running process reports itself as frozen, its executable is the extracted EXE, and the application modules load from the extracted `_internal` folder, not the project |
| Runs without the project `.venv` | PASS — environment cleared; the package contains its own runtime |
| Storage and BOM load | PASS (through the same function the Browse button calls) |
| Product search | PASS — partial lower-case text lists the 2 matching IDs of 3; partial text alone is refused |
| Quantity input and CHECK | PASS |
| SHORTAGE / EXCEPTION / ENOUGH shown correctly and in order | PASS — 2 / 7 / 2 rows, red → yellow → white, assumed zeros marked |
| EXPORT EXCEL | PASS — report contains `Shortage` and `Exceptions` |
| Source workbooks unchanged | PASS — SHA-256 and modified time identical |
| Package contains no project paths, user name or business names | PASS — files and the compressed module archive were scanned |
| Native Browse and Save dialogs clicked by a person | NOT EXECUTED |
| Source directory renamed or moved during the test | NOT EXECUTED — the project folder is in use by the build session and is inside a synced folder; independence was shown by the module-location check above instead |
| Real company workbooks with the packaged EXE | NOT EXECUTED — synthetic data only, by design |

Observation: at the captured window size the status line of the two file cards is partly cut off. This is the existing layout, not a packaging effect, and was left unchanged.

## Antivirus / SmartScreen

| Check | Result |
| --- | --- |
| Microsoft Defender, real-time protection on, during build and test | No warning, nothing blocked or quarantined |
| Microsoft Defender custom scan of the ZIP | No threats found |
| Microsoft Defender custom scan of the extracted folder | No threats found |
| SmartScreen | Not observed. SmartScreen acts on files downloaded through a browser; the test used a local copy |

No security software was disabled or bypassed. The EXE is unsigned, so a "Windows protected your PC / unknown publisher" notice is expected when a downloaded copy is first started. This is a limitation of an unsigned internal application.

## Second PC

Not tested. Everything above ran on the build computer (Windows 11).

## Limitations

- Unsigned executable; SmartScreen notice expected on first start after download.
- Not verified on a second computer, on Windows 10, or on a computer that has never had Python installed. The package brings its own runtime, but this has not been observed on a clean machine.
- One-folder build: the `.exe` must stay next to `_internal`.
- 64-bit Windows only.
- The interface was not operated by a person in the packaged form; dialogs were not clicked.
- The version number appears in the ZIP name and release, not in the window title.
