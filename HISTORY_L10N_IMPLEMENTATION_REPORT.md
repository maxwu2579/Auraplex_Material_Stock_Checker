# History Window Localisation — Implementation and Focused Verification

Date: 2026-10-23. Baseline: ba8c9aa (Reliability R2 local commit).
Status: implemented, focused source checks passed; not independently reviewed or committed.

## Change

The Inventory History window now receives the main interface LanguageState and re-renders when the main Chinese / EN / BM selector changes. A newly opened window uses the current language. No separate language preference or subscription survives a closed window.

Translated: window title, permanent historical/cloud warning, safety caveats, control labels, search feedback, Sheet-filter placeholder, range controls, tab names and counts, column headings, initial detail hint, query/loading/failure status and coverage-summary framing. The translation resources live in checker/history_i18n.py and use the existing i18n.Message/Join/render path. Parameters are retained separately, rather than translating already-formatted source strings.

Switching language does not read Excel or SQLite, restart queries, change worker generations/limits, or change source selection, quantities, authorization, calculated results or pagination. Already-running work renders its completion in the current language. Candidate selection and actual Sheet names remain exact. The all-Sheets choice is identified by its combobox index instead of its translated string.

Failed queries remain failed, with cleared rows and cleared counts. A subsequent language change cannot resurrect the previous loaded-count message.

## Deliberately partial localisation

This is the first History-window localisation slice, not completion of all application languages:
- Raw codes, material descriptions, source paths, Sheet names, quantities and timestamps are preserved.
- Existing query-layer notes, per-row detail narratives, change explanations and row-level status glosses remain in their original English. Coverage explicitly labels original query notes. No regex substitution is applied to data-bearing notes.
- Alert, analytics and daily windows, plus maintenance/cache/upgrade dialogs, remain separate follow-ups.
- Assistant reply routing and exported report language are unchanged.

History-query/business/database/retention/export modules were not changed.

## Focused verification

Added 5 tests in tests/test_history_l10n.py:
1. Three-language switching with loaded rows, selected candidate/row, source/filter/input preservation, unchanged source/database hashes and forbidden reads.
2. Language changes during a held background query: no restart; eventual result uses the latest language.
3. Failure stays failure after switching; no old rows/counts; reopen uses the current language; original error details preserved.
4. Equivalent resource placeholders; actual Sheet names passed unchanged to the query and retained across switching.
5. 960x600 geometry in three languages at Tk font scaling 100% / 150%; controls remain inside the window and the records table stays above 60 pixels.

Also ran two directly affected existing M4A tests: query flow/historical labels/read-only hashes, and 200-row pagination.

Successful runs:
- Initial four new tests + two existing tests: 6 passed, 11.840 s.
- After tightening stale-count clearing and candidate-selection coverage: the two affected new tests plus the new compact-layout test: 3 passed, 12.658 s.
- These are 9 successful test executions covering **7 distinct tests**, not 9 distinct tests. No full suite, R2 suite or unrelated modules were run.

Development failures: the first two attempts failed at a common initialization/query path because the new message wrapper used a reserved `key` parameter and a local `_clear` parameter shadowed the message helper. Both implementation errors were corrected before the successful runs. The assertions were not weakened.

Important warning: the second successful run printed four ignored Tk Variable finalizer exceptions (`RuntimeError: main thread is not in main loop`) while the three assertions/tests still passed. These were not ordinary Tk callback errors. Their cause was not independently isolated; no claim of warning-free thread/lifecycle acceptance is made. Review this signal before treating the slice as commit-ready. Do not broaden it into unrelated changes without reproducing the cause.

`git diff --check` passed. audit_test_run.txt hash stayed 307AA1DF2B507A48D936081F35F0F5367FDC9168AEF1E4EC490A4117A96CE7EC.

## Not executed

No screenshots or manual visual inspection, native DPI, 1280/1366 matrix, real company data, real Drive/API, packaged EXE, second PC or Windows 10. Tk geometry checks are not visual/native-DPI acceptance. No production user configuration was written by the tests.

No commit, push, packaging or release. Next: independent review, including the Tk finalizer warning, before committing; then continue the remaining secondary-window localisation slices.

## Follow-up: test-owned Tk object lifetime (2026-10-23)

The History localisation fixture now releases its app/window/root references and explicitly collects destroyed Tk cycles on the UI thread before subsequent workers start. With an unraisable-exception recording hook, the five History tests passed in 17.648 s with zero finalizer exceptions. This narrows the earlier warning to a test-object lifetime concern but does not prove its complete cause or production-wide absence. No production thread/cancellation logic was changed for this follow-up. See ALERTS_L10N_IMPLEMENTATION_REPORT.md.

## Correction and source-lifetime follow-up (2026-10-23)

Subsequent deterministic window-level review reproduced four Tk Variable finalizer errors when a closed History window was collected on a background thread with its master app still alive. The warning therefore cannot be attributed only to test fixtures. Bound lane callbacks, UI-owning worker closures and the recursive localisation visitor were removed as retainers. History/Alerts close/held-read tests now force off-thread collection and assert zero finalizer errors. Analytics/Daily variable traces were also explicitly released on close. See SECONDARY_WINDOWS_L10N_REVIEW.md for reproduced failures, corrections and scope. Its conclusions supersede earlier suggestions that the warning was narrowed to test-only lifetime management.
