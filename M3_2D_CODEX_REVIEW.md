# M3.2D — Codex focused acceptance review

Date: 2026-10-22 (Asia/Singapore). Base `adee725` (accepted M4A/M3.2C local commit). Reviewed current uncommitted M3.2D sources, shared-code diff, tests and reports. No production/test code changes, real workbook/database access, commit, push, release or next milestone were performed by this review.

## Decision

**NO-GO for a local M3.2D commit: two P1 saving defects reproduced.** No P0 was established. The generation/date/normal-save tests pass, but final data-version validation and failed paired publication are incomplete.

## Verification and evidence

- Read `checker/daily.py`, the window's generation/confirmation/save/lifecycle paths, tests and reports. Shared `alerts.state_in(conn)` is a refactoring to let callers share one read transaction. The main UI diff adds the Daily Summary link/session/window lifecycle without changing CHECK calculations.
- Independently ran `python -m unittest tests.test_m32d -q`: **35 passed, 0 skipped, 6.729 seconds**. Log: `%TEMP%\MRC_M32D_codex_review.txt`.
- Inspected prior logs: `%TEMP%\MRC_M32D_full_suite.txt` has **370 tests, 365 passed, 5 skips, 139.839 seconds**; `%TEMP%\MRC_M32D_after_reorder.txt` has **39 passed, 9.012 seconds**. Those executions were not repeated here. The full suite predates the documented final statement reorder; the affected tests and the 35 tests above cover the ensuing source state, not another full run.
- Used synthetic `SaveTests` fixtures to independently execute the two fault scenarios below; temporary directories were cleaned by fixture teardown.
- `git diff --check` passes. Published v1.0.0 ZIP and EXE SHA256 were rechecked unchanged:
  - ZIP: `768759C9961D9027D1A990E678C5581001F151EE2B54AB1C424AB425ED1517D5`
  - EXE: `E232F2074F0F6DFE35EC623C96ED913C4EC570A53B098ABA45F7F74183930E50`
- Located the synthetic HTML/JSON samples in `%TEMP%\MRC_M32D_evidence`. Actual browser visual inspection **was not executed**: the available browser rejected the local `file:` URL under its security policy. No workaround/alternate serving route was used. Static HTML escaping/self-contained structure is covered by source tests; it is not a visual or print pass.

## P1-D1 — Database changes during staging still publish a VERIFIED report

Location: `checker/daily.py:909–956`, `save()`.

`read_basis(database)` is compared with the summary only at entry, before HTML rendering and file staging. The final publication guard checks this application's SessionGate, not the current database basis. Another instance can publish a new Storage/BOM version or sync/evaluation record without invalidating this process's gate.

Independent reproduction:

1. Generate a verified summary using the synthetic `SaveTests` fixture and retain its basis.
2. Wrap `_stage`; after the HTML stage has been written, update the synthetic stock workbook and publish it with the actual inventory sync service. Leave the summary's SessionGate unchanged, as with a different app instance.
3. Continue the real `daily.save()`.

Observed:

```text
basis_changed = True
report_status = VERIFIED
html_published = True
json_published = True
```

This contradicts the requirement and implementation claim that data/version changes before saving finishes cause refusal and regeneration. The existing tests cover changes before save begins and gate invalidation during staging, not an external database publication during staging.

Required repair:

- Revalidate the latest database basis after rendering/staging and immediately before final publication, including retries after name collisions. Do not treat the session guard as protection against another process.
- Refuse stale saves and publish no final report; preserve the immutable HTML/JSON identity and existing files.
- Keep SQLite/session-lock ordering safe. Do not introduce a path that waits for a database read/write lock while holding a session guard that a database writer needs for COMMIT.
- State verification as a point-in-time version observation, not a permanent local/cloud freshness guarantee.
- Add deterministic tests for Storage, BOM, UNCHANGED sync and newer alert evaluation publication during staging, plus publication retry/name-collision boundaries. Include UNVERIFIED summaries, which must also remain bound to their stated database basis.

## P1-D2 — Failed rollback silently leaves a complete-looking member of the report pair

Location: `checker/daily.py:941–952` and `_undo()` at 967–972.

Files are published separately (JSON first, HTML second). If the second publication fails, `_undo()` tries to remove the first, but silently discards all removal errors. The caller receives only the original write failure while an ordinary final-name JSON, potentially marked VERIFIED, remains visible. The in-process compensation is not a guarantee of paired publication.

Independent reproduction:

1. Generate a verified synthetic summary.
2. Allow the actual JSON publication.
3. Inject an OSError when publishing the HTML.
4. Inject PermissionError only when rollback tries to unlink the final `.json`, representing a Windows sharing/permission failure. Permit normal staging cleanup.

Observed:

```text
error = synthetic second-file publication failure
remaining_files = [Daily_Stock_Summary_... .json]
rollback_error_reported = False
```

Required repair:

- Define a publication format that makes completeness explicit and preserves the pair contract even when compensation fails. For example, stage and validate both members in a private bundle directory, then publish the directory with one no-overwrite rename on the supported filesystem; or use another clearly documented completion protocol that readers/UI enforce. Do not claim two independent renames are an atomic pair.
- On failure, never delete an unrelated/replaced file and never overwrite an existing report. Preserve the initial exception and surface any rollback/cleanup failure with the affected path; no silent `_undo` failure.
- Keep incomplete artefacts clearly distinguishable from successful reports. Test failure of the second publication plus failed deletion, name collision, retries, and the actual chosen commit/completion boundary. Do not claim crash/power-loss atomicity without appropriate evidence.
- Maintain the same report ID/date/basis and JSON hash relationship; adapt the UI/open-saved path to the chosen report layout without adding unrelated features.

## Other findings and limits

- No new generation/classification P0/P1 was established in this bounded review. Historical dates remain explicitly UNVERIFIED and separate generation-time alerts from unavailable historical alert state. Zero, unknown and cross-source differences are qualified in the reviewed paths.
- Actual HTML browser/print acceptance remains open. The sample's presence, parsing and escaped text do not prove layout readability. Ask the user to inspect locally if an allowed visual surface is unavailable; do not mark it passed.
- Strict staleness, local-path disclosure in JSON, observation-date attribution, synchronous export outside this module and the earlier M4A worker limit remain documented limitations/follow-ups.
- No M3.2D frozen EXE, real Drive, company data, second PC, Windows 10 or physical-DPI validation was performed.

## Bounded repair handoff for Claude Code

Read this report and the M3.2D implementation/test reports. Repair **P1-D1 and P1-D2**, retaining accepted M3.2C authorization/publication and source-isolation behavior. Do not alter inventory business rules, add notifications/scheduling/AI, migrate the real database or begin M3.2E.

Use synthetic fixtures and temporary output folders. Run affected save/UI tests during development, then one related regression after the code is final; run one full suite only if shared production paths change or a failure justifies it. Do not repeatedly rerun passed suites. Record before/after repros, the precise publication/completion contract, and any unexecuted visual/packaged checks in `M3_2D_REMEDIATION_REPORT.md`. No commit, push or release. Stop for re-review.
