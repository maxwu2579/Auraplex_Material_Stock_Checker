# Readability independent review — 2026-10-23

Decision: **NO-GO for local commit until P1-RD1 is fixed.** No P0 found in the inspected scope.
Review only: no production/test fixes, no commit/push/package/release, no real key/API/workbook/database.

## P1-RD1 — Alert chat summaries hide a relevant BOM synchronisation failure

Location: checker/assistant.py:451–468 (`_status_lines`, `BOM_TOOLS`).

`roles` includes BOM only for get_bom, estimate_requirements and search_products. get_stock_alerts
also contains BOM coverage results, but is excluded. A BOM UNAVAILABLE/FAILED latest attempt is
therefore removed from the default answer and visible only inside Evidence. The default answer can
still display the older “BOM material not found” count, including zero, without the relevant failure.

Independent synthetic reproduction:
1. DailyBase creates successful Storage/BOM imports and a completed alert evaluation.
2. Remove only the temporary BOM fixture and sync BOM: latest attempt becomes UNAVAILABLE.
3. Bind the preserved recorded data, call the actual get_stock_alerts tool, and render in Chinese.
4. Provenance has [('bom', 'UNAVAILABLE'), ('stock', 'IMPORTED')].
5. Summary says stock data as of …, UNVERIFIED, stored/not re-checked, and BOM-not-found 0.
   It has no BOM-unavailable/failed warning. Raw provenance retains it.

Requested fix: include relevant dependencies when composing the summary status. At minimum alert
queries depend on both roles. Data-status queries also describe both roles. Preserve a visible,
translated failure/unavailable warning without adding full logs. Do not change counts or authorisations.
Test both single-tool alert replies and a combined reply containing stock plus alerts.

## P2-RD2 — History summary calls an obsolete quantity the latest record

Location: checker/assistant.py:608–631 (`_history`).

The summary filters out non-RECORD observations before selecting `records[0]`. An ABSENT or
NOT_RETAINED latest observation is not considered when choosing the headline quantity.

Independent reproduction using temporary fixtures:
- First snapshot has A=100; a later snapshot in the same file removes A.
- Actual tool history rows are [ABSENT at 08:00:08, RECORD at 08:00:02].
- Chinese summary says “最近记录 …：100”, followed by “不再出现: 100 → —”.
- Minute formatting makes both observations look simultaneous. The full evidence is correct, but
  the short headline is misleading for a reader skimming the answer.

Requested fix: first describe the latest observation, including not-present/unknown/pruned states.
An older numeric value may be shown separately as the last recorded quantity with its own time.
Do not treat absence/pruning as zero. Preserve differences between Sheets/source identities.

## P2-RD3 — Truncated details are advertised as a complete list

Location: checker/readable.py:63–65,313–315 and summary list callers.

`shown` says the complete list is in details, even when the database extraction itself is bounded.
Daily changes load at most 2000 rows across both source scopes, and other tool outputs are bounded.
The aggregate counts are complete, but expanding details cannot retrieve omitted rows.

Independent synthetic reproduction: in the 24-change source-switch fixture, temporarily lower the
read-only row limit (no production edits) to exercise truncation. With zero loaded items, the summary
says “显示 0 项，共 1 项；完整清单见明细。” while the saved HTML correctly says only 0 of 24 changes
are listed. Using a small limit simulates the boundary; a real >2000-row workload was not run.

Requested fix: distinguish UI-shortened lists from backend-truncated results. Say “已载入明细” or
state the loaded/total counts and offer an existing narrower-range query where available. Do not
remove bounds, claim full coverage, or calculate counts from truncated rows.

## Verified strengths and preserved scope

- Independently ran tests.test_readability once: **15 passed in 5.858 s**.
- Independent synthetic reproductions above used disposable workbooks/databases and fake key/transport.
- Same-source and cross-source SQL aggregation uses complete counts, not limited detail rows.
- Added facts /2 retain aggregate-only fields; inspected the strict validation/disclosure changes.
- Key computation/sync/schema/retention/Agent/Provider/credential/tool modules have no diff against HEAD.
- Daily/report-delivery publication, transaction guards, attachment verification and locks have no
  functional changes in the inspected diff; a full new race audit was not run.
- Reviewed three developer screenshots: Chinese Chat, AI report and Daily summary at the stated
  small-window setting. The visible output is considerably less technical; daily still needs scrolling.
  This was screenshot review, not independent native-DPI/browser/print acceptance.
- git diff --check passed. audit_test_run.txt SHA-256 is unchanged:
  307AA1DF2B507A48D936081F35F0F5367FDC9168AEF1E4EC490A4117A96CE7EC

## Nonblocking usability follow-ups

The plain-text email body still appends the former detailed stats/quality codes after the new summary;
it is not actually collapsible in an .eml text body. Consider a short email with details in attachments.
HTML print behaviour, raw quota timestamps, untranslated original reasons and the absence of browser
visual verification remain acknowledged limitations. None was silently marked passed.

## Minimal next validation

Add small regressions for RD1–RD3, run only those new tests and directly affected Chat/status/history/
summary tests once. No need to repeat 177 tests or the full suite. Preserve current uncommitted
direct-send work and unrelated files. Return for review before any local commit.


## Remediation re-review — 2026-10-26

**Updated decision: GO for a local Git commit of the reviewed readability/direct-send changes.**
This supersedes the original NO-GO above. No commit was performed in this re-review. It is not
release, packaging, real-provider, browser-print or production-data acceptance.

- **P1-RD1 PASS:** inspected BOM_TOOLS and _status_lines. get_stock_alerts and data_status now
  include the BOM dependency. Relevant UNAVAILABLE/FAILED attempts appear in the top status block;
  unavailable and failed use separate wording, and never-synchronised roles remain explicit. Pure
  stock replies are not polluted with unrelated BOM warnings. Counts are untouched.
- **P2-RD2 PASS:** inspected _history and _latest_observation. The latest snapshot identity is
  considered before searching older RECORD rows. ABSENT and NOT_RETAINED are explicitly unknown,
  not zero; older values are labelled separately with their own timestamp. Multiple returned Sheet
  rows in the newest snapshot remain separate. Cross-file older values carry the file name.
- **P2-RD3 PASS:** inspected both list helpers and their callers. Loaded, shown and total counts
  are separate; search/alerts/history and daily lists can disclose backend truncation. Aggregate
  totals continue to come from complete queries; existing read bounds were not removed.

Independent targeted execution: the three new regression classes in tests.test_readability,
**7 tests passed in 0.564 seconds**. These replay the reviewed scenarios with disposable workbooks,
temporary databases, fake keys/transport and reduced limits where documented. No broad suite rerun.

`git diff --check` passed. Frozen business/sync/schema/credential/Provider/tool/retention modules
remain unchanged against HEAD. audit_test_run.txt SHA-256 remains
307AA1DF2B507A48D936081F35F0F5367FDC9168AEF1E4EC490A4117A96CE7EC.

No production or test code was modified during re-review. Only this review report was appended.
Prior nonblocking usability limitations remain: verbose plain-text email details, HTML printing of
closed details, raw quota timestamps, partially untranslated original reasons, and no browser visual
acceptance. Native DPI, packaged EXE and large real-data boundary acceptance were not performed.
