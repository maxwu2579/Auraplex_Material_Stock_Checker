# Stock Alerts Localisation — Implementation and Focused Verification

Date: 2026-10-23. Baseline: ba8c9aa plus the uncommitted History localisation slice.
Status: implemented; targeted checks passed; not independently reviewed or committed.

## Scope

Stock Alerts follows the main Chinese / EN / BM selector, including open windows. Its title, banner, caveats, rule explanation, controls, table headings, tabs, loading/evaluation/upgrade feedback, read-failure messages, session-verification framing and displayed-count framing are translated. Cloud Not Verified and canonical alert/failure/status codes remain visible unchanged.

A language change re-renders stored messages and selector labels. It does not call load_state, observed_changes_view or request_alerts; it does not re-filter, restart reads or evaluations, change selected rows, pagination, input, database/source hashes or authorization. A pending read finishes in the currently selected language. Closed windows are not subscribed; the main window directly updates only its current open window.

The all-types/all-Sheets/all-changes choices use selector position rather than comparing translated text. Actual Sheet names, alert types and change types retain their exact values. Source-file isolation and resolved/other-source filtering are unchanged.

Read failures still invalidate the owner's evidence through the existing path, clear the failed tab and mark the session NOT RE-CHECKED. Switching language preserves that failure, original details and cleared counts. It does not restore authorization or older successes.

Data-bearing evaluation details, original row narratives, raw errors and row-level status glosses remain verbatim (generally English); evaluation details are explicitly labelled as original. This is not a claim that every secondary-window sentence is translated.

No alert evaluation, SQL, synchronization, migration, transaction, retention, M2 calculation or export code was changed.

## Focused checks

Added 5 tests in tests/test_alerts_l10n.py:
- Live switching preserves loaded alerts/changes, exact filters, row selection, details, source hashes, CHECK state and session authorization; read/evaluate entry points are forbidden during the switch.
- Alert/observed-change read failures stay failed in all three languages, including raw error details and no resurrected counts.
- A held background read is not restarted by switching; completion and reopening use the latest language.
- 960x600 geometry at Tk font scaling 100%/150%, in three languages: tested controls stay inside the window and the alert table remains above 60 pixels.
- Resource-format placeholders are equivalent across languages.

Also ran existing checks for automatic evaluation, alert/observed-change filters, and read-failure invalidation/reopening.

Actual executions:
- Existing automatic-evaluation check alone: 1 passed, 1.051 s.
- Five new tests plus two existing filter/failure checks: 7 passed, 26.177 s.
- **Alerts scope: 8 distinct tests passed.** No full suite, R2 suite or unrelated modules.
- git diff --check passed; audit_test_run.txt SHA-256 remains 307AA1DF2B507A48D936081F35F0F5367FDC9168AEF1E4EC490A4117A96CE7EC.

## Follow-up of the prior Tk finalizer warning

The previous History test run printed ignored Tk Variable finalizer errors while using multiple temporary Tk roots/windows. The new localisation fixtures now explicitly release test-owned app/window/root references and collect destroyed UI object cycles on the main thread, before another test's workers start. The compact-window loop also collects destroyed-window cycles on that thread.

Reran only the five History localisation tests, with sys.unraisablehook recording finalizer exceptions: **5 passed, 17.648 s; zero unraisable exceptions recorded.** The Alerts run above also printed no such warning. This is targeted evidence after improving fixture lifetime management, not a complete proof of the original cause or of production-wide thread safety. No production threading/cancellation code was changed to suppress the warning, and the hook forwarded any captured exception to the original handler.

## Remaining work and limits

Analytics and Daily Summary localisation remain pending, as do maintenance/cache/upgrade confirmation bodies and some raw detail explanations. No real data, Drive, API, manual visual/screenshot review, packaged EXE, physical Windows DPI, second PC or Windows 10 acceptance. Geometry checks are not native-DPI or visual acceptance. No commit, push, package or release.

## Completion review follow-up (2026-10-23)

SECONDARY_WINDOWS_L10N_REVIEW.md supersedes the earlier provisional Tk-warning interpretation: window-level off-thread collection reproduced the error. Worker callbacks now capture plain values/queues and iterative label traversal avoids a recursive closure cycle. Close/held-read regressions pass with zero captured finalizer errors; no alert calculation or transaction code changed. This remains source self-review, not independent packaged acceptance.
