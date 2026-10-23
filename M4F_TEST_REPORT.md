# M4F First Slice — Test Report

Updated: 2026-10-22

## Results

- Latest M4F-specific tests after P1 remediation: **26 passed, 0 failed**, 4.265 seconds.
- Related regression command (`tests.test_m4f`, `tests.test_m4e`, `tests.test_m4d`, `tests.test_m4c`): **134 passed, 0 failed**, about 29 seconds.
- `py_compile` for changed Python modules and the new test module: passed.
- `git diff --check`: passed.

No full repository test suite was run.

## M4F cases exercised

- Daily and weekly fact shapes, weekly observed-event comparison, incomplete/pruned history, unknown alert counts, and strict allowlisted field validation.
- No Material IDs, descriptions, Sheet names, local file paths, hashes or database rows in the API payload; no tool definitions are sent.
- Building a local preview reads no key and makes no request.
- General API permission and separate one-report permission are both required. The one-use grant is tied to the database basis, aggregate-fact digest, output language and exact serialized request SHA-256.
- Changed request bodies and a database update after preview are rejected before provider network calls. Declining the dialog sends nothing; Yes submits the exact reviewed request once.
- Numeric-digit AI claims are discarded. Successful AI answers retain the UNVERIFIED / Cloud Not Verified presentation.
- Report preview clears after source invalidation and after a database-basis mismatch. The new report page was checked in a simulated 960×600 source UI window.
- New report/disclosure text and stale-report errors have Chinese, English and Malay variants.

## Test boundary

All files and databases used for destructive or failure scenarios were synthetic and temporary. API transport and key access were fake. No live provider/API request, real company workbook/database, Google Drive mount, packaged EXE, Windows 10, second PC or physical high-DPI display was tested. The UI measurement is a source-level simulation, not native-DPI acceptance.

This is implementation evidence for independent review, not a milestone acceptance or release claim. No commit, push, packaging or release was performed.

## Claude review remediation — 2026-10-22

P1-F1: quality counts are now separate for Storage and BOM. Each role without a published source version has null counts, rendered as unknown in the preview and preserved as null in the API facts. Known clean sources still have zero counts. NUMERIC_MATERIAL_ID is included separately for each role (also addresses P2-2).

P1-F2: each period exposes recorded Storage sync attempts and successful Storage checks. Weekly comparison requires coverage from the start and at least one retained snapshot or successful Storage check in each window. Failed checks and BOM checks alone do not establish Storage observations. A successfully checked but unchanged week remains eligible; an unobserved week has INCOMPLETE_HISTORY with null deltas, rendered as unknown. Eligibility does not imply continuous observation or comparable observation frequency.

Eight new regressions cover no sources, Storage only, BOM only, numeric ID issues per role, an unobserved prior week, successful UNCHANGED checks, failed/BOM-only checks, and preview rendering of unknown quality/deltas. The existing weekly test now explicitly establishes a previous-window observation rather than assuming that an older baseline implies observations during that window.

Final command: `.venv\Scripts\python.exe -m unittest tests.test_m4f -v` — 26 passed in 4.265 seconds. `git diff --check` passed. No shared M2/M3 business code changed, so the full suite and M4D/E regressions were not repeated. The earlier 134-test run above predates this remediation.

Remaining review P2s: the AI reply guard enforces digits/tool-call rejection, while other unsupported wording is prompt-constrained (P2-1); the preview body remains English (P2-3). No live API test or independent re-acceptance is claimed. The user's already-open demo process was left running; it must be restarted to load the corrected source.

## Final review update (2026-10-22)

See `M4F_FINAL_REVIEW.md`. P1-F1/P1-F2 and P2-2 were independently re-checked. P2-1: a conservative trilingual keyword guard (`narrative.reply_problems`) now discards narrative replies that state counts or plainly claim sufficient/production-ready stock, cloud verification, actual consumption or a purchase action (`NARRATIVE_REJECTED`; local counts kept; not a guarantee). P2-3: the local preview is rendered in Chinese, English or Malay from the same facts and follows the assistant language. Final runs: `tests.test_m4f` 34 passed (4.66 s); `tests.test_m4d tests.test_m4e` 67 passed (8.13 s). Full suite not run.
