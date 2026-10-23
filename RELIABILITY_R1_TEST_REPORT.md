# Reliability R1 — test report

Date: 2026-10-23. Environment: the project `.venv` (Python 3.12) on Windows 11, with about 1.2 GB free memory before
the final runs.

All tests used synthetic workbooks, temporary folders and temporary SQLite databases. No real company data, real
`%LOCALAPPDATA%`, API, mail client or user-opened window was used. Tk roots were created and withdrawn by the tests
themselves.

## Final runs

| Run | Tests | Result | Time |
| --- | ---: | --- | ---: |
| New: `tests.test_reliability_r1` | 7 | OK | 10.7 s |
| Directly affected regressions (one process) | 34 | OK | 44.2 s |
| **Total** | **41** | **OK** | **54.9 s** |

The 34 regressions were:

| Test class | Tests | Why it is affected |
| --- | ---: | --- |
| `test_m4a.HistoryQueryTests` | 14 | `history.read_view` changed |
| `test_m4a.HistoryWindowTests` | 9 | History window workers changed; includes the old "older query cannot overwrite newer" and "closing during query" tests |
| `test_b1_l10n.PreferenceAppTests` | 4 | `set_language` and preference save changed |
| `test_b1_ui.LanguageSwitchTests` | 3 | `set_language` changed |
| `test_b1_ui.StateProtectionTests` | 4 | switching language must preserve state |

`git diff --check` passed, and every changed file stays LF.

As requested, the following were not rerun: the full suite, the 17-module group, the earlier 80 and 94 test groups,
the smoke test, packaging and screenshots.

## New tests (`tests/test_reliability_r1.py`)

| # | Test | Requested case |
| --- | --- | --- |
| 1 | `SameLanguageRetryTests.test_clicking_the_current_language_repairs_a_corrupt_file` | Corrupt `{broken` file → English with warning → click EN → valid file and warning cleared. The result, status, job and busy state are unchanged, there is no re-render and no Excel read, no other files were created, and no dialogs appeared. |
| 2 | `SameLanguageRetryTests.test_clicking_the_current_language_retries_a_failed_save` | Save fails twice (zh stays active, warning shown, nothing written) → writable again → click zh → saved, warning cleared, nothing else touched. |
| 3 | `HistoryLaneTests.test_rapid_searches_and_queries_stay_bounded` | 30 searches and 30 queries interleaved against held reads. Each lane starts exactly 2 threads (alive threads ≤ 2) and keeps 1 pending request. After release, exactly one more runs: the newest. Candidates and result belong to the last text, key and range. |
| 4 | `HistoryLaneTests.test_newer_selection_replaces_the_pending_one_and_owns_the_result` | Selections A, B, C, B: C is replaced while pending and never runs. The result, label and first row belong to B, and earlier selections never show a result. |
| 5 | `HistoryLaneTests.test_a_superseded_real_query_stops_cooperatively` | The real `material_history` is cancelled between statements and raises `HistoryCancelled` with no partial result. A 200-million-step SQLite statement is interrupted by the progress handler (< 5 s). Outside `cancellable`, queries still work. |
| 6 | `HistoryLaneTests.test_closing_during_queries_starts_nothing_and_applies_nothing` | Close with 2 held and 1 pending: pending cleared, held reads signalled, and `query()`/`search()` after close start nothing. The 2 late responses stay unapplied, no worker remains alive and there are no Tk callback errors. |
| 7 | `HistoryLaneTests.test_failures_recover_on_the_next_request` | A search failure, then a successful search. A query failure ("QUERY FAILED", earlier result cleared), then a successful query. |

## Mutation checks (development only, not counted above)

- With `checker/ui.py` temporarily reverted to `HEAD`, both preference tests failed (2/2). The file was restored and
  its diff re-checked.
- With `_Lane.LIMIT` raised to 10⁶, which effectively means one thread per request, 3 of the 5 lane tests failed. The
  cancellation and recovery tests do not depend on the limit.

## Not verified

- **Real conditions:** a real database, a real locked database (busy wait) and a large real history.
- **Visuals:** no screenshots; the layout was not changed.
- **The actual app:** no real `%LOCALAPPDATA%` write, packaged EXE, other PC or physical DPI.
- **Other windows:** Alerts, Analytics, Daily and the assistant were not reviewed for worker bounds.
- **Earlier broad B1 regression:** still not completed. Passing these focused tests does not complete it.
