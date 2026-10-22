# M3.2D — Daily Stock Summary: implementation report

Date: 2026-10-22 (local, UTC+08:00). Base commit: `adee725` (accepted M4A + M3.2C, committed locally in this session before development). M3.2D is **uncommitted working-tree code awaiting Codex review**. Nothing was pushed, built, packaged or released. M3.2E and M4B were not started.

## Scope delivered

Manual generation, preview and saving of a one-day **Daily Stock Summary** as a self-contained HTML page plus the matching JSON data. No AI, no e-mail, no scheduled task, no background server. The service (`checker.daily.generate` / `save`) has no Tk dependency so M3.2E can call it unchanged.

| File | Change |
|---|---|
| `checker/daily.py` (new) | Day window, one-view collection, verification contract, immutable `DailySummary`, HTML/text rendering, no-overwrite save, bounded `DailyRunner` |
| `checker/daily_ui.py` (new) | Daily Stock Summary window: date (◀ / Today / ▶), Generate, preview, Save HTML + JSON…, Open saved report |
| `checker/alerts.py` | Refactor only: `load_state` body extracted to `state_in(conn, …)` so the summary reads alerts inside its own read transaction. `load_state` behaviour unchanged |
| `checker/ui.py` | `Daily Summary…` link beside the Stock Alerts line, `open_daily()`, `daily_session()`, window closed on exit. No change to CHECK, sync, alerts, cache, export or maintenance logic |
| `tests/test_m32d.py` (new) | 35 tests (service, date window, verification, saving, runner, window) |
| `README.md`, `DEVELOPMENT_ROADMAP.md` | M3.2D section / status; note that M3.2E reuses the service |

No schema change (schema 3 used as is; schema 1/2 databases work, alerts are then shown as unavailable). No new dependency. Excel is never parsed by the summary.

## Report content

1. **Report information** — report date (today / past), time-zone label, local and UTC day window, generation time, report ID, status, reasons, database basis (schema, current Storage/BOM version, newest sync-run IDs, newest alert-evaluation ID). Per source: current version (file, path, import time, file modified time, SHA-256, counts), the version in effect at the end of a past day, versions imported that day (with source-switch flag), latest check, last verified check, freshness state, the version/path this session verified, and that day's check outcomes. Cloud Not Verified is always present.
2. **Stock alerts** — from the stored M3.2C alerts of the current files (no rule re-implemented). Per type: alerts, distinct Material IDs, entries without an ID, Storage Sheets, DATA_ISSUE subtypes; distinct IDs with any alert; an explicit note that per-type counts are not a number of materials. Item list with raw values, threshold column/header, trial shortfall, first/last seen. Alert evaluations recorded on the date (recorded counts only). Other-source active alerts counted, not included.
3. **Observed changes** — inventory changes whose snapshot `observed_at` falls in the day window, all source files: counts and distinct IDs per change type, every Storage snapshot of the day, source switches (Storage and BOM), items with before/after as recorded, the observed difference only for two single valid records of the same file (otherwise `null` with a reason). "Observed Change ≠ Actual Consumption" and the attribution rule are always present. An empty day says "no record", explicitly not "no movement".
4. **Data limitations** — history coverage (`NO_HISTORY`, `BEFORE_HISTORY`, `REMOVED`, `PARTLY_REMOVED`, `STARTS_DURING_DAY`, `COVERED`) with the cleanup boundary, log-retention note, synchronisation notes (never synchronised, latest check failed, not checked that day, failures that day), threshold column state per Sheet with the pending-confirmation note, raw Storage counts (blank, invalid, without usable ID, duplicate IDs) from the current snapshot, data-quality issues of the current versions, and a "not calculated" list (actual consumption, cross-material totals, differences of non-quantity changes) with `value: null` and the reason.

## Date handling

`day_window(day, tz)`: local midnight of the day (inclusive) and of the next day (exclusive), converted to UTC stamps; queries use `>= start AND < end`. Local time uses the computer's zone (`tz=None`); tests inject fixed and DST zones. The time-zone label and the offsets at both ends of the day are recorded. Future dates are refused. A past date is always UNVERIFIED.

## Verification contract

The UI captures a `Session` on the Tk thread: gate generation, the M3.2C `Authorization` (version + selected path per role) and whether a verified alert evaluation of that generation was confirmed. `generate()` reads everything in **one** `history.read_view` transaction, then:

