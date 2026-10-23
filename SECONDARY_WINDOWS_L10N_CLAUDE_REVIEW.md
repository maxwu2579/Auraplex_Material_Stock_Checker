# Secondary-window localisation and window lifecycle — independent Claude review

Date: 2026-10-23. Baseline: `ba8c9aa`, plus the uncommitted localisation and lifecycle changes.

This review is source inspection plus targeted independent checks. No production or test code in the repository was
modified. Nothing was committed, reset, staged or pushed. The independent check scripts live only in the session
scratchpad, outside the project.

## Decision

**GO for a local commit of this batch.** No P0, P1 or P2 was found. Four P3 observations are listed below; none
blocks the commit.

## Scope inspected

The author documents were read but not relied on: `SECONDARY_WINDOWS_L10N_REVIEW.md` and the History, Alerts and
Analysis/Daily implementation reports. Conclusions below come from the actual diff:

| Files | Change |
| --- | --- |
| `checker/history_ui.py`, `alerts_ui.py`, `analytics_ui.py`, `daily_ui.py`, `ui.py` | Modified |
| `checker/history_i18n.py`, `alerts_i18n.py`, `analysis_daily_i18n.py`, `maintenance_i18n.py`, `window_language.py`, `daily_preview.py` | New |
| `README.md`, `DEVELOPMENT_ROADMAP.md` | Status sections |

### Business freeze

`git diff --name-only` lists only these UI files plus `README.md` and `DEVELOPMENT_ROADMAP.md`. None of the following
were changed: `core`, `analytics`, `daily`, `alerts`, `history`, `sync`, `queries`, `inventory_db`, `retention`,
`upgrade`, `cached`, `report`, `providers`, `agent`. The `ui.py` diff contains only:

- the language hand-off to the four windows;
- maintenance and cache dialog text;
- the added `self.closed` guard in the cache-consent callback.

The export publication path (`report.Cancellation`) is untouched.

`audit_test_run.txt` is unchanged: SHA-256 `307AA1DF2B507A48D936081F35F0F5367FDC9168AEF1E4EC490A4117A96CE7EC`.

## Findings

### P0 / P1 / P2

None.

### P3-1 — The zh/ms Daily preview shortens two stored notes

Location: `checker/daily_preview.py`, the alert section; resources in `checker/analysis_daily_i18n.py` around lines
98 and 103.

The English preview prints `SUM_NOTE` and `NOT_STOCK_NORMAL` verbatim. The zh/ms projection uses shorter fixed
translations:

- **`SUM_NOTE`:** the zh/ms text keeps "counts overlap across types; do not sum them as materials". It drops "the same
  Material ID in different Storage Sheets is one ID here; each Sheet entry is listed".
- **`NOT_STOCK_NORMAL`:** the zh/ms text drops "alerts follow the M3.2C rules only".

The saved HTML/JSON and the English preview are unaffected, and no number is changed. This is a wording completeness
item only. Suggested follow-up: translate the full constants.

How to reproduce: compare `daily.SUM_NOTE` and `daily.NOT_STOCK_NORMAL` with
`daily_preview.render(summary, 'zh')` for any generated summary.

### P3-2 — Window language updates are not isolated from the main switch

Location: `checker/ui.py`, `_language_changed`, first lines.

The four secondary windows' `language_changed()` run before the main window re-renders, with no exception isolation.
If any of them raised, the main-window re-render and the subsequent preference save in `set_language` would be skipped
for that click.

No failing case was found:

- all four guard `closed`;
- every `message(...)` template literal resolves (AST check below);
- the zh/ms Daily projection rendered all tested summary shapes.

This is a robustness note, not a reproduced defect.

### P3-3 — An invalid-options message in Analytics does not re-translate

Location: `checker/analytics_ui.py`, `query()`.

The "Choose 30, 60 or 90 days." `ValueError` is rendered to a plain string when raised. A later language switch
leaves that one coverage message in the earlier language. This is cosmetic.

### P3-4 — Developer-test gaps

These are now covered by the independent checks below, not by repository tests.

