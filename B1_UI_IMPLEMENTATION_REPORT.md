# B1 「浅蓝工作台」 UI port and interface language: implementation report

Date: 2026-10-23. Implementer: Claude Code. **Uncommitted, awaiting Codex review.** No commit, push, packaging, release, dependency installation, real data, real API call or e-mail sending. No further M4F work.

## Baseline

- Git before any edit: `HEAD = d545995` (M4F aggregate AI reports and local report delivery), working tree clean except `?? audit_test_run.txt`.
- A snapshot was saved to `%TEMP%\MRC_B1_baseline\`. It holds `HEAD.txt`, `status.txt`, copies of `ui.py`, `assistant_ui.py`, `presentation.py` and all tests, and `sha256.txt`.
- The design reference `C:\Dev\Auraplex-MSC-UI-Concepts\claude\` (b1.html, assets, README) was only read, never modified.

## What changed

| File | Change |
|---|---|
| `checker/ui.py` | +471 / −159. `_build` replaced by the B1 shell. New: `_build_sidebar`, `_build_topbar`, `_build_check_page`, `_build_launcher_pages`, `show_page`, `set_language`, `_language_changed`, `_tr`/`t`, `toggle_sidebar`, `open_ai_reports`, `_fixed_height`, product/sheet box helpers. Existing handlers unchanged except for the display lines listed below. |
| `checker/home_ui.py` (new, 407 lines) | Home page "库存概览与提醒": quick check, last trial card, alert tiles + table, data sources. Display only. |
| `checker/i18n.py` (new, 292 lines) | Shared interface-language resource: 139 keys × zh/en/ms, 10 state glosses, `LanguageState`, `tr`, `state_text`. |
| `checker/presentation.py` | `BG/INK/MUTED/BLUE` set to the B1 tokens (`#eef5fc/#132f4c/#4b6684/#1f6fbf`). Row colours `RED/AMBER` unchanged (pinned by M2 tests). The other windows inherit the new background and ink. |
| `tests/test_b1_ui.py` (new, 14 tests) | Language, navigation and state-protection tests (see the test report). |
| `tests/test_m21/m32b/m32c/m32d/m4a.py` | 5 layout tests adapted (+20 / −11 lines in total): each opens the page that now holds the entry before checking that it fits. Details in the test report. |

Unchanged byte for byte:
- `core`, `reader`, `service`, `sync`, `queries`, `binding`, `cached`, `report`, `alerts`, `daily`, `retention`, `upgrade`;
- `assistant*.py`, `narrative.py`, `report_delivery.py`, `providers.py`, `agent.py`;
- all secondary windows (`alerts_ui`, `history_ui`, `analytics_ui`, `daily_ui`) and `app.py`.

No calculation, matching, exception, duplicate-ID, sync, binding, cache, transaction, retention, AI consent, report-saving or e-mail-draft rule was touched.

## B1 shell (Tkinter only)

The B1 HTML was used only as a visual and interaction reference; no prototype code or demo data was carried over.

