# M4F first slice — final review and bounded fixes

Date: 2026-10-22. Reviewer/implementer: Claude Code. Baseline `HEAD` = `85f8a65` (M4E). M4F remains **uncommitted**. Existing working-tree changes, `M4F_CLAUDE_REVIEW.md` and `audit_test_run.txt` were kept. No real workbook, database, API key or API call, no dependency installed, no packaging, commit, push, release, e-mail or next milestone. The user's open demo window was not touched.

## Decision

**GO for a local commit of the M4F first slice. This is not a release, and not M4F as a whole.**

- The two earlier P1s are fixed and independently re-checked.
- P2-2 is fixed.
- P2-1 and P2-3 are fixed within the limits stated below.
- No P0/P1 remains in this bounded scope.
- Purchase suggestions, e-mail, notifications and automatic purchasing are still absent, as intended.

## 1. P1 re-check (independent synthetic repro, not only the tests)

Script: session scratchpad `m4f_final_repro.py`, 10 cases, temporary DB, fake keys/transport.

### P1-F1 — unknown quality counts — **PASS**

| Situation | Storage issue counts | BOM issue counts |
|---|---|---|
| Nothing synchronised | all `null` (latest retained Storage counts `null` too) | all `null` |
| Storage only | `0` | `null` |
| BOM only | `null` | `0` |
| Both synchronised, clean | `0` | `0` |
| Both synchronised, with issues | `DUPLICATE_STOCK 2, INVALID_MATERIAL_ID 1, NUMERIC_MATERIAL_ID 1` | `DUPLICATE_BOM 2, INVALID_BOM_QTY 1, NUMERIC_MATERIAL_ID 1` |

- **Preview and transport agree.** Storage synchronised; BOM check `UNAVAILABLE`, never published. The facts parsed out of the body the fake transport actually received are equal to the preview facts, and BOM issue counts are `null` there.
- **P2-2 — PASS.** Counts are kept per role, and `NUMERIC_MATERIAL_ID` is counted for both roles.

### P1-F2 — unobserved week — **PASS**

| Previous week | Current week | Status | Deltas |
|---|---|---|---|
| No Storage activity (snapshots 0, attempts 0) | two imports | `INCOMPLETE_HISTORY` | all `null` |
| Only an `UNAVAILABLE` Storage check (attempts 1, successes 0) | import | `INCOMPLETE_HISTORY` | `null` |
| Only a BOM import | import | `INCOMPLETE_HISTORY` | `null` |
| One `UNCHANGED` Storage check | one `UNCHANGED` Storage check | `COMPARABLE` | all `0` (genuine zero recorded change events) |

- **Boundary.** A Storage check 1 s after the previous window's local start (10-07 16:00:01 UTC) counts in the previous window. Windows are half-open, reusing the M3.2D day boundaries.
- **Residual found and fixed.** Nothing in the facts or the preview said that observations exist only at sync times. Changes:
  - added the limitation `OBSERVED_ONLY_AT_RECORDED_SYNC_TIMES_NOT_CONTINUOUS` to the facts;
  - added one sentence to the model's system prompt;
  - `COMPARABLE` is now displayed as "both periods have Storage observations; not continuous monitoring";
  - the preview limitations state that observation frequency can differ between periods. Observed change ≠ consumption is unchanged.

## 2. P2 fixes and remaining limits

### P2-1 — AI reply guard (narrative path only)

**What changed:**
- `narrative.reply_problems(text)` is applied in `DeepSeekProvider.complete_narrative` only. M4E chat and the M2/M3 rules are untouched.
- A rejected reply raises the new code `NARRATIVE_REJECTED`. It has its own trilingual message: the interpretation was not used, the local counts are unchanged, and the keyword check cannot guarantee correctness.
- The local preview, facts and digest are kept. The one-use grant stays spent: one request, no retry.

**Categories rejected (Chinese, English and Malay patterns):**
- stock sufficient / normal / production-ready
- cloud verified
- actual consumption
- explicit purchase action
- counts: any digit, or a number word attached to a counted noun (`twelve materials`, `十二项`, `dua belas perubahan`)

**How false positives are limited:**
- A claim is ignored when a negation or "whether" cue precedes it in the same sentence (within 40 characters) or appears inside the match. Examples that pass: "not actual consumption", "Cloud Not Verified", "无法判断库存是否充足", "不建议采购".
- A negation does not carry over to the next sentence.
- Chinese numerals exclude a bare 一/两 (一些, 一个, 两个时间段) and ordinals (第二个).
- Malay excludes `satu` (salah satu).

**Evidence:**
- Probe: 18 reject / 21 accept example sentences, 0 misclassified.
- Tests: 4 guard tests plus a provider test, which covers four forbidden replies with one request each and a spent grant.
- UI test: a rejected reply keeps the local preview and never shows the model text.

**Remaining limits (stated, not hidden):**
- This is keyword matching, not understanding. Paraphrases ("there is no shortage risk at all"), unlisted wording, or a negation cue elsewhere in the same sentence can let a claim through. Unusual cautious wording can be rejected.
- Number words detached from a counted noun, and `satu`/一/两, are not counted.
- The prompt, the UNVERIFIED caveat and human review remain necessary. No live model was tested against the guard.

### P2-3 — trilingual preview

