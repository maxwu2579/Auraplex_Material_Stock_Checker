# Analytics and Daily Summary Localisation — Implementation and Focused Checks

Date: 2026-10-23
Baseline: ba8c9aa plus uncommitted History / Stock Alerts localisation.
Status: implemented with focused source verification; not independently reviewed, committed, packaged or released.

## Implemented

### Inventory Analytics

An open/new Analytics window follows the main Chinese / EN / BM selector. Titles, caveats, controls, headings, loading/cancellation/failure feedback, adjustable-policy framing, pagination and unknown-value labels are translated. Original source names, IDs, Sheet names, status/signal codes, timestamps and raw details/limitations remain unchanged.

A language change only renders stored messages and already displayed row cells. It does not query, alter options/policy, clear selection, advance pages, increment generations or change authorization. None remains unknown; valid 0 remains 0. Stop, failures, query cancellation and stale-response checks retain their existing logic.

### Daily Summary

Titles, hints, controls, date-validation framing, generation/save/failure status, default-No UNVERIFIED confirmation, stale-preview messages, save/open dialogs and Task Scheduler draft dialogs follow the main language. Draft generation remains XML-only; no task is installed or enabled.

The preview is rendered from the same immutable DailySummary JSON. English uses daily.render_text unchanged. Chinese/Malay translate preview headings, labels and safety explanations while preserving IDs, paths, times, statuses, quantities and original detail/reason text. Unknown values are not converted to 0; unavailable alerts remain unavailable. The preview retains the existing 200-item-per-list cap.

Interface language does not change the saved HTML/JSON report format (still the existing English report). This distinction is explicitly shown in the window. Original summary JSON/digest, report ID, database basis, authorization and save/publication contract remain unchanged. Changing language during generation or saving does not create a new request or cancel it. A stale/failed preview remains stale/failed after switching.

### Structure and scope

- checker/window_language.py: UI-thread-only helper for stored labels, text bodies, status variables and headings; no query/save/task operations.
- checker/analysis_daily_i18n.py: shared translation resources using existing i18n.Message/Join/render.
- checker/daily_preview.py: pure translated on-screen projection; no external I/O or authorization operations.
- checker/analytics_ui.py, checker/daily_ui.py: window integration.
- checker/ui.py: dispatch current interface-language changes to current open windows; pass language to Analytics.

No calculations, alert rules, query SQL, database schema, source synchronization, provider/agent rules, retention, report publication or business export code was changed.

## Actual checks (no repeated suite)

| Execution | Result | Time |
| --- | --- | --- |
| Existing Analytics failure/reuse and Daily verified-generate/save/stale UI checks | 2 passed | 2.303 s |
| Initial new localisation tests | 7 passed | 13.331 s |
| Added empty-database projection test plus existing Analytics pagination, Daily latest-request/failure, and two schedule-draft checks | 5 passed | 4.063 s |

Total: **14 distinct tests passed (8 new, 6 existing), 19.697 s**. No failures or Tk finalizer warnings printed in these runs. No full suite or previous History/Alerts/R2 suite rerun.

Coverage:
- Language switches preserve selected rows, filters/options, displayed pages, result identity, session authorization, generations and source/database hashes.
- Analysis pending work, Stop and read failure cannot be restored by a language change.
- Daily pending generation/saving completes in the latest language without another request.
- Saving during a language change produces HTML byte-for-byte equal to the original renderer and JSON semantically equal to the original canonical summary.
- UNVERIFIED confirmation defaults to No in all three languages; declining starts no worker.
- Past-date previews retain UNVERIFIED and NOT AVAILABLE; stale previews refuse saving; read failure clears preview and session evidence.
- Unknown and literal zero remain distinct. An empty synthetic database remains UNVERIFIED/UNAVAILABLE with no invented source versions.
- Resource placeholders match across languages.
- 960x600 geometry, three languages, Tk font scaling 100% / 150%: tested controls fit and tables/preview remain above 60 pixels. Geometry assertions are not visual/native-DPI acceptance.
- Schedule drafts retain default-No confirmation, XML-only behavior and no-overwrite protection.

## Remaining work

The four independent windows now have language integration for their interface framing. This is not exhaustive translation of all original query/evaluation/detail narratives. Several raw diagnostics and row-level glosses intentionally remain English. Maintenance/cache/upgrade confirmation bodies and some detail/tooltips still need localisation.

Outside localisation, the roadmap still has M4F purchase-review suggestions, real email sending/automatic notifications; M3.2E missed-schedule/deployment acceptance; final API/data/security and Windows delivery acceptance. RAG remains optional.

## Limits and safety

Used only synthetic Excel, temporary databases and temporary report/draft folders. No real company workbooks/database, real API/Drive, native DPI, second PC, packaged EXE or Windows 10 acceptance. No manual screenshot/visual inspection or 1280/1366 matrix in this slice. No automatic task installation or email sending.

Existing uncommitted localisation work was retained. audit_test_run.txt is untouched. No commit, push, package or release. Obtain independent review of the combined localisation changes before committing.

## Close-lifetime follow-up (2026-10-23)

Analytics/Daily now remove their own variable trace callbacks on close, and shared label registration uses iterative traversal. A targeted test initially reproduced a retained closed Analytics window and then passed for both windows after repair. Existing Stop/close and close-during-generation checks also passed. Details and self-review limitations are recorded in SECONDARY_WINDOWS_L10N_REVIEW.md.