- The four-window integration test (`test_all_four_open_windows_switch_without_queries_or_authorization_changes`)
  switches windows that have no loaded results, selection or filters. The per-window developer tests (not rerun here)
  do cover loaded states.
- `tests.test_window_lifecycle` checks Analytics/Daily release only when idle. It does not cover a close while their
  runner job is in progress.
- The lifecycle tests temporarily disable GC to force collection on a background thread, then assert that no
  unraisable error was captured. They do not show whether a reference cycle remains. The refcount probe below
  addresses that.

## Boundary verification (source reading)

### Language switching

- **The four windows are notified directly.** `CheckerApp._language_changed` calls each open window's
  `language_changed()`; the windows do not subscribe to `LanguageState`, so no listener remains after a close.
  Each `language_changed()`:
  - re-renders stored `Message` objects, headings, combobox "All" labels and tab titles;
  - re-renders the Analytics row cells and the Daily preview from the stored result or immutable summary;
  - schedules no worker job, reads no file or SQLite, and changes no generation or request counter.
- **Filters use the combobox index, not the label text.** The History, Alerts and change filters use
  `combobox.current() == 0` for "All", so translating the label cannot drop a filter. A specific Sheet or type keeps
  its index and its original text.
- **Raw values stay original.** Sheet names, Material IDs, paths, versions, times, status codes, query notes and
  evaluation details are passed as data, never translated by substitution.
- **Unknown stays unknown.** Analytics `_row_values` keeps the earlier `number()` semantics: `None` is "unknown"
  (translated), never 0. The zh/ms Daily projection shows `None` counts as "unknown"; the English path is unchanged.
- **Failure states persist.** Failure, stale, cancelled and pending states are stored as messages and re-rendered.
  None of them is re-derived into a success state.
- **"Cloud Not Verified" remains** in banners and status texts in all three resource sets.

### Daily

- **Translated preview.** zh/ms previews use `daily_preview.render` on `summary.data()`, which is a JSON decode of the
  immutable summary. English still returns `daily.render_text`, unchanged.
- **Saving is unaffected by the interface language.** `save()` passes the same `DailySummary` to `daily.save`, which
  writes `json_text` and `render_html`. The window hint states that saved HTML/JSON keep the English report format.
- **Protections unchanged:**
  - the UNVERIFIED confirmation keeps `default="no"`;
  - `can_save()` and the stale and verification checks are unchanged;
  - the schedule draft still only writes XML after a default-No confirmation.

### Cache, cleanup and upgrade

- **Previews match the English originals.** `cache_description`, `retention_description` and `upgrade_description`
  are field-by-field re-renderings of `Snapshot.describe`, `Plan.describe` and `UpgradePlan.describe`. They have the
  same fields, paths, version IDs, UTC times, counts and policy (12 calendar months / 90 days / 180 days), and the
  same `from_version` branch. English calls the original `describe()`.
- **Default No is kept everywhere.** All `askyesno` calls keep `default="no"`.
- **Declining authorises nothing.** The decline branches return before any authorisation, apply or backup call.
- **Guards are unchanged:**
  - `job != self.job`, `self.busy` and `self.closed` for cleanup and upgrade;
  - in cache consent, `self.closed` is now also checked before `cache_selection` and `cache_authorized` are set.

### Lifecycle

- **History.**
  - Worker actions are `functools.partial` objects over the database path and plain query arguments. The worker
    closure references only `action`, `cancel`, `events`, `kind` and `generation`.
  - `close()` stops each lane and sets `lane.start = None`. After close, no `submit` or `finished` path reaches
    `_next`: `query()`/`search()` return when closed, and `_poll` stops.
  - The R1 bound (`LIMIT`) and generation checks are unchanged.
- **Alerts.** The worker captures `database`, `events`, `include`, `days` and `kind` only.
- **Translation-label discovery** in History, Alerts and `WindowLanguage.register` uses an iterative stack: no
  recursive closure.
- **Analytics and Daily** store their own `trace_add` tokens and remove only those on close. No other trace or
  callback is removed. The Analytics/Daily runner actions close over plain values (database, day, session, gate,
  policy, cancel), never the window.

## Tests actually run

### Developer tests, as requested (run once)

