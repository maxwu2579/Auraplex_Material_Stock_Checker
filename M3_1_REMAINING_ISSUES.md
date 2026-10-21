# M3.1 Remaining Issues

1. **Only the local file is checked.** Whether Google Drive has finished downloading cloud changes cannot be seen. `Cloud Not Verified` is shown permanently beside the status in every state (audit round 2, P0-C). A file can still change right after it is verified. Success means "this local version matched at this time", not "still current". The same applies to a CHECK result marked `Local Sources Verified`.
2. **The checker still needs the Excel files.** With Drive offline, CHECK fails even though the database holds the previous data. Feeding the checker from the database is possible (parity is proven), but it was not switched on. This is a decision for M3.2.
3. **Retention.** Every Storage and BOM version and every `sync_runs` row is kept; no pruning policy exists yet. Real data is about 0.65 MB per Storage+BOM import, and each CHECK adds two run rows.
4. **Observed changes** are compared by (sheet, normalized text key) only. Rows without a key (numeric or invalid codes) are counted, not diffed. A change of file path (for example a new Drive letter) is recorded with `same_source_path = 0` and still compared.
5. **A Drive letter change** shows `Source File Unavailable`. The user must use Change… to select the file again; there is no automatic search.
6. **Closing the window during a sync** ends the daemon worker thread. SQLite rolls back the incomplete transaction on the next open; that run is simply not recorded.
7. **A corrupted or newer database** is refused and left untouched. The checker keeps working, but there is no in-app reset or repair.
8. **Not executed:** Google Drive mount tests, a person using the UI, a second PC.
9. **Short windows:** the per-file database line is hidden to keep the table usable; its content is in the tooltip and details. The file overview (title and file cards) still scrolls when space is short, as in M2.1.
10. **Housekeeping:**
   - ~~`build_portable.ps1` still defaults to version `1.0.0`.~~ Fixed (audit P1-1): `-Version` is required, must equal `app.py`, and a dev version needs `-AllowDevBuild`.
   - Decide whether `/M3_*.md` should be added to `.gitignore` like earlier internal reports. These reports contain no company names or paths.

## Items for independent Codex audit

- The transaction and revalidation path in `sync.py` (`_publish`, `_wait_until_settled`), and the classification of outcomes.
- The ordering in `ui.py` (`_start`, `_poll`, `_show_inventory`): the sync runs after the action on the same worker, reusing the shared cache.
- That the database is opt-in, so existing behaviour is unchanged without it.
- The short-window compaction in `ui.py` (`_compact_inventory`, called from `_resize`). It is decided from the height with the per-file line shown, so it should not oscillate; check this on real high-DPI screens.
- Freshness semantics: "Last Successful Sync" includes `UNCHANGED` confirmations; the overall time is the oldest across the two files.
- The `stock_quantity` / `bom_quantity` validity rules, which must mirror `core.check_materials`.
- Parity coverage in `ParityTests` and on the real data.
- The tests in `tests/test_m31.py` whose expectations were corrected during development: overall-state priority, 90-day coverage, and changing the file before the mid-import test.
