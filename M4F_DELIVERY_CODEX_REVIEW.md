# M4F delivery — focused Codex review

Date: 2026-10-23. Baseline: HEAD `85f8a65` plus the existing uncommitted M4F work.

Initial decision: **NO-GO pending P1-DL1**. **Remediation re-review: P1-DL1 CLOSED**, with the evidence below. This is a narrow review of publication/session handling and language switching, not a comprehensive acceptance. No production code was modified by Codex. No commit, push, packaging or release was performed.

## Test scope

The developer-reported 94-test run was not repeated. One independent race reproduction used `DeliveryUiTests` setup, temporary synthetic workbooks/database, fake keys/transport, and an event barrier at the real `report_delivery._checkpoint('staged')`. The probe drove an isolated Tk test instance, not the user's application window. Temporary artifacts were removed by the fixture teardown.

Result: reproduced in **0.609 seconds** (probe timer). No real API calls. No full suite or additional regression run.

## P1-DL1 — Old save completion becomes the saved report for a new preview

Relevant code: `checker/assistant_ui.py`, `build_report`, `_drain_delivery`, and report button state handling.

Reproduction:

1. Generate a DAILY preview in an authorised session.
2. Start its real HTML/JSON export; pause the worker after both files have been staged.
3. While the export is pending, the Build local preview button is still `normal`. Select WEEKLY and generate a new preview successfully.
4. Release the original DAILY export. It passes its original database/session guard and publishes the DAILY report, as requested by the earlier action.
5. `_drain_delivery` assigns that DAILY `SavedReport` to the active WEEKLY preview. Its acceptance check only requires a report to exist, the current session epoch, a nonempty saved ID and no previously associated saved report. It does not match the report generation or facts digest.

Observed values:

```json
{
  "build_button_during_save": "normal",
  "preview_period": "WEEKLY",
  "saved_period_attached_to_preview": "DAILY",
  "saved_json_period": "DAILY",
  "draft_button_state": "normal",
  "real_api_calls": 0
}
```

Impact: the active preview is weekly but its enabled email-draft action uses the previous daily report. The saved files are internally labelled DAILY; this finding is a preview-to-artifact association failure, not corrupted report contents or a false cloud-freshness claim.

Suggested bounded repair:

- Capture immutable job identity and preview generation at submission, including relevant facts digest, basis, session epoch and report language/AI selection.
- Accept a completed save as the active preview's `report_saved` only if it still belongs to that exact preview generation. An older successful export can remain on disk without becoming a new preview's attachment source.
- Make the handler safe as well as the button state; disabling Build while writing alone is insufficient protection against stale asynchronous completions.
- Add a regression using the DAILY → WEEKLY staging barrier above, plus one same-period regeneration case, since period equality alone cannot identify a preview.
- Ensure language switching or a new AI interpretation cannot silently attach an older export to a newer presentation.

Only those new race regressions and directly affected delivery tests need to run; do not repeat the reported 94 checks by default.

## Language switching status and requested next feature

Current assistant controls set `host.language` and the report preview is re-rendered by the poll loop. Report rendering and email documents already have en/zh/ms text. This is not whole-application localisation: static assistant captions and other main-program windows do not uniformly switch live.

The user's requested global selector should separate interface language, per-question assistant routing and explicit report output language. Switching display language must preserve fields, product selection, results, provenance and authorisations without issuing API requests. Existing source labels/IDs/units and canonical status codes must not be translated. An already-running save should retain its captured output language, while the UI states that language accurately; do not rewrite an already-saved report. This feature should be a separate implementation slice after the delivery race fix, independent of the pending visual redesign.

## Not executed

Live API, real company data/database, browser or mail-client acceptance, cloud/network destination behavior, EXE, Windows 10, another PC, physical DPI, crash/power-loss testing and the full suite remain unverified here. Existing developer test reports are not replaced by this focused reproduction.

## P1-DL1 remediation re-review

Codex inspected the actual implementation of preview generations, immutable presentation identity, job metadata, completion matching and handler-level draft checks. Save results now attach only to the submitted presentation. Stale failures clear only their own preview. Generation changes distinguish even repeated WEEKLY builds; language and included AI content are part of the output identity. No production code was changed in this re-review.

Independent original reproduction was re-run against the real save worker with a staging barrier: the original DAILY export remained on disk, the new WEEKLY preview remained active, `report_saved`/`saved_report()` stayed empty, and the email handler refused to start a task. PASS in 0.515 seconds; zero real API calls.

Only three additional targeted regressions ran, once: same-period regeneration during save, old failure preserving a new preview, and language/AI-selection detachment. All three passed in 2.118 seconds. Total: four focused scenarios, approximately 2.6 seconds of measured probe/test time. `git diff --check` passed. The 28-test module, prior 94 checks and full suite were not repeated.

P1-DL1 no longer blocks this work. No new finding arose in this narrow re-review; this does not add live API, packaged, physical-DPI, mail-client or broad acceptance coverage. HTML design prototypes already have three-language selection, while full-application live localisation remains a separate implementation task; no redesign is needed merely to reuse that interaction concept.
