# M4A — Inventory History and Observed Changes

Date: 2026-10-21 (Asia/Singapore). Base: local commit `d0633fd` (M3.2A/B). This report records implementation verification by Claude Code. It is not an independent acceptance. Nothing was committed, pushed or released, and M4B was not started. Codex review is pending.

## What was built

A separate, read-only **Inventory History** window, opened from a new **Inventory History…** button in the top file area, beside *Local History…* and *Use Cached Data…*.

- **Search:** partial Material ID text with the checker's own normalisation (`normalize_code`: NFKC, trimmed, upper case). Candidates are distinct keys from the `materials` registry that were ever seen in Storage. The exact match comes first, then prefix matches, then other matches. `%`, `_` and `\` are matched literally. At most 200 candidates are shown, with a "type more" note. Typing never queries. The user must select one exact key. Similar IDs are never merged, and IDs held in numeric cells are not text keys.
- **Filters:** Storage Sheet (exact names from retained history, or "All Sheets (shown separately)") and 30 / 60 / 90 days. The window is `[now − days, now]`, inclusive at both ends, on the UTC snapshot time `observed_at`.
- **Records tab:** newest first, one row per stored Storage row of that key in every snapshot in the window. Each row shows snapshot time (local), Material ID, description, raw stock, data status, Rack, Level, Sheet, row, source file and version. The last snapshot before the window is added and marked **Before window**. Snapshots without the key show `NOT PRESENT — not 0`. Snapshots whose Storage rows were removed by maintenance show `NOT RETAINED — values unknown`.
- **Observed Changes tab:** stored `inventory_changes` rows of that key, with before/after time, before/after stock (duplicates listed individually), change type, and a note. An **observed difference** is shown only for `QUANTITY_CHANGED` between single valid records **from the same source file**. Across a source switch the window shows `not comparable (source switch)`, even though M3.1 stored a numeric delta.
- **Coverage panel:** window bounds, the number of snapshots in the window and whether the window is fully covered. Explicit notes cover history starting inside the window, records removed by Local History maintenance (`history_retained_from`), no snapshot in the window, the Before-window row, and each source-file switch. The notes always say that missing means unknown, not 0, and repeat the observed-change caveat.
- **Permanent labels:**
  - the banner `HISTORICAL OBSERVATIONS · Not current stock · Cloud Not Verified`;
  - the caveat line *Observed Change ≠ Actual Consumption · Blank stock ≠ 0 · Duplicate IDs never added · Invalid quantities never converted · Sheets / source files never merged · No comparable difference across a source switch*;
  - a status bar that always ends with Cloud Not Verified.

  `Local Sources Verified` never appears in this window.

## Design

| File | Role |
|---|---|
| `checker/history.py` (new) | Read-only query layer. `read_view()`, `search_materials()`, `list_sheets()`, `material_history()` return frozen dataclasses (`HistoryResult`, `HistoryRow`, `ChangeRow`, `Coverage`, `Candidate`). |
| `checker/history_ui.py` (new) | `HistoryWindow` Toplevel: workers, generation guards, batched rendering, labels. |
| `checker/ui.py` | +22 lines: the entry button, `open_history()` (one window, brought forward if open) and closing it on app close. No change to the CHECK area, calculations, cache mode, maintenance or export. |

**Reuse:** `queries.open_readonly`, `queries.snapshots`, `queries.OBSERVED_CHANGE_CAVEAT`, `inventory_db.decode/stamp/SCHEMA_VERSION`, `core.normalize_code/display`, the M3.1 schema (`inventory_snapshots.same_source_path`, `inventory_changes`, `source_versions.record_count`) and the M3.2B `history_retained_from` marker. `queries.py`, the M2 engine, the reader, sync, the schema, retention and cached mode are **unchanged**. No migration.

