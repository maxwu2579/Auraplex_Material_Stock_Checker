# M4C — Codex source review

Review date: 2026-10-22
Scope: M4C tools/Agent, M4B Sheet ownership repair, affected M4A/M4B/M2/parity regressions.
Decision: **GO for a local Git commit.** No P0/P1 findings. Two P2 performance follow-ups are recorded below.

## Review evidence

Inspected `checker/agent.py`, `checker/agent_tools.py`, the history/analytics changes, tests and milestone reports.
Ran:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_m4c tests.test_m4a tests.test_m4b tests.test_m2.RuleTests tests.test_m31.ParityTests -q
```

Result: **105 passed, 0 skipped, 0 failed in 17.581 seconds**. `git diff --check` passed. The full suite, packaged
application, actual AI provider, real Google Drive, company database/workbooks, second PC and physical DPI were not
tested. Review and tests used synthetic data; no production code/data was changed during this review.

## Findings

### P2-1 — Remaining Agent time is not passed into M4B analysis

`Agent` passes the remaining run budget to `InventoryTools.call`, and the tool installs a deadline on its SQLite
connection. The `material_analysis` branch then calls `analytics.analyze` without its `budget_seconds` argument.
That function installs a new five-second deadline and replaces the connection progress handler. A request that
starts with less than five seconds remaining can therefore keep working for almost another five seconds before
the outer layer rejects its result. This does not publish stale evidence, but the documented twenty-second run
limit can be exceeded by a material amount. Pass the remaining tool budget into `analytics.analyze` and retain
cancellation; add a near-deadline regression before real-provider integration.

Relevant code: `checker/agent_tools.py` around the `analytics.analyze` call; `checker/analytics.py` deadline and
progress-handler setup.

### P2-2 — Historical Sheet integrity precheck scans all retained Storage rows

Before a material-history or material-analysis query, the tool counts orphan/cross-version stock rows with an
unscoped join over `stock_records`. The subsequent query is capped to the requested period and reference
snapshot, but this precheck still visits rows from every retained version. At the current retention limit it is
finite, but it adds avoidable work to each history request and can consume the five-second tool budget as history
grows. Validate ownership only for the selected snapshot/source-version IDs, using the existing per-version
indexes, and preserve the fail-closed behavior.

Relevant code: `checker/agent_tools.py` around the `broken` ownership query in the history/analysis branch.

## Verified safety properties

- Model-facing tool names and argument schemas are allowlisted; no SQL, write, sync, export, arbitrary database
  path or consent grant is exposed. Cache consent defaults to denied and is session/version bound.
- Data and provenance share a read-only SQLite view. Normal synchronization, alert-evaluation, retention and
  database-replacement changes invalidate the selected basis. A synthetic WAL test imported stock 0 during a
  query that read 100; the result was rejected and the next selected query read 0.
- Errors, status and results retain `UNVERIFIED` / `Cloud Not Verified`. Recorded success is not described as a
  live source check. An unknown/missing stock row stays unknown, and duplicates remain separate.
- Multi-candidate material/product searches stop for selection. The M2 engine remains the estimator and its
  tested categories/exception rules are unchanged; no production-ready status is introduced.
- Model prose is not returned as a numeric inventory answer. Provider exceptions are sanitized; cancellation,
  session revocation, changed database basis and exhausted limits discard earlier evidence.
- M4B now refuses missing Sheet metadata and cross-version row ownership; fully pruned historical payloads remain
  explicitly unavailable. The original M4B cases passed.

## Decision and limits

The P2 findings affect bounded latency and efficiency, not inventory arithmetic, source writes or freshness
claims. They do not block a local commit. Address both before relying on larger histories or integrating a live
provider. M4C remains source-only: no AI provider, chat UI, multilingual response layer, API-key handling or
packaged acceptance is included. Do not treat this source review as release approval.
