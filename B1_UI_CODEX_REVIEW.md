# B1 UI — focused Codex review

Date: 2026-10-23. Baseline: local HEAD `d545995` plus the uncommitted B1 changes.

## Decision

**GO for a local source commit of the B1 first-stage UI. P2-B1-1 below has since been repaired at the user's explicit request.** No new P0/P1 was identified in the inspected paths and focused checks. This does not mean complete application-wide localisation, full-suite completion, packaged acceptance or release readiness. No commit was made by this review or the bounded repair.

## Scope and preservation

Inspected the implementation/test reports, main-window diff, `home_ui.py`, language state and translations, alert-read generation handling, input/result preservation, result freshness display, navigation and assistant integration. Reviewed the five modified legacy layout tests. The obsolete M3.2D same-header-row width relation was replaced with a page vertical-fit assertion; the other entry tests navigate to the page containing the control before applying their visibility/bounds checks. This is layout adaptation, not calculation-rule relaxation.

The production changes are confined to the main UI, its presentation colours, and the new home/i18n modules. Git reports no changes to calculation, reader, sync, query, source binding, cache, report delivery, alert evaluation, retention, provider or assistant business modules. No production code was changed by Codex; only this review report was added. Existing untracked `audit_test_run.txt` was excluded and left alone.

## Independent checks run

Only synthetic workbooks, temporary databases and isolated Tk test instances were used. No real source workbook, production database, API, mail client or user test window was operated.

| Run | Result | Time |
|---|---|---|
| `test_b1_ui.LanguageSwitchTests` (3), `StateProtectionTests` (4), `test_m32c_rereview.ReadFailureUiTests` (4) | **11 passed** | 15.271 s |
| Isolated `test_m4a.HistoryWindowTests.test_rows_render_in_batches` with a 20-second diagnostic watchdog | **1 passed** | 7.428 s |
| M4A adapted entry-fit test; M4B real main-entry/window-reuse/read-failure test; M4E `MainIntegrationTests` (2); B1 forced-dock visibility test | **5 passed** | 32.399 s |

**17 completed tests passed; measured test time 55.098 seconds.** The developer's 94 checks, 17-module batch and full suite were not repeated. Unchanged pure query/analysis suites were not rerun simply to reproduce existing coverage.

An earlier eight-test history/analytics batch was interrupted by Codex while diagnosing unexpectedly slow execution under low available system memory (approximately 900 MB). It produced no summary and is not counted as either passed or failed. The specific history batching case subsequently passed in isolation. No OOM exception or product deadlock was established by this review. Small processes were used afterwards to avoid accumulating Tk resources in a long run.

`git diff --check` passed. The developer's interrupted run remains incomplete; these targeted checks do not turn it into a completed full regression.

## State and integration conclusions

- Language switching retains inputs, selected product/Sheet, result, filters and permissions without source reads or synchronisation; a running CHECK completes across a switch.
- Language/navigation do not restore invalidated or outdated CHECK results. Export remains blocked for outdated bindings.
- Unknown/no-evaluation/database-read-failure alert states do not become zero counts.
- The repaired alert-read generation guard is present, and all four independent existing read-failure UI regressions pass. An earlier home success cannot apply across a newer alert-gate generation.
- History batching, analysis read failure, main-window assistant revocation/close and forced docking have targeted passing evidence.
- HTML prototype behaviour is not being counted as actual Tk implementation evidence.

## P2-B1-1 — Last-trial ENOUGH count is clipped at 960×600 / 150% font scaling

Location: `checker/home_ui.py`, `_build_cards`, the three `last_counts` labels packed horizontally inside the right card.

The author-provided `final/s150/home_zh_960x600_150.png` shows the ENOUGH total cut off. Codex also independently measured the current source after loading synthetic files, running a CHECK, selecting Chinese and opening Home at 960×600 with Tk scaling set to 96/72 × 1.5:

| Label | Measured text width | Allocated label width |
|---|---:|---:|
| SHORTAGE 2 | 123 px | 127 px |
| EXCEPTION 1 | 126 px | 130 px |
| ENOUGH 1 | **103 px** | **95 px** |

The label is mapped but is narrower than its text even before allowing its padding. Larger counts can lose more content. The stored result/counts and results page remain correct, so this is a P2 presentation defect, not corrupted calculation or a false production approval.

Suggested repair: wrap/stack these three counters at narrow widths or use a responsive grid. Do not shrink away the count or replace it with a misleading zero. One geometry regression at 960×600 / 150% plus a normal-width check is sufficient; another broad regression run is unnecessary for that bounded layout fix.

## Language and visual coverage

The main shell has a real shared zh/en/ms language state. Whole-application live localisation is **not complete**: independent Alerts/History/Analytics/Daily windows, several dialog bodies, the status messages and some details remain in their previous language as disclosed. The assistant retains its independent language controls, and report output remains separately bound. The chosen interface language is not persisted across restart.

Two existing screenshots were viewed: Chinese Home and Malay CHECK at 960×600 / 150% font scaling. These are author-produced evidence, not newly captured independent screenshots. A current-code geometry probe confirmed P2-B1-1. No claim is made to have reviewed all 69 screenshots or to have captured a new full visual matrix. Later source changes also mean existing screenshots are not blanket proof of final-source rendering.

Real 1366×768, natural wide-screen docking, physical Windows 150% DPI, full business regression, packaged EXE, Windows 10, another PC, real Drive/API and complete language coverage remain unverified. These limitations should remain visible in the roadmap and delivery documentation.

## Next step

The B1 first-stage shell is suitable for a local source checkpoint with this P2 recorded. CC can repair the narrow counter layout separately, with one small targeted check, then continue the missing language surfaces. Do not call the whole UI or all three-language functionality finished, and do not package/publish from this review alone.

## P2-B1-1 repair — user-authorised Codex change

On 2026-10-23 the user explicitly requested Codex to fix this small issue directly. `HomePage` now measures the requested widths of the complete counters and uses a responsive grid (three, two or one counter per row). It fits again when the card width or displayed counts change. No count is shortened or recalculated; no business, data, authorisation or freshness logic changed.

Added only two focused tests in `test_b1_ui.LastTrialLayoutTests`, at 100% and 150% Tk font scaling. Both exercise 960×600 and 1280×720 and long six-digit display counts, check that each complete text fits its label and parent frame, and retain the existing CHECK result object. Both passed in **7.409 seconds**. No broad suite was repeated. This is Tk geometry evidence, not physical Windows DPI or new screenshot acceptance.

The earlier P2 description and measurements remain as the defect history. **P2-B1-1 is now CLOSED.** The original developer changes and audit log remain preserved; no commit, push or packaging was performed.
