# M3.2C — Final Codex acceptance

Date: 2026-10-22 (Asia/Singapore). Scope: the current uncommitted M3.2C re-review repair, against `M3_2C_CODEX_REREVIEW.md`. Prior accepted M4A and M3.2C source-scope/provenance changes remain in the working tree. No production code/test changes, real workbook/database reads, builds, commits, pushes or releases were made by this acceptance run.

## Decision

**GO for a local Git commit of the reviewed M3.2C implementation. Not a release/deployment decision.**

| Finding | Result |
| --- | --- |
| P1-R1, invalidation during the transaction still committed recovery | PASS |
| P1-R2, database read failure left verified UI/evidence and manual reauthorization available | PASS |
| Earlier source-scope isolation, migration, provenance retention, filters and historical change-view regressions | PASS in the targeted suite |

No unresolved P0/P1 was reproduced within this bounded review. The limits below remain; passing source tests does not establish packaged, real-cloud or multi-PC readiness.

## Source inspection

- `SessionGate.publishing(generation)` holds the session lock across the final generation check and actual SQLite COMMIT. `AlertRunner` supplies that guard to `AlertService.run`.
- The write transaction acquires its SQLite EXCLUSIVE lock before taking the publication guard. A refused final guard rolls back the complete tentative verified evaluation and alert changes; a separate transaction records UNVERIFIED without recovering alerts. A stale authorization remains stale on retry.
- Invalidation discards the affected roles' version/path verification evidence, increments the gate and removes current verification. Read failures invalidate both roles. A later successful database read clears only the read-error flag; it does not restore source authorization.
- Alert-window, observed-change, background-status and existing maintenance/cache read-error paths route to session invalidation. The entry and fixed window line reflect unknown/not-rechecked state. Fresh source sync is required to rebuild authorization.

## Executed evidence

1. Ran `python -m unittest tests.test_m32c tests.test_m32c_remediation tests.test_m32c_rereview -q`: **50 passed, 0 skipped, 15.252 seconds**. Log: `%TEMP%\MRC_M32C_final_codex.txt`. Includes publication injection at four transaction boundaries, cross-thread invalidation, gate ordering, SQLite reader contention, stale retry, read-failure/reopen/manual reevaluation and Refresh recovery, plus earlier scope/migration/provenance regressions.
2. Independently repeated the exact prior SQLite trace-callback reproduction, rather than only using the new checkpoint hook. After the first `INSERT INTO alert_evaluations`, invalidated the real gate. Observed **UNVERIFIED**, `resolved=0`, B **ACTIVE**. The earlier false COMPLETED/recovery was not reproduced.
3. Independently repeated the actual background Stock Alerts reload failure with `sqlite3.OperationalError`. The session became not-rechecked, `sources_verified=False`, `alert_authorization=None`. Manual Re-evaluate afterwards remained **UNVERIFIED**, with no regenerated authorization or current-success UI.
4. Inspected the prior final complete-suite log `%TEMP%\MRC_M32C_rereview_full_suite.txt`: **335 tests, 330 passed, 5 mounted-drive skips, 104.146 seconds**. It was not rerun because this review made no code changes.
5. `git diff --check` passed. Published v1.0.0 artefacts were rehashed and remain unchanged:
   - ZIP: `768759C9961D9027D1A990E678C5581001F151EE2B54AB1C424AB425ED1517D5`
   - EXE: `E232F2074F0F6DFE35EC623C96ED913C4EC570A53B098ABA45F7F74183930E50`

All new executions used synthetic workbooks/temporary databases. No real stock/BOM statistics were repeated; numeric evaluation rules were outside this repair's changes.

## Remaining limitations and recorded follow-ups

- EXCLUSIVE publication can briefly block other reads; waiting/slow I/O may surface a read failure. The fail-closed UI is intentional, but large-volume and slow-disk responsiveness is not established. Session invalidation may wait for the final COMMIT while the publication guard is held; do not describe this as a hard millisecond guarantee.
- Only local session/transaction ordering is verified. Neither finite file checks nor locks prove Google Drive cloud freshness.
- Observed changes remain a read-only historical view, not automatically delivered notifications or recoverable alert episodes. Notifications remain explicitly deferred for later design, not counted as completed here.
- Threshold/units semantics and duplicate/overlapping alert presentation still require business confirmation. Trial warnings remain necessary.
- M4A worker fan-out and synchronous report export remain previously documented P2 follow-ups.
- M3.2C frozen EXE, actual Drive behavior, Windows 10, another PC and physical high-DPI tests were not executed. The real user's schema upgrade was not performed or approved by these synthetic tests.

## Commit boundary

This report supports a local commit only; it does not execute or authorize an automatic push/release. The working tree also contains accepted, uncommitted M4A and the separately authored `DEVELOPMENT_ROADMAP.md`. If the user requests a commit, identify those scopes explicitly, review the exact file list, preserve/exclude unrelated `audit_test_run.txt`, and never include temporary fixtures, databases, real workbooks, binaries or evidence screenshots. Do not start M3.2D until instructed.