**What changed:**
- `show_report(facts, language)` renders title, period labels, statistics fields, `unknown`, comparison status, coverage states, alert status, issue rows and all limitation lines in Chinese, English or Malay.
- Canonical codes (`COMPARABLE`, `QUANTITY_CHANGED`, `IMPORTED`…) stay visible, e.g. `可比较…(COMPARABLE)`. UNVERIFIED / Cloud Not Verified are kept verbatim in every language.

**What stays fixed:**
- The facts, their JSON fields, the digest and the request binding are unchanged.
- When the assistant language changes, the poll loop re-renders the same `report_facts` object. `send_report` also re-renders before showing the request if the language differs. So the reviewed preview, the exact request (`Simplified Chinese` etc.) and the one-use approval all use the same language.

**What cannot be bypassed:**
- Re-rendering only uses `report_facts`, which invalidation clears. A language switch after invalidation cannot bring an old preview back (tested).
- It never mints or reuses an approval.

**Remaining limits:**
- The static tab captions/intro keep the language the panel was built in (existing M4E behaviour for all tabs).
- Recorded UTC/ISO timestamps are shown unformatted.

## 3. Historical items — current status (code and documents re-checked; not fixed in this round)

| Item | Status | Evidence |
|---|---|---|
| 1. M4A history worker count unbounded | **Still present** | `checker/history_ui.py:218–225` starts a new daemon thread per search/query. Generations still discard stale results. Roadmap line 32 still records the P2 follow-up |
| 2. Excel export on the UI thread | **Still present** | `checker/ui.py` `write_export` calls `save_verified_report` / `cached.save` directly from the button handler (Tk thread). A slow disk blocks the window during the write |
| 3. `--self-test` with a missing output folder | **Not confirmed by a run.** The code path still exists | The output folder is not created explicitly. A merely missing folder is probably created indirectly when `OUTPUT_DIR\appdata` is initialised (`mkdir(parents=True)`). If that fails (uncreatable or unwritable path), `finish()`'s `write_text` raises inside the `except` handler of a Tk `after` callback. `app.close()` is then never reached, so the process may not exit. Not executed in this round |
| 4. Business rules: duplicate IDs, OUT_OF_STOCK + LOW_STOCK on the same zero row, threshold/unit meaning | **Still pending business confirmation** | `alerts.PENDING_CONFIRMATION` and the M3.2C note remain. Duplicates are kept separate and never added (DATA_ISSUE). A zero row with threshold > 0 produces both OUT_OF_STOCK and LOW_STOCK (M4F labels the alert categories as overlapping). No confirmation is recorded in the repository |
| 5. Real API / Google Drive / EXE / second PC / Windows 10 / physical high-DPI | **Not covered for M4D–M4F** | No live API call in any M4D/M4E/M4F report. M3.2E has a focused temporary-EXE validation (`M3_2E_PACKAGED_VALIDATION.md`) only. Earlier M3.2A/B packaged acceptance predates M4. Roadmap: real Drive and the Windows EXE matrix (Win10/11, DPI, another PC) are "remains open" |

## 4. Tests actually run (this round)

| Run | Result | Time | Log |
|---|---|---|---|
| Development: targeted classes (`ProviderReportConsentTests`, `ReplyGuardTests`, `ReportDialogTests`) | 18 passed (after one expected failure: the digit test now expects `NARRATIVE_REJECTED`) | 4.74 s | console |
| Development: guard probe (39 example sentences), P1 repro script (10 cases) | as reported above | <1 s each | console |
| **Final:** `python -m unittest tests.test_m4f -v` | **34 passed** | 4.66 s | `%TEMP%\MRC_M4F_final.txt` |
| **Final:** `python -m unittest tests.test_m4d tests.test_m4e` (provider narrative path and the shared language table changed) | **67 passed** | 8.13 s | `%TEMP%\MRC_M4F_final_m4de.txt` |

- 34 = 26 earlier + 1 provider forbidden-claim test + 4 guard tests + 3 UI tests (rejected reply keeps preview; language follows preview and request; language switch after invalidation).
- `py_compile` and `git diff --check` passed.
- **Not run:** M4C suite (the only `agent.py` change adds one failure code to the allowlist), the full suite, packaging.

## 5. Files changed in this round

- `checker/narrative.py`: limitation, prompt sentence, `reply_problems`.
- `checker/providers.py`: narrative reply check only.
- `checker/agent.py`: `NARRATIVE_REJECTED` code.
- `checker/assistant_language.py`: report preview strings, state labels, error text.
- `checker/assistant_ui.py`: trilingual `show_report`, language re-render.
- `tests/test_m4f.py`.
- `README.md`, `DEVELOPMENT_ROADMAP.md`, short status notes in `M4F_IMPLEMENTATION_REPORT.md` / `M4F_TEST_REPORT.md`.

No database schema, sync, alert, M2/M3 calculation or M4E chat logic changed.

## 6. Not verified

- Live DeepSeek API, real key storage, actual model behaviour against the prompt and the guard.
- Real company workbooks or database, real Google Drive.
- Packaged EXE, Windows 10, a second PC, physical high-DPI.
- Manual operation of the UI. UI evidence is the source-level Tk tests at 960×600.
- The `--self-test` failure path (item 3) was not executed.
