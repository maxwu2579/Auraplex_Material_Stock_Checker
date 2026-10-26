# GitHub Windows pre-release preparation — 2026-10-26

Target: maxwu2579/Auraplex_Material_Stock_Checker, tag v1.1.0.dev0 (pre-release, not latest stable).
User authorised source upload and executable delivery. Existing v1.0.0 remains untouched.

## Deliverables

- Auraplex_Material_Stock_Checker_1.1.0.dev0_Windows.exe — single-file, windowed PyInstaller EXE; no Python install or command line needed.
- Auraplex_Material_Stock_Checker_1.1.0.dev0_Windows.zip — same EXE, recipient guide, validation and EXE checksum.
- SHA256SUMS.txt — EXE and ZIP checksums.
- README_FIRST.txt and VALIDATION.txt.

EXE SHA-256: `b32f1a1985585cfdbe37b5654389f5349f13f256b5dd2a1b0504ed43b9ff25c2`
ZIP SHA-256: `727b3863ccd6649d5e4fe9dbcbea009a3116c9d661c4c32fd998271e5b41f99d`

## Safety and verification

- Inspected current-user Windows Credential Manager storage. No actual credential read/export.
- Scanned 168 tracked/new files and 232 unpublished-history blobs for common secret patterns, no hits.
- 3 focused fake-credential/outbound-projection tests passed, 0.007 s. No full business suite rerun.
- Added ignore rules for local databases/settings, runtime audit log and generated binaries/archives.
- Built in isolated output/work directories. Default portable script cleanup was not executed.
- 47 embedded code modules match the working source snapshot. No business data in the archive.
- Standalone smoke and synthetic Excel self-test passed with Python environment variables removed
  and PATH reduced to Windows System32. Self-test classified 1 shortage / 0 exceptions / 1 enough,
  exported Excel, and kept unchanged-refresh snapshot counts stable.
- Existing published package hashes and audit_test_run.txt hash remain unchanged.

## Remaining limits

Unsigned pre-release. No clean second PC, Windows 10, native physical DPI or real API/Drive acceptance
for this artifact. Some assistant UI is still English. No installer is needed for this single-file
option; it does not install a server/service. Each recipient supplies their own Excel files and Key.
PyInstaller bytecode is not a guarantee against reverse engineering.
