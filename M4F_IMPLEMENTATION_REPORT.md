# M4F First Slice — Implementation Report

Updated: 2026-10-22

## Scope delivered

The assistant has an **AI reports** tab with a daily local preview and a weekly comparison. The weekly window uses the previous seven complete local days and compares aggregate observed-change event counts with the preceding seven-day window. The existing deterministic M3/M4 calculations and alert classifications are reused without changing their business rules.

Report facts are assembled inside one read-only SQLite view. The report includes only fixed status enums, date windows, aggregate counts, history-coverage state, recorded sync outcome/times, retained Storage data-quality counts, and alert-category counts when a matching stored evaluation exists. Unknown or pruned values stay unknown. Alert counts are labeled stored/not re-checked, categories may overlap, and an absent snapshot is not treated as proof of no change.

## External data and consent

Building a preview is local and does not read the API key or make a network request. Sending requires both the existing session-level API permission and a separate confirmation for that report. The confirmation defaults to No and shows the exact serialized DeepSeek request. If a previously authorized account-balance check is due, the dialog discloses that a separate balance request may also occur.

The request contains aggregate periods and category counts, sync outcomes/times, history coverage and data-quality counts. It excludes Material IDs, descriptions, individual stock/BOM quantities, Sheet names, local paths, file hashes and database rows. The narrative request has no tools or tool-calling definitions. A one-use approval is tied to the session epoch, database basis, fact digest, response language and SHA-256 of the exact request body. The provider rechecks that body hash before reading the key or making a request. A changed database basis or request is refused.

The preview and AI response remain **UNVERIFIED / Cloud Not Verified**. AI output is qualitative and is checked for length, tool calls and numeric digits; invalid responses are discarded. Prompts forbid causal claims, forecasts, production decisions and purchase recommendations. No purchasing suggestion, order action, email notification or report-file delivery is implemented in this slice.

## Files and compatibility

- Added `checker/narrative.py` for allowlisted aggregate facts, strict validation, weekly comparison and request construction.
- Updated `checker/assistant.py`, `checker/providers.py`, `checker/agent.py`, `checker/assistant_ui.py` and `checker/assistant_language.py` for local preview, per-report consent, request binding and the trilingual report UI.
- Added `tests/test_m4f.py`.
- Updated `README.md` and `DEVELOPMENT_ROADMAP.md`.
- No dependency, database schema, source workbook, inventory data or M2 calculation rule changed. Reports are not persisted.

## Acceptance boundary

The implementation is ready for independent source review, not milestone acceptance or release. Verification used synthetic workbooks and temporary SQLite databases with fake API/key providers. No real API, company data, real Google Drive, packaged EXE, second PC or native high-DPI environment was used. Purchase-review suggestions and email notifications remain future M4F work.

## Fact-accuracy remediation after Claude review

P1-F1: recorded issue counts now preserve role identity. Unsynchronised roles use null/unknown instead of zero, and numeric Material ID issues are counted for both roles (P2-2).

P1-F2: weekly comparison also requires an actual Storage observation in each window: a retained snapshot or a successful IMPORTED/UNCHANGED check. Per-window attempt and success counts are disclosed. Failed checks alone never establish observation. Missing observation yields INCOMPLETE_HISTORY and unknown deltas; successful unchanged checks permit genuine zero recorded change events. These are observed event counts, not consumption, and unequal sampling frequency remains a limitation.

The preview renders unknown issue counts and comparison deltas explicitly. Only narrative construction, preview rendering, tests and documentation changed in this remediation. M4F targeted tests: 26 passed; see M4F_TEST_REPORT.md. P2-1 (model wording guard limitations) and P2-3 (English preview body) remain open. No commit or live API call was made.

## Final review update (2026-10-22)

See `M4F_FINAL_REVIEW.md`. P1-F1/P1-F2 and P2-2 were independently re-checked. P2-1: a conservative trilingual keyword guard (`narrative.reply_problems`) now discards narrative replies that state counts or plainly claim sufficient/production-ready stock, cloud verification, actual consumption or a purchase action (`NARRATIVE_REJECTED`; local counts kept; not a guarantee). P2-3: the local preview is rendered in Chinese, English or Malay from the same facts and follows the assistant language. Final runs: `tests.test_m4f` 34 passed (4.66 s); `tests.test_m4d tests.test_m4e` 67 passed (8.13 s). Full suite not run.
