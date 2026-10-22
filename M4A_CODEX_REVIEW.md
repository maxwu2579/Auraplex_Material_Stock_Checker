# M4A — Codex focused acceptance review

Date: 2026-10-21. Base: `d0633fd`; reviewed the current uncommitted M4A sources. No production code, tests, source Excel or real user database was modified. No commit, push, build or release was performed.

## Decision

**GO for a local M4A commit, not a release.** No P0/P1 defect was reproduced. The P2 resource-management finding below is non-blocking for local acceptance, but should be addressed during reliability finalization before broader deployment. Frozen M4A acceptance remains unexecuted.

## Actual checks

- Read `checker/history.py`, `checker/history_ui.py`, M4A tests/reports and the main UI diff. The main diff adds the entry/window lifecycle only. Existing calculation, matching, synchronization, source-export guards, cached calculations, retention code, `queries.py` and schema remain unchanged.
- Independently ran `python -m unittest tests.test_m4a -q`: **23 passed, 0 skipped, 21.602 seconds**. Evidence: `%TEMP%\MRC_M4A_codex_review.txt`.
- Inspected the prior final full-suite log `%TEMP%\MRC_M4A_full_suite_final.txt`: **285 tests, 280 passed, 5 skipped, 203.385 seconds**. Did not repeat the full suite because no code changed during review.
- Independently exercised a true separate-process commit during a history query using a temporary synthetic WAL database. The external process committed a stock-value mutation from 100 to 77 at the `snapshots` checkpoint. The in-progress query returned 100; the next query returned 77. No mixed view was observed. This specifically validates SQLite snapshot isolation under WAL, not another full application import.
- Separately held synthetic queries and invoked Query 20 times: measured 20 simultaneously active query workers. Released them after closing the window: all completed, with zero Tk callback errors. This confirms generation filtering/lifecycle safety but exposes unbounded worker creation.
- `git diff --check` passed. Recomputed the published v1.0.0 ZIP and EXE hashes; both match their protected values:
  - ZIP: `768759C9961D9027D1A990E678C5581001F151EE2B54AB1C424AB425ED1517D5`
  - EXE: `E232F2074F0F6DFE35EC623C96ED913C4EC570A53B098ABA45F7F74183930E50`

## Findings

### P2-1 — Superseded searches/queries keep running without a worker limit

Location: `checker/history_ui.py:218–225`, callers `search()` and `query()`.

Every request starts a new daemon thread. Generation numbers prevent older results from replacing newer ones, but do not stop/coalesce superseded database work. Twenty rapid Query calls produced twenty active workers in a deterministic held-query reproduction. Slow databases can therefore accumulate readers and work; in rollback-journal mode these reads can extend the time a synchronization commit waits. Closing the window suppresses delivery but does not cancel in-flight reads.

Suggested bounded follow-up: one active query plus one replaceable latest pending request, or an equivalently bounded executor with cancellation/progress handling for obsolete work. Preserve main-thread-only Tk access and the existing generation checks. Test bounded concurrency and latest-result behavior; no need to repeatedly run unrelated business tests.

### Additional performance limitation — result caps are not strict scan/memory caps

`history.material_history()` caps returned records/changes, but it enumerates all snapshots in the window and `fetchall()` loads all matching duplicate rows of each version before applying the returned-row limit (`checker/history.py:242`). This does not invalidate totals or displayed quantities, but the 1,000-row result cap must not be described as a strict limit on database work or peak memory. For unusually large duplicate groups or high-frequency imports, consider SQL counts/window counts plus bounded fetching. No large-volume performance benchmark was executed in this review.

## Evidence interpretation and limits

- The existing M4A concurrent synchronization test uses another `InventorySync` instance on another thread in the same process. It demonstrates cross-connection locking and consistent reads; it is not itself a second-process or second-PC test. The ad hoc WAL test above fills the separate-process database-commit case only.
- Read-only and historical labeling, exact candidate separation, Sheet/source isolation, non-comparable cross-source differences, missing/pruned data, coverage, pagination, stale delivery, close handling and compact-window geometry are covered by the 23 passing source tests. No claim that finite tests cover every interleaving is made.
- Missing stock payload currently produces NOT RETAINED and a maintenance explanation based on row-count mismatch. This safely avoids reconstructing missing values, but a mismatch alone cannot prove cleanup rather than manual deletion/corruption was the cause. Treat that causal wording cautiously when diagnosing a damaged database.
- No M4A frozen EXE, real Drive, second PC, Windows 10 or physical high-DPI acceptance was performed. The pre-existing v1.0.0 artefacts were hashed only, not used as M4A executables.
- The user's actual database and source workbooks were not opened. Ad hoc failure/mutation checks used temporary synthetic fixtures and were cleaned by their temporary-directory lifecycle.

## Next handoff

M4A source acceptance is complete subject to the documented non-blocking limitations. Local commit still requires the user's instruction. Preserve `audit_test_run.txt`; `DEVELOPMENT_ROADMAP.md` is the separately authored approved plan, not an accidental M4A code file. Do not automatically start M4B. The roadmap's next implementation milestone after M4A is M3.2C automatic stock alerts, with MIN QTY discovery/validation before threshold logic; the robot/chat and three-language requirements remain in M4E.
