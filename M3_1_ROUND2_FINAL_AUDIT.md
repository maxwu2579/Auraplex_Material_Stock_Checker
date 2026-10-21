# M3.1 Round 2 Final Independent Acceptance Audit

Date: 2026-10-14

Project: `C:\Users\25795\OneDrive\Desktop\Projects\ChatGPT\工作\MaterialRequirementChecker-M0`

## Decision

**NO-GO for a local Git commit.** The three Round 2 P0 fixes pass the required scenarios, including the original Storage/BOM synchronization race, unrecorded failure override, startup after failure, and the cloud warning layout. However, an additional **P1 export freshness gap** remains: after a successful CHECK, an external save to either source does not invalidate the in-memory binding until the user triggers Refresh. Both export entry points can then write the earlier result while the UI still says `Local Sources Verified`.

No production code, source workbook, or published build artifact was changed. The only project-file addition is this report; nothing was staged or committed, and no push or release was made.

## Required results

| Check | Result | Independent evidence |
|---|---|---|
| P0-A — CHECK/source-version consistency | **PASS** | Synthetic Storage changed from stock 100 to 0 after calculation; the earlier calculation was discarded, the second attempt used 0, and only that result was rendered as verified. The BOM equivalent, sync retry with a newer version, retry exhaustion, outdated export refusal, and Refresh-after-CHECK recalculation also passed. |
| P0-B — Unrecorded synchronization failure | **PASS** | With an older successful Storage sync still in SQLite and `_record_failure()` returning `recorded=False`, the current source-unavailable failure overrode the historical success in the panel and status bar. The database rows/history stayed intact and the old success time was labelled historical. A gated restart test showed `Checking` and blank verification time before sync completed, then `Using Previous Data` after the failure. |
| P0-C — Persistent cloud-freshness warning | **PASS** | `Cloud Not Verified` remains visible in success, failure, unavailable, unknown, previous-data, not-synced, syncing, and database-unavailable states. The suite exercised 960×600, 1280×720 and 1366×728 at Tk scaling simulations of 100%, 125% and 150%. The status bar also carries the warning in error states. |
| Restart after an unrecorded failure | **PASS** | In addition to the Round 2 startup regression test, I paused startup synchronization after a prior success. Before the worker completed, the visible UI showed `Checking`, `Last Verified: —`, and no old success timestamp. After the unavailable-source failure, the UI showed `Using Previous Data` and a historical time. |
| Refresh after CHECK | **PASS** | A synthetic Storage save from 100 to 0 followed by Refresh recalculated the result to a shortage of 20 for production quantity 10. The newly calculated result was current and exportable. |

### P0-A — version binding and bounded retries

`checker/ui.py` calculates, synchronizes, compares the resulting `SourceBinding`, and repeats the full read/calculate/sync workflow when the confirmed version differs (`_start`, `check`, and `verify`; see `checker/ui.py` around lines 677–712 and 911–936, and `checker/binding.py`). The previous CHECK result is cleared before starting a job. When retries are exhausted, the result is explicitly `OUTDATED / RECHECK REQUIRED`; both `export()` and `write_export()` refuse it and write no file.

The exact synthetic 100→0 race passed independently: two calculations ran, the result reflected stock 0, the SQLite Storage row held 0, and the old calculation was never rendered as verified. The corresponding BOM-change, source-change-during-sync-retry, and retry-exhaustion regression tests passed. The exhaustion case used three CHECK attempts, rendered only an outdated result, and verified that both export paths refused it.

I also injected a change immediately after the import transaction committed but before `sync_all` returned. The database retained a complete committed historical version, the final result was `SourceChanged` rather than successful local verification, and `PRAGMA integrity_check` returned `ok`. The existing tests cover the UNCHANGED-record boundary, the pre-COMMIT boundary, a concurrent publication by another instance, and a file changing while the other role synchronizes. No partial SQLite publication was observed.

Finite checks establish a local file version at a check time; they do not establish permanent freshness or Google Drive cloud freshness.

### P0-B — current failures override stored success

`checker/ui.py` applies in-memory failed `SyncResult` values through `with_known_failures()` after reading SQLite. A role override is cleared only after this program verifies that role again. The independent reproduction preserved the older successful rows and snapshot while rendering the current source failure, showing its time as `Previously Verified`, and keeping the failure visible in the status bar. Later jobs that synchronize only BOM did not erase the Storage failure override.

The restart path begins without loading historical freshness into the panel; while remembered paths are being checked, the UI shows `Checking` rather than the old database success. This avoids even a brief old-success display before an unrecorded failure is known.

### P0-C — cloud limitation and layout

The cloud warning is a separate persistent label beside the inventory status, not a tooltip-only detail. Automated geometry tests passed for the requested three window sizes and three Tk scaling simulations, with the warning inside the window and to the left of Refresh Excel. These are Tk scaling simulations; no physical 125%/150% monitor was available for a native-DPI visual check.

## New finding

### P1 — a source save after CHECK does not invalidate export

