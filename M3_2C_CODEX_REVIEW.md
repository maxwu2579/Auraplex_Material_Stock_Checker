# M3.2C — Codex acceptance review

Date: 2026-10-21. Reviewed the uncommitted M3.2C implementation on top of `d0633fd` and the accepted, uncommitted M4A work. This review changes no production code, tests, real workbook or real database. No commit, push, release, upgrade of the user's database or M3.2D work was performed.

## Decision

**NO-GO for a local M3.2C commit pending the three P1 fixes below.** The normal rules and existing tests pass, but independent synthetic reproductions demonstrate failure/freshness races and source-scope identity loss. Passing the full suite does not override these failures.

No P0 was established. Two P2 items also need an explicit disposition. Missing original requirements are reproduced below so the next repair session has them in the repository.

## Validation performed

- Read alerts/query/persistence/runner/UI code, explicit upgrade code, reader/sync/schema/reconstruction/retention/cache changes and M3.2C tests/reports.
- Independently ran `python -m unittest tests.test_m32c -q`: **24 passed, 0 skipped, 6.599 seconds**. Evidence: `%TEMP%\MRC_M32C_codex_review.txt`.
- Inspected `%TEMP%\MRC_M32C_full_suite.txt`: prior full suite **309 tests, 304 passed, 5 skipped, 253.816 seconds**. Not repeated during this review. The five mounted-drive tests remain unexecuted here.
- Independently executed the race, source-switch, delayed-completion and provenance-pruning probes described below. All inputs used existing synthetic test fixtures and temporary databases. No real workbook or production database was opened.
- `git diff --check` passed. No existing tests were weakened in this review. Actual M3.2C EXE, real Drive, second PC, physical high-DPI and Windows 10 were not tested.

## P1-1 — A sync failure between evaluation and publication can still resolve alerts

Location: `checker/alerts.py:274–326` (`AlertService.run`).

`verified` is calculated from freshness read earlier plus a boolean supplied by the caller. Under `BEGIN IMMEDIATE`, the code rechecks current source-version IDs but does not recheck the latest sync/failure state. A failed sync does not change those version IDs.

Independent reproduction, using `tests.test_m32c.AlertEvaluationTests` fixtures:

1. Run a verified evaluation with material B below its threshold.
2. Publish a new stock version where B is above its threshold.
3. At the alerts write-connection boundary, after the evaluation read closes, remove the synthetic stock file and run an actual sync. This records `Source File Unavailable` without changing the current version IDs.
4. Continue `service.run('race', True)`.

Observed: database stock state **Source File Unavailable**; alert evaluation **COMPLETED**, `verified=True`, `resolved=1`; B becomes **RESOLVED**. This directly violates “sync failure must not resolve old problems”.

Required fix: bind evaluation authorization to concrete source paths, version IDs and verification/sync observations, not just a session boolean. Recheck the relevant freshness/run identity under the publication lock, including failure-only changes. Session-observed unrecorded failures need invalidation even if SQLite still holds success. A stale/failed authorization must produce no resolution/upsert of current alerts; retry must not silently reuse old verification for newly published versions.

## P1-2 — A late successful result removes a newer failure warning

Location: `checker/ui.py:608–711` and `checker/alerts_ui.py:242–285`.

The alert runner delivers `(result, error)` without an application/source generation. `_drain_alert_events()` uses `result.verified` to render the label even if a later main-app sync has failed. `_note_sync()` only appends a warning when the label already contains “active”; it does not replace “evaluating…” on failure. The alert window's basis uses only persisted alert-evaluation records and does not incorporate current session sync failures.

Independent reproduction with `AlertUiTests` fixtures:

1. Import both synthetic files and obtain two active verified alerts; open Stock Alerts.
2. Let a real `AlertService.run` complete and commit, but hold its return to the worker queue.
3. Remove the synthetic stock file and execute a failed Refresh in the main app.
4. Release the earlier successful alert result.

Observed: after failed Refresh the label remained **Stock Alerts: evaluating…**; after the old completion it became **Stock Alerts: 2 active**, with no “not re-checked”. `sources_verified()` was **False**. The window's first line still said **Basis: verified evaluation #2 ...** and contained no unverified/not-rechecked/out-of-date warning.

Required fix: immediately invalidate alert verification on source selection, a newer sync/check, failure, database-status read failure and startup before source checks complete. Tag background status/evaluation messages with a generation and source/version context; obsolete messages cannot remove a failure warning. Overlay the current invalidation on both the entry and the open/reopened alert window. Old persisted alerts remain visible as historical/not re-checked, without falsely resolving them. Do not change the main CHECK's independent direct-Excel safety rules.

## P1-3 — De-duplication merges alerts from different warehouse files

Location: `checker/alerts.py:100–102` (`Alert.key`) and `AlertService.run` existing/upsert/resolve scope.

The key contains type, subtype, Sheet and material/row, but no source file. Existing rows are updated and absent keys resolved globally. Switching from one warehouse file to another with the same Sheet and ID therefore reuses the old alert identity; querying a different source can also mark an old source's alert resolved without checking it.

Independent reproduction:

1. Evaluate a synthetic warehouse with A=0.
2. Copy the synthetic workbook to a different absolute file path; import that file as the newly selected stock source.
3. Evaluate again.

