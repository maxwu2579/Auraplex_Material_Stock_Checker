# M3.2C — Remediation of the Codex review

Date: 2026-10-21. Input: `M3_2C_CODEX_REVIEW.md` (NO-GO; P1-1, P1-2, P1-3, P2-1, P2-2). Repair by Claude Code on the uncommitted working tree (base `d0633fd` + accepted M4A + M3.2C). Nothing was committed, pushed or released. The real Excel files were only read. The user's real database was not opened or upgraded. M3.2D was not started. Re-review `M3_2C_CODEX_REREVIEW.md` found two remaining P1 gaps (P1-R1, P1-R2); their repair is the first section below. **Ready for Codex re-review**; this is not an independent acceptance.

## Re-review repair (2026-10-22): P1-R1 and P1-R2

Input: `M3_2C_CODEX_REREVIEW.md` (NO-GO). It found two remaining P1 gaps; P1-3, P2-1 and the P2-2 filters/view were accepted. Only P1-R1 and P1-R2 were changed. The accepted source-scope, migration, provenance and filter fixes are unchanged, and their tests and mutation checks still pass. Nothing was committed, pushed or released. The real Excel files and the real database were not touched. **Ready for Codex re-review.**

### P1-R1 — authorization is checked at the actual publication point

**Before (Codex):** the gate was invalidated after the one pre-write check, at `INSERT INTO alert_evaluations`. The run still finished `COMPLETED` with `resolved=1`, and B became RESOLVED.

