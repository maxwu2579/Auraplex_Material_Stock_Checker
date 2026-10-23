# B1 Round 2 localisation — Codex focused review

Date: 2026-10-23. Baseline: HEAD `d545995` plus the existing uncommitted B1 shell and Round 2 work.

## Decision

**GO for a local source commit, with P2-L10N-1 recorded below.** No P0/P1 was identified in the inspected Round 2 paths. This is not whole-application localisation, full regression, release or real-environment acceptance. No commit was made in this review.

## Source inspection

Reviewed `InterfacePreferences` and its app-entry wiring, the message/State/Join renderers, `_set_status`, `_language_changed`, main-window error/status construction, the new tests and adapted legacy assertions. Preferences use their own `interface.json`; existing `Settings` operations are unchanged. Temp-file/fsync/replace publication leaves the earlier preference intact on a failed replace. Startup loading does not itself save the preference.

Main-window status is retained as a template and captured values; re-rendering does not call readers or recalculate statistics. The original task-generation checks and refusal/state-invalidation branches remain in place. Legacy test changes replace Chinese-only fragments with their English-interface equivalents while preserving the assertion's substantive fact, not weakening result/export guards. Independent window translation and a few canonical labels/detail surfaces remain outside this slice, as disclosed.

No production code, test code, source workbook, real database, API key or user application window was changed by Codex. This review adds this report and updates stale roadmap status only.

## Independent verification

The developer-reported 80 tests / 117.2 seconds and smoke test were not repeated as a group.

1. `PreferenceFileTests` (2), `PreferenceAppTests` (4), `StatusLanguageTests` (4): **10 passed in 4.615 seconds**. Covers default/corrupt files, atomic replacement failure, settings isolation, restart restoration, write failure preserving session state, snapshot rendering and failure/running-job language switching.
2. Real `app.main()` bootstrap in a temporary `--data-dir` with `--smoke-test`, seeded with `interface.json` language `ms`: **PASS, 0.375 seconds** measured. The actual `CheckerApp` initialisation was observed; its initial language was `ms`, and Home's title was `Gambaran stok & amaran`. Preference bytes stayed unchanged and no source-path `settings.json` was created. Credential loading and socket connection were patched to fail if attempted; neither occurred. Only the temporary bootstrap database was created, never the real app-data folder.
3. Independent same-language recovery probe: reproduced P2-L10N-1 below using a temporary corrupt preference file and the actual EN button.

`git diff --check` passed. No full suite, earlier 94 tests, 17-module group, packaging or screenshot matrix was rerun.

## P2-L10N-1 — Choosing the already-active language cannot retry preference saving

Location: `checker/ui.py` `set_language` / `_language_changed`, and `checker/i18n.py` `LanguageState.set`.

`LanguageState.set` returns immediately for the current language. Preference saving and clearing the read/write problem warning happen only in `_language_changed`. Consequently an explicit click on an already-active language never retries saving.

Independent reproduction:

- Put `{broken` into a temporary `interface.json`.
- Start the real UI with that preference object: language falls back to English, with the expected recovery warning.
- Click the actual EN button.
- Language is still `en`, the file is still `{broken`, and the warning remains visible.

Likewise, after a failed preference save, selecting that same current language cannot retry once the folder becomes writable. Switching to another language works, so this is a minor recovery/usability defect, not a calculation, data-integrity or authorisation defect.

Suggested bounded fix: separate explicit preference-save/retry from translation change notifications. An explicit same-language selection can retry saving and refresh the preference warning without re-rendering the whole UI, rereading sources or changing authorisation. One corrupt-file/same-EN case and one recovered-writeability/same-language case are sufficient targeted tests; do not rerun the whole 80-test group for that fix.

## Remaining limits

- Alerts, History, Analytics, Daily and several maintenance/cache dialog bodies are not fully localised. The assistant's language is intentionally independent.
- Underlying error details remain raw; some result labels, alert entry text, detail popups and tooltips still use their earlier language.
- `InterfacePreferences.load` accepts a recognised language without enforcing the stored version. No compatibility/security claim beyond this simple current format is made here.
- No write was made to real `%LOCALAPPDATA%`; no real company data, API, mail client, Drive, EXE, Windows 10, other PC, physical DPI or new visual acceptance was tested.
- Passing these focused checks does not complete the earlier interrupted broad B1 regression.

The roadmap now records main-window status/dialog translation and language persistence as implemented and source-reviewed, while keeping the actual remaining surfaces and the P2 recovery follow-up open.
