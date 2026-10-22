# M3.2E E1 — Focused implementation checks

Date: 2026-10-22. All workbooks, database writes and output files used temporary synthetic fixtures. No real user database/workbook was opened or upgraded. Initial checks created no Windows task; subsequent user-authorized temporary registration is recorded in `M3_2E_SCHEDULER_VALIDATION.md`.

## Executions and result interpretation

| Run | Result | Evidence |
| --- | --- | --- |
| Initial new headless/XML tests | 13 passed, 2.036 s | `%TEMP%\MRC_M32E_development.txt` |
| Added actual successful CLI + affected Daily UI cases | Initially 1 test error: test read UTF-8 JSON with Windows default GBK; production report/CLI succeeded | Test fixed to specify UTF-8; CLI JSON also made ASCII-safe for console portability |
| New module plus compact Daily UI and verified generation/save tests, after correction | 16 passed, 4.161 s | `%TEMP%\MRC_M32E_related.txt` |
| Two schedule-dialog tests | 2 passed, 0.869 s | Console; default-No prevents save, affirmative writes XML only, overwrite refused |
| Final related run after per-attempt log details | 18 passed, 5.346 s | `%TEMP%\MRC_M32E_final_related.txt` |
| Subsequent final empty-output CLI guard | 1 passed, 0.452 s | Exact new test only; confirms empty `--daily-run` cannot start GUI |
| Source normal GUI `app.py --smoke-test` | PASS | Tk initialization; no local data used |
| Windows Task Scheduler in-memory XML acceptance | PASS: 1 action, 1 trigger, StartWhenAvailable=True, LogonType=3 (InteractiveToken), RunLevel=0 | `%TEMP%\MRC_M32E_TaskXml_iacuu8qz\daily.xml`; no registration call |

There are **17 new tests** in `tests/test_m32e.py`. The related run also includes two existing Daily UI tests. The last argument-guard test was added after the 18-test run and executed separately; no full-suite result for the final E1 source state is claimed. No full business regression, rebuild or repeated large-Excel validation was performed, consistent with the user's targeted-test preference.

## Covered behavior

- Successful headless sync/evaluation/report generation: HTML+JSON status VERIFIED, matching report ID, sources' SHA256/mtime unchanged, receipt points at actual bundle.
- Missing source after a successful import: two configured attempts, one injected delay, recorded attempt failures, no extra report, retained cache/snapshots never used as fallback.
- Unchanged next run produces no duplicate inventory snapshot.
- Missing database not created; schema 1 not migrated; missing paths/output rejected before import.
- WAL mode preserved; no report published under unsupported saving mode.
- Another real CLI process cannot pass the per-data-directory OS lock. After release the next run succeeds.
- Actual separate-process successful entry invokes `app.main` without importing `checker.ui`, exits 0 and saves a valid report. Missing configuration exits nonzero without a GUI/data directory creation. Empty output exits argparse code 2.
- Stale saving produces no success receipt/report. Corrupt existing receipt history is preserved; if report publication already succeeded, its path survives in the explicit error outcome.
- Receipt bounding preserves the last success after a long synthetic failure sequence.
- XML uses quoted absolute arguments, least privilege, logged-in current-user token, no password, bounded application-managed retries, no parallel instances and delayed-run request. Invalid times/paths refused; the application itself never registers a task. External user-authorized integration harnesses registered and then removed only the named temporary tasks documented in the acceptance reports.
- GUI draft cancel/No does not save; confirmation saves only XML and refuses overwrite. Compact Daily UI and existing verified generation/save paths still pass.

## Not executed

Initial implementation checks did not register tasks. Subsequent temporary timed executions passed, including packaged retry recovery and exhaustion. Native Task Scheduler restart was not observed in source-mode tests and is deferred for CC review. See `M3_2E_SCHEDULER_VALIDATION.md` and `M3_2E_PACKAGED_VALIDATION.md`. Missed-run/logoff, clean-machine, Windows 10, real Drive, physical-DPI and second-PC checks remain unexecuted. No source-parser, stock calculation, matching, schema, cached consent, inventory retention or M3.2C business rule was changed by E1.

## Retry follow-up (2026-10-22)

Subsequent focused frozen-EXE validation also passed actual timed normal/recovery/exhaustion cases, missing-configuration refusal and GUI startup. See `M3_2E_PACKAGED_VALIDATION.md`; this supersedes earlier statements that packaged execution was entirely unexecuted. Full GUI/clean-machine/missed-run acceptance remains pending. No additional full suite was run.

Final focused run: **19 tests passed, 4.932 seconds** (`python -m unittest tests.test_m32e -q`). This supersedes the earlier 17-test module count. Two new tests cover recovery after a missing source is restored, and exact three-attempt exhaustion without any report. XML checks now require explicit `--daily-attempts 3 --daily-retry-delay 30` and absence of RestartOnFailure. Actual timed application recovery (attempt 2) and exhaustion (attempt 3) also passed; four follow-up temporary tasks were removed. See `M3_2E_SCHEDULER_VALIDATION.md` for direct evidence, native-retry comparison and remaining limits. No full suite rerun, real company data, release or commit.
