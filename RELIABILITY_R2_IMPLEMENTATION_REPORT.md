# Reliability R2 — implementation report

Date: 2026-10-23. Baseline: `7c9b90c` (Reliability R1, committed locally). The only pre-existing uncommitted item,
`audit_test_run.txt`, was left untouched. Nothing was committed, pushed, packaged or released.

Scope:

1. Background Excel export from the main window.
2. `app.py --self-test` failure exit.

No layout or navigation change, no business or calculation change and no window localisation. No real API, mail,
inventory write or real data were used.

## 1. Background Excel export

### Files

| File | Change |
| --- | --- |
| `checker/report.py` | Optional `progress`/`cancelled` arguments; stage names; `ExportCancelled`; `Cancellation` (serialised cancel/publish); cancellation boundaries in `_stage_report` |
| `checker/cached.py` | `save()` passes the same two optional arguments through |
| `checker/ui.py` | `ExportTask`, `start_export`, worker, completion handling, cancellation hooks, `write_export` now waits for the task |
| `checker/i18n.py` | Seven status keys in en/zh/ms (four stages, cancelled, "published before the change", staging file not removed) and one dialog body (cancelled-export leftover) |

All new arguments in the shared code are keyword-only and default to `None`. Without them, `save_verified_report`,
`cached.save` and `_stage_report` behave exactly as before. No other caller passes them.

### Flow

1. **On the Tk thread, unchanged.** `export()` refuses without a result, runs the existing source pre-check
   (`_verify_export_sources`), opens the file dialog, and refuses if the result changed while the dialog was open. The
   dialog and every message box stay on the Tk thread.
2. **`start_export(path)`, Tk thread.**
   - Refuses when `busy`, closed, without a result, or when the result is not exportable. The existing normal-mode and
     cache-mode refusals are reused.
   - Captures an `ExportTask`: path, result object, both workbook snapshots, the binding (`SourceBinding` or
     `CacheBinding`), the selected source paths, the job number and a cancel event.
   - Sets `busy`. This disables CHECK, Refresh, loading, maintenance and Export, so at most one export runs and nothing
     is queued.
   - Starts one worker thread.
3. **The worker** calls the existing `save_verified_report` (normal mode) or `cached.save` (cache mode) with the
   captured values only. It never reads interface state or touches Tk.
   - Stage notifications and the outcome travel through `export_events`.
   - `_poll` on the Tk thread shows the stages in the status bar:
     - "checking the sources"
     - "generating the report"
     - "writing the file"
     - "final source check before publishing"
   - Then the existing success or failure handling runs. No percentage is shown, because none of these stages has
     measurable progress.
4. **`write_export(path)`** keeps its earlier contract for automation and the existing tests: path or `None`. It now
   starts the same background task and waits while processing Tk events. The Export button does not wait.

### Protections kept

- **Normal mode:**
  - the source pre-check with two passes;
  - "report data differs from CHECK";
  - private staging next to the target, no overwrite, numbered names, never a source workbook;
  - the final `verify_export` immediately before the no-overwrite publication;
  - the binding is invalidated on failure.
- **Cache mode:**
  - explicit authorisation, the token, source-path and data-belongs checks;
  - `cached.verify` before building and again immediately before publication;
  - `UNVERIFIED_` file name and banners.
- **Report content:** the M2 two-sheet content, categories and provenance are produced by the same functions.

### Race window not enlarged

The final verification and the publication are still consecutive steps in the same thread, as in the synchronous
writer. Between them, the worker takes the publication lock (see below), checks for cancellation and publishes.

### Cancellation and publication boundary (revised after `RELIABILITY_R2_CODEX_REVIEW.md` P1-R2-1)

- **What cancels.** The Tk thread cancels the task synchronously when the interface moves on:
  - `invalidate()`, which fires on any change of Storage selection, Product or quantity, and before any new job;
  - any change of `cache_authorized`, now a property;
  - `close()`.
- **There is no Stop button in the main window.** Closing the window is the user's stop.
- **Serialised boundary (`report.Cancellation`).**
  - Each export task has one `Cancellation` object with its own lock.
  - The Tk thread's `cancel()` and the worker's publication both take that lock.
  - In the worker, the publication step is: final source or cache verification (outside the lock), then lock, then a
    cancellation check, then the no-overwrite `os.rename` (Windows) or `os.link` (POSIX), then the published path is
    recorded, then unlock.
  - So exactly one of "cancellation" and "publication" comes first:
    - **Cancellation first:** the worker sees it under the lock and raises `ExportCancelled`. Nothing is published,
      and the task's own staging file is removed by the existing `finally` block. The status says the export was
      cancelled.
    - **Publication first:** `cancel()` returns `False`, and the report stays published. It passed the final
      verification for the result it was made from. Completion shows it as "published for the earlier result" and
      never as the export of the current result: no success panel and no change to the current result. Cancellation
      cannot recall a published file, and nothing claims it can.
