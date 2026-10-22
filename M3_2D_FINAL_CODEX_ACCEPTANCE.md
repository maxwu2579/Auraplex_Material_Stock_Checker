# M3.2D — Final bounded Codex acceptance

Date: 2026-10-22 (Asia/Singapore). Base `adee725`; scope: current uncommitted M3.2D, specifically the saving fixes and final journal-mode guard. No production/test code edits, real workbook/database access, commit, push, build or release were performed by this review.

## Decision

**GO for a local M3.2D Git commit, not release or deployment.** No unresolved P0/P1 was reproduced in this bounded acceptance. Earlier findings are resolved within the documented Windows/local rollback-journal saving contract:

- **P1-D1: PASS.** Both members are staged first. The final database basis is checked in a held read transaction before the session publication guard and directory rename, and rechecked on retry. That same transaction explicitly accepts only DELETE/TRUNCATE/PERSIST. WAL and other unsupported modes are refused without changing journal mode or publishing a report.
- **P1-D2: PASS.** One no-overwrite directory rename publishes the complete pair; failure leaves no formal report directory. Cleanup failures preserve the original exception and identify incomplete `.partial` remnants.

## Checks actually executed this round

1. Inspected `_publication_basis`, the journal-mode allowlist/exception, final save lock ordering and retry path. Detection precedes accepting the final basis and entering the session guard. It does not change/checkpoint/migrate the database.
2. Ran only the affected save classes:

   `python -m unittest tests.test_m32d.SaveTests tests.test_m32d.PublicationBasisTests tests.test_m32d.PairPublicationTests tests.test_m32d.JournalModeTests -q`

   **18 passed, 0 skipped, 2.435 seconds**. Evidence: `%TEMP%\MRC_M32D_final_codex.txt`.
3. Independently prepared a synthetic WAL database, generated a verified preview and attempted the actual save. It raised `DailyUnsupported`, left the output directory empty (including no staging directory), and retained `journal_mode=wal`: **PASS**. The formerly unsafe publication path is now rejected before final publication.
4. `git diff --check` passed. No full suite, unrelated module suite, real-data revalidation, artefact rehash, build, UI automation or browser/print run was repeated. Earlier validation remains recorded in the implementation, test and review reports; it is not relabelled as a full run of this final source state.

## Remaining limits

- Saving requires a supported rollback-journal database; WAL can still generate/preview summaries but cannot save them. The application does not silently change modes.
- Verification is a local point-in-time observation. Cloud freshness, later source stability and production sufficiency are not asserted.
- Windows local-directory behavior is the tested publication target. Network/cloud-synced folders, crash/power-loss durability, browser visual/print layout, M3.2D EXE, real Drive, another PC, Windows 10 and physical DPI remain unverified.
- Existing JSON path-disclosure, strict-staleness, observation-date attribution and earlier M4A/export responsiveness limitations remain documented. No new feature or next milestone is authorized by this acceptance.

## Commit boundary

The working tree contains M3.2D code/tests, shared integration changes, README/roadmap and reports. A local commit requires the user's instruction and exact staged-file review. Preserve/exclude unrelated `audit_test_run.txt`, real data, databases, temporary evidence and packaged binaries. Do not push/release or start M3.2E automatically.
