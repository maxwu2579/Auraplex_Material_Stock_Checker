# M4B — Focused test evidence

2026-10-22. All fixtures were synthetic workbooks and temporary SQLite databases. No company workbook/database, Google Drive mount or real scheduled task was used. Codex implementation verification, not independent acceptance.

## Executions

| Run | Result | Evidence |
| --- | --- | --- |
| Initial M4B module | 18 passed, 3.192 s | `%TEMP%\MRC_M4B_development.txt` |
| Added trailing-unchanged/partial/future-date cases and main UI regressions | 26 passed, 14.687 s | `%TEMP%\MRC_M4B_related.txt` |
| Added legacy schema and missing-payload cases | 28 passed, 16.951 s | `%TEMP%\MRC_M4B_final_related.txt` |
| Final M4B module with control-visibility and real 230-group paging assertions | **24 passed, 3.958 s** | `%TEMP%\MRC_M4B_final.txt` |

The related 28-test run comprised the then-current 23 M4B cases and five existing checks: M3.1 InventoryUi compact panel, both CloudNotice cases, M4A main History entry, and M3.2D Daily entry/window layout. One paging test was added afterward and visibility assertions strengthened. Final production code is the same as during the 28-test run. Across these runs, 24 new + 5 existing distinct checks passed; this is not a full-suite count. No repeated full business regression or package rebuild was performed.

## Scenarios

- Steady positive observations produce explicit human-review cues only after sufficient span. A recent change ends the trailing unchanged cue even if an older unchanged segment was long.
- Exact decimal absolute movement differs from net change on a reversal; percentage threshold uses positive prior quantity. Zero-to-positive has unknown percent.
- Blank, `0+10`, duplicate rows and numeric-cell IDs remain unusable/excluded as appropriate, with raw values/provenance preserved. Duplicates are never added.
- Disappearance/reappearance, source switch/return, exact Sheet names, similar IDs and literal search punctuation are isolated. Missing quantities do not become zero.
- Before-window reference, 30/60/90 ranges, stale reference-only history and future snapshots are handled without extrapolation. Incomparable partial history withholds net; retention boundaries suppress whole-chain classifications.
- Removed snapshots break the stored previous-version chain. Missing payloads are unknown, including an empty result where all known payloads were removed.
- Legacy schema 1 reads without migration. Missing/unsupported databases fail closed without creation or modification. Source/database hashes remain unchanged by analysis.
- Snapshot/row/group limits, explicit cancellation and processing timeout return no partial result. Invalid heuristic settings are rejected.
- During a query, a synthetic concurrent writer reached its commit but was blocked until the read view closed; the returned observation remained entirely from the old view. The writer then completed.
- Newest-only requests, Stop, Close, failed reads and reopened windows do not restore old results. One active + one pending request is verified under rapid requests. Database read failures invoke the existing verification invalidation path.
- 230 actual result groups render 200 first, then all 230 on Show more. Editing a filter clears table and old coverage summary.
- Small-window matrix: 960×600, 1280×720, 1366×728 at Tk scaling 1.0 and 1.5. Permanent Cloud Not Verified, table height (>70 px), and Analyze/Stop/Close visibility checked. Main-window regressions also passed.

## Synthetic scale check

1,000 materials across 8 imported versions (8,000 historical rows): **0.2062 s** for the read-only analysis on this computer. SHA-256 of source workbook/database unchanged. Fixture/evidence: `%TEMP%\MRC_M4B_perf_fsp380qn\benchmark.json`. This is not a real-workbook, large-history or slow-PC performance claim.

## Remaining acceptance

No M4B EXE, real Google Drive/company workbook, another PC, Windows 10, native physical DPI or visual screenshot/printing acceptance. Business meaning of thresholds, units, critical spares and purchase/usage conclusions remains unconfirmed. No consumption/reorder/excess-stock quantities were calculated. No production database/source updates, commit, push, release or next milestone started.
