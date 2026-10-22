# M4C P2 focused remediation — pending Luna review

Date: 2026-10-22. Base commit: `434357d`. Implemented locally; not committed, pushed or released.
This is implementation evidence, not independent acceptance. M4D has not started.

## Scope

Only production file changed: `checker/agent_tools.py`. Regression cases are in `tests/test_m4c.py`.
No changes to M2 calculations, analytics rules, database schema, synchronization, UI or source workbooks.

### P2-1: Preserve the remaining time budget

`InventoryTools.call` passes its original absolute deadline into `_execute`. Immediately before calling
`analytics.analyze`, `_execute` calculates the remaining budget; a non-positive remainder refuses the call.
The remaining budget and original cancellation event are passed to analytics. Analytics no longer receives
a fresh default five seconds after metadata and prechecks. Its removal of the SQLite progress handler is
followed by restoration of the caller's original deadline/cancellation handler, including on exceptions.

The existing limits remain cooperative, not hard real-time: SQLite lock waits, Python scheduling and the
final separate basis read are not preemptible. No new timeout or cloud-freshness guarantee is claimed.

### P2-2: Restrict ownership validation to selected history

Select the same inclusive start/end window and last pre-window reference used by the history/analysis query.
Fetch at most 401 window snapshots to enforce the existing 400-snapshot limit; retain the 50,000-row limit.
Validate ownership only for selected source-version IDs, using two indexed EXISTS branches:

- Selected rows must reference an existing Sheet belonging to their own version.
- Selected Sheets must not have foreign-version rows attached, even if the row declares an out-of-window version.

Unrelated older payload corruption is outside this query's validation scope. Selected-window/reference
corruption still fails closed. This is scoped validation, not a full database-integrity audit.

`EXPLAIN QUERY PLAN` on synthetic history confirmed `stock_records_key`, the per-version Sheet unique index
and `stock_records_sheet` are used. No full `stock_records` scan appeared in either ownership branch.
Snapshot selection/metadata may still inspect snapshot metadata; this patch removes the full payload precheck.

## Checks performed

Seven targeted tests passed in **0.676 seconds**:

- Five new regression tests: remaining budget/event forwarding; actual analysis deadline exhaustion; unrelated
  old payload excluded while window/reference remain; selected reference/window orphan rejection; foreign old
  rows attached to a selected Sheet rejected.
- Two existing safety tests: concurrent WAL publication rejects old stock; attempted writes through the
  read-only connection are rejected and the database hash remains unchanged.

The initial targeted run had one fixture failure: synthetic timestamps used ISO format instead of the
database's canonical timestamp format. Corrected the fixture; the final seven-test run above passed.
`git diff --check` passed. Only temporary synthetic workbooks/databases were used.

## Luna handoff

Review the diff against `434357d`, reproduce near-deadline and selected-reference/foreign-Sheet cases,
and check cancellation, workload limits and unchanged historical result semantics. Suggested focused run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_m4c tests.test_m4b -q
```

The full suite, packaged EXE, real workbooks/database, Google Drive and large-history timing benchmark were
not run. Existing `audit_test_run.txt` is untouched. No dependency installation, commit, push or release.

## Follow-up regression before local commit

At the user's request, ran the focused M4C/M4B command above: **73 tests passed, zero failures,
8.696 seconds**, exit code 0. No production code changed after this run. This adds regression evidence;
it does not constitute packaged acceptance or a separate independent code audit. The user subsequently
authorized a local commit of the two P2 fixes, tests and this record. Push and release remain separate.
