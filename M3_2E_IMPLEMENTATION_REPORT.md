# M3.2E E1 — Unattended daily entry and schedule drafts

Date: 2026-10-22 (Asia/Singapore). Implementation and verification by Codex after the user requested primary development takeover. This is not an independent acceptance or release approval.

## Delivered boundary

The accepted M3.2D work was committed locally as **`fa72f04` — Complete M3.2D verified daily stock summaries** (13 explicitly staged files; staged whitespace check passed; no code change requiring retesting for that commit). `audit_test_run.txt`, real workbooks/databases, build/dist and temporary evidence were excluded. Nothing was pushed or released.

New M3.2E E1 changes remain **uncommitted**. They implement a usable headless execution entry, run logging/process exclusion, and an explicit schedule-XML draft export. Subsequent user-authorized OS validation registered and removed two temporary synthetic tasks: actual timed execution passed, but native retry was not observed within the bounded window. See `M3_2E_SCHEDULER_VALIDATION.md`; native retry was subsequently replaced with explicit application-managed retries, and actual timed recovery/exhaustion passed. Full deployment acceptance remains pending other checks.

## Implementation

- `app.py --daily-run OUTPUT_DIR [--data-dir DIR]`: parses and executes before importing Tk/GUI modules. Returns machine-readable ASCII-safe JSON and an OS exit code when a console exists; the windowed build can rely on local receipts. Empty output arguments or conflicting GUI test flags are refused rather than opening a GUI.
- `checker/jobs.py`: requires existing folders, a readable existing schema-3 database and remembered successful source selections. It does not create a missing inventory database or migrate an older one. Every attempt verifies BOTH sources with the existing sync service, constructs its own authorization, evaluates through M3.2C's publication guard, generates today's report and saves through M3.2D's unchanged guarded bundle publication. It never borrows GUI/cache consent and never produces a cached/unverified fallback report. Retries are 1–3 attempts, 0–30 seconds apart, with individual failure reasons retained. CLI defaults to one attempt; generated schedules explicitly request three attempts, 30 seconds apart, without native scheduler restarts.
- A per-data-folder OS lock prevents overlapping processes, released on process/file-handle termination. The sentinel file is not an indication of an active job. A duplicate returns code 6 without changing the active run's receipt file.
- `daily-runs.json` is an atomic, bounded history for this feature only: latest 200 receipts plus the last success. It never deletes inventory/sync/alert history. Corrupt logs are preserved and reported. If a report was published before log writing failed, the nonzero outcome retains its report path/ID.
- `checker/scheduling.py`: exports UTF-16 Task Scheduler XML, never invokes registration tools. Absolute frozen-EXE or source-Python command paths and Windows-quoted arguments support spaces/Unicode paths. Current user, InteractiveToken, least privilege, no stored password, daily local-time trigger, IgnoreNew, StartWhenAvailable, three application-managed attempts 30 seconds apart (no RestartOnFailure loop), ten-minute task execution limit, no wake and no start on batteries. Moving executables/data/output paths requires a new reviewed draft.
- **Daily Summary → Schedule draft…**: choose an existing output folder/time, read a default-No explanation, then save a new XML. Cancel/No does not save; existing files are never overwritten. The UI says no task was installed. No main CHECK layout or inventory rule changes were made.

## Verification

Latest update: temporary packaged timed execution, recovery/exhaustion, missing-configuration and GUI smoke checks passed. See `M3_2E_PACKAGED_VALIDATION.md`. Earlier packaged-not-tested statements below describe the initial stage; broader clean-machine/GUI acceptance is still pending. Native restart diagnosis is explicitly deferred for CC; the current draft uses tested application-managed retries. No commit or permanent schedule was created.

See `M3_2E_TEST_REPORT.md` and the subsequent `M3_2E_SCHEDULER_VALIDATION.md`. Validation used synthetic workbooks and temporary databases/output only. Initial XML checks were in memory; the later actual tasks were explicitly registered, executed and removed.

Primary scheduler references: [StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-startwhenavailable-settingstype-element) and [MultipleInstancesPolicy](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-multipleinstancespolicy-settingstype-element).

## Deliberate limits / next acceptance

- E1 is not the complete deployment of M3.2E. There is no automatic task import/removal or hidden service. Actual registration/enabling must follow a review of the concrete XML and explicit user confirmation.
- InteractiveToken requires the configured user logged in, with sources available. A delayed run generates the current day after fresh checks; it does not reconstruct every missed historical date. Exact start time is not promised. Battery/no-wake conditions are visible in the draft.
- Actual native timed execution passed in source and temporary EXE modes. Native retry was not observed before timeout in either minimal probes; replacement application-managed retries passed actual recovery and exhaustion in both source and EXE modes. The precise native-restart cause remains unknown. Wake/missed schedules, logoff/mount behavior, another PC, real Drive and physical DPI remain untested.
- Source I/O may block at the OS/filesystem level; the per-process attempt count is bounded, but no hard timeout is claimed for each filesystem call. The draft's ten-minute execution limit takes effect only after an actual task is installed.
- If the daily bundle is published but its receipt cannot be saved, the job returns an explicit log/save error with the published path; an external retry can create another timestamped report. No email or external side effect occurs in E1.
- The receipt bound is a separate local-job-log policy, not a change to the accepted 12-month/90-day/180-day inventory policies. Inventory rows, snapshots, source Excel and credentials are not pruned/modified by it.
- Existing threshold/business caveats, default rollback-journal saving restriction, JSON source-path disclosure, M4A worker fan-out and synchronous normal Excel export limitations remain unchanged.
- No AI, Email, M4B or company-PC deployment was started. New E1 work needs a separate review before any local commit.
