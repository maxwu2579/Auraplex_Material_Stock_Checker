# Release Checklist — v1.0.0

Date: 2026-10-07. Evidence for each item is in `PACKAGING_REPORT.md`.

## Before publishing

- [x] **Tests passed** — 110 tests: 105 run and passed, 5 mount-only tests skipped. Run before and after the packaging changes.
- [x] **Launcher smoke test passed** — `launch.ps1 -SmokeTest`.
- [x] **Source data excluded** — no Storage, BOM or other workbook is in the repository or the ZIP. `.gitignore` excludes `*.xlsx`, `*.xlsm`, `*.xls`, `*.csv`, `~$*`, `test-artifacts/`, `.venv/`, `build/`, `dist/`.
- [x] **Sensitive-file audit passed** — every file to be committed was listed and searched for drive and user paths, synced-folder names, real workbook and product names, e-mail addresses, passwords, tokens and keys. Findings were removed before the first commit:
  - real workbook names in two interface placeholder texts → generic wording;
  - real product and workbook names used as labels in synthetic test fixtures → invented names;
  - internal development records and the real-data verification tool, which refer to company files → kept out of the repository.
- [x] **Source workbooks unchanged** — the packaged build was exercised with synthetic workbooks only (hash and modified time identical before and after). The company Storage and BOM workbooks were not opened by the packaged build, and their SHA-256 values still match the values recorded earlier in the project.
- [x] **Portable build passed** — `build_portable.bat`; one-folder windowed build; isolated smoke test outside the repository passed; Microsoft Defender found no threats.
- [x] **Business logic unchanged** — no change to matching, calculation, stock rules, categories, sorting, duplicate handling, Product ID behaviour, file handling or report logic.

## Publishing

- [x] **Git push passed** — `main` pushed to `origin` without force; the remote was empty beforehand. Commit `0b49f812b078181caf8fbf80cd9d0be0f92f7c5b`. A final check immediately before the push found a clean working tree and no sensitive content in the 30 committed files.
- [x] **Release created** — tag `v1.0.0` on that commit, title "Auraplex Material Stock Checker v1.0.0", notes from `RELEASE_NOTES_v1.0.0.md`, published (not a draft, not a pre-release): https://github.com/maxwu2579/Auraplex_Material_Stock_Checker/releases/tag/v1.0.0
- [x] **ZIP attached** — `Auraplex_Material_Stock_Checker_v1.0.0_Portable.zip`, 11,920,934 bytes, SHA-256 `768759c9961d9027d1a990e678c5581001f151ee2b54ab1c424ab425ed1517d5`. Nothing else attached.
- [x] **Release and download verified** — the repository page and release page load without signing in; the ZIP was downloaded anonymously from the release and its size and SHA-256 match the built file.

## After publishing

- [ ] Download the ZIP from the Release page on another computer, extract it and start the EXE (second-PC test; not yet done).
- [ ] Note what SmartScreen shows on that first start.