Observed: import **IMPORTED**, `new_alerts=0`; A has the **same alert key and first_seen**, while its stock version is rewritten from **1 to 3**. Source-specific provenance and notification identity are merged.

Required fix: include normalized source identity in alert scope (Storage path; relevant BOM source identity for BOM-coverage alerts). A source's absence from a different evaluation scope cannot mean recovered. Distinguish scope change/inactive history from genuine recovery. Retain source-specific first/last-seen and episodes, and migrate/handle existing schema-2 alert keys safely. Never use the source-version ID alone as identity, because normal new versions of the same source must still deduplicate. Test file switching, same Sheet/ID across files, switching back, normal new-version deduplication and BOM-source changes.

## P2-1 — Automatic evaluation pruning removes live alert provenance

Location: `checker/alerts.py:337–342` and `load_state()`.

Pruning keeps only the latest 200 evaluation rows, regardless of whether active alerts or the last successful basis depend on older rows. Failure inserts through `_record_failure()` do not call this pruning at all.

Independent reproduction with `KEEP_EVALUATIONS=3`: one COMPLETED evaluation followed by four UNVERIFIED evaluations leaves **14 active alerts**, but `load_state().latest_completed is None`. `first_evaluation_id`/`last_evaluation_id` have no foreign keys and can point to deleted evaluations. The current UI consequently loses the verified basis for retained alerts. Conversely repeated read failures may grow evaluation history indefinitely.

Required follow-up: preserve at least the latest successful basis and evaluation metadata needed by retained active/current alert records; bound routine/failure history consistently without deleting required provenance. Document alert-retention rules separately from the existing inventory/log retention policy. Do not solve this by pruning real user data during development.

## P2-2 — Original functional requirements are not all implemented

The original M3.2C instruction in this conversation required identifying **observed stock changes**, a **stock-change filter**, and **Storage Sheet/material filters**. Current code offers the five supplementary alert types and only Type / Show resolved filters. There is no independent observed-change alert/view path in Stock Alerts, no material search/filter and no Sheet selector. The supplement defines the five stock/data categories but does not explicitly cancel those original requirements.

The original also required a threshold shortfall when values are valid/comparable, and full provenance. Alert details currently carry no source file path, Rack/Level are not shown in `_show_row`, and no explicit threshold-shortfall field is rendered. Evaluation summaries retain filenames/versions, but that is not the same as complete per-alert source detail, especially after a scope switch.

Required disposition: implement the missing original scope or obtain an explicit user decision to defer it; do not label the entire original instruction satisfied based only on the supplement. Observed changes remain historical differences, never consumption or a production-order shortage. Any observed-change notifications need bounded, version-specific event deduplication; reuse M4A/snapshot data instead of reparsing Excel. Keep unverified/stale data visibly separate.

## Original safety requirements available for the repair session

- Exact roles: `LOCATION MAP AURA - MASTER` is Storage; `MASTER BOM LIST- AURA` is BOM. Paths remain user-selectable. `MIIN QTY` and `MIN QTY` are explicit aliases only.
- Valid unique stock 0 is OUT_OF_STOCK, not proof of an order shortage. Stock below a valid threshold is a trial LOW_STOCK; equality is not low. A numeric threshold 0 is preserved, not “alerts off”. Blank/invalid thresholds are not zero.
- A BOM ID absent from the selected warehouse scope is unknown stock, not verified stock 0. Duplicate/invalid rows remain data issues and retain raw values; no merging or summing. Existing M2 ASSUMED 0 calculations remain unchanged.
- De-duplicate repeated unchanged problems **within the same source/Sheet/material/rule scope**; distinguish new issues, substantive changes, recovery and recurrence. Never recover issues on a failed/unverified read or from a different source scope.
- One worker plus one latest pending request; no stale-result restoration. Always show Cloud Not Verified; historical cache data never becomes current-stock verification.
- Local read-only source files; no inventory edits, API, email, scheduling, M3.2D or M4B. Fault/migration tests use synthetic files and temporary databases only. Explicit backup/consent for schema upgrade; protect earlier M3.1/M3.2/M4A safeguards.

## Repair handoff for Claude Code

Read this report plus the implementation/test reports and `DEVELOPMENT_ROADMAP.md`. Preserve the current uncommitted M4A, roadmap, review files and unrelated `audit_test_run.txt`.

1. Fix P1-1, P1-2 and P1-3 with deterministic regression tests reproducing the scenarios above. Cover an unrecorded failure, same-version recorded failure, delayed status load/completion, restart and source/BOM switches.
2. Address the two P2 items or explicitly document unresolved scope for user decision. Do not silently broaden the approved inventory retention policy.
3. Keep upgrade transactional and backed up. If alert identity/storage changes require a migration, ensure existing schema-2 databases are handled explicitly and tested; no silent destructive reset.
4. During repair run the affected tests only. Once final shared code is ready, run one complete suite and report counts; no repeated full runs without new failures/changes.
5. Update README and implementation/tests reports; deliver `M3_2C_REMEDIATION_REPORT.md` with before/after evidence and any remaining limitations. Do not call unexecuted packaged/real-Drive checks passed.
6. Do not commit, push, publish, upgrade the real database or begin the next milestone. Stop for Codex re-review.
