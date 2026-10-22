# M3.2C — Codex remediation re-review

Date: 2026-10-21. Reviewed the current uncommitted schema-3 remediation against `M3_2C_CODEX_REVIEW.md` and `M3_2C_REMEDIATION_REPORT.md`. No production code or tests were edited, no real source workbook/database was opened, and no commit/push/release or next milestone was started.

## Decision

**NO-GO for a local M3.2C commit: two P1 gaps remain.** The changes fix the original pre-write failure race and delayed-success example, but authorization is not protected through transaction publication and some database-read failures still leave verified session UI/authorization intact. No P0 was established.

| Prior finding | Re-review |
| --- | --- |
| P1-1, failure after evaluation read | Original boundary test passes; PARTIAL overall because invalidation during the ensuing write transaction still commits recovery |
| P1-2, late success clears failure warning | Original delayed-completion/status-read scenarios pass; PARTIAL overall because alert-window read errors do not invalidate the session |
| P1-3, source identities merged | PASS for covered Storage/BOM switch, switch-back, same-file version and schema-2 attribution cases |
| P2-1, provenance pruning | PASS for latest per-scope verified basis, retained alert references and failed-attempt bounds |
| P2-2, missing original scope | Filters, observed-change view, threshold shortfall and provenance implemented and tested. Observed-change notifications explicitly remain deferred/unimplemented; do not claim those complete |

## Executed verification

- Read the actual source for SessionGate/Authorization, evaluation/publication, per-source resolution, pruning, the UI invalidation/runner/status paths, observed-change view and explicit schema-1/2→3 upgrade.
- Ran `python -m unittest tests.test_m32c tests.test_m32c_remediation -q`: **41 tests passed, 0 skipped, 20.637 seconds**. Log: `%TEMP%\MRC_M32C_rereview.txt`.
- Inspected the previously completed final log `%TEMP%\MRC_M32C_remediation_full_suite.txt`: **326 tests, 321 passed, 5 mounted-drive skips, 141.015 seconds**. Did not repeat that full suite.
- Independently injected a failure after source attribution, just before COMMIT, during a synthetic schema-2→3 upgrade with an existing evaluation and alert. The database's complete logical digest and `user_version=2` remained unchanged: **PASS**.
- Independently reproduced both remaining gaps below using temporary synthetic fixtures. `git diff --check` passes. No M3.2C packaged EXE, real Drive, second PC, Windows 10 or physical DPI test was executed.

## P1-R1 — Session failure after the gate check still commits a verified recovery

Location: `checker/alerts.py`, `AlertService.run`, approximately lines 382–440.

`still_valid()` is checked once before `alert_evaluations` insertion and all alert upserts/resolutions. A newer session failure/selection can invalidate the gate after this check while the worker is still writing. The SQLite lock serializes database writers, but does not serialize `SessionGate.invalidate()`. There is no final gate check or coordinated publication guard before COMMIT.

Independent reproduction:

1. Use the `AuthorizationTests` synthetic fixture, where B has an active LOW_STOCK issue.
2. Publish the corrected stock and obtain an authorization for its version and current gate generation.
3. Wrap the actual alerts write connection with a SQLite trace callback. At the first `INSERT INTO alert_evaluations`, invalidate the SessionGate, representing a session-observed failure that cannot be recorded in SQLite. This is after the first `still_valid()` check, before alert recovery and COMMIT.
4. Complete the real `service.run(..., lambda: gate.valid(granted.generation))`.

Observed:

```text
invalidated_after_initial_gate_check = True
authorization_still_valid = False
outcome = COMPLETED
resolved = 1
B_status = RESOLVED
```

The UI may now retain its warning because generation delivery is guarded, but persistent alert data has already been incorrectly recovered. This is a remaining P1-1 data-integrity failure.

Required repair:

- Ensure verification remains authorized at the transaction's actual publication point. Invalidation before publication must prevent/roll back verified upserts and recovery.
- Coordinate final authorization validation with COMMIT using an explicit, short publication guard or equivalent linearization mechanism. Adding another uncoordinated boolean check leaves a smaller race; do not claim it closes publication ordering entirely.
- Establish consistent lock ordering; do not hold the gate lock while waiting for a SQLite write lock or performing a long evaluation/backup. Avoid deadlocks and long Tk-thread blocking.
- Add regression injections after evaluation insertion, during upsert/recovery, and immediately before COMMIT. Assert that an invalidated transaction cannot publish COMPLETED recovery; prior active alerts remain intact and the runner retry is bounded/unverified until genuinely reauthorized.
- This is local transaction/session ordering only. No finite file check or lock proves absolute cloud freshness.

## P1-R2 — Alert-window read failure leaves the session verified

Locations: `checker/alerts_ui.py:_alerts_loaded`, `checker/ui.py:_invalidate_alerts` / `alert_authorization` and background status error handling.

Independent reproduction:

1. Use `SessionUiTests.current_session()` to obtain a verified evaluation and open Stock Alerts.
2. Patch `alerts.load_state` to raise `sqlite3.OperationalError('synthetic database read failure')` for a real background window reload.
3. Wait for the error to be delivered through the window's worker queue.

Observed:

```text
query_failed_visible = True
app_alert_current = True
session_text = Re-checked in this session: the alerts of the current files come from a verified evaluation ...
gate_invalidated = False
```

The body clears results and reports the read failure correctly, but the fixed session line and main alert verification remain successful. `_drain_alert_events` also ignores background `alert_status_events` read errors. These paths do not satisfy the reported promise that database read failures immediately invalidate alert verification throughout the UI.

Related authorization gap: `_invalidate_alerts(reason)` increments the gate and sets `alert_current=False` but leaves the per-role verification evidence intact. In a direct synthetic check, `sources_verified()` remained True and `alert_authorization()` immediately reissued an authorization with the new generation without another source check. Error recovery must not merely stamp historical evidence with a new generation when that evidence has been invalidated.

Required repair:

- Route alert-state/status read failures to the owning session invalidation on the Tk thread; show NOT RE-CHECKED / database-read failure consistently in the fixed session line and main entry, not only the cleared table body.
- Make invalidation of verification evidence explicit. After a read/failure event requiring new source verification, manual Re-evaluate alone cannot regenerate a verified authorization from old role/path/version facts. Require the appropriate new successful source checks before permitting COMPLETED recovery.
- Preserve the actual inventory rows, active alert records, Excel inputs and historical basis; failure means unknown, not deletion or zero.
- Cover window read failure, delayed status-read failure, reopening the window, manual Re-evaluate after failure, and successful Refresh recovery. Historical counts may remain visible only with the failure/unverified qualification.

## Remaining non-blocking limitations

- Observed changes are a historical view only; automatic observed-change notifications are not implemented and must stay explicitly listed as deferred. They should not be modeled as recoverable low-stock issues without a separate event design.
- M4A history worker fan-out remains the previously documented P2 outside this patch scope. Existing synchronous export responsiveness and deployment/physical DPI limitations remain open.
- Numeric rules, zero/blank distinctions, duplicate handling and same-row threshold trial assumptions remain as reported. Business confirmation is still pending; this review does not convert trial thresholds into approved warehouse policy.

## Bounded next repair task for Claude Code

Repair only **P1-R1 and P1-R2** above. Preserve the accepted source-scope, migration, provenance and filtering fixes. Read this file together with `M3_2C_CODEX_REVIEW.md`; the latter contains the original requirements reconstructed from the conversation and is now present in the repository.

Use deterministic synthetic regression tests; no real workbooks/database, no new dependencies. Run affected tests during repair and one final full suite after shared source changes are final. Do not repeat passing full suites without a new change/failure. Update the remediation report with each injection boundary, rollback results, manual re-evaluation authorization behavior and any remaining limitation. Do not commit/push/publish, upgrade the real database or start another milestone. Stop for re-review.