| Test | Result |
| --- | --- |
| `tests.test_window_lifecycle` (3) | OK |
| `tests.test_maintenance_l10n.ClosedCacheConsentTests` (1) | OK |
| `tests.test_maintenance_l10n.MaintenanceLanguageTests.test_all_four_open_windows_switch_without_queries_or_authorization_changes` (1) | OK |
| **Total: 5 tests** | **OK, 5.873 s** |

### Independent checks (my own synthetic scenarios, scratchpad only, not repository tests)

All use the existing synthetic fixtures (`SessionUiBase`), temporary SQLite and folders.

| Check | Result |
| --- | --- |
| **R1 — Daily saved while switching languages.** Language set to zh before generating. Generate a VERIFIED summary. Save via the window, held at the `before_publish` checkpoint; switch ms → en → zh while held. Assertions: same summary object; authorisation and gate generation unchanged; `daily_session()` equal before and after. Saved JSON and HTML are **byte-identical** to a direct `daily.save` of the same summary, the JSON equals `summary.json_text`, and no Chinese interface text appears in the HTML. | OK |
| **R2 — History with results loaded.** Search, 60 days, a specific Sheet (index 1), selection A, result loaded. Switching zh/ms/en keeps the result object, selection, range, Sheet index, `query_gen`/`search_gen`, every lane's started count, candidates, row cells and paging, with list/search/query reads patched to fail. Status keeps "Cloud Not Verified". A later query failure remains "QUERY FAILED" with its original error and no rows in all three languages. | OK |
| **R3 — Alerts with filters.** Type filter index 1 plus a material filter. Switching keeps the filter values and indexes, the visible rows, the state object, the gate generation and `alert_current`. `load_state` was patched to fail. Re-applying the filters after each switch yields the same rows. | OK |
| **R4 — Analytics and Daily closed while a job runs.** Analyze or generate is held, the window closed and dereferenced, and garbage collection is forced on a background thread. Both windows are released, and no unraisable Tk finalizer error occurs, including after the held job completes. | OK |
| **Run time** for R1–R4 (4 tests) | 16.211 s |
| **S1–S2 — zh/ms/en Daily preview** for summaries the developer tests did not render: UNVERIFIED with no session, yesterday's historical date, and an empty-application database. Each renders in all three languages, keeps the report ID, "Cloud Not Verified" and "UNVERIFIED", and English equals `render_text`. | OK, 2 tests, 1.171 s |
| **P1 — refcount probe.** With GC disabled and no collection at all, History, Alerts, Analytics and Daily are each freed immediately after `close()` and dereferencing. Result `{history: True, alerts: True, analytics: True, daily: True}`: no reference cycle is left for a background collector. | OK, 1.057 s |
| **AST check:** every literal `message(...)` / maintenance template in the five UI modules (105 calls) exists in its resource table, so no runtime `KeyError`. | OK |
| `git diff --check`; new untracked files checked separately for CR, trailing whitespace and final newline (`git diff --check` does not cover untracked files) | OK; all LF, clean |

Totals: 5 developer tests and 7 independent tests, all passing, plus the AST and whitespace checks. Independent
results are reported separately from the developer tests and were not added to the repository.

## Not executed / remaining limits

- **Developer tests not rerun.** The remaining l10n developer tests (`test_history_l10n`, `test_alerts_l10n`,
  `test_analysis_daily_l10n`, most of `test_maintenance_l10n`), the R1/R2 suites, the 47 export regressions and the
  full suite were not run.
- **No visual or layout acceptance.** No screenshots or DPI matrix. Geometry tests were not run.
- **No real-environment runs:** real company data, real database upgrade, Drive, API, email, Task Scheduler
  registration, packaged EXE, Windows 10 or a second PC.
- **Untranslated surfaces.** Row-level glosses (for example "BLANK — not 0", "NOT RETAINED — values unknown"), detail
  popups, original query and evaluation narratives, raw diagnostics and some tooltips stay English, as the authors
  disclose. Native OS dialog buttons follow the OS language.
- **Lifecycle scope.** The checks cover the four secondary windows. A whole-application shutdown or GC audit was not
  done.
