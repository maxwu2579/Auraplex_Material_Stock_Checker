# M3.2A/B acceptance review and focused CC handoff

Date: 2026-10-21. Scope: current uncommitted M3.2A/B changes on top of `311a69a`.

## Decision

No new P0/P1 defect was identified in this focused source review and execution. The reviewed source paths pass their targeted checks. Complete packaged acceptance remains open for the new cached-mode and retention workflows. This is a subsequent review by the implementation agent, not an independent human or separate-agent audit. No production code was changed during this review, and no commit/push/release was made.

## Evidence verified this turn

- Read `checker/cached.py`, `checker/retention.py`, and the relevant UI, query, export and test changes. Cached exports cannot enter the verified-source writer. Explicit consent is session-only. Database changes invalidate a cached selection. Final export validation occurs after workbook generation.
- Retention rechecks the preview against the database under a write lock after backup. Deletions and retention metadata share one transaction. Current/latest snapshots, baseline predecessors, and required successful/failed status records remain protected.
- Executed `python -m unittest tests.test_m32a tests.test_m32b -q`: **57 passed, 0 skipped, 57.719 seconds**. Log: `%TEMP%\MRC_M32AB_acceptance.txt`.
- Added an ad hoc execution using only temporary synthetic files: cleanup, restore its backup into another SQLite database, compare the complete logical database digest to its pre-cleanup state, reconstruct both workbooks and calculate/export from the restored database. All passed. Restored workbook data equals the original cached data; exported sheets contain UNVERIFIED titles and warnings.
- Independently changed cached stock data while the report was being generated. Final validation refused publication; no final report or staging file remained. Synthetic source workbook hashes/mtimes stayed unchanged.
- Inspected the existing full-suite log: **262 tests, 257 passed, 5 mounted-drive tests skipped, 165.338 seconds**. This full suite was completed previously and was not repeated in this review.
- Re-read the existing frozen self-test JSON: normal Excel sync/CHECK/export/unchanged Refresh passed, `frozen=true`, errors empty, Cloud Not Verified present. This packaged smoke was completed previously, not rerun here.
- Recomputed protected v1.0.0 EXE and ZIP SHA256 values: both match the pre-build records. `git diff --check` passes. Calculation engine, source reader, synchronization implementation, schema and original test files remain unchanged relative to HEAD.

## Findings and remaining limitations

- **P0/P1:** none newly reproduced in this review. This is not proof that every possible interleaving is covered.
- **P2, known responsiveness limitation:** export verification/report writing remains synchronous on the Tk thread. Slow local/Drive filesystem operations may delay the interface; retention and cached selection/CHECK run through workers. No evidence here supports calling it a deadlock.
- **Acceptance gap:** source Tk tests cover cached and retention flows; the existing frozen test covers normal Excel flow only. Do not describe packaged cached/retention acceptance as complete yet.
- Backups intentionally preserve old history and have no automatic expiry; logical deletion does not guarantee file shrinkage or secure erasure. No real user database was cleaned.
- No real Drive mutation/cloud freshness, physical display scaling or second-PC validation was performed this turn. Local file checks remain point-in-time observations only.

## Instructions for Claude Code — next bounded task

Work only in this project. Read this report and both M3.2 implementation reports first. Inspect Git status; preserve existing uncommitted changes and unrelated files.

Complete **packaged M3.2A/B acceptance**, without adding features or starting M4:

1. Use the existing isolated temporary development package if it corresponds to current sources; otherwise build in a new isolated temporary build/dist folder. Do not run a default clean that touches the project's published `dist`. Do not install dependencies or rebuild if unnecessary.
2. Exercise the actual frozen EXE with a separate temporary application-data directory and synthetic workbooks/database. Never use the user's real database or real source workbooks. Do not change Google Drive settings.
3. Cached workflow: establish synthetic imports, make the synthetic Excel sources unavailable, verify no silent fallback, accept cached use explicitly, CHECK, and export. UI/report must say UNVERIFIED and Cloud Not Verified. Reject stale cache export after an independently published database version. Restart must not restore consent.
4. Retention workflow: seed expired synthetic history, preview and decline with no deletion, then explicitly confirm. Verify backup, current/latest/baseline protection and database integrity. Restore the backup into a separate temporary database and compare its logical contents. CHECK/export must require a new CHECK after maintenance. Never modify the original published database to perform recovery.
5. Prefer existing actual-app entry points and minimal test instrumentation over a new testing framework. If the frozen workflows cannot be exercised, record the precise limitation rather than marking them passed. Any added harness must test the frozen application, not silently substitute source Python imports.
6. No production changes unless a concrete defect is reproduced. If fixing one, keep the M2 calculation/stock rules and M3.1 freshness protections intact; add a focused regression test and run the affected subset. No repeated full-suite runs without new code/failures. If production code changes, perform one final full suite at the end.
7. Deliver `M3_2AB_PACKAGED_ACCEPTANCE.md` with actual commands, package/source identity, results, elapsed time, limitations, P0/P1/P2 findings and GO/NO-GO for a local commit. Recheck published EXE/ZIP hashes. Do not commit, push or release. Stop after this task.
