# Reliability R1 — implementation report

Date: 2026-10-23. Baseline: `1219182` (B1 workbench and trilingual main interface, committed locally). The only
pre-existing uncommitted item, `audit_test_run.txt`, was left untouched. Nothing was committed, pushed, packaged or
released.

Scope was limited to two findings:

1. **P2-L10N-1** (`B1_L10N_CODEX_REVIEW.md`): choosing the already-active language could not retry saving the
   interface preference.
2. **M4A worker fan-out** (`M4A_CODEX_REVIEW.md`, P2): the History window started one thread per search/query, so
   rapid requests piled up readers, and closing the window did not stop in-flight reads.

No UI layout, business calculation, database schema, history rule or sync/export path was changed.

## 1. Same-language preference retry

### Files

`checker/ui.py`.

### Change

Saving the preference is now separate from the language-change notification.

- **`set_language(language)`** is the explicit click. It ignores unknown codes. It calls `LanguageState.set`, which
  notifies listeners only when the language actually changes, and then calls `_remember_language()` every time.
- **`_remember_language()`** contains the save code formerly in `_language_changed`, unchanged:
  `InterfacePreferences.save` is atomic (temp file, fsync, `os.replace`) and writes only `interface.json`.
  - On success it clears both `preference_problem` (the corrupt-file warning) and `preference_error` (the failed-save
    warning).
  - On `OSError` it records the error and the session keeps the chosen language.
  - Either way it re-renders only the preference label.
- **`_language_changed`** no longer saves. It still re-translates the interface and the preference label.

### Behaviour

- **Corrupt file, then EN.** The app falls back to English with the warning. Clicking EN rewrites a valid file and
  clears the warning.
- **Failed save, then the same language.** Clicking the current language once the folder is writable again saves the
  file and clears the warning. If the folder is still read-only, the warning stays and the language remains in effect.
- **What a same-language click does not do.** It does not re-translate widgets or rebuild pages. It does not read
  Excel, synchronise, call AI or change authorisation. Inputs, results, filters, the status message and running jobs
  are untouched; the tests spy on `_apply_tree_headings` and `load_file` to prove this.
- **Startup** still never writes the file. Source-path `settings.json` is never touched.

## 2. Bounded History window workers

### Files

`checker/history_ui.py` and `checker/history.py`.

### Bounded lanes (`history_ui._Lane`)

There is one lane per kind of request: Storage Sheets, search and query. Lanes run on the Tk thread only.

- **The newest request is the only current one.** On submit, the lane:
  - cancels its running job(s) cooperatively;
  - stores the request as the single pending request, replacing any older pending one;
  - starts it at once if a thread slot is free.
- **At most `LIMIT = 2` threads per lane:** the current job plus at most one superseded job that is still finishing.
  Anything newer waits in the one pending slot.
  - This deviates slightly from the literal "one running job". It is the "equally simple" alternative the request
    allows.
  - Why: a superseded read can sit in a step that cannot be interrupted, such as SQLite's 1.5 s `busy_timeout` on a
    locked database. A strict single slot would make the newer request wait for it. With the second slot it starts
    immediately, yet the thread count is still fixed.
  - Only one job per lane is ever non-cancelled.
- **Freeing a slot.** The `_poll` loop on the Tk thread calls `lane.finished(cancel)` for every response, current or
  stale. That frees the slot and starts the pending request.
  - Results are still applied only when their generation matches. This keeps the original
    `search_gen`/`query_gen` rule, so an older result can never overwrite a newer one.
- **Closing the window** calls `lane.stop()` for all lanes: pending requests are dropped and running reads are asked to
  stop.
  - Polling ends, so late responses stay in the queue and never touch destroyed widgets. This part is unchanged.
  - `search()` and `query()` still return immediately once closed.
  - The History window has no Stop button; closing is its stop path.
- **Clearing the search text** stops the search lane, so an obsolete search neither runs on nor starts later.
- **Unchanged:**
  - The 250 ms keystroke debounce.
  - The search → select → query dependency. A new search clears the candidate list immediately, so nothing can be
    picked from a stale list. A query captures its own key, range and Sheet when requested.
  - The "Querying…" state, which is shown for the newest request even while it is pending.
- **Threading rules.** Worker threads only run the read and put a tuple on the queue; Tk is touched only on the main
  thread. Threads are never killed.

### Cooperative cancellation (`history.cancellable`, opt-in)

- **What it is.** `history.cancellable(event)` is a context manager that sets a `ContextVar` for the current worker
  thread. Only the History window workers use it.
- **What `read_view` does inside such a block:**
  - Refuses to start if the event is already set.
  - Installs a SQLite progress handler that aborts a statement once the event is set (checked every
    `PROGRESS_STEPS = 1000` VM steps).
  - Yields a thin wrapper that checks the event before each `execute`.
  - An interruption raises `HistoryCancelled`, a subclass of `HistoryError`, rather than `HistoryReadError`.
  - The connection closes as before, and nothing partial is returned.
- **Without such a block, `read_view` behaves exactly as before.** This is the case for alerts, daily, analytics,
  assistant, jobs, report delivery and agent tools. The connection is still `mode=ro` with one deferred read
  transaction and the same schema checks, so the single consistent view is unchanged.
- **No signatures changed.** No function signature in `history.py` was changed. The existing tests that replace
  `history.material_history` with positional stubs still work.

### Semantics preserved

The following are unchanged:

- read-only transaction, one consistent view, source/Sheet/row/version provenance;
- `MAX_RECORDS`/`MAX_CHANGES`/`MAX_CANDIDATES` caps with totals, and 200-row batch rendering;
- "blank / missing / not retained ≠ 0";
- coverage notes, "Cloud Not Verified", and failure clearing the earlier result.

## Remaining limits

- **Non-cooperative code inside a read** (Python between statements, or a busy wait) cannot be interrupted. A lane
  then holds at most two threads until that code returns. A third and later request waits in the single replaceable
  pending slot.
- **The `_Cancellable` wrapper forwards attributes, not special methods.** No path in the History window uses the
  connection as a context manager or iterator.
- **Other windows were not reviewed in R1.** This covers Alerts, Analytics, Daily and the assistant, and whether their
  background work is equally bounded.
- **Still open from the roadmap:** background export and the self-test failure exit.