- **The lock covers only the cancellation check and the single rename or link.** It is never held while generating,
  writing, verifying or reading sources. The Tk thread therefore waits at most for one rename already under way.
- **The final source verification and the cache verification stay outside the lock**, immediately before it.
  Cancellation that arrives during or after them is still caught at the lock. The no-overwrite rule is unchanged: a
  `FileExistsError` releases the lock and tries the next numbered name, at most 10 times.
- **Other cancellation checks.** These run before verifying the sources, before building, before writing and before
  the final verification. They are early exits only. Building, the workbook save and each verification are never
  interrupted midway, and no thread is killed.
- **Completion double-check.** Besides the cancellation, completion also compares the result, binding and job number;
  any mismatch is treated as stale. This is an extra check, not the protection itself.
- **Cleanup failure is never hidden** (revised after review item P2-R2-2).
  - When a cancelled or stale task's staging file cannot be removed, the writer attaches `cleanup_warning` to the
    original exception. The warning contains the file path and the reason.
  - The stale branch now shows:
    - a status line with the cancelled/late outcome plus "Temporary export file not removed: …";
    - an "Export failed" dialog with the original error, the warning, and a note that the current result was not
      changed and the file may still contain report data.
  - Nothing is deleted beyond the task's own staging file. The stale task never touches the current result, its
    binding or the success panel, so it cannot restore an old success state.
- **Refresh, CHECK or a second export during an export** are refused while `busy`, with buttons disabled. They do not
  cancel the running export.
- **Closing the program.** The worker is a non-daemon thread. When the program closes during an export, Python waits for
  the worker to reach its next boundary and remove its staging file, instead of killing it mid-write. That wait is
  bounded by the longest single stage.
- **Errors.** Write failures (`OSError`) keep the earlier "choose another folder" dialog. Other unexpected errors now
  show the export-failed dialog instead of escaping as a Tk callback traceback.

## 2. `--self-test` failure exit

### File

`app.py`.

### Changes

- **`OUTPUT_DIR` is created on demand** (`mkdir(parents=True, exist_ok=True)`) before any window is created. It is never
  replaced by another folder. The self-test's default data folder remains `OUTPUT_DIR\appdata`, never the real
  application data.
- **Unusable `OUTPUT_DIR`** (an existing file, invalid path or creation failure): the error goes to stderr when a
  console exists. Exit code is 2 and no window opens.
- **`finish()` is idempotent** and always closes the window. If `app.close()` fails, it falls back to `root.destroy()`.
  If `self_test.json` cannot be written or serialised, the error goes to stderr and the exit code is 2.
- **Watchdog (a Tk timer, not a hard process deadline).** After `SELF_TEST_TIMEOUT_MS = 180 s` the
  `after` callback records an unfinished check as failed and closes the window. It cannot fire while a Tk callback is
  blocked. A non-daemon export worker in an uninterruptible step (build, save or verification) keeps the process
  alive until that step returns. Exit within 180 s is therefore not guaranteed in those cases. No new process
  supervisor was added in R2.
- **Exit codes:**

  | Code | Meaning |
  | --- | --- |
  | 0 | Passed |
  | 1 | Ran but did not pass, or the window was closed before the check finished |
  | 2 | `OUTPUT_DIR` or `self_test.json` was unusable |

  Earlier, a self-test always returned 0. If `self_test.json` could not be written, the error escaped the Tk callback
  and the window stayed open indefinitely. This was reproduced against `HEAD`'s `app.py`: an unusable `OUTPUT_DIR` was
  still running after a 30 s timeout.
- **Uses the background export.** The self-test starts the export with `start_export` and waits for it in its own
  step loop, without a nested event loop. It records an extra `export_started` field.
- **Unchanged:** normal start-up, `--smoke-test` and `--daily-run`. Main still returns `None` (exit 0) for a normal
  start.

## Remaining limits

- **Uninterruptible stages.** Building, the workbook save and the verifications cannot be interrupted. A cancellation
  waits for the current stage, and so does process exit after closing.
- **No progress percentage**, by design.
- **A cancellation after publication keeps the published report.** This is intentional and is disclosed in the
  status; cancellation cannot recall a published file.
- **Cancelling may wait.** `cancel()` on the Tk thread may wait for one rename already under way, for example on a
  slow network or synced folder.
- **The self-test watchdog is not a hard deadline** (see above).
- **POSIX staging cleanup.** After a successful `os.link`, a failed removal of the staging file still makes the
  writer report an error, which is pre-existing behaviour. Windows is unaffected, because the rename consumes the
  staging file. This was not changed in R2.
- **Exports are refused, not queued, while another job runs.** The user must try again.
- **Read-only folder not exercised directly.** The genuinely read-only `OUTPUT_DIR` case relies on the same path as
  "`self_test.json` cannot be written". The test uses a real `OSError`: `self_test.json` exists as a folder. No
  Windows ACL was changed.
- **Not covered:** secondary windows (Alerts, Analytics, Daily, assistant) were not reviewed for blocking work in R2.
  Nothing packaged or frozen was built or run.