**Consistency:**
- Each search or query runs in one deferred read transaction on a `mode=ro` connection: `BEGIN`, then a first `SELECT` that starts the read snapshot.
- The busy timeout is 1500 ms per acquisition.
- A missing file is refused before connecting, so the database is never created. A foreign or newer schema (`user_version`) is refused.
- SQLite, OS, decoding and JSON errors become `HistoryReadError`, never a partial result.
- With the default rollback journal, a concurrent publisher's COMMIT waits until the read transaction ends. A test checks this with the other writer still blocked mid-query.

**Payload check:** a snapshot's version is "retained" only if its stored `stock_records` count equals `source_versions.record_count`. Otherwise it is `NOT_RETAINED`, never "absent" and never 0.

**Threads:**
- Workers only compute and put `(kind, generation, data, error)` on a queue. A 50 ms `after` poll owned by the window applies only the current generation of each kind (search or query).
- A new query clears the previous result *before* it starts, so a stale table is never left looking current.
- `close()` sets `closed` and cancels the poll and the debounce. Late responses stay in the queue unapplied, and the main app's `close()` closes the window first.
- The window is independent of the main app's job lock; it never disables or changes CHECK controls.

**Bounded loading:** up to 1,000 records and 1,000 changes per query, with totals counted in the same transaction, rendered 200 rows at a time with **Show more**. When totals exceed what was loaded, both the coverage panel and the footer say so.

**Failure:** a query error clears the tables and shows `QUERY FAILED — no history is shown. Earlier results were cleared.` with the error, and the status `Query failed · no results shown · … Cloud Not Verified`. A search error clears the candidates. A failure to read the Sheet list is reported in the status bar.

**Layout:**
- The two control rows are compact.
- When the result tables would get short, the coverage panel (3→2 lines) and details box (2→1 line) give up one line each, and expand again when there's room. The two thresholds are different, so the layout doesn't flip back and forth.
- Columns have a minimum width equal to their normal width, so narrow windows scroll sideways instead of squeezing *Data Status*.

## Issues found and fixed during development

1. **960×600 at 150% font scale:**
   - **Symptom:** the result notebook got 64–88 px, and the tables collapsed to 1 px.
   - **Found:** the full suite showed it only when `test_m32b` ran first. Tk keeps `tk scaling` for the process, so the window was really built with 1.5× fonts.
   - **Fixed:** compact control rows, shorter caveat wording, the selected label moved onto the candidate row, a fixed-height details box, and adaptive coverage/details height.
   - **Test:** the window is now rebuilt per scale. In the real large-font case the Records table keeps 86 px at 960×600 and 187 px at 1280×720; at 100% it keeps 189 px and 305 px.
2. **Squeezed status column:** Treeview stretch columns (Description, Data Status) were squeezed to a few pixels at 960 px. Columns now have `minwidth = width` and scroll horizontally, and a test asserts it.

No defect was found in M2/M3 code; none was changed.

## Known limitations and items for acceptance

- **No packaged (frozen EXE) run of M4A.** Not built and not executed. The visual check ran from source in a DPI-unaware process, like the EXE.
- Not executed: real Google Drive data, another PC, and native high-DPI (per-monitor) rendering. 1280×720 could not be fully shown on this 300% display (its logical work area is about 1280×680); geometry at 1280×720 is checked by tests only.
- The Sheet list is read when the window opens. Sheets published later appear after reopening the window. A query for a Sheet not in a version reports that explicitly.
- Times: the tables show local time; the coverage notes and row details show exact UTC stamps.
- Rows with numeric-cell or invalid IDs (no text key) cannot be searched. This matches the checker's matching rules.
- 150% layout testing relies on the process-wide Tk scaling behaviour described above. Scaling changed after window creation does not resize fonts in a running Tk, so a user switching Windows scaling while the app is open is not covered.
- In the default rollback-journal mode, a long history query briefly delays another program's commit, by up to the query's duration. The queries are indexed and short; the writer's busy timeout is 15 s.
- History is read only from this computer's SQLite mirror. It cannot show changes never synchronised (the app not running, sync failures), and says that a snapshot exists only when a new Storage version was imported.

Verification is in `M4A_TEST_REPORT.md`.
