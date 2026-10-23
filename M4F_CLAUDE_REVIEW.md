# M4F first slice — Claude Code independent review

Date: 2026-10-22. Reviewer: Claude Code (review only). No production code, tests, real workbook, real database, real API or packaging was touched; nothing was committed, pushed or released. `audit_test_run.txt` and all existing working-tree changes were left as found.

## Decision

**NO-GO for a local commit until two bounded P1 fact-accuracy defects are fixed.** No P0 was found. The outbound-data boundary and the consent/version binding held in every check I ran. The P1s are in what the report *says*. Both are reproduced below, both appear in the local preview and in the request sent to the model, and both are small fixes inside `checker/narrative.py`.

This is the first M4F slice only (AI reports page, local daily/weekly aggregate preview, per-report AI interpretation). It is not a review of M4F as a whole. Email, notifications, purchasing suggestions and automatic purchasing are absent, as intended.

## Scope and baseline

- Baseline `HEAD` = `85f8a65` (M4E). Working tree: modified `DEVELOPMENT_ROADMAP.md`, `README.md`, `checker/agent.py`, `checker/assistant.py`, `checker/assistant_language.py`, `checker/assistant_ui.py`, `checker/providers.py`; new `checker/narrative.py`, `tests/test_m4f.py`, `M4F_IMPLEMENTATION_REPORT.md`, `M4F_TEST_REPORT.md`; untracked `audit_test_run.txt` (untouched).
- Read: both M4F reports, the roadmap/README M4F sections, the full diff, the whole of `narrative.py`, and the reused helpers it depends on: `daily._changes`/`_alerts`/`day_window`, `agent_tools._basis`/`_metadata`, `AssistantSession` lifecycle, and `DeepSeekProvider._complete`.
- Main CHECK, export, sync, alerts, daily summary and history code are not in the diff. `agent.py` only adds the `STALE_REPORT` failure code.

## Tests actually run

| Run | Result | Time | Log |
|---|---|---|---|
| `python -m unittest tests.test_m4f -v` | **18 passed** | 7.30 s | `%TEMP%\MRC_M4F_claude_review.txt` |
| `python -m unittest tests.test_m4d tests.test_m4e` (authorization, cancel/Stop, basis-change, outbound-consent regressions; `assistant.py`/`providers.py` are shared) | **67 passed** | 17.08 s | `%TEMP%\MRC_M4F_claude_review_m4de.txt` |
| Synthetic repro script (5 cases, temporary DB, fake keys/transport) | ran; findings below | 0.77 s | script: session scratchpad `m4f_review_repro.py` |

`git diff --check` passed. **Not run:** M4C suite (the only `agent.py` change adds one failure code), the full suite, live API, packaging.

## What held (checked, not only taken from the reports)

**A. Outbound boundary.**
- Repro R2 captured the actual bodies passed to the fake transport, through the real `AssistantSession` → `DeepSeekProvider` path, for one daily and one weekly report.
- The workbook contained hostile data: private Material IDs, a numeric-cell ID, an invalid quantity, a duplicate ID, a secret description, secret Storage and product Sheet names, and the real temporary paths. I also searched the bodies for every `file_sha256` and `content_signature` in the database.
- **None appeared.**
- Top-level request keys were `model, messages, stream, thinking, max_tokens`, with no `tools`. The only non-enum free text in the facts was the format string.
- `validate_facts` is a strict allowlist on exact key sets, enum values, integer counts and timestamp/ISO patterns. Arbitrary strings cannot reach the payload.
- Preview and local report building read no key and make no request (`test_preview_reads_no_key_and_sends_nothing`).
- The key is loaded only after the general consent check, the per-report grant and the exact-body SHA-256 check (`providers.py` `_complete`).
- A due balance check runs under the existing M4D consent and is disclosed in the per-report dialog. Two balance calls occurred in R2, as expected.

**B. Consent and binding.**
- Three separate grants are required: local data (`authorized`), API outbound (`outbound`), and a one-use report approval.
- The report approval is bound to:
  - the session epoch
  - the database basis (versions, latest sync runs, `schema_info`/retention, snapshots, latest alert evaluation)
  - the facts digest
  - the response language
  - the SHA-256 of the exact request body
- Consumption:
  - The session consumes the approval at `submit`.
  - The provider consumes its narrative flag before building the body.
  - A changed body gives `STALE_REPORT` before the key is read.
  - A database change before sending gives `STALE_DATA` with no network call.
- Reuse is refused.
- `invalidate()`/`close()`/`_revoke()` clear the approval and the provider flag. `allow_outbound` also clears it.
- Deliveries are filtered by epoch. The UI clears the preview on `STALE_DATA`, `DATABASE_READ_FAILED` and `STALE_SESSION`.
- The dialog shows the exact request. The default and Enter/Escape/close all answer **No**. The session state is re-checked after the modal returns.

**C (partly).**
- Daily window: local midnight today → now.
- Weekly windows: the previous seven complete local days, then the seven days before. Both are half-open, reusing the M3.2D day-window helper.
- Pruned or removed history gives `PARTLY_PRUNED`/`REMOVED`, never 0.
- Alert counts are used only when the stored COMPLETED evaluation matches the current versions. They are always labelled `STORED_NOT_RECHECKED`, otherwise counts are `null`.
- The limitations list states that observed change ≠ consumption and that categories may overlap. UNVERIFIED and Cloud Not Verified appear in the facts, the preview and the rendered AI reply.

