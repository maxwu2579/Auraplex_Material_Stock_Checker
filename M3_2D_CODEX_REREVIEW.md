# M3.2D — Saving remediation re-review

Date: 2026-10-22. Bounded review of `M3_2D_REMEDIATION_REPORT.md` and the modified save/publication paths. No production code/tests, real Excel/database, commit, push, release or next milestone was changed/executed by this review.

## Decision

**NO-GO pending one bounded P1-D1 mode-handling fix.**

- **P1-D2: PASS** for the reviewed Windows directory-publication contract. Both members are staged/read-back-verified before one no-overwrite directory rename. Cleanup failure preserves the initial exception and exposes the incomplete `.partial` path. Existing destination, staging failure, interruption and rollback-error scenarios pass.
- **P1-D1: PASS in the default rollback-journal mode, still FAIL for an accepted WAL database.** A read transaction does not serialize writer commits in WAL mode, and the save path neither refuses that mode nor implements a WAL-compatible publication boundary.

## Minimal executed verification

Ran only the affected classes:

```text
python -m unittest tests.test_m32d.SaveTests tests.test_m32d.PublicationBasisTests tests.test_m32d.PairPublicationTests -q
15 passed, 0 skipped, 2.085 seconds
```

Log: `%TEMP%\MRC_M32D_save_rereview.txt`. The entire module/full suite was not repeated. `git diff --check` passes. No browser/print, packaged EXE, real Drive, second PC, Windows 10 or physical DPI acceptance was executed.

## Remaining P1 — WAL read lock does not protect final publication

Location: `checker/daily.py:_publication_basis` and `save()` around the final database check and directory rename.

The new docstring correctly qualifies its lock behavior to rollback journaling, but the code never checks that prerequisite. SQLite journal mode persists in the database. A database opened/changed by another instance or maintenance tool can be WAL even though this app does not itself enable it. The project already has synthetic WAL compatibility coverage for retention (`tests/test_m32b.py`); no general application rejection makes this save route unreachable.

Independent reproduction, using the synthetic `PublicationBasisTests` fixture:

1. Import both fixtures and evaluate alerts.
2. Set only the temporary database to `PRAGMA journal_mode=WAL`.
3. Generate a verified summary.
4. At `before_publish`, after the final basis read and while its read transaction/session guard remain held, run the actual other-instance inventory sync with changed synthetic Storage contents.
5. Continue the normal directory publication.

Observed:

```text
journal_mode = wal
other_instance_imported_before_report_publish = True
basis_changed = True
saved_status = VERIFIED
complete_report_folder_exists = True
```

Thus the same obsolete-report defect remains in that mode. This is a concrete publication-boundary failure, not a request to implement more infrastructure.

## Smallest acceptable repair

**Do not expand scope to support WAL publication.** Detect the journal mode inside the same final publication read transaction, before accepting the basis/entering the session guard. If the mode is WAL or otherwise outside the explicitly supported locking contract, fail closed with a clear DailyError and no final report. Document that Daily Summary saving currently requires a supported rollback-journal database.

- Do not automatically change journal mode, checkpoint/truncate WAL, migrate or modify the user's database.
- Preserve the working directory-publication and cleanup-error handling.
- Check the mode on every final publication attempt/retry, not merely before staging. Retain the existing SQLite-before-session lock ordering.
- Add only targeted tests: default-mode save still succeeds; synthetic WAL VERIFIED and UNVERIFIED saves refuse with no final directory; journal mode is unchanged; no-overwrite/cleanup behavior remains valid. Generation/preview may stay read-only and usable in WAL; it is saving that must not promise unsupported publication ordering.
- Run those exact tests plus the affected save classes once. **No full suite, real-file validation, rebuild, broad UI matrix or unrelated tests are needed for this bounded guard.** If the implementation unexpectedly changes shared business code, stop and explain that scope change instead of broadening silently.

Update the remediation report with mode detection and test evidence. Do not commit/push/release, start M3.2E or alter real data. Stop for a final bounded recheck.

## Unchanged limitations

Windows local-directory rename behavior is the accepted target; network/cloud-synced target behavior and crash/power-loss durability are not established. Browser visual/print review remains open under the earlier browser-policy restriction. Known strict staleness, local-path disclosure and observation-date attribution remain documented. No other new P0/P1 was established within this bounded save-path review.
