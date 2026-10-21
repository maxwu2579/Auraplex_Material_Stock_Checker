# M3.2B — Manual Local History Retention

Date: 2026-10-21 (Asia/Singapore).

Implementation verification, not an independent acceptance audit or release approval. M3.2A remains uncommitted alongside these changes; no commit, push or release was performed. All destructive/failure tests use synthetic Excel and temporary databases. Real workbooks, Drive settings and the user's real local database were not opened or cleaned in this stage.

## Scope and safety contract

The **Local History…** action reads a preview on a worker. The default confirmation is No. Nothing automatically prunes at startup, on CHECK, on Refresh or on a timer. After explicit confirmation, the exact preview is applied to local SQLite only.

- Inventory snapshots and unnecessary old Storage payloads: 12 calendar months, using UTC observation/import time. Leap-day subtraction clamps to the previous year's last valid February day.
- Routine `IMPORTED`/`UNCHANGED` logs: 90 days; failed/unavailable logs: 180 days, using UTC finish time. Exact-boundary entries are kept.
- Latest successful/current snapshots and current Storage/BOM payloads are always retained. The last snapshot before the window is kept as a trend baseline, together with predecessor payloads needed to explain retained differences. Source-version headers remain so historical references are not broken. BOM history and the material registry are not pruned by this policy.
- Each role's latest attempt, latest success and successful current-version provenance are protected even when older than the normal log cutoff. A final failure cannot disappear and expose an older success as current.
- Old source headers may remain without their expired stock payload. `load_workbook_data()` explicitly refuses missing/incomplete payloads rather than returning an empty workbook. Retained-history metadata makes trend coverage conservative; 30/60/90-day material results remain unchanged.

## Implementation

`checker/retention.py` uses read-only transactions for preview. It validates schema/integrity/foreign keys, refuses unexpected tables/triggers, and binds an immutable plan to the database file identity and a streamed logical digest of the schema and rows. The digest includes WAL-visible content. Logical scans are linear in database size and run in the worker; memory is bounded to one raw row plus the smaller version/snapshot/log metadata lists. This is a deliberate consistency cost for infrequent manual maintenance, with no source-Excel reads.

After consent the service checks the plan again. It creates an exclusively named `.partial` backup inside the database's `backups` directory, copies a consistent SQLite snapshot, checks integrity and logical equality with the preview, then publishes the `.sqlite3` recovery file without overwriting another backup. A redirected backup directory outside the database folder is refused. Copy progress has a 30-second deadline and cancellation checks. This is not a whole-operation filesystem timeout.

The live database is opened with `mode=rw`, never created when missing. Under `BEGIN IMMEDIATE` the plan is recalculated again; stale/tampered plans are refused. Deletion of expired changes/snapshots, unneeded stock rows/sheets/quality issues and expired logs, plus retention metadata, is atomic. Integrity is checked before COMMIT. Failures attempt rollback, preserve the original error if rollback also reports an error, and close all connections. Database lock wait is bounded to 1500 ms per acquisition. A refused/stale attempt may leave a valid recovery backup but deletes no planned records. A failed copy can leave a distinctly named `.partial` file.

`checker/ui.py` serialises preview/apply with the existing job mechanism. A confirmation that starts another worker cannot allow its older completion to overwrite the newer job. Maintenance read errors clear the database's old success indicators and expire cached consent; ordinary maintenance refusal preserves readable Excel inputs. Maintenance clears the displayed calculation, so CHECK is required afterwards.

`checker/queries.py` records/reports `history_retained_from` through existing `schema_info`. Coverage before this known boundary is false even if a much older sparse baseline remains. Schema version and existing tables are unchanged; no migration or BOM calculation change is introduced.

M3.2A was reviewed against the new maintenance path: explicit cache consent, never-verified cache bindings, separate export guards and source read-only behaviour remain. Protected current payloads/success logs allow cached reconstruction after cleanup. This is implementation-level review, not a separate reviewer’s acceptance.

## Verification

Final full suite: **262 tests, 257 passed, 5 skipped, 0 failures**, in 165.338 seconds (`python -m unittest discover -v`). The five mounted-drive tests were skipped because no mount test directory was configured; this stage does not claim real Google Drive mutation testing. Evidence: `%TEMP%\MRC_M32AB_full_final.txt`.

The 31 new M3.2B tests passed independently in 18.479 seconds (`%TEMP%\MRC_M32B_focused_latest.txt`). M3.2A contributes 26 tests. Chunked SQL operations (500 IDs per statement) are exercised with more than 1,200 expired logs to avoid SQLite parameter limits and repeated whole-table scans.

An isolated PyInstaller build passed the frozen application's normal synthetic Excel flow: initial sync, product selection/search, CHECK, guarded Excel export and unchanged Refresh. `passed`, `frozen`, `result_verified` and `refresh_unchanged` are true; errors are empty and `Cloud Not Verified` remains visible. Evidence: `%TEMP%\MRC_M32B_Package_51f10b568dc14f25abafdefec259a023\smoke\self_test.json` and `build-final.txt`. Maintenance and cached-mode UI behaviour were tested from source, not separately exercised inside the packaged EXE. No second-PC compatibility claim is made.

SHA256 comparisons confirm the existing v1.0.0 portable ZIP and published-folder EXE are unchanged. The build used only the isolated temporary folder. `git diff --check` passed; original calculation, reader, synchronization, database schema, packaging scripts and existing test files remain unchanged. No staging or commit was performed.

Focused tests include preview byte/mtime preservation; calendar boundaries; baseline/predecessor protection; protected logs and unchanged freshness; current cache/source integrity; standalone backup equality; WAL backup; backup failure/timeout; lock contention; missing/foreign/corrupt database refusal; unexpected triggers; stale/forged plans; change after backup; rollback at every deletion stage; combined write/rollback failure; cancellation; no-op/idempotence; trend coverage/results; subsequent sync and unchanged snapshot behaviour; UI consent, responsive workers, job serialisation, stale confirmations, unknown status, expired cached consent and small-window geometry.

Original M3.1/M3.2A tests remain in the full suite. Source workbook and database mutations occur only in temporary synthetic fixtures; existing tests are not weakened. No new dependencies were installed. `git diff --check` is required at completion.

## Limitations and review gate

- Retention limits active database history. Recovery backups still contain older records, have no automatic expiry and may increase total disk usage. No secure erasure or VACUUM is provided. A backup-retention policy requires separate approval.
- Logical deletion allows SQLite pages to be reused, without promising immediate filesystem size reduction.
- Lightweight source headers, BOM history, material registry and protected boundary records can outlive the default periods. This is intentional reference/trend/status preservation, not a claim that every older row is deleted.
- Default storage remains the local per-user application folder; custom cloud/network data folders, physical high-DPI displays, another PC and cloud freshness are not validated here. No cloud-freshness claim is made.
- Export remains synchronous as in M3.2A; this stage does not address its known I/O responsiveness risk.
- New M3.2A/B changes require independent acceptance before a new local commit/release decision. In particular review stale preview handling, protected snapshot/log dependencies, backups and rollback.
- M4 is not started. No cleanup has been applied to the real user database.
