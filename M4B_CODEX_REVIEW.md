# M4B — Independent Codex Review

Date: 2026-10-22
Scope: `checker/analytics.py`, `checker/analytics_ui.py`, the `checker/ui.py` integration, M4B documentation, and the existing M4B tests. This review did not modify production code.

## Decision

**GO for a local Git commit**, with one P2 integrity-hardening follow-up. This is source-level review only; it does not approve a packaged release or real-data deployment.

## Findings

### P2 — Missing Sheet metadata can silently hide stored rows

In `checker/analytics.py`, lines 163–173, a snapshot is considered complete when the total `stock_records` count equals the two recorded counts. The subsequent row load uses an inner join to `stock_sheets`. If a Sheet metadata row is missing or points to the wrong source version, the join can drop records even though the count check passed. The analysis then reports no material group and no incomplete-payload warning.

I reproduced this with a temporary synthetic database: one stored stock record and zero `stock_sheets` rows produced zero reported groups and no payload warning. The fixture required disabling SQLite foreign-key enforcement to create the inconsistent state; normal application transactions are not expected to produce it.

Recommended follow-up: validate the recorded Sheet count and that the joined record count equals the stored record count, including source-version ownership. On mismatch, fail the query as a database read/integrity error rather than treating the material as absent. Add a synthetic regression case before packaged or real-database acceptance.

## Review checks

- Historical quantities remain explicitly unverified and are not presented as current stock or cloud-verified.
- Source path, original Sheet name, and normalized exact Material ID remain separate; similar IDs are not merged.
- Blank, invalid, duplicate, absent, and pruned data do not become zero. Net change is withheld across incomplete chains; comparable movement is clearly scoped to retained adjacent observations.
- Low movement, unchanged stock, and percentage-change thresholds are visible heuristics. No consumption, demand, purchase, or confirmed excess-stock conclusion is inferred.
- The read-only transaction gives a consistent SQLite view; cancellation, limits, and UI generations prevent partial, unbounded, or late results from being displayed.
- The main-window integration is limited to the Analytics link and window lifecycle. Existing business calculation and export paths are unchanged.

## Test evidence and limits

Independent focused run: **29 tests passed in 12.346 seconds** — 24 M4B tests plus five relevant existing M3.1/M4A/M3.2D UI checks. The full suite was not rerun. The read-only failure reproduction used only a disposable synthetic database.

### Read-only check with the supplied desktop workbooks

Both supplied workbooks were imported with the application's existing read-only parser into a disposable SQLite database under the system temporary directory; that directory was automatically removed at the end. The source fingerprints matched before and after. The user's real application database was not opened.

Business meaning confirmed by the user: a blank Storage quantity means no stock record was entered. It does not establish that actual stock is zero; the amount remains unknown until recorded.

- Storage: 885 rows, 873 keyed material groups across one Sheet; 54 groups had blank quantities, 46 had text/invalid quantities, and 12 groups had duplicate records. The remaining 761 groups had one valid quantity.
- BOM: 882 material lines across 11 product Sheets, with 496 distinct keyed IDs. Exact normalized matching found 133 IDs / 373 BOM lines with no Storage match.
- M4B saw one imported Storage snapshot and returned 873 historical groups. It produced no low-movement or large-change signal, correctly leaving trend classification unavailable with only one observation. Missing and duplicate quantity states remained explicit.

This validates source parsing and single-snapshot behavior against these desktop files. It does not establish Google Drive freshness or a multi-snapshot trend from real history. No M4B EXE, Google Drive, second PC, Windows 10, physical high-DPI display, or human visual inspection was tested. Those remain separate acceptance work.