**Reproduced.** I completed a verified CHECK using synthetic Storage stock 100. After CHECK returned, I saved the Storage workbook with stock 0 but did not click Refresh. The UI continued to show the prior `Local Sources Verified <time>` label, `result_current` remained true, and `write_export()` successfully wrote the old in-memory result. The two export guards only inspect the stored `SourceBinding`; `result_current` compares the calculation fingerprint with the fingerprint confirmed during CHECK, but does not compare either fingerprint with the current workbook at export time. See `checker/ui.py` around lines 1008–1035 and `checker/binding.py` around lines 35–45.

Clicking Refresh after that save does recalculate correctly, so the Refresh-after-CHECK requirement passes. The gap is the direct export path before Refresh: the report is generated later than the check, yet the report does not include the binding's verification time or content signature. It can therefore be mistaken for a report using the source version current at export time.

This does not invalidate the point-in-time confirmation at CHECK, so it is classified P1 rather than P0. It does leave an unsafe path for exporting known-changed local sources and conflicts with the requirement that outdated results be rejected by all export paths. Before commit, both export paths should re-fingerprint the selected Storage and BOM files and refuse on a mismatch, or adopt an equivalently explicit versioned-export contract that cannot present the older result as current.

## Regression and integrity results

- Full suite: `.\.venv\Scripts\python.exe -m unittest discover -v` — **179 tests, 174 passed, 5 skipped, 0 failed** (100.975 seconds). All five skips require a real mounted folder via `MRC_TEST_MOUNT_DIR`; no Google Drive/cloud freshness was verified.
- Six additional focused synthetic checks passed: exact 100→0 CHECK race, gated startup after unrecorded failure, Refresh recalculation plus export, SQLite failure during CHECK with readable Excel, rapid CHECK/Refresh serialization, and an immediate post-COMMIT source-change injection. The post-CHECK source-save/export case is the P1 reproduction above, not a passing acceptance case.
- The SQLite failure-during-CHECK injection left Excel calculation functional and bound the result by direct local re-reads. The inventory panel separately showed `Status Unknown`; the result displayed its own local-source verification state.
- Rapid CHECK/Refresh requests were serialized to one job. The older-job event regression test also passed; stale events did not overwrite the newer result or sync state.
- Duplicate and invalid stock preservation, transaction rollback, history, no duplicate snapshot for unchanged stock, independent role sync, read-only source handling, and Tk main-thread updates passed in the full suite.
- M2 calculation/report files (`checker/core.py`, `checker/reader.py`, `checker/service.py`, `checker/report.py`, `checker/report_style.py`, and `checker/presentation.py`) have no tracked diff. M2.1 calculation and Excel report regression tests passed, including the frozen report-payload comparison. Synthetic Excel/SQLite parity passed. I did not inspect or hash the real company Storage/BOM workbooks in this audit, so no real-workbook parity claim is made.
- An isolated PyInstaller 6.22.3 onedir/windowed build of the current source completed in `%TEMP%`; its frozen `--self-test` passed with `frozen=true`, `result_verified=true`, successful export, visible `Cloud Not Verified`, and no new snapshot after unchanged Refresh. Synthetic inputs and output were used. The scratch directory is `C:\Users\25795\AppData\Local\Temp\MRC_M31_R2_FrozenAudit_bcdd48496b854e0192c023e9649cd780`. Cleanup of that audit-only directory was refused by the execution policy; I did not retry, and it remains outside the project and release folders.
- Packaging-version tests passed: missing version, mismatched version, and development version without `-AllowDevBuild` were rejected; development `-ValidateOnly` passed without changing build/dist listings. The published v1.0.0 artifact hashes remain unchanged from the previous audit: ZIP `768759c9961d9027d1a990e678c5581001f151ee2b54ab1c424ab425ed1517d5`; EXE `e232f2074f0f6dfe35ec623c96ed913c4ec570a53b098aba45f7f74183930e50`.
- `git diff --check` passed. The worktree already contained M3.1 modifications and untracked audit/build documents before this report; this audit did not stage or commit them.

## Findings summary and limitations

| Severity | Finding | Status |
|---|---|---|
| P0 | CHECK calculation can be published against a different source version after synchronization | **Resolved and independently verified** |
| P0 | Unrecorded sync failure can be hidden by older SQLite success | **Resolved and independently verified**, including startup display timing |
| P0 | Cloud freshness limitation only visible in details | **Resolved and independently verified** in the Tk size/scaling matrix |
| P1 | Source changes after CHECK remain exportable until Refresh; export does not re-fingerprint sources | **Open — commit blocker** |
| P2 | Google Drive cloud freshness and a second PC were not tested; five mount tests skipped | Open environmental limitation |
| P2 | Scaling was simulated through Tk, not checked on native high-DPI monitors | Open environmental limitation |
| P2 | Real company workbook parity/source hashes were not rechecked | Open data-validation limitation |
| P2 | Retention, encryption, and ACL hardening policies remain outside M3.1 | Deferred; do not infer M3.2 completion |

**Final decision: NO-GO for a local Git commit until the P1 export freshness gap is resolved and independently retested.** No fix was made in this audit.
