# Reliability R1 — Codex independent focused review

Date: 2026-10-23. Baseline: local HEAD `1219182` plus the uncommitted R1 changes.

## Decision

**GO for a local source commit.** P2-L10N-1 and the M4A per-window worker fan-out follow-up are resolved within the stated scope. No new P0/P1/P2 finding was identified in the inspected changes. The two-slot lane variation is accepted as a bounded alternative; it does not require architectural rework.

This review did not modify production code or tests. It adds this report and updates roadmap review status only. No commit, push, packaging, release or real API call was performed.

## Implementation inspected

- `set_language` separates explicit preference-save retry from language-change listeners. Same-language selection saves only the preference and refreshes its warning. Atomic save and the source-path settings implementation are unchanged.
- Each History window owns three `_Lane` instances: Sheets, search and query. Each has at most two outstanding executing jobs and one replaceable pending request. A new request cancels older jobs cooperatively; its generation remains the delivery authority. There is at most one non-cancelled current request per lane; when both slots are occupied the latest request waits, replacing the preceding pending request.
- Thus the cap is **per window**, up to six executing reads across three lanes and three pending requests, not two threads for the whole application. Closing/reopening a window can briefly overlap old reads that have not yet returned; this is not a process-wide/global worker pool.
- Slots are released by the Tk polling thread, including for obsolete results. Workers perform reads and queue messages, not Tk updates. Close clears pending work, signals running reads and cancels polling/debounce callbacks. Closed-window search/query handlers return without submitting work.
- Opt-in cancellation uses a `ContextVar` scoped to the worker, an execute wrapper, and SQLite progress checks every 1,000 VM steps. Its token resets in `finally`; the read connection closes in `read_view`'s existing `finally`. Ordinary callers outside that context keep the original raw-connection path and exception semantics.
- Database URI read-only access, transaction/snapshot checks, data origin, caps and paged rendering remain in place. No calculation or database-schema change was found.

## Independent tests and probes

The developer-reported 34 regressions, larger B1 groups and full suite were not repeated.

1. `python -m unittest tests.test_reliability_r1 -q`: **7 passed in 10.124 seconds**. Exercises same-language recovery, bounded bursts, latest selection, cooperative interruption, closing, and error recovery using synthetic data and fake slow reads.
2. Independent real SQLite-lock probe on a **temporary synthetic database**: held `BEGIN EXCLUSIVE` on a separate writer connection while running two reader threads. One reader had an opt-in cancel event; the other did not. The cancelled reader returned `HistoryCancelled` in 2.906 seconds and the ordinary reader returned `HistoryReadError` in 2.875 seconds. Both threads finished. No production database was involved.
3. Rolled the writer back, then read the database again: `PRAGMA integrity_check` returned `ok`, with no snapshots introduced by the probe.
4. Entered an already-cancelled context on the main probe thread and confirmed refusal; after leaving it, a normal `read_view` succeeded. This independently checks that cancellation state does not leak into later ordinary callers.

`git diff --check` passed. All workbooks, databases and preference files were synthetic/temporary. Existing company workbooks, user windows and real app-data files were not used.

## Limits and accuracy of claims

- The 1,500 ms SQLite busy timeout is not an end-to-end task deadline. Filesystem activity, opening/initialising a connection, multiple operations and scheduling can increase wall time; this probe observed about 2.9 seconds. Do not promise that every cancellation completes within 1.5 seconds.
- Python work between SQL statements and non-cooperative substituted/custom reads are not forcibly interrupted. They occupy their bounded slots until they return. Finite slots intentionally trade latency for bounded resource use.
- A thread can be returning after it queues completion; the lane cap describes tracked read work, not a strict instantaneous OS-thread-count proof at every instruction.
- The new API is opt-in. Other windows' scheduling/worker bounds were not audited here; the passing isolation probe is not a broad re-acceptance of all shared-history callers.
- No layout changes warranted a repeated visual matrix. Packaged EXE, real Drive/history workloads, physical DPI, Windows 10, another PC, real mail/API and the earlier incomplete broad B1 run remain outside this review.

## Next step

The R1 source change is suitable for a local checkpoint. Background Excel export and robust self-test failure exit remain separate reliability tasks. Complete remaining secondary-window localisation separately; do not expand this change into those tasks or treat source GO as release approval.