**Fix (`checker/alerts.py`):**
- **Publication guard.** `SessionGate.publishing(generation)` is a context manager. It holds the gate lock, yields whether the generation is still current, and keeps `invalidate()` waiting until the block ends.
- **Guarded COMMIT.** `AlertService._publish()` makes the verified COMMIT the only statement inside that guard: `with guard() as current: if current: COMMIT`. If the guard refuses, everything in the transaction is rolled back: the evaluation row, upserts, re-opened episodes and resolutions. A separate transaction then records the attempt as **UNVERIFIED** ("the session's verification changed before publication") and changes no alert.
- **Early check.** The earlier check is kept only as an early exit. The authoritative check is the one around COMMIT.
- **Linearisation and lock order:**
  - The publication transaction now starts with `BEGIN EXCLUSIVE`, so by the time the guard is entered no other connection can hold a lock that COMMIT must wait for.
  - Lock order is always SQLite first, then the gate, briefly. The gate lock is never held while waiting for SQLite, during evaluation, or during a backup.
  - `invalidate()` on the Tk thread therefore waits at most for one COMMIT, and is ordered entirely before the publication (rolled back) or entirely after it (a later event, which the UI's generation check treats as newer).
- **Runner.** `AlertRunner` passes `lambda: gate.publishing(generation)`. A retry with the same old authorization stays UNVERIFIED; only a new authorization at the current generation can publish.
- **Scope.** This orders local transactions against session events. It does not prove cloud freshness.

**Injection boundaries and results (`tests/test_m32c_rereview.py::PublicationTests`).** The test hook `alerts._checkpoint(stage, conn)` runs inside the publication transaction:

| Invalidated at | Outcome | Alerts table | Evaluation rows |
|---|---|---|---|
| `evaluation_inserted` (Codex's boundary) | UNVERIFIED, new 0, resolved 0 | identical to before (B still ACTIVE LOW_STOCK) | the verified row rolled back; one UNVERIFIED row recorded |
| `alerts_upserted` | same | identical | same |
| `alerts_resolved` | same | identical | same |
| `before_commit` | same | identical | same |
| `alerts_resolved`, invalidated from **another thread** | same | identical | same |
| Re-authorised (new gate, new authorization) | COMPLETED, resolved 1 | B resolved | — |

**Additional tests:**
- The guard holds `invalidate()` from another thread until the publication block ends; the observed order is `check → commit → invalidated`.
- While a publisher waits for its EXCLUSIVE lock behind a reader, `invalidate()` returns in under 0.2 s, and the publication is then refused.
- Runner: an invalidation at `before_commit` gives UNVERIFIED; a retry with the old authorization is UNVERIFIED and B stays active; a fresh authorization publishes, with resolved 1.

### P1-R2 — read failures invalidate everything; evidence is discarded, not re-stamped

**Before (Codex):**
- A failed alert-window read cleared only the table body; `alert_current` stayed True and the session line said "Re-checked in this session".
- Background status read errors were ignored.
- `_invalidate_alerts()` kept the per-role evidence, so `alert_authorization()` reissued an authorization at the new generation.

**Fix (`checker/ui.py`, `checker/alerts_ui.py`):**
- **Evidence is discarded.** `_invalidate_alerts(reason, roles, read_failure)` now **removes the verification evidence** (verified role, version and path) of the given roles, besides moving the gate generation on:
  - a sync start removes it for exactly the roles being checked again;
  - a sync failure removes it for the failed roles;
  - any database read failure, a failed evaluation and an upgrade remove it for **both**.

  Only new successful source checks rebuild it. A manual Re-evaluate after a failure therefore has **no authorization** and is recorded as UNVERIFIED.
- **All read failures route the same way.** `CheckerApp.alert_read_failed(error)` handles every read failure of alert data:
  - the window's alerts read;
  - the window's observed-changes read;
  - the background status read;
  - retention and cache read failures.

  It invalidates as above and sets a read-failure flag. A later successful read clears only that flag; it never re-verifies.
- **What the user sees:**
  - The entry line reads `N active · not re-checked · database read failed`, and its tooltip shows the reason.
  - The window's session line starts with **DATABASE READ FAILED · NOT RE-CHECKED IN THIS SESSION — reason**.
  - Stored inventory rows, alerts, Excel inputs and the historical basis are kept and shown as historical and unverified; nothing is deleted or set to 0.

**Tests (`ReadFailureUiTests`):**
- An alert-window read failure invalidates the session line, the entry and the evidence: generation bumped, `alert_sources` empty, `sources_verified()` False, `alert_authorization()` None. On reopening, the data is readable again but the session is still NOT RE-CHECKED, and the count is shown qualified.
- An observed-changes read failure invalidates in the same way.
- A delayed background status read failure invalidates in the same way.
- Manual Re-evaluate after a failure, while another program has published data in which A is fixed: the evaluation is UNVERIFIED and A's OUT_OF_STOCK / LOW_STOCK stay ACTIVE. A successful Refresh then re-checks both files, publishes COMPLETED, resolves A, and clears the read-failure flag (`Stock Alerts: 0 active`).

### Mutation evidence

Each defect was re-introduced in a temporary copy, and its regression test **fails**:
- no guard at the publication point;
- the guard releases the gate lock before COMMIT;
- evidence only re-stamped with a new generation;
- the alert-window read failure not routed;
- the background status read failure ignored.

The six earlier mutations (P1-1 ×2, P1-2, P1-3, P2-1 ×2) are still detected, so all 11 are detected. The earlier "session gate ignored" mutation was replaced: that pre-check is now only an early exit, and the guard around COMMIT is the authoritative check.

### Verification

| Run | Result | Time |
|---|---|---|
| `tests.test_m32c_rereview` | 9 passed | ~4 s |
| `tests.test_m32c_remediation` (17; one test now passes the publication guard instead of a boolean; UI helpers moved into a test-free `SessionUiBase`) | passed | ~7 s |
| Affected modules (`test_m31 test_m32a test_m32b test_m32c test_m32c_remediation test_m32c_rereview test_m4a test_ui`) | 206 passed | 102 s |
| **Final full suite** (once, code final) | **335 tests: 330 passed, 5 skipped, 0 failures** | **104.1 s** |

The 335 tests are the previous 326 plus 9 new. The 5 skips are the mounted-drive tests. Log: `%TEMP%\MRC_M32C_rereview_full_suite.txt`. `git diff --check` passes, and all files use LF line endings. The real-data counts were not re-run in this round: the evaluation logic is unchanged, and only publication ordering and UI invalidation changed.

### Changed in this round

| File | Change |
|---|---|
| `checker/alerts.py` | `SessionGate.publishing`; `run()` / `_publish()` with `BEGIN EXCLUSIVE`, guarded COMMIT, rollback and a separate UNVERIFIED record; `_checkpoint` hooks; the runner passes the guard |
| `checker/ui.py` | `_invalidate_alerts(reason, roles, read_failure)` discards evidence; `alert_read_failed` / `alert_read_ok`; status-read and evaluation failures routed; the entry line shows read failures |
| `checker/alerts_ui.py` | Window read failures (alerts and observed changes) routed to the owner; DATABASE READ FAILED in the session line |
| `tests/test_m32c_rereview.py` | 9 new tests |
| `tests/test_m32c_remediation.py` | Guard API in one test; `SessionUiBase` helper split (no test changed in substance) |

### Remaining limitations of this round

- **Tk thread wait.** `invalidate()` on the Tk thread can wait for one in-progress COMMIT, normally milliseconds; a very slow disk would lengthen that wait.
- **Readers blocked briefly.** `BEGIN EXCLUSIVE` blocks other readers (history, status, cache) for the duration of one short alert write; their 1.5 s busy timeout covers it, but a very slow disk could make one of their reads fail. Such a failure is then shown as a read failure, never as success.
- **Re-check after a read failure.** After a database read failure, alerts become current again only after a successful source check of **both** files (Refresh Excel, or start-up). This is deliberately conservative.
- **Still open, as before:**
  - observed-change notifications are not implemented;
  - M4A history-worker fan-out (P2);
  - synchronous export responsiveness;
  - business confirmation of the threshold, zero, duplicate and unit rules;
  - not executed: frozen EXE, real Drive, second PC, Windows 10, physical DPI.

## First remediation round (2026-10-21)

## Summary

| Finding | Status | Regression tests (`tests/test_m32c_remediation.py`) | Mutation check |
|---|---|---|---|
| P1-1 sync failure between evaluation and publication could resolve alerts | **Fixed** | 4 `AuthorizationTests` | 3 mutations, all detected |
| P1-2 late success removed a newer failure warning | **Fixed** | 4 `SessionUiTests` (+ 1 window test) | detected |
| P1-3 alerts of different Storage/BOM files were merged | **Fixed**, including the schema-2 migration | 3 `ScopeTests` + 1 `SchemaTwoMigrationTests` | detected |
| P2-1 pruning removed live provenance; failures unbounded | **Fixed** | 2 `ProvenanceTests` | 2 mutations, both detected |
| P2-2 original requirements not all implemented | **Implemented as listed below**; observed-change *notifications* remain unimplemented (see "Not done") | 2 `OriginalScopeTests` + UI filter test | — |

**Mutation evidence.** Each fix was removed again in a temporary copy of the code, and its regression test was run against that copy. All 7 tests **failed**, so they detect the defect they cover. The mutations were:
1. no re-check of sync records under the write lock;
2. session gate ignored;
3. authorization not bound to versions;
4. obsolete UI result accepted;
5. source missing from the alert identity;
6. latest verified basis pruned;
7. referenced provenance pruned.

The script is `mutation_check.py` in the session scratchpad.

## P1-1 — authorization bound to concrete facts

**Before (Codex):** a stock sync recorded `Source File Unavailable` after the evaluation read, without changing version IDs. The evaluation still finished `COMPLETED`, verified, with `resolved=1`.

**Fix (`checker/alerts.py`):**
- `evaluate()` records each role's **newest sync record** (id, outcome, version, selected path). `db_verified` holds only if both newest records are successes for the current versions.
- `AlertService.run(trigger, authorization, still_valid)`. The `Authorization` is what the caller itself verified: for each role, the version ID and selected path of its own successful syncs, at a `SessionGate` generation.
- Under `BEGIN IMMEDIATE`, both the current versions **and the newest sync record of each role** are compared with what was read. Any difference, including a failure recorded for the same version, raises `AlertStale` and **nothing is written**.
- In the same locked step, the evaluation counts as verified only if all of these hold:
  - `db_verified`;
  - the authorization names exactly the current version and path of each role (`same_path`);
  - `still_valid()` reports the gate generation unchanged. The gate is thread-safe; the UI invalidates it on unrecorded failures too.

  Otherwise the evaluation is recorded as **UNVERIFIED** with the reason, and no alert is added, updated or resolved.
- The runner's single retry after `AlertStale` starts from scratch. An old authorization never covers a newly published version.

**Tests:**
- recorded same-version failure at the write boundary → `AlertStale`, then the retry is UNVERIFIED and B stays ACTIVE;
- unrecorded session failure (gate invalidated at the write boundary) → UNVERIFIED, nothing resolved;
- authorization of an older version → UNVERIFIED;
- authorization naming another path → UNVERIFIED, while the proper session resolves exactly one alert.

## P1-2 — the session state always overrides late or stored results

**Before (Codex):** after a failed Refresh the label stayed "evaluating…". The old completion then showed "2 active" with no warning, and the window's basis showed no warning either.

**Fix (`checker/ui.py`, `checker/alerts_ui.py`):**
- The application holds a `SessionGate`, and `alert_sources` (per role, the version and path from its own successful syncs). It invalidates the gate and marks alerts *not re-checked*, with a reason, on:
  - every sync job start (start-up, source selection, Refresh, Reload, CHECK);
  - every sync failure, recorded or not;
  - a database status read failure, including retention and cache read failures;
  - an upgrade;
  - a failed evaluation.
- Runner events carry the generation of their request. A result is accepted as current only if it is verified, its generation is still current, and the session is still verified. **An obsolete result updates the stored count only and never clears the warning.** Background status reads also update counts only.
- One renderer builds the entry line from the stored count plus the session state, giving `… N active · not re-checked · evaluating…`.
- The window's first line always shows either *Re-checked in this session…* or **NOT RE-CHECKED IN THIS SESSION — reason …**, updated immediately on invalidation. The basis also states the files current in the database and the last verified evaluation of **exactly those files**.
- The main CHECK's direct-Excel rules are unchanged.

**Tests:**
- Codex's scenario: a real run commits, its delivery is held, Refresh fails, then the run is released. The label and window keep "not re-checked" both before and after the late success.
- A delayed status read cannot clear the warning.
- A restart with unverifiable Storage shows `2 active · not re-checked` and the window warning.
- Source selection bumps the generation immediately, and only the new file's own verified evaluation makes alerts current.

## P1-3 — identity per source file (schema 3)

**Before (Codex):** a copied Storage file at another path reused the old alert key and first-seen time, and overwrote its version.

**Fix:**
- **Identity:** `alert_key(type, subtype, storage_source, bom_source, sheet, material_key, row)`. `storage_source` / `bom_source` are normalised file identities (`source_identity`: `normcase`, `normpath`, absolute path). The BOM file belongs to the identity of BOM-coverage alerts only. The version ID is **not** part of the identity, so new versions of the same file still de-duplicate.
- **Resolution scope:** an evaluation loads and resolves only alerts of its own Storage file, and for coverage alerts only those of its own BOM file.
- **Other files:**
  - Alerts of other files stay ACTIVE.
  - `load_state()` marks them `in_scope=False` and counts them as `other_sources_active`; the label count covers the current files only.
  - The window hides them by default (*Show other source files*), labelling them *OTHER SOURCE · not re-checked*.
  - Switching back continues the same alerts, first-seen kept.
- **Schema 3** (`UPGRADE_TO_3`, add-only): `storage_source` and `bom_source` on `stock_alerts` and `alert_evaluations`, plus an index. New databases are created at schema 3.
- **Upgrades**, both explicit with preview, default No, verified backup and one transaction:
  - From **schema 1**, `UPGRADE_TO_2 + UPGRADE_TO_3`.
  - From **schema 2**, every existing evaluation and alert is attributed to the files of the versions it references (`source_versions` headers are never deleted), and its key is rewritten in the new form, keeping first/last-seen. Nothing is reset. An alert without an attributable version would keep an empty scope and never be resolved.
- Schemas 1 and 2 stay usable for every other function; alerts report "upgrade required".

**Tests:**
- Storage file switch: new alerts for the copy; the original's untouched (provenance kept), out of scope, not resolved. Switching back gives `new = 0, resolved = 0`, first-seen kept.
- A new version of the same file still de-duplicates.
- A BOM file change creates only the coverage alert anew and does not resolve the old BOM's.
- A schema-2 database with alerts in the old key format: preview counts them; the backup equals the pre-upgrade database; after the upgrade the alerts carry their files and a verified evaluation matches them (no duplicates, original first-seen kept).

## P2-1 — bounded history that keeps provenance

**Before (Codex):** with `KEEP_EVALUATIONS=3`, one COMPLETED and four UNVERIFIED runs left 14 active alerts but `latest_completed=None`. Failure rows were never pruned.

**Fix:** `_prune()` deletes an evaluation only if it is none of these:
- among the newest `KEEP_EVALUATIONS` (200);
- the **latest COMPLETED evaluation of each file scope**;
- **referenced by any stored alert** (first, last or resolving evaluation).

Resolved alerts are kept for 180 days; once they are removed, their references stop protecting old rows. `_record_failure()` now writes inside a transaction and prunes as well. This alert-retention rule is separate from the approved M3.2B inventory/log retention, which is unchanged, and it is documented in the README.

**Tests:**
- 1 COMPLETED, then 1 more COMPLETED, 4 UNVERIFIED and 5 FAILED runs: the verified basis survives, there are no dangling references, and exactly 5 rows remain.
- A verified basis referenced by no alert (clean data, old resolved alerts aged out) survives 5 unverified runs.

## P2-2 — original requirements

The original M3.2C instruction is still not in the repository; Codex's review reconstructs its functional points. Implemented now:

| Original requirement | Implementation |
|---|---|
| Identify observed stock changes | **Observed Changes** tab in Stock Alerts: `alerts.observed_changes_view()` lists every observed change of the **current Storage file** in 30/60/90 days, from the stored M3.1 snapshots (no Excel parsing). It uses the M4A change semantics: a difference only between single valid records of the same file, `not comparable (source switch)`, and blank/invalid/duplicate changes shown without a difference. Totals are counted; up to 2,000 rows load, 200 render at a time; coverage notes are shown. **Observed Change ≠ Actual Consumption.** |
| Stock-change filter | Change-type filter (QUANTITY_CHANGED / ADDED / REMOVED / VALIDITY_CHANGED / DUPLICATE_CHANGED) and range |
| Storage Sheet / material filters | Shared **Storage Sheet** and **Material ID contains** filters for both tabs (filtering only; similar IDs are never merged) |
| Threshold shortfall when valid and comparable | `threshold_shortfall` = threshold − LIVE STOCK, for LOW_STOCK only, in a *Shortfall (trial)* column and the details ("not a production requirement") |
| Full provenance | Each alert stores its Storage file path and version (and BOM file and version for coverage alerts), row, raw values, threshold column and header. The window shows a *Source File* column, and the details show full paths, Rack/Level, versions, and first/last-seen times in UTC. |

**Not done (needs a separate decision, not claimed as complete):**
- Observed changes are a historical **view**, not alerts with an ACTIVE/RESOLVED lifecycle.
- **No observed-change notifications** exist: there is no notification channel; daily summaries are M3.2D. If notifications are wanted, version-specific event de-duplication should be designed with M3.2D.
- If the original instruction contains requirements beyond Codex's reconstruction, they are not known here.

## Verification

| Run | Result | Time |
|---|---|---|
| `tests.test_m32c_remediation` (17 tests) | passed | ~5 s |
| `tests.test_m32c` (24, adapted to the concrete authorization API and schema 3; assertions not weakened) | passed | ~5 s |
| Affected modules (`test_m31 test_m32a test_m32b test_m32c test_m32c_remediation test_m4a test_ui`) | first 196/197 passed (alert window too short at 960×600 with 1.5× fonts → window compacted, see below), then passed | 93 s |
| Order-dependent layout check (`test_m32b` then `AlertUiTests`) | passed | — |
| **Final full suite** (once, code final): `python -m unittest discover -v` | **326 tests: 321 passed, 5 skipped, 0 failures** | **141.0 s** |

The 326 tests are the previous 309 plus 17 new. The 5 skips are the mounted-drive tests; no Drive test ran. Log: `%TEMP%\MRC_M32C_remediation_full_suite.txt`. `git diff --check` passes, and all changed and new files use LF line endings.

**Layout:** the Stock Alerts window got shorter caveats (the full rules moved into the scrollable basis panel), and its basis and details boxes adapt to small windows like M4A's. Measured table height:

| Fonts | 960×600 | 1280×720 |
|---|---|---|
| 100% | 244 px | 345 px |
| 1.5× | 110 px | 289 px |

**Real data (read-only, temporary databases, deleted afterwards):** re-run on the final code. The fresh schema-3 path and the schema-1 → 3 upgrade path (0.10 s, verified backup, thresholds captured from the same parse) give identical results:
- OUT_OF_STOCK 494;
- LOW_STOCK 133;
- not in stock master: 133 distinct IDs / 373 BOM rows / 11 products;
- DATA_ISSUE 112 (blank 54, invalid 46, duplicate 12);
- THRESHOLD_NOT_CONFIGURED 417.

The workbooks were unchanged before and after. The single-version history has 0 observed changes. Evaluation took 0.02 s, recording 0.07 s.

## Changed files in this remediation

| File | Change |
|---|---|
| `checker/inventory_db.py` | Schema 3: `UPGRADE_TO_3`, `ALERT_SCHEMA_VERSION`, supported 1/2/3, `source_identity()` |
| `checker/upgrade.py` | Explicit upgrades 1 → 3 and 2 → 3; attribution and key rewrite of schema-2 alerts |
| `checker/alerts.py` | Source-scoped identity; `SessionGate` / `Authorization`; write-lock re-check of sync records; scope-limited resolution; provenance-safe pruning (failures included); scope-aware `load_state`; `observed_changes_view`; shortfall and per-alert sources; generation-tagged runner |
| `checker/alerts_ui.py` | Session line; Alerts and Observed Changes tabs; Sheet, material, type and change filters; other-source handling; Source File and Shortfall columns; Rack/Level details; compact adaptive layout |
| `checker/ui.py` | Gate, verified sources, invalidation points, generation-checked event handling, single label renderer |
| `tests/test_m32c.py` | API and schema adaptations (no weakened assertions) |
| `tests/test_m32c_remediation.py` | 17 new regression tests |
| `README.md`, `M3_2C_IMPLEMENTATION_REPORT.md`, `M3_2C_TEST_REPORT.md` | Updated; superseded statements marked |

Unchanged in this remediation: the M2 engine and matching, reader, sync and threshold capture, retention policy, cache rules, M4A query logic, and the CHECK area.

## Remaining limitations

1. **Business decisions still open** (from the implementation report):
   - duplicate IDs give only a DATA_ISSUE;
   - stock 0 below a positive threshold shows both OUT_OF_STOCK and LOW_STOCK;
   - per-Sheet coverage in multi-Sheet workbooks;
   - threshold and unit semantics.
2. **Upgrade of the user's real database** is the user's explicit action; it was not done.
3. A manual *Re-evaluate* while a Local History or Upgrade confirmation dialog is open makes that apply refuse safely ("changed after preview").
4. **Authorization and paths:** authorization compares the selected path string through `same_path`, and file identity uses `normcase`/`normpath`. Two different paths to the same physical file (for example via a mapped drive and a UNC path) count as different sources: kept apart, never merged.
5. **M4A Codex P2** (unbounded history-query workers) is not part of this task and remains open.
6. **Not executed:** frozen EXE, real Google Drive, another PC, native high-DPI, Windows 10, and observed-change notifications.
