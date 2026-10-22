# M4E — Focused source verification

Date: 2026-10-22. Base `d25ad29`; development verification, not an independent acceptance audit.
All workbooks/databases/providers used here are synthetic. No live API/company data or application key.

## Final checks

| Run | Scope | Result |
| --- | --- | --- |
| Broader UI/freshness regression | M4E (35 then), M4D (31), M4C (49), base UI (7), M3.1 InventoryUi/CheckBinding/FailureOverride/CloudNotice (29) | 151 passed, 0 skipped/failed, 44.190 s |
| After final status-query basis guard and its new test | M4E (36), M4D (31), M4C (49) | 116 passed, 0 skipped/failed, 16.859 s |

There are **152 distinct tests** across these two runs. The earlier 36 base/M3.1 UI checks were not repeated
after the narrow assistant-controller/language follow-up; their main integration code was unchanged. The final
run covers every M4E test and all M4C/M4D tests. No production code changed afterwards. Only docs and isolated
screenshot tooling were updated. Full suite was intentionally not run; this avoids repeated unaffected
business/retention/scheduler tests. No new dependency or EXE build was needed.

Commands:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_m4e tests.test_m4d tests.test_m4c tests.test_ui tests.test_m31.InventoryUiTests tests.test_m31.CheckBindingTests tests.test_m31.FailureOverrideTests tests.test_m31.CloudNoticeTests -q
.\.venv\Scripts\python.exe -m unittest tests.test_m4e tests.test_m4d tests.test_m4c -q
```

## Covered by 36 M4E tests

- All roadmap Chinese/English/Malay cases, mixed precedence, turn switching, explicit/manual overrides,
  identifiers/technical tokens/source labels/quotes, full-width identifiers and unspaced Chinese IDs.
  Shared/uncertain words explicitly retain the previous language rather than guessing English.
- All translated warning/error templates; identical stock and required quantities across reply languages.
- Denied/restarted independent cache/API permissions; preview performs no credential read/network request.
  Real source UI No-default data dialog and actual scrollable API preview/Yes/No controls are exercised.
  Accepting either old dialog after invalidation cannot restore permission, even without a database change.
- Offline actual candidate selection; similar IDs and whitespace-distinct Sheets remain separate. Invalid
  candidate/product/Storage selection and malformed/nonpositive/out-of-range quantity inputs are refused.
- Blank, text `0+10`, duplicate and missing records preserved. Empty searches clear old candidate capabilities.
  BOM/multiple products, shortage estimates, history/analytics and unevaluated-alert states use existing tools.
- Two-round mock DeepSeek output uses local stock 100, discards invented stock 999999/freshness prose, and
  omits source paths/stock quantities from outgoing projected evidence. Workbook/SQLite digests and mtime
  are unchanged by the assistant. Provider rate failure leaves authorized direct tools usable.
- Database version changes/read failure, queued/in-flight late results, rapid overlapping requests, Stop,
  closure during authorization and late consent grant are refused/revoked. A status-only query cannot
  silently upgrade old consent to a newer database basis.
- Main Refresh, unrecorded source failure and maintenance start revoke both permissions. Main close leaves
  no assistant callback/permission. Append/widget callbacks run on the test's Tk thread.
- Masked-key host operations use fake storage, revoke prior permissions and do not echo keys into results.
  No real application credential target is read. M4D regression separately creates/deletes its existing
  randomized synthetic Windows Credential Manager target; it does not use the application's target.
- Chat Send/Enter and Shift+Enter behavior, disabled controls during jobs, preserved draft after collapse,
  fixed historical/cloud banner, offline data access and no automatic quick-question sending.
- Persistent quota observation/time/due state, low/unknown/exhausted credit, local request/output caps,
  selected-language notices and deduplication; arming a balance recheck sends nothing by itself.
- 960×600, 1280×720 and 1366×728 main-window geometry with available Tk scaling simulations. Small windows
  use separate chat. Wide dock mode leaves >=960 px for the checker in its geometry test.
- Explicit 150% point-size enlargement verifies font line metrics actually increase by >=40%, since changing
  Tk scaling alone can reuse cached fonts. It checks visible warning/actions/input and an actual candidate
  row at 680×555 chat size; Settings notes remain accessible through scrolling.

## Visual checks and evidence

Temporary evidence: `%TEMP%\MRC_M4E_4ob3i_8o\` (outside repository/release). `capture.py` uses only its own
synthetic application's window handles with PrintWindow; it imports available bundled Pillow for PNG output,
without installing it in the project. It drives the source host using fake credentials/transport and deletes
only its own temporary workbook/database fixture on exit. Each capture records **0 network calls / 0 key reads**.

Reviewed final images:

- `fresh_scale_1.0_layout2\main_960x600.png`: robot, CHECK/EXPORT, source/cloud warning and material table.
- `fresh_scale_1.0_layout2\chat_font100.png`, Local tools and Settings variants.
- `fresh_scale_1.5_layout2\chat_font150.png`, `local_tools_font150.png`, `settings_font150.png`:
  actual candidate visible, key controls visible, notes scroll, chat controls and quota status visible.

Fresh separate-process scaling runs set Tk scaling before building widgets. Input line spacing measured
17 px / 28 px, confirming enlarged fonts rather than trusting the scaling setting alone. This is source
software/font simulation, not native physical-DPI acceptance on this 300% desktop. Legacy `chat_150.png`
captures made after switching scaling in-process can reuse old fonts; they are not evidence of enlarged text.
Wide-window captures extend beyond the monitor and contain black/offscreen regions; wide layout is covered
by geometry checks only, not claimed as a full visual/physical-monitor pass.

## Development corrections

The initial 27-test run had eight failure entries (including six layout subcases) and one harness error.
The harness tried to JSON-serialize its cancellation object, measured a new Toplevel before it mapped,
clicked before queued authorization re-enabled a button, and let the window manager cap a simulated wide
window to the monitor. These were corrected without weakening the assertions; the 27-test run then passed.

Source visual inspection additionally found compressed candidate space and clipped Settings notes with
real enlarged fonts. Compact labels, width-aware wrapping and scrollable Settings notes fixed them. Inspection
also fixed mixed-evidence formatting and added the final explicit status-query basis guard. Regression tests
cover mixed stock/analysis/estimate rendering, stale dialogs and status-version invalidation.

## Integrity and limitations

- Source M2 engine/readers, M3 sync/transactions/export, database/schema, retention, scheduler, M4A/B and M4C/D
  implementations were not changed. `checker/ui.py` has only assistant integration/lifecycle/available-width hooks.
- No real Storage/BOM, real database, real key, real Google Drive or account/billing API was used. Source-read
  protection evidence is synthetic hash/mtime plus the existing related regressions, not a new real-file audit.
- No full suite, packaged EXE, Windows 10/another PC, native physical DPI, live TLS/API failure, or company
  outbound approval/model/account compatibility check was executed. No cloud freshness is claimed.
- No release artifact was opened/rebuilt/rehashed. No new artifact hash-verification claim is made.
- Language detection is a bounded lexical heuristic; uncommon wording can need manual language selection.
  Model prose is deliberately discarded; each Send is independent, without inferred conversational pronouns.
- Host metadata cap is 200 Storage/200 product Sheets; display/tool limits are documented in README.
- No commit/push/release/M4F. Ready for separate source review; this report does not replace it.
