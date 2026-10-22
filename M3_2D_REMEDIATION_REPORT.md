# M3.2D — Remediation of Codex findings P1-D1 and P1-D2

Date: 2026-10-22. Scope: only P1-D1 and P1-D2 of `M3_2D_CODEX_REVIEW.md`. Changed: `checker/daily.py` (`save()` and its helpers), `checker/daily_ui.py` (save result/error text), `tests/test_m32d.py`, README saving paragraph. **No shared business code changed** (`alerts.py`, `sync.py`, `inventory_db.py`, `queries.py`, `history.py`, `ui.py` untouched in this round). No real workbook or database was read; no commit, push, build or release; M3.2E not started.

## Publication / completion contract (new)

1. `save()` refuses early if the folder is missing, the database basis already differs, or (VERIFIED only) the session gate moved.
2. Both members are written into a **private staging directory** `<folder>\.mrc-daily-<report-id12>-<random8>.partial\` as `<stem>.json` and `<stem>.html` (exclusive create, flush, fsync, read-back comparison).
3. For each candidate name `<stem>`, `<stem> (2)`, … (skipped if anything already exists under that name):
   - open a read transaction on the database (`history.read_view`, read-only connection) and read the current basis — **this read lock is held until after the rename**;
   - basis ≠ summary basis → `DailyStale`, nothing published;
   - VERIFIED summary: enter `SessionGate.publishing(generation)`; not current → `DailyStale`;
   - **commit point:** one `os.rename(staging, folder\<name>)` of the whole directory;
   - `FileExistsError` (name taken at the last moment) → leave the lock, try the next name, **re-checking the basis from scratch**.
4. Success returns `Saved(folder, html, json)`; the report directory exists only with the complete pair.
5. Failure: the original exception is re-raised unchanged. The staging directory is removed; if removal fails, the exception gets `cleanup_warning` (path + cause), `leftover` (the path) and an exception note. The UI shows the warning with the error. A leftover is always named `.mrc-daily-….partial`, never a report name.

Lock ordering: SQLite lock first, then the session guard — the same order as the accepted M3.2C publisher (`BEGIN EXCLUSIVE`, then `publishing`). The save never waits for SQLite while holding the gate lock, and the M3.2C publisher never holds the gate while waiting for SQLite, so no wait cycle exists. While the read lock is held, other writers (this or another program) wait at COMMIT for the duration of one directory rename; their normal busy timeouts (15 s for this program's writers) apply.

## P1-D1 — basis re-checked at publication

- **Before (Codex reproduction):** another `InventorySync` published a new Storage version after staging; the save published a VERIFIED HTML and JSON (`basis_changed = True`, both files published).
- **After:** the basis is compared inside the held read transaction immediately before the rename and again on every name-race retry. `test_another_program_publishing_during_staging_refuses_the_save` performs the change from a separate `InventorySync`/`AlertService` at the `staged` checkpoint, for **VERIFIED and UNVERIFIED** summaries and four changes — new Storage version, new BOM version, UNCHANGED sync record, newer alert evaluation: all `DailyStale`, the gate generation is untouched (proving the refusal is not from the session guard), and the folder stays empty.
- `test_no_commit_can_happen_inside_the_publication_window`: at the `before_publish` checkpoint the staging directory is complete and no final name exists; a separate connection's `BEGIN IMMEDIATE … COMMIT` fails with `database is locked`; after publication the basis still equals the summary's.
- `test_every_name_race_retry_checks_the_basis_again`: a racing "other program" creates the first name at rename time; at the `retry` checkpoint a new Storage version is published → `DailyStale`, and the other program's directory is untouched. Without a data change the same race publishes as ` (2)` with the correct JSON.
- Existing `test_changed_data_or_verification_refuses_saving` and `test_verification_withdrawn_while_saving_publishes_nothing` (now via the `staged` checkpoint) still pass.

Statement of meaning: VERIFIED is a point-in-time observation that the local database still held exactly the summarised versions when the report was published. It is not a guarantee about later changes or the cloud copy (Cloud Not Verified remains).

## P1-D2 — pair publication without compensating deletes

- **Before (Codex reproduction):** JSON renamed, HTML rename failed, deletion of the published JSON failed silently → a complete-looking `Daily_Stock_Summary_….json` remained and nothing reported it.
- **After:** there is no second publication and no compensating delete of a published file: the pair appears by a single directory rename or not at all. Tests:
  - `test_failed_publication_leaves_no_report_and_keeps_the_original_error` — rename fails: the original error, no report, staging removed.
  - `test_cleanup_failure_is_reported_with_the_leftover_path` — rename fails **and** staging removal fails (`PermissionError`): the raised error is still the original one; `cleanup_warning`/note name the `.partial` path and cause; nothing exists under a report name.
  - `test_staging_failure_after_the_first_file` — HTML staging fails after the JSON was staged: nothing published or left.
  - `test_existing_report_file_or_folder_names_are_never_replaced` — an existing file and an existing folder with the report names stay untouched; the report becomes ` (3)`.
  - `test_interrupted_before_the_commit_point_publishes_nothing` — an interruption (KeyboardInterrupt) at the commit boundary leaves nothing.
  - `test_html_and_json_come_from_one_summary` (updated) — the folder holds exactly the pair; same report ID, JSON == summary data, HTML `data-sha256` == SHA-256 of the JSON bytes; a second save becomes ` (2)` and the first is unchanged.

Platform notes (not over-claimed): on Windows, renaming a directory onto any existing name fails with `FileExistsError` (checked here for an empty folder, a non-empty folder and a file). On other systems an existing **empty** directory could be replaced by `rename`; this program targets Windows. Crash/power-loss atomicity is **not** claimed: after a crash a `.partial` staging directory may remain (never a final-name report); the NTFS rename itself was not power-cut tested.

## UI adaptation

`Saved` now has `folder`, `html`, `json`; "Open saved report" opens the HTML inside the report folder; the status line names the report folder; a save error dialog also shows any cleanup warning. Save remains disabled while work runs; DailyStale / DailyReadError still mark the preview out of date (read errors still invalidate the session like other alert reads).

## Tests actually run (this round)

| Run | Scope | Result |
|---|---|---|
| Development | `tests.test_m32d.SaveTests`, `PublicationBasisTests`, `PairPublicationTests` | 15 run, 2 failures — the test's second external "change" rewrote identical content (UNCHANGED instead of IMPORTED); test fixed to write new content each time |
| Development | `tests.test_m32d.PublicationBasisTests` | 3 passed |
| Final, once (affected save + UI regression) | `python -m unittest tests.test_m32d -v` | **42 passed**, 7.75 s; log `%TEMP%\MRC_M32D_remediation.txt` |

42 = 35 earlier − 1 replaced (`test_failed_publication_leaves_no_complete_looking_report`, which tested the removed two-file protocol) + 8 new. `git diff --check` passed.

**The full suite was not re-run in this round** (no shared business code changed and no cross-module failure appeared). The last full run remains the pre-remediation `%TEMP%\MRC_M32D_full_suite.txt` (370 tests: 365 passed, 5 skipped). M3.2C/M4A suites were not re-run; their code is unchanged.

## Not executed / remaining

- Browser visual/print inspection of the HTML (open, as in the review), EXE packaging, real Drive, second PC, Windows 10, physical DPI — not repeated or claimed.
- Cloud-synchronised or network target folders: directory rename behaviour under OneDrive/Drive clients and slow shares was not tested; a sync client holding a handle makes the rename fail (reported, nothing published).
- The `M3_2D_IMPLEMENTATION_REPORT.md` "Immutability and saving" section describes the earlier two-file protocol; this report supersedes it for saving.
- Other review limitations (strict staleness, local paths in JSON, observation-date attribution, M4A worker limit) are unchanged and remain open.

## Re-review fix — journal mode (M3_2D_CODEX_REREVIEW.md, P1-D1 in WAL)

**Finding:** in a WAL database a held read transaction does not block other commits, so the final basis check could be overtaken by another instance's sync before the rename (Codex reproduced a VERIFIED report over a changed basis).

**Fix (`checker/daily.py` only):** `_publication_basis` reads `PRAGMA journal_mode` inside the same final publication read transaction, before the basis comparison and before the session guard. Supported: `DELETE`, `TRUNCATE`, `PERSIST` (rollback journals, where the held read lock blocks COMMIT). Anything else — `WAL`, `MEMORY`, `OFF` — raises the new `DailyUnsupported` (a `DailyError`): nothing is published, the staging directory is removed (cleanup-failure reporting unchanged). The check runs on every publication attempt, including name-race retries. The database mode is never changed, checkpointed or migrated. Generation and preview remain available in WAL; only saving is refused, with a message saying why. WAL publication is not implemented.

Contract update: Daily Summary saving currently requires a rollback-journal database (this program never enables WAL; the default is `DELETE`).

**Tests added (`JournalModeTests`):**
- `test_default_rollback_journal_saves` — mode `delete`; save succeeds; mode unchanged.
- `test_wal_database_is_refused_without_leftovers_or_mode_change` — synthetic database switched to WAL; VERIFIED and UNVERIFIED summaries still generate; both saves raise `DailyUnsupported`; no report folder and no `.partial` left; mode still `wal`.
- `test_mode_is_checked_in_the_final_transaction_and_on_retry` — WAL switched at the `staged` checkpoint (after the early checks) → refused; WAL switched at the `retry` checkpoint after a name race → refused, the other program's folder untouched; mode left as found.

**Run (once):** `python -m unittest tests.test_m32d.SaveTests tests.test_m32d.PublicationBasisTests tests.test_m32d.PairPublicationTests tests.test_m32d.JournalModeTests -v` → **18 passed**, 2.15 s; log `%TEMP%\MRC_M32D_journal_mode.txt`. During development `JournalModeTests` alone: 3 passed. `git diff --check` passed.

Not run in this round: the rest of `tests.test_m32d` (UI/generation, code unchanged), M3.2C/M4A suites, the full suite, packaging, real data or browser checks. No shared business code changed. No commit, push or release.