- VERIFIED requires: date == today; Authorization present and `alert_current`; the gate still at that generation after the read; database current versions equal the authorised version IDs; newest sync run of each role a success for that version and of the authorised path (`same_path`); the newest COMPLETED evaluation of the current file scope is of exactly the current Storage and BOM version IDs; and every in-scope ACTIVE alert was last confirmed by that evaluation. An evaluation of an older version of the same path is never accepted.
- Otherwise `ConfirmationRequired(reasons)` unless `allow_unverified=True` (given only after the user's explicit, default-No confirmation). The UI pre-checks the obvious cases (past date, unverified session) and asks before starting; a problem found by the worker produces a second confirmation.
- Alert section status: `CURRENT` (verified), `STORED_NOT_RECHECKED` (evaluation matches the current versions but this session did not re-check; listed and labelled with basis/time), or `UNAVAILABLE` (schema < 3, no data, no verified evaluation, version lag, or inconsistent rows; nothing listed, "not a statement that there are no alerts"). For a past date "alerts for that date" is always *not available*; the alerts at generation time are listed separately with their actual basis and time.
- No text anywhere states that stock is normal or sufficient.

## Immutability and saving

> Superseded for saving by `M3_2D_REMEDIATION_REPORT.md` (P1-D1/P1-D2): the pair is now published as one report folder by a single directory rename, with the database basis re-checked under a held read lock immediately before it. The two-file description below is historical.

`DailySummary` is a frozen dataclass holding the canonical JSON text, report ID, date, verified flag, gate generation and database basis. The preview, the HTML and the JSON file are all produced from that text; the JSON file is the text itself and the HTML records its SHA-256 and the report ID in `<meta>` tags and the footer.

`save(summary, folder, database, gate)`:
1. folder must exist; re-reads the database basis in a read view — any difference (new version, sync record, alert evaluation) → `DailyStale`; a VERIFIED summary whose gate generation moved → `DailyStale`;
2. stages `.mrc-daily-*.json.partial` / `.html.partial` in the target folder, fsyncs and reads each back;
3. publishes both under the M3.2C `SessionGate.publishing` guard (VERIFIED summaries only), with no-overwrite rename (Windows) / link (POSIX); an existing name gets ` (n)`; if the second file cannot be published the first is removed; staging files are always removed.

File names: `[UNVERIFIED_]Daily_Stock_Summary_<YYYY-MM-DD>_generated_<YYYYMMDD_HHMMSS>.html|.json`. The HTML has inline CSS only (print styles included), no scripts, fonts, images or links; all dynamic text goes through `html.escape(quote=True)`.

## Window behaviour

- One `DailyRunner`: one task plus one newest waiting request (a newer request replaces the waiting one). Generate requests carry IDs; only the newest generation result is applied. Save is disabled while anything runs, and Generate is refused while a save runs.
- A failed generation clears the preview ("GENERATION FAILED — no summary is shown"). A database read failure (generation or save) calls the application's `alert_read_failed`, exactly like the M3.2C windows: the session's verification and its evidence are discarded until Refresh Excel.
- A VERIFIED preview is marked **OUT OF DATE** (Save disabled) as soon as the gate generation changes or the application's alert state is no longer current; a preview whose date differs from the selected date cannot be saved.
- Only the Tk thread touches widgets (50 ms poll). Close cancels the poll and closes the runner; a running task completes but nothing is delivered.
- Layout: the entry is a link on the Stock Alerts line, so the top button row and the title keep their previous width (measured worst-case link row 507 px vs. 519 px button row at 100 %). Save / Open / Close sit in a footer row and remain visible down to 760×480.

## Data safety

Read-only `mode=ro` connections; no database write, migration, upgrade or cleanup; Excel, stock values and Drive settings untouched; source workbooks never opened. Report files are new files only. M2 calculation/matching, M3.1 version/freshness/export safeguards, M3.2A cache authorisation, M3.2B backup/cleanup/rollback, M3.2C authorisation/isolation/de-duplication and M4A history queries are unchanged (the only shared-code edit is the behaviour-preserving `state_in` extraction).

## Known issues and limitations

1. **Past alert state is not reconstructible** (by design); evaluations of that day are shown with their recorded counts only, and evaluation history is bounded (newest 200 + provenance), so the list can be incomplete.
2. **Attribution is by observation time.** If the program did not synchronise on a day, that day's edits appear on the later synchronisation date. Business dates are never inferred.
3. **Strict staleness.** Any newer sync record or alert evaluation (even UNCHANGED/UNVERIFIED, e.g. from Refresh Excel or Re-evaluate) makes a preview unsaveable; the user must regenerate.
4. **Not a single atomic DB+file step.** Another program can commit between the save-time basis check and the rename; the files then remain a correct point-in-time report of their recorded basis. The publishing guard holds this session's gate lock during two renames, so `invalidate()` may wait for them (milliseconds locally; longer on a slow network folder).
5. **Fail-closed reads.** As in M3.2C, a transient lock during an alert publication can make a generation fail and discard the session verification (Refresh Excel restores it).
6. Large summaries: the HTML lists every loaded row (≤ 5,000 alerts, ≤ 2,000 changes) without pagination; the preview shows 200 per list. No volume/performance benchmark was run.
7. "Distinct Material IDs" counts normalised IDs across Sheets; per-Sheet entries are listed separately.
8. The time-zone name comes from Windows; the offsets are authoritative. Not tested with a real DST zone on Windows (DST logic tested with a synthetic tzinfo).
9. The JSON contains full local source paths (provenance). Consider this before sharing reports outside the company.
10. The entry link (like the Stock Alerts link) is mouse-only; there is no keyboard shortcut.
11. Thresholds/units remain pending business confirmation (inherited from M3.2C).

## Not executed (not claimed)

- Frozen EXE / portable package build and run; real Google Drive behaviour; second PC; Windows 10; physical high-DPI or printer output.
- The saved HTML was checked by tests and by reading the generated sample text; it was **not** visually inspected in a browser or printed in this session. No screenshots were taken (Pillow is not installed and was not added).
- No real company workbook or the user's real database was opened.

## Evidence

Synthetic samples (temporary workbooks + temporary database, deleted after generation) in `%TEMP%\MRC_M32D_evidence\` — not in the repository or any release:
- `Daily_Stock_Summary_2026-10-22_generated_20261022_091510.html/.json` — VERIFIED; alerts of all types, observed quantity/blank/invalid/duplicate/added/removed changes, a synthetic UNAVAILABLE check, hostile `<script>`/`<A>`/`&` text.
- `UNVERIFIED_Daily_Stock_Summary_2026-10-21_….html/.json` — past date, confirmed UNVERIFIED.
- `UNVERIFIED_Daily_Stock_Summary_2026-10-23_….html/.json` — unverified session, no observed change.
- `PREVIEW_verified_2026-10-22.txt`, `README.txt`.

Test details: `M3_2D_TEST_REPORT.md`.