**D.**
- Workers never touch Tk. All dialogs and updates run on the Tk thread.
- `submit` refuses while busy, so repeated clicks create no extra threads or requests.
- The modal grab prevents double Send.
- Stop/invalidate discards late results by epoch.
- The 960×600 tab test passes.

## Findings

### P1-F1 — Unknown data-quality counts are reported (and sent) as 0

Location: `checker/narrative.py:125–141` (`_quality_summary`), `ISSUE_TYPES` at line 21.

`recorded_issue_rows` always starts every issue type at 0. It is then filled from `queries.data_quality_summary`, which only covers roles that have a current version. If a role was never synchronised, or its current version is not readable, its issue counts are unknown, yet they are emitted as `0`.

Repro R1:
- Only Storage synchronised: `latest_sync_attempts.bom = NOT_SYNCED`, but `DUPLICATE_BOM: 0, INVALID_BOM_QTY: 0`.
- Nothing synchronised: `latest_retained_storage: null` (correctly unknown), but `recorded_issue_rows` are all `0`, including `DUPLICATE_STOCK`.

The same zeros are in the model request, so a reply such as "no BOM data-quality issues were recorded" would be supported by the facts. This breaks the explicit rule that unknown is never 0. It is also inconsistent with `latest_retained_storage`, which does use `null`.

Suggested bounded fix:
- Key the issue counts per role, or set a role's types to `null` when that role has no current version.
- Let `_validate_quality` accept `null` for unknown.
- Show "unknown" in `show_report`.
- Add a test with one role unsynchronised and one with none synchronised.

### P1-F2 — Weekly comparison is labelled COMPARABLE when a week has no observations at all

Location: `checker/narrative.py:166–173` (`build_in`, `comparable = …`).

Comparability is decided only by global history coverage: was the first snapshot before the window, and is it not pruned. Whether the program actually observed anything in each window is not considered.

Repro R3:
- Baseline on 1 Oct.
- No sync at all during the previous week (8–15 Oct).
- Daily imports during the current week (15–22 Oct).
- Result: `status = COMPARABLE`, previous week `snapshots 0, events 0`, current week `snapshots 6, events 6`, `QUANTITY_CHANGED` delta `+6`.

A week in which the program never ran is missing data, not a week of no change. Labelling it COMPARABLE with a positive delta invites "more stock changes than last week" in the preview and in the AI narrative. The facts also carry no per-window sync-attempt count, so neither the user nor the model can tell "synchronised, file unchanged" (a genuine 0) from "not observed".

Suggested bounded fix:
- Require evidence of observation in both windows before `COMPARABLE`. For example: at least one sync attempt (any outcome) or one snapshot recorded inside each window. Otherwise use `INCOMPLETE_HISTORY` (or a new `NOT_OBSERVED`) with `null` deltas.
- Add the per-window count of recorded sync attempts (an aggregate integer) so the gap is visible.
- Test the R3 shape plus the "synchronised but unchanged all week" case, which should remain comparable.

### P2-1 — Model output is only guarded against digits

Location: `checker/providers.py:259`.

The guard rejects any digit and any tool call, which works as described. Everything else relies on the prompt.

Repro R4 accepted "Twelve materials changed and stock is sufficient; 十二项变化。" Number words (English, Chinese numerals, Malay) and forbidden claims all pass: "stock is sufficient/normal", "cloud-verified", purchase advice.

The reply is displayed beside the deterministic preview, with the UNVERIFIED caveat and the "review" note, so it does not overwrite local statistics. But nothing in the host enforces criterion C ("must not claim cloud verification" / "not normal stock").

Suggested: a small host-side deny-list per language for those claims, plus number words, before display. Or state plainly in the reports that only digits and tool calls are enforced. Not release-blocking for a local commit.

### P2-2 — Issue categories are incomplete and merge roles

Location: `checker/narrative.py:21, 136–140`.

- `NUMERIC_MATERIAL_ID`, which sync records for both roles, is excluded. BOM numeric-ID rows therefore appear nowhere, while Storage ones are covered by `rows_without_usable_id`.
- `INVALID_MATERIAL_ID` adds Storage and BOM rows together.

The labels do not say either of these, so a reader can take the issue table as complete per role. Fix together with P1-F1 (per-role keys).

### P2-3 — Report preview body is English-only

Location: `checker/assistant_ui.py:710` (`show_report`).

The tab, intro, disclosure and errors are trilingual. The preview body is not: "Current period", "Coverage", the limitation sentences and so on are hard-coded English, unlike the M4E three-language presentation of assistant output. The caveats are present, only not translated. The API request language is correct.

## Not verified

- Live DeepSeek API, real key storage, real company workbooks or database, real Drive.
- Packaged EXE, Windows 10, a second PC, physical high-DPI.
- Manual operation of the UI window. I did not drive the user's open window; the UI evidence is the existing source-level Tk tests.
- Behaviour of the actual model against the prompt (only fake replies were used).
- Network timing: a database change during an in-flight HTTP call results in `STALE_DATA` on delivery, but the approved request has by then already been sent. That is a point-in-time boundary and is acceptable as designed; I did not separately test it.

## Handoff

Fix P1-F1 and P1-F2 in `narrative.py`, adjust the preview rendering, add the targeted tests, and re-run `tests.test_m4f` once. If only `narrative.py`/`assistant_ui.py` change, the M4D/M4E runs above need not be repeated. P2s can be fixed or documented at the owner's discretion. No commit, push, release or next milestone was started by this review.
