# Reliability R2 — Independent Codex Review

Date: 2026-10-23
Baseline: 7c9b90c
Current decision: **GO for local commit after targeted remediation re-review below.** The initial NO-GO findings are retained as historical evidence. This is not release acceptance.

## Scope and evidence

Inspected the actual changes in app.py, checker/ui.py, checker/report.py and checker/cached.py, the new regression tests, and implementation documentation. This is a targeted source review, not packaged acceptance.

Executed once:
- `python -m unittest tests.test_reliability_r2`: **8 passed**, 17.900 s. Includes isolated self-test subprocesses and normal/cache export scenarios.
- Two independent synthetic fault injections: **2 reproduced defects**, 2.016 s. These checks assert the observed unsafe behavior; they are not passing product acceptance tests.
- `git diff --check`: passed.

Did not rerun the reported 47 export regressions or any full suite.

## P1-R2-1 — Cancellation and publication are not serialized

Locations: checker/report.py:244–248; checker/ui.py:1476–1481.

The final cancellation check and os.rename are separate operations on the worker. The Tk thread can invalidate the result or revoke cache authorization after the check and before publication. No common publication/cancellation lock protects this interval.

Independent reproduction:
1. Used ExportBase synthetic workbooks and a real CHECK result.
2. Wrapped the real os.rename with a barrier immediately before calling it. The target did not exist at this point; staging and final validation had completed.
3. On the Tk thread changed production quantity to 2, observed task.cancel.is_set() == True, then released the barrier.
4. The actual rename published r2.xlsx after cancellation. The UI correctly refused to attach it to the current result (accepted=False), but displayed st_export_late, despite cancellation having preceded actual publication.

This is different from the existing test that calls the real rename first and then injects cancellation. That existing post-publication behavior is correct and should remain.

Impact: invalidated tasks can still publish files, contrary to the specified pre-publication cancellation contract. The same shared writer serves normal and cached exports. No source Excel was changed and no current-result success indicator was restored in this reproduction.

Requested repair: define one serialized publication/cancellation boundary shared by invalidation and final publication. Cancellation winning that boundary must prevent publication; publication winning must preserve the completed file and report its ownership accurately. Preserve final source/cache validation and no-overwrite behavior. Do not broaden filesystem work held under a UI-sensitive lock unnecessarily. Add one deterministic pre-publication concurrent-cancellation test and retain the post-publication test.

## P2-R2-2 — Cancellation hides cleanup failure

Locations: checker/report.py:258–268; checker/ui.py:2054–2063.

The writer correctly attaches cleanup_warning to the original exception if staging-file deletion fails. However, _export_finished handles cancellation/stale ownership before examining the error and immediately returns, dropping that warning.

Independent reproduction:
1. Held real report generation, changed quantity to cancel, then resumed.
2. Injected PermissionError only for removal of this task's .mrc-export- staging file.
3. One staging file remained. No error dialog appeared, and the status contained only the generic cancellation text, with no residual path or cleanup failure.
4. Removed this synthetic leftover after restoring normal deletion.

Impact: users are not told that a temporary report remains, potentially containing report data. A stale task must not clear or replace a newer result, but its cleanup failure still needs an explicit notification containing its own path and original error.

## Confirmed behavior and limits

- Worker export code sends events through a queue; inspected worker does not directly operate Tk.
- Single-export admission and tested ordinary cancellation, cache revocation, error cleanup, successful report content and post-publication preservation passed the new tests.
- Self-test subprocesses passed: missing output directory creation, successful exit 0, unusable output/result path exit 2. These tests do not establish all possible I/O failure behavior.
- The 180-second self-test timeout is a Tk callback, not a hard process deadline. A blocked Tk callback cannot run it, and a non-daemon export worker can keep the process alive until an uninterruptible step returns. The documented graceful-shutdown limitation should not be described as a universal hard exit guarantee.
- No broad M2/parity acceptance was independently rerun; source calculation rules were outside this patch's intended scope.
- No real company workbooks/databases, API, Drive, packaged EXE, disk-full/ACL experiment, physical DPI or second PC were used.
- audit_test_run.txt SHA-256 remains 307AA1DF2B507A48D936081F35F0F5367FDC9168AEF1E4EC490A4117A96CE7EC.
- No production code modified by this review. No commit, push, package or release.

## Next step

Repair P1-R2-1 and preferably P2-R2-2 together. Independently rerun only the two repaired boundary reproductions plus the affected R2 export tests; do not repeat the full suite or 47 regressions absent further shared changes. R2 remains uncommitted.

## Remediation re-review — 2026-10-23

**Decision: GO for a local Git commit of Reliability R2.** No new blocking finding in this targeted review. No commit was performed.

### P1-R2-1: PASS

Inspected Cancellation.publishing/cancel and the main-window task integration. The real application now passes a per-task Cancellation object through normal and cached export paths. Final publication checks cancellation and executes the no-overwrite rename/link while holding the same lock used by cancellation. The published path is recorded before releasing that lock. Failed publication releases the lock without recording publication; name conflicts retain the bounded retry loop.

Cancellation winning the lock prevents publication. Publication already holding the lock wins; concurrent cancellation waits for that one publication operation, and completion treats the report as belonging to the earlier result. Generation, workbook save and source/cache validation are outside the lock. This is an explicit serialized publication boundary, not an assurance that a filesystem rename is instantaneous or cloud data is current.

A plain Event remains supported by the low-level optional callback API with weaker cancellation semantics; the reviewed main-window export paths use Cancellation, not a plain Event.

### P2-R2-2: PASS

The stale/cancelled completion branch now retains the cancellation/earlier-result status while adding cleanup_warning to the status and an error dialog. Original error, residual path and cleanup reason are included. It does not restore the previous result or success panel, and deletion remains restricted to this export's staging file.

### Independently executed, once

- PublicationBoundaryTests: 3 tests (cancellation first, publication first, cancellation plus cleanup failure).
- CachedExportTests.test_revoking_cache_authorisation_after_the_final_check_prevents_publication: 1 test.
- ChangeDuringExportTests.test_a_change_after_publication_keeps_the_file_but_not_as_the_current_export: 1 test.
- **Total: 5 passed, 4.785 seconds.** Used synthetic workbooks and temporary directories. No full suite or 47-test export regression repeat.
- git diff --check: passed.
- audit_test_run.txt SHA-256 unchanged from the initial review.

The initial review's 8-test run, including self-test subprocess checks, predates remediation and is not recounted as a new run. Current self-test documentation accurately distinguishes the Tk timer from a hard process deadline.

Remaining limitations: one slow rename may delay cancellation on the Tk thread; an uninterruptible worker step may delay shutdown; no packaged EXE, real data, Drive, network target, disk-full/ACL, physical DPI or second-PC acceptance was performed. No production code changed during re-review; no commit, push, package or release.

The initial Next step section above is historical and superseded by this GO decision.
