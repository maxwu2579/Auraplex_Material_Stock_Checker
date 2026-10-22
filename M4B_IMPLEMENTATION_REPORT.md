# M4B — Historical inventory analytics implementation

2026-10-22. Codex implementation after the user's next-step instruction. Source development completed; **uncommitted and pending review**. This is not independent acceptance, release approval or M4C/AI implementation.

## Delivered

- `checker/analytics.py`: deterministic read-only analysis over retained Storage snapshots in a single existing `history.read_view` transaction. No Excel read, stock update, schema change, migration, material aggregation across files/Sheets or network/provider call.
- `checker/analytics_ui.py`: **Analytics…** link opens a separate window. Choose 30/60/90 days, exact original Sheet, optional normalized partial Material ID and explicit review thresholds. Every actual source path + Sheet + exact ID is its own group. The table shows last observation UTC, quantity/status, window-clipped span, comparable movement/net and signals. Details retain raw quantities, source path, Sheet, row numbers, snapshots, version IDs and Rack/Level.
- The main UI has 21 added lines for import, link, window lifetime and close. Existing CHECK/export, alert/sync/retention rules and daily code are unchanged. A database read failure uses the existing alert-verification invalidation callback on the Tk thread.
- No export or AI interpretation was added. MIN QTY evaluation remains in the existing Stock Alerts flow; M4B risk cues cover last-observed zero, data problems, missing history and large observed changes.

## Rules and business limits

All output is **HISTORICAL / UNVERIFIED**, Not current stock, Cloud Not Verified. The default policy is visible and adjustable: minimum 30-day span, low movement ≤ 0, large step ≥ 50% of a positive previous quantity. These are trial review heuristics, not business-approved risk thresholds.

Movement = sum(abs(after − before)) across adjacent global snapshots only when the source path matches, the stored previous-version relationship is intact and both material records are unique, valid and retained. Similar IDs, source paths and Sheets never merge. Blank, invalid, duplicate, absent and missing-payload records remain explicit states. No quantity is filled in as 0. Zero-to-positive changes do not get an invented percentage.

Net change is unavailable across any incomparable interval or pruning boundary, although the subtotal of valid comparable absolute movements can still be shown with explicit gap signals. First/last timestamps, before-window references and window clipping are preserved. Snapshot times are observation/import times; changes are not actual consumption. No observation is extrapolated through the time of the query.

LOW_OBSERVED_MOVEMENT requires a complete comparable chain, at least two observations and the minimum span in the selected window. LONG_UNCHANGED_OBSERVATIONS and POSITIVE_UNCHANGED_REVIEW use the **trailing** unchanged segment. A past unchanged period followed by a recent change cannot trigger the positive-unchanged cue. Positive unchanged stock remains a manual review suggestion; demand, critical-spare importance, lead time, units, confirmed excess quantity, purchase quantity and days remaining are unknown. Former-source cohorts are explicitly marked and do not receive the low-movement/positive-unchanged cues.

## Resource/concurrency behavior

- Reuses the accepted `DailyRunner`: at most one active + one newest pending request. No Tk calls from workers. Editing inputs, Stop or Close cancels previous work and invalidates its generation. Closed-window queues are discarded; late results cannot repopulate the window.
- Query budget: five seconds of processing; 400 in-window snapshots plus one reference, 200,000 total payload rows, 5,000 material/source groups. Limits fail closed with no partial result. SQLite progress cancellation and per-record checks release the read transaction on cancellation/timeout. Existing connection/lock startup waits can add latency.
- The full-version row cap still applies to a material/Sheet-filtered query. Shortening the date range, not just filtering an ID, is required for that cap. This is deliberate conservative memory protection; material-specific high-volume optimization is future work.
- Table rendering is paged in batches of 200. Snapshot deletion, payload cleanup and source switches break comparability even if valid records exist on both sides.
- Each query may briefly delay a writer in rollback-journal mode; this milestone does not change journal mode. The M4A worker-fan-out P2 is not modified; M4B has its own bounded worker.

## Verification

See `M4B_TEST_REPORT.md`. Latest M4B run: **24 passed in 3.958 seconds**. Related earlier run: 28 passed in 16.951 seconds (23 then-current M4B cases + 5 existing main-window/cloud/History/Daily layout checks). The final addition improved control visibility/paging assertions; production sources were unchanged after the related run. No full suite rerun.

Synthetic benchmark: 1,000 groups × 8 snapshots = 8,000 rows, query **0.2062 seconds**, source and database SHA-256 unchanged. No real workbook/database was opened. Existing published v1.0.0 artifacts remain unchanged. `audit_test_run.txt` is preserved.

Not executed: M4B EXE rebuild, real company workbooks, real Drive/cloud verification, another PC, Windows 10, native high-DPI or human visual review. Automated geometry checks covered 960×600, 1280×720 and 1366×728 with Tk scaling 1.0/1.5; they are not physical display acceptance. M3.2E native-restart diagnosis remains deferred for CC; this milestone does not revisit it.

## Review gate

No commit, push, release, production-data sync/upgrade, permanent schedule or M4C work was performed. Review the observation-chain rules, policy labels, cancellation/failure handling and limits before authorizing a local M4B commit.
