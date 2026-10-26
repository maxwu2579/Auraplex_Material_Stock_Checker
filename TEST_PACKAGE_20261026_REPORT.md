# Local test package — 2026-10-26

Version: 1.1.0.dev0 (not a release). Git base: e060b99 plus the existing uncommitted query-guidance and UI cleanup.
No source edits were made for packaging. No commit, push, GitHub release or dependency installation.

## Outputs

- Desktop entry: C:\Users\25795\OneDrive\Desktop\Auraplex 库存测试版.lnk
- Package folder: C:\Users\25795\OneDrive\Desktop\Auraplex_MSC_Test_20261026_1\Auraplex_Material_Stock_Checker
- ZIP: C:\Users\25795\OneDrive\Desktop\Auraplex_MSC_Test_20261026_1\Auraplex_MSC_1.1.0.dev0_Test_20261026.zip (13.9 MiB)
- EXE SHA-256: eceb0a0e09828066ee0872e0ec5ef616c82a212078ab2de97a192a1b86cbb773
- ZIP SHA-256: 1a9eb863e979e862dd67dcf83ed5b6f9c4ce3b0e78e3095a3e26e4ce03038f03

The desktop shortcut and Start Test.bat use C:\Users\25795\AppData\Local\Auraplex\MaterialStockChecker-Test-20261026-1 as their isolated application data directory.
That directory is separate from the normal inventory database; the build did not initialise it.
The current user's Windows Credential Manager key target remains shared, is not copied into the package,
and is not read by packaging checks. Directly launching the EXE without arguments uses the standard data directory.
The package has an updated test-build README rather than the old v1.0.0 guide.

## Verification performed

- Existing packaging version validation accepted 1.1.0.dev0 only with AllowDevBuild.
- Built with existing project Python 3.12.10, PyInstaller 6.22.3 and openpyxl 3.1.5.
- Used isolated dist/build directories; did not run the script's destructive old-dist cleanup.
- Embedded code comparison: app.py and all 46 checker modules match the source snapshot (47 total),
  normalising code filenames only. No project modules are missing.
- EXE smoke check: exit 0.
- EXE self-test with temporary synthetic workbooks: exit 0, frozen=true, passed=true.
  Expected result: SHORTAGE 1, EXCEPTION 0, ENOUGH 1. Background Excel export and unchanged Refresh passed.
- ZIP CRC check, fresh extraction and another smoke check passed (exit 0) with Python environment
  variables removed and PATH reduced to Windows System32. This is on the current computer, not a clean-PC claim.
- Package contains no .py/.pyw project sources, business Excel/CSV, databases, settings, audit log or .log files.
  Python bytecode is packaged by PyInstaller; no promise of resistance to decompilation is made.
- Published v1.0.0 EXE and ZIP and audit_test_run.txt hashes unchanged.
- No real workbooks, production database, API key, provider calls or business-suite reruns.

## Remaining acceptance

No second PC, Windows 10, physical DPI, real Drive/API validation or new packaged-assistant workflow acceptance.
The built-in self-test covers import/CHECK/export/Refresh, not all new assistant interactions. Package is unsigned.
The test snapshot includes uncommitted work already disclosed in BUILD_INFO.json.

## UI review: recommended next small increment

1. Assistant: translate tab names, actions, form labels and empty/busy/error states together; keep reply-language
   routing separate. Put local tools under a clearly named advanced/manual query entry, retaining offline access.
2. AI report: allow Generate to bind current recorded data itself, show an explicit empty/loading/failure state,
   and retain per-report external-request disclosure and stale-publication protections.
3. Information hierarchy: one compact data-status area, one clear primary action, concise quota notices; hide raw
   timestamps/internal booleans behind detail views while keeping low-credit/failure warnings visible.
4. Continue the selected B1 light-blue style with consistent buttons, spacing and tables. Avoid a new architecture
   migration during UI polish. Keep this packaged snapshot unchanged as a comparison and rollback build.

No additional production UI changes were made during this packaging task.