**Sidebar** (`#dbeafa`, 212 px; 60 px icon rail below 1100 px of shell width, or by the user's collapse button).
- Seven pages: 库存概览与提醒 (default), 产品缺料检查, 材料与历史, 提醒, 日报, AI 报告, 设置.
- Icons are Segoe MDL2 Assets glyphs. Each item has a tooltip and responds to keyboard Enter/Space.
- The Alerts item shows the stored active count; it shows `?` while this session has not re-checked it, and the tooltip carries the full entry line.

**Top bar** (white):
- page title;
- 中文 / EN / BM buttons;
- data bar: Inventory Database status, the permanent **Cloud Not Verified** chip, Last Verified / Last Checked, the per-file line, and **Refresh Excel** (primary).
- Without a database, the bar shows only the Cloud Not Verified chip, as v1 had no Refresh.

**Status bar.** Status text (cut at its cell; full text in the tooltip), Verification Required, and the assistant robot.

**Pages and controls.**
- Pages switch with `grid_remove`, so widgets, Tk variables and objects are never rebuilt.
- `self.outer` is now the whole shell frame, so `AssistantLauncher` docking (pack beside `outer`) works unchanged.
- Every former `CheckerApp` attribute still exists with the same behaviour. `history_button`, `maintenance_button`, `cache_button`, `daily_link`, `analytics_link` and `alerts_label` moved to their pages; `reload_button` moved to the shortage-check page. `mode_label` is still the notice line.

**Shortage check page.**
- The earlier screen without its title row and without the four summary cards.
- The counts now sit on the filter buttons (全部 25 / 缺料 4 / 异常 2 / 足够 19), taken from the same `summary_counts`.
- Unchanged: file cards (Browse/Change), product/quantity, CHECK, EXPORT, multi-sheet selector, notice + Use Cached Data + Reload Files, result table, details panel or popup, export feedback.
- `_resize` now measures the check page plus the top bar and status bar.

**Launcher pages.** Secondary functions keep their existing windows; every entry opens the real function (asserted by tests).
- 材料与历史: Inventory History…, Analytics….
- 提醒: Open Stock Alerts…, plus the M3.2C entry line.
- 日报: Daily Summary….
- AI 报告: opens the assistant on its AI reports tab.
- 设置:
  - Use Cached Data… (explicit consent dialog, unchanged);
  - Local History…;
  - Upgrade database…;
  - Storage / BOM file selection;
  - an explanation of the three languages.

## Home page (`home_ui.HomePage`)

**Quick check.**
- Shares `product_text`, `quantity_text` and `stock_name` with the check page. Two combo boxes, one state, with the same search, pick and Return bindings.
- A Storage-sheet selector appears only for multi-sheet workbooks.
- CHECK calls the existing `check()`.
- A user CHECK (`trigger="check"`) switches to the shortage-check page after validation passes. Refresh (`trigger="manual"`) stays on the current page.
- Before any check, the card states that product shortage cannot be judged yet.

**Last trial card.**
- Product × quantity, time, SHORTAGE / EXCEPTION / ENOUGH counts from the real result.
- The basis line is derived only from the existing objects:
  - `SourceBinding.current` → "bound to the local file versions confirmed at … (Cloud Not Verified)";
  - not current → `OUTDATED / RECHECK REQUIRED`;
  - `CacheBinding` → "Historical cached data · UNVERIFIED" (or OUTDATED when `result_exportable` is false);
  - a result that the existing `invalidate()` withdrew → "No longer shown as current … CHECK again". Its counts show `—` and Open result is disabled.
- There is no green "有效" tag. Every state carries "trial calculation … not production approval, no automatic purchasing".

**Alerts.** One background `alerts.load_state(…, include_other_sources=False)` per request.
- When a read runs:
  - only while the home page is visible, no job is running and no evaluation is running;
  - requested on page show and after stored alert data changed;
  - never on a language switch.
- A read failure goes to the existing `alert_read_failed` (fail closed, as in the Stock Alerts window).
- A successful read is accepted, and calls `alert_read_ok`, only if the alert gate generation is unchanged since the read started. A read that straddled a selection, sync or read failure is discarded, so it can never clear that newer state. This was found by the final run's one failure.
- **Tiles group stored rows only:**

| Tile | Stored rows |
|---|---|
| OUT_OF_STOCK | zero stock |
| LOW_STOCK | below minimum |
| DATA_ISSUE / BLANK_STOCK | stock not recorded |
| DATA_ISSUE / INVALID_STOCK | quantity to confirm |
| DATA_ISSUE / DUPLICATE_STOCK_ID | duplicate ID |
| BOM_MATERIAL_NOT_IN_STOCK_MASTER | BOM material not in stock list |
| THRESHOLD_NOT_CONFIGURED | threshold not configured |
| any other DATA_ISSUE subtype | other data issues |

  - Each stored row is in exactly one tile; no rule is re-evaluated.
  - The table rows reuse `AlertsWindow._alert_values` (raw values, codes untranslated). Clicking a tile filters the table; Show all clears the filter; double-click opens Stock Alerts.
- **Overlap note.** "N alerts across M materials; one material can be in several categories, so category counts do not add up to materials." When more rows exist than were loaded, the note says the distinct count is not shown and tile counts show `n+`.
- **Unknown is never 0.** Every tile shows "unknown / 未知 / tidak diketahui", with the reason, when:
  - there is no database;
  - an upgrade is required;
  - the read failed;
  - the current files have no completed evaluation;
  - or the data is loading.
- "Re-checked in this session" or "Stored results, not re-checked" follows `alert_current`. Zero alerts read "no active alerts of these types in the last verified evaluation — this does not mean stock is sufficient".
- **Responsive tiles.** Four per row on wide pages, two on narrow pages. The page scrolls only when it cannot fit the cards and a few alert rows (small windows, 150 % fonts).

**Data sources.** File names (untranslated), per-file database state, and an explanation chosen from the existing overall state by a fixed table:
- Local File Checked;
- Not Synced;
- Checking / Syncing;
- Status Unknown;
- Using Previous Data;
- Sync Failed / Source Unavailable / Source Changed;
- no database;
- cache mode.

## Interface language

`i18n.LanguageState` is owned by `CheckerApp.language`, and the 中文 / EN / BM buttons call `set_language`.

**How a switch works.**
- Widgets register once through `_tr(widget, key)`. `_language_changed` reconfigures them and re-renders the derived texts: inventory panel, alert line, file cards, home, table headings, filter labels, nav and title.
- There are no per-widget language conditionals.
- English strings are identical to the earlier interface labels and status texts. The default is English. Since round 2 the last choice is remembered in its own file (see round 2).

**A switch never reads Excel, syncs, reads alerts, calls AI or invalidates anything.** It does not touch the alert gate, the cache authorisation or the assistant session. Product, quantity, sheet, result object, binding, filter, selection, job and page stay as they are. `test_switching_keeps_every_input_result_filter_and_permission_and_reads_nothing` patches every reader to fail if called. A check running during a switch completes normally.

**Never translated:**
- Material IDs, source file names and paths, original Sheet names, units;
- result and status codes: SHORTAGE / EXCEPTION / ENOUGH, data status, alert type and subtype codes;
- `UNVERIFIED`, `OUTDATED / RECHECK REQUIRED`, `CACHED DATA / UNVERIFIED`, **`Cloud Not Verified`** (in every language, as a permanent chip, never only in a tooltip).

State words such as "Local File Checked" are glossed in zh/ms by a fixed table. Unknown state text is passed through unchanged, never guessed.

**Three separate languages.**

| Language | Owner | Effect of the top switch |
|---|---|---|
| Interface | `i18n.LanguageState` | Changes |
| Assistant reply | `assistant_language.route` (mixed-language rules, the assistant's own language box) | None |
| Report output | `report_delivery`, fixed when a report is saved | None |

The AI-reports page and the Settings language card state this.

### Covered (rounds 1 and 2)
- Main window: sidebar, top bar, page titles, home page, shortage-check page labels, buttons, table headings, filter labels, file cards, inventory database panel (status, times, per-file line), launcher and settings pages.
- Titles of the main window's own error dialogs and of the file-open / export-save dialogs.
- **Round 2:** dialog bodies for file reading, invalid input, CHECK failure and export failure, the database notes shown with them, the "needs a database" dialogs, and every status-bar message the main window generates.

### Not covered — listed explicitly
- **Separate windows** — their own English UI, unchanged: Stock Alerts, Inventory History, Inventory Analytics, Daily Stock Summary, and the AI assistant (keeps its own language selector by design).
- **Maintenance and cache dialogs:**
  - Local History cleanup and database upgrade: titles and English bodies, including the plan descriptions from `retention` / `upgrade`;
  - "stock alerts are being evaluated";
  - the cache consent text from `cached`.
  The status-bar results of these jobs are translated.
- **Error details from lower layers are shown as produced** (by design, as the original detail):
  - reader / `DataReadError` messages (mostly Chinese);
  - `production_quantity` wording;
  - sync errors;
  - export `ReportError` / `ExportVerificationError` / `OSError` text;
  - `cleanup_warning`.
- **Result-state label** (`Local Sources Verified HH:MM:SS` / `OUTDATED …` / `CACHED DATA / UNVERIFIED`) and the alert entry line `Stock Alerts: n active …`: canonical English state text.
- **Detail popups:** file details (`file_status`, Chinese, pinned by tests), the inventory details popup, row details, the summary text, and most tooltips.
- **Other:** the window title, Excel export content, the daily summary output.

## Assistant placement

The robot stays in the status bar at the bottom right, away from CHECK, EXPORT, Refresh, the data status and the window's close button.
- **Docked** (unchanged rule: window ≥ 1440 px × scale): a 440 px column beside the shell. The shell then measures narrower, so the sidebar collapses to icons.
- **Below that:** the existing separate, non-modal, non-topmost window, so the main window can always be brought to the front.

Mode changes keep the draft, transcript and session (the existing `_adapt`, asserted with a forced dock in `test_docked_assistant_keeps_check_export_status_and_robot_visible`). Canned prototype answers were not copied.

## Known limits

- Docking needs 1440 px × scale. On the 1280 × 720 test display it could only be shown by forcing the mode.
- At 960 × 600 with 150 % fonts the home page scrolls and the file overview of the check page scrolls, as it did before.
- The secondary windows inherit the new colour tokens but keep their old layout.

## Round 2 — main-window messages, status bar and remembered language (2026-10-23)

**Baseline.** HEAD `d545995` plus the uncommitted B1 work, including Codex's last-trial counter repair (`home_ui.py`, `test_b1_ui.LastTrialLayoutTests`) and `B1_UI_CODEX_REVIEW.md`. A full copy and `git diff` were saved to `%TEMP%\MRC_B1_L10N_baseline\`. A byte comparison afterwards shows that only the files below changed.

| File | Change against the round-1 state |
|---|---|
| `checker/i18n.py` | +221 lines: 59 message keys × zh/en/ms; `Message`, `State`, `Join`, `render` |
| `checker/ui.py` | +149 / −78 |
| `checker/appdata.py` | +47: `InterfacePreferences` |
| `app.py` | +4 / −2: passes the preference file |
| `tests/test_b1_l10n.py` (new) | 14 tests |
| `tests/test_export_freshness.py`, `test_m1.py`, `test_m2.py`, `test_m31.py`, `test_ui.py` | 10 assertion lines adapted (see the test report) |

Unchanged: `home_ui.py` (Codex's repair included), `test_b1_ui.py`, every business module, the secondary windows, the colours and the navigation.

### Structured messages

- **Format.** `i18n.Message(key, **values)` stores a key and raw values; `render(message, language)` formats it in the language current at display time. Values may be:
  - plain strings, shown as given: exception details, file names, paths, `OUTDATED`, `UNVERIFIED`, `CACHED DATA / UNVERIFIED`, `Cloud Not Verified`;
  - numbers;
  - `State` (a sync-state constant, glossed by the existing `state_text`);
  - nested messages;
  - `Join` (parts with a separator; empty parts dropped).
- **English** equals the earlier text. **Chinese** reuses the earlier Chinese wording wherever one existed; `test_former_chinese_text_is_kept` pins the main ones. **Malay** is new.
- **Dialogs** render when they are shown. They are modal, so the language cannot change while one is open.
- **Behaviour unchanged.** Every condition, exception path, invalidation and refusal is unchanged: the same branches run and only the text argument changed. One mechanical change: CHECK input refusals now raise a local `InputProblem(ValueError)` carrying the message instead of a bare `ValueError`. The same inputs are refused in the same order, with `invalidate()` and one dialog, as before.

**Dialog bodies covered:**

| Area | Messages |
|---|---|
| File reading | File-specific failure with the role name, the original error and a recovery step. Sheet removed during CHECK: a `SheetGone(DataReadError)` marker, text `err_sheet_gone`, same refusal as before. Unexpected whole-action failure: original error, plus "both files cleared; choose again or Reload Files". Database notes after a sync (previous data kept / none / status unreadable / not recorded / Refresh Excel to retry). No files selected. |
| Input | Quantity: the `checker.core` rule text is kept verbatim as the detail, with a translated explanation and recovery. Files not loaded; product not selected (n matches / none); Storage Sheet; cache authorisation expired. |
| Export | No result; result changed during the save dialog; outdated / cache outdated (title stays the `OUTDATED` code); write failure (path + detail + "choose another folder or close the open file"); other export failure (detail + "nothing exported; CHECK again"). |
| Other | The five "a readable local database is required" bodies; the Open Folder failure title. |

### Status bar

- `CheckerApp.status_message` holds the newest structured message; `_set_status(message)` stores it and renders it into the existing `status` variable. A language switch re-renders that one message. There is no string replacement and no history, so an older job's text can never return: a running job shows its running text, a finished job its outcome, a failure its failure.
- All values are snapshots taken when the message was created:
  - the database suffix captures the `db_overall` state of that moment;
  - "Checked N materials in X s" keeps its numbers.
  Re-rendering never re-derives anything from the current state.
- **Messages converted:**
  - jobs: loading, checking materials, checking sources, refreshing, cleanup and upgrade preview / apply;
  - outcomes: checked, loaded, ready, cache mode, outdated during CHECK;
  - maintenance results: `maintenance_message` is now a message key;
  - read/check failures (with the database suffix);
  - maintenance and upgrade failures;
  - export outdated / cache export failed / exported;
  - "could not remember the selected file".
- The English output is byte-identical to before; every status-pinning test that was rerun passes.

### Remembered interface language

- **File.** `appdata.InterfacePreferences` → `interface.json` = `{"version": 1, "language": "zh"}` in the data folder `app.py` already uses (`%LOCALAPPDATA%\Auraplex\MaterialStockChecker`, or `--data-dir`). It is separate from `settings.json` (source paths), the database and every authorisation; none of those is read or written by it.
- **Start-up.** `load()` never raises:
  - a missing file gives English;
  - an unreadable file, invalid JSON, a non-object or an unsupported value gives English plus a problem note.
  Loading starts no job, sync or AI call. The file is not rewritten until the user chooses a language.
- **Save.** Each switch saves atomically: temporary file in the same folder, `fsync`, `os.replace`, temporary file removed on failure.
- **Failures.**
  - A failed save keeps the language for this session, writes nothing else and shows no dialog. A note on the Settings → Interface language card says the language applies only to this session; a later successful save clears it.
  - An unreadable file is reported on the same card.
- **No preference file.** Tests, `--smoke-test` and any app created without `preferences` read and write nothing (English).

**Unchanged by a language switch:** inputs, product, Sheet, filters, result, binding, job, authorisations, alert gate and assistant session. There is no Excel read, sync or API call. Codes, paths, Sheet names, units and Material IDs are never translated. Cloud Not Verified / UNVERIFIED / OUTDATED / unknown keep their meaning. Assistant reply language and report output language stay independent.
