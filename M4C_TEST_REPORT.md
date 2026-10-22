# M4C — Focused source validation

Date: 2026-10-22. Synthetic workbooks/databases in temporary directories only. No external AI calls or real data.

## Final regression command

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_m4c tests.test_m4a tests.test_m4b tests.test_m2.RuleTests tests.test_m31.ParityTests -q
```

Result: **104 passed, 0 skipped, 0 failed in 16.512 seconds**. After this run, only the new tool module was refined:
analysis cancellation/limit errors retain their correct error categories, recorded alert state explicitly says
NOT_EVALUATED / UPGRADE_REQUIRED when applicable, and status provenance omits alert summaries. One new regression
test and stronger existing alert assertions were added. The final affected-module check was:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_m4c -q
```

Result: **44 passed, 0 skipped, 0 failed in 2.415 seconds**, on the finalized implementation. The unchanged
M4A/M4B/M2/parity paths were not repeated after this isolated tool-only refinement. This is intentionally an
affected-module regression, not the entire suite or packaged acceptance. These runs cover 105 distinct cases;
the 43 original M4C cases were repeated, not counted twice as independent cases.

## New tests (44 distinct cases)

- Tool allowlist, strict argument types/sizes, rejected SQL/write/export/consent/path capabilities.
- Denied-by-default access; explicit cached selection; revoke/restart; version/UNCHANGED/failure/evaluation changes.
- Historical status versus current local/cloud verification; source hashes/import times/row provenance.
- Exact normalization, significant suffix/space differences, original Sheet identity and separate duplicates.
- Blank and text stock, missing IDs and raw row preservation; unchanged M2 estimated calculation parity.
- BOM and candidate queries; ambiguous searches stop before a provider can select a convenient candidate.
- Source/database bytes and modification times unchanged by every registered tool.
- Missing database is not created; unsupported schema refused; legacy schema not migrated; WAL read not reconfigured.
- Read-only SQLite connection rejects an injected write; read failure revokes earlier session consent.
- New sync between data read and publication; actual WAL import of 0 while the query holds old stock 100.
- Orphan and cross-version Sheet metadata refused in M4B/tools.
- Output/time/row/context/step/call limits, invalid provider replies, duplicate call IDs, concurrent-run BUSY.
- Cancellation/revocation during provider or final basis read discards late evidence.
- Database failure/source publication after successful tool calls discards all earlier evidence.
- Fake model's invented number/production approval never becomes a returned inventory answer.
- Source prompt-injection text remains untrusted tool data; provider errors do not leak their exception strings.
- No provider configured does not prevent authorized direct deterministic tool use; no fallback provider is invoked.

## Development failures corrected

The first run had three fixture cleanup errors: Python's SQLite connection context manager commits/rolls back but
does not close connections. Test helpers now use explicit `closing()`. Adding the ninth tool exposed a missing
fixture argument entry, which was added. A tiny real-time budget assertion was nondeterministic on Windows;
it now uses a deterministic injected clock. These failures were not ignored or counted as passing.

The existing M4A/M4B tests exercise coverage, retention gaps, concurrent reads, default caller compatibility and
their UI paths. M2 RuleTests and M3.1 ParityTests cover the reused calculation/export data behavior. No shared
calculation/report logic changed. M3.2C publication/retention/scheduling and the full suite were not rerun because
their code paths were not modified; a complete delivery regression remains a later acceptance step.

## Not executed

Independent review, real provider interpretation and cancellation, cloud freshness, real company workbook/database,
M4C EXE build/smoke, other PC, Windows 10, physical DPI and chat UI. No release readiness is claimed. The existing
untracked `audit_test_run.txt` was left outside this work; no commit, push, task installation or release occurred.
