# Secondary Windows Localisation — Completion and Source Self-Review

Date: 2026-10-23
Baseline: ba8c9aa plus the uncommitted localisation slices documented in the History, Alerts and Analytics/Daily reports.

## Decision

**Source self-review PASS within the scope below.** No remaining P0/P1 was identified in the examined localisation/close-boundary paths. This is an author self-review with fault injection, not an independent audit or packaged acceptance. No commit was made. Independent peer review remains advisable for the combined patch.

## Localisation completed in this step

Cache selection, Local History cleanup and database-upgrade dialog titles, consent framing, preview fields, counts, safety explanations, backup/result notices and busy notices now follow Chinese / EN / BM. Preview descriptions are rendered from immutable Snapshot/Plan/UpgradePlan fields, without parsing or substituting text inside paths or original values. English descriptions call their original describe() functions unchanged.

All confirmations still default to No. No cleanup, upgrade or cached authorization is triggered by language switching. Retention policy remains 12 calendar months / 90 days / 180 days with the same protected snapshots, trend baseline, latest attempt/success logs, source headers, BOM history and material registry. Backend preview/apply/backup/transaction logic is untouched.

The four secondary windows now follow the main selector. Actual source names, Sheet names, IDs, values, timestamps and canonical safety/status codes remain original. Daily on-screen framing is translated; saved HTML/JSON remain the existing English report format, explicitly disclosed in the window.

This is not exhaustive translation of original query/evaluation/detail narratives, raw backend diagnostics, every tooltip or native operating-system dialog control. Those are not rewritten through text substitution.

## Findings reproduced and repaired

### P2-CLOSE-1 — Cached consent callback after application close

Before repair, a synthetic default-No dialog hook closed the app and then returned True. The callback set cache_authorized=True and attempted to update a destroyed combobox, producing an invalid-command Tk callback error. It did not persist consent or modify stock, but violated the closed-session boundary.

Repair: the affirmative callback now checks self.closed before enabling cached mode, matching the existing cleanup/upgrade guards. The new regression reproduces the same sequence and asserts no authorization, no selection and no Tk callback error after close.

### P2-LIFE-1 — Closed History/Alerts retained by callbacks and worker closures

A real synthetic History window was closed, references dropped, and garbage collection deliberately run on a background thread while the master app remained alive. Four ignored Tk Variable finalizer RuntimeErrors were captured. This establishes a window-lifetime path; it was not solely an assumed test-fixture issue.

Retainers included the History lane's bound start callback, background functions retaining the UI through self, and a newly added recursive localisation-label visitor retaining itself and its window in closure cells. The visitor cause was directly identified with gc.get_referrers. The recursive visitor was introduced during this uncommitted localisation work; it is now corrected.

Repairs:
- History uses partials with plain database/query arguments and worker-local event queues. On close, pending work stops and the lane releases its bound start callback.
- Alerts workers capture only database path, include/days values and their queue, rather than the window.
- History/Alerts/shared localisation label discovery uses iterative traversal, eliminating the recursive closure cycle.

New tests force collection off the UI thread, including while real reads are held across close. Closed windows become collectible without worker-thread Tk finalization; late events remain unapplied. Existing bounded-worker and closed/pending-request checks remain intact.

### P2-LIFE-2 — Analytics/Daily variable traces retain destroyed windows

An Analytics window remained alive after close and forced collection because its option-variable Tcl traces still referenced its bound callback. Daily used the analogous date-variable trace.

Repair: both windows store the trace IDs they create and remove only those traces on close, on the UI thread. Existing cancellation/runner close behavior is retained. The new lifecycle test verifies both windows release their references with no captured background finalizer error. This does not audit every Tk owner elsewhere in the application.

## Checks actually run in this step

The final observed results cover **16 distinct passing tests**: 9 new checks and 7 selected existing regressions. They were run in affected batches, not one full suite.

| Run | Result | Time |
| --- | --- | --- |
| Initial 5 maintenance tests + 3 existing cache/cleanup/upgrade checks | 7 passed, 1 failed | 6.890 s |
| Initial 2 lifecycle checks + corrected cache check + 2 bounded-history regressions | 3 passed, 2 failed | 14.648 s |
| Repaired History/Alerts lifecycle checks | 2 passed | 1.450 s |
| Analytics/Daily trace-lifetime reproduction | 1 failed before repair | 0.717 s |
| Same trace-lifetime test after repair | 1 passed | 0.668 s |
| Four-window integration + existing Analytics Stop/close and Daily close-during-generation checks | 3 passed | 3.643 s |

Initial maintenance failure was a new test expecting the full CACHED DATA / UNVERIFIED string in a compact, ellipsized badge. The corrected assertion checks the full warning in the status plus the CACHED badge, preserving the authorization/UNVERIFIED assertions. No product behavior was changed to satisfy that layout assumption.

The lifecycle failures were real implementation issues and were fixed, not skipped or suppressed. New lifetime tests install an unraisable-exception recording hook while the master Tk interpreter remains alive; they assert zero captured finalizer errors. GC disabling is temporary during deterministic reproduction and is restored afterward, not used to hide production errors.

The standalone unsafe-state reproduction/introspection scripts are diagnostic evidence and are not counted as passing acceptance tests.

Coverage includes:
- All three languages preserve preview paths, source versions, UTC times, count values and equivalent formatting placeholders.
- Cache, cleanup and upgrade confirmation defaults stay No; declining writes no backup or database change.
- Existing actual synthetic cleanup/backup, schema-upgrade flow, and offline UNVERIFIED CHECK/export regressions passed.
- Four open windows switch together without invoking new read/analyze/generate calls or changing session authorization/generation.
- Rapid History work stays bounded and pending work never starts after close.
- Running History/Alerts reads do not retain a destroyed window; late work cannot update it.
- Analytics/Daily close during running work retains the existing cancellation and late-result protections.

No full suite or prior localisation/R2 suites were repeated. git diff --check and syntax/new-file whitespace checks passed.

## Preserved files and limits

Git comparison against HEAD confirms no edits to core.py, analytics.py, daily.py, alerts.py, inventory_db.py, sync.py, queries.py, providers.py, agent.py, report.py, cached.py, retention.py or upgrade.py. UI lifetime changes are limited to close/callback ownership and do not change those business modules.

audit_test_run.txt remains unchanged, SHA-256:
307AA1DF2B507A48D936081F35F0F5367FDC9168AEF1E4EC490A4117A96CE7EC

Only synthetic workbooks/temp SQLite/report folders were used. No real database/workbook, Drive, API, credential access, installed scheduled task, email sending, EXE packaging, screenshots/native-DPI matrix, second PC or Windows 10 acceptance. A complete main-process shutdown/GC audit is outside this window-local scope. Earlier small-window checks are geometry/font-scaling checks, not visual acceptance.

No commit, push, package or release. Remaining product work: review/commit this combined patch, optional remaining detail/tooltip localisation, M4F purchase-review/real notification features if retained in scope, and real-provider/Drive/security/packaged delivery acceptance. RAG remains optional.
