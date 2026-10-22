# M4C — Controlled tools and Agent core

Date: 2026-10-22. Source implementation complete, pending separate review/acceptance. Not committed or released.

## Implemented

`checker/agent_tools.py` exposes nine allowlisted operations: recorded data status, material search, product search,
exact stock lookup, exact original product-Sheet BOM lookup, recorded stock alerts, estimated requirements,
material history and historical analysis. Model arguments cannot contain a database path, SQL, a command,
an export destination or a consent flag. Unknown tools/arguments and incorrect types are refused.

`checker/agent.py` defines a provider-independent protocol and a bounded tool-calling loop. No SDK, provider,
network call, key storage, dependency or database migration was added. The default without a provider is
`PROVIDER_NOT_CONFIGURED`; ordinary direct tool calls remain usable. Tests use an in-process scripted provider.
M4D owns real DeepSeek integration; M4E owns the robot/chat window and Chinese/English/Malay response routing.

## Data and trust contract

- New tool access defaults to denied. A trusted host must show historical-cache information, obtain explicit
  consent, then call `InventoryTools.authorize_cached()`. That method is absent from the model tool registry.
  Consent is session-only, version-bound, and not restored on restart. This does not silently reuse the existing
  main window's M3.2A consent; a future UI integration must explicitly bind the two workflows.
- Every result/error is UNVERIFIED / Cloud Not Verified. These tools do not read Excel or claim local-source
  verification. Recorded sync success is explicitly historical; an unrecorded failure cannot be inferred from SQLite.
- The host must call `revoke()` on file selection, sync/reload, known failure, mode change and closure. Read failures
  revoke consent automatically. Final results carry the session generation/basis; a future UI must check the job
  generation again immediately before displaying them.
- One read-only transaction binds each tool's data and provenance. M4A/M4B accept an optional already validated
  read-view connection so the new tools can reuse the same view and query cancellation handler. Existing callers
  retain their original default behavior. Version/sync/retention/alert-evaluation changes invalidate selection.
- A post-query and final Agent basis check reject changed/replaced databases. An actual WAL publication from stock
  100 to 0 during a tool query was reproduced: old evidence was discarded, and re-selection read 0.
- Checks describe finite database observations, not permanent freshness, Excel availability or cloud freshness.
  The basis assumes the application's immutable version records; it is not cryptographic protection against a
  hostile editor rewriting SQLite rows in place while preserving metadata.
- Exact normalized IDs preserve internal spaces, suffixes and punctuation. Original Sheet names are preserved.
  Several search candidates stop the Agent with NEEDS_SELECTION before further calls in that run. This is not a
  general natural-language disambiguation guarantee; real-provider identity interpretation needs M4D/E acceptance.
- Blank quantities remain unrecorded/unknown, invalid text stays text, and duplicate rows stay separate. Stock
  lookup supplies no aggregate quantity. The unchanged M2 calculation engine still applies its approved ASSUMED 0
  exception rules; the result remains ESTIMATED / UNVERIFIED / Verification Required, never a production approval.
- Final Agent answers contain deterministic tool evidence only. Unrestricted provider prose is not published as
  an inventory answer. Workbook strings remain JSON tool data and are explicitly untrusted in the system contract.
  Natural-language answer rendering/translation is intentionally deferred, including free-form clarification text.
- Provenance includes source paths, versions, hashes, import times, recorded sync attempts and original row/Sheet.
  It can contain sensitive company data. M4D must define and authorize outbound disclosure/redaction before sending
  these envelopes to any real API; this milestone sent nothing externally.

## Bounds and errors

Defaults: five model steps, eight calls, at most four calls per reply, twenty seconds per run, five seconds per
tool (or the remaining run budget), 128 KiB per tool result and 512 KiB context. Candidate/history/alert displays
are limited to 200 entries with explicit totals/truncation; large full BOM/calculation outputs are refused.
Workbook reconstruction is capped at 50,000 rows. Historical tools cap the window/reference workload and M4B
keeps its own snapshot/group bounds. SQL progress handlers check time and cancellation. IDs and input sizes are
validated before execution; decimals are serialized as exact strings.

One Agent instance permits one synchronous run; concurrent requests get BUSY. No threads or Tk calls are created.
Cancellation, revoked consent, provider failure, changed data and exhausted budgets do not return prior successful
evidence as a new answer. There are no automatic retries, provider switches or cached-mode fallbacks. Concrete
provider adapters must enforce network timeout/cancellation: Python cannot preempt an arbitrary blocking adapter.
SQLite lock waits can add up to the existing 1.5-second read-view busy timeout; these are cooperative bounds, not
hard real-time deadlines. The future UI must invoke this synchronous API from a worker, not the Tk main thread.

## M4B P2 follow-up

Historical analysis now checks Storage ownership, Sheet counts and row-to-Sheet version ownership. Missing Sheet
metadata and cross-version links refuse analysis instead of silently returning an empty/incorrect grouping.
Fully removed historical payloads retain NOT_RETAINED behavior. Ownership queries use per-version indexed branches
instead of scanning all historical rows for every snapshot. Synthetic reproductions and original M4B tests pass.

## Scope and remaining acceptance

No changes to M2 rules, existing CHECK/export protection, sync, alerts publication, retention, scheduling, UI,
schema, source files or released packages. This is an implementation with self-tests, not an independent audit.
Real AI, GUI integration, live Google Drive, company workbooks/database, EXE, second PC, Windows 10 and physical
DPI were not exercised. See `M4C_TEST_REPORT.md` for the focused validation. Separate review precedes commit.
