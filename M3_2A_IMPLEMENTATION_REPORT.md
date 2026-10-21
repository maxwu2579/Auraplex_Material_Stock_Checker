# M3.2A — Explicit Historical Cache Calculations

Date: 2026-10-21 (Asia/Singapore).

This report records implementation verification, not an independent acceptance audit or release approval. The base is local M3.1 commit `311a69a`. The M3.2A changes are not committed or published.

Subsequent M3.2B development is documented separately in `M3_2B_IMPLEMENTATION_REPORT.md`; the verification and scope below describe the M3.2A milestone.

## Behaviour

- Excel remains authoritative and the default CHECK source. A failed Excel load/synchronisation never switches to SQLite calculations.
- **Use Cached Data…** previews the latest successful published Storage and BOM versions. The user sees both original paths, version IDs, source modification dates, import dates and historical verification dates in UTC. The files may have different dates. The confirmation defaults to No; preview alone does not calculate or authorise a report.
- Explicit consent enables a session-only historical mode. Both roles must exist, have successful sync records and contain complete reconstructed data. The user still selects an actual product/Storage sheet and a positive integer quantity.
- The calculation uses the original `check_materials` function. Matching, SHORTAGE/EXCEPTION/ENOUGH classifications, duplicate IDs, blank/text quantities and source row provenance remain unchanged.
- Cached results always display **CACHED DATA / UNVERIFIED**, never `Local Sources Verified`. Existing inventory sync failures stay visible and are not cleared by cached calculations. `Cloud Not Verified` remains permanent.
- Refresh/Reload exits cached mode and reads Excel. A failed refresh does not restore cached consent. Browsing another workbook clears the cached selections. Restarting always begins with the normal Excel workflow, including when sources are unavailable.

## Consistency and export boundaries

`checker/cached.py` opens SQLite using the existing read-only URI and reads both roles inside one read transaction. It does not create/migrate a database or open source workbooks. Connections close before user confirmation; no database lock is held across a dialog.

The selected snapshot binds the absolute database path, database file identity, per-role version metadata, and a digest of the reconstructed immutable workbook data. Counts are checked against the source-version metadata to reject incomplete cached records. The digest is calculated once per loaded snapshot rather than repeatedly hashing all rows on the Tk thread. This detects accidental version/data replacement; it is not an authentication or encryption mechanism.

CHECK verifies the selection before and after calculation. UI preflight and the actual cached writer verify it again; the writer also verifies after staging, immediately before publication. A changed/unreadable database expires consent and blocks reports. A new CHECK cannot restore expired consent; the user must select and confirm the cache again. Product/quantity/sheet changes invalidate the previous result. Old worker responses remain subject to the M3.1 job guard.

`CacheBinding.current` is always false. The normal `save_verified_report()` explicitly rejects cached bindings. Cached export has its own contract and cannot silently become verified Excel export.

Cached reports have an `UNVERIFIED_` filename, a visible UNVERIFIED title and warning on both sheets, and version/import information beside each source path. Comments retain source/version metadata and the calculation time. Printed pages repeat the UNVERIFIED warning. The two M2 business tables are preserved.

Both writers share the existing staging/no-overwrite publication logic. Source paths are refused, existing reports get numbered names, publication collisions are bounded, and a cleanup error cannot mask a verification or write error. An OS-refused staging deletion may leave an unpublished temporary file whose path is shown in the error.

## Changed files

| File | Purpose |
|---|---|
| `checker/cached.py` | Read-only historical snapshot, explicit cache binding, cache verification and UNVERIFIED report contract |
| `checker/ui.py` | Explicit confirmation, mode indication, cached CHECK/export, invalidation and return to Excel |
| `checker/binding.py` | Reject non-Excel bindings at the verified export boundary |
| `checker/report.py` | Reuse staging/publication through a shared helper; retain the Excel verification contract |
| `checker/queries.py` | Documentation of the existing reconstruction API's explicit-cache caller |
| `tests/test_m32a.py` | Synthetic cache acceptance and failure injection |
| `README.md` | User workflow and limitations |

The M2 engine, Excel reader/service, report styles, SQLite schema/synchroniser, existing tests and release build script are not changed. Schema version and application development version remain unchanged; this work does not produce a release.

## Verification

Final command: `.\.venv\Scripts\python.exe -m unittest discover -v`.

**231 tests: 226 passed, 5 skipped, 0 failures, 155.310 seconds.** This includes all 205 pre-existing tests and 26 new M3.2A tests. The five skips require `MRC_TEST_MOUNT_DIR`; no mounted-drive mutation tests were run. Full output is `%TEMP%\MRC_M32A_full_complete.txt`. `git diff --check` passed.

The new synthetic tests cover:

- Missing/foreign/corrupt databases, incomplete rows, both successful roles required, raw-value preservation and Excel/cache parity.
- Version changes, database replacement even with identical IDs, changes during consent and report generation, expired consent and explicit reselection.
- Offline failure without fallback, cancelled consent, session-only opt-in, cached search/selection/quantity validation, busy-job serialisation, source selection and input invalidation.
- Database read failures during CHECK/export, visible unknown database status, and final verification failure combined with denied staging cleanup.
- No Excel reads/database writes during cached CHECK/export; source overwrite prevention, visible report provenance and unchanged M2 table payload.
- Refresh returning to real Excel, failed refresh without fallback, and restart without restored cached consent.
- Tk geometry at 960x600, 1280x720 and 1366x728 with 100/125/150% scaling simulations, including the permanent cloud notice and usable table.

The first integration run exposed a 960x600 layout regression from adding an extra pinned row. The cache button was moved into the top file overview and the existing notice line reused for mode warnings; the original layout tests were retained and passed. Initial test-fixture cleanup errors were fixed by explicitly closing the new tests' SQLite connections.

Final source was built with the existing PyInstaller in an isolated `%TEMP%` directory, not project build/dist. The frozen application's normal Excel workflow passed its synthetic self-test: `passed=true`, `frozen=true`, `result_verified=true`, `refresh_unchanged=true`, `Cloud Not Verified`, no errors. Cache-specific behavioural tests run against the source Tk application; packaged cache interaction on another machine has not been tested.

Package evidence directory: `%TEMP%\MRC_M32A_Package_034b30b8818e4c87b70f31030a333b44`.

The protected v1.0.0 ZIP and EXE SHA-256 values were checked before/after the isolated build and did not change. No company workbook or real user database was opened or modified for M3.2A tests. Test inputs and databases are synthetic temporary files. No dependencies were installed. The existing untracked `audit_test_run.txt` was preserved.

## Limits and next review

- M3.2B retention/pruning is not implemented: no versions, snapshots or logs are deleted. M4 is not started.
- Cached data has no claim of local Excel freshness or Google Drive cloud freshness. Independent Storage/BOM dates are shown explicitly; there is no automatic configuration/version merge or older-version picker.
- Finite verification cannot prevent a change immediately after the last observation. No continuous watcher, cryptographic authenticity, encryption/ACL hardening or crash-durable publication was added.
- Source loading/cached CHECK use background workers and Tk updates stay on the main thread. Export retains synchronous staging/verification, so slow filesystem/database I/O may delay the UI; cache read lock waiting is bounded to 1500 ms per connection, not a whole-operation timeout.
- The current M3.2A run does not validate cloud download completeness, native physical DPI or a second computer. The earlier M3.1 real G-drive normal-flow test is separate evidence, not a cached-mode acceptance claim.
- Independent review should focus on expired consent, mixed-source prevention, database replacement/changes at export, and the shared staging helper's M3.1 regression before a new commit/release decision.
