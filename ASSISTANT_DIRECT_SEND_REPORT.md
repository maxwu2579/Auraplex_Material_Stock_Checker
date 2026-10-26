# Assistant direct Send repair — 2026-10-23

## User-requested interaction policy

Chat no longer requires separate historical-cache and outbound permission dialogs. A deliberate
Send selects the current recorded SQLite snapshot and enables the existing bounded DeepSeek chat
path. A visible three-language notice explains this. No background auto-send was added. Main CHECK
cached-mode permission and per-report narrative approval remain unchanged.

## Findings and implementation

- The old Send submitted work and cleared input before discovering missing permissions. Failed
  questions now remain; a successful result only clears the matching submitted question.
- Candidate results previously selected Local tools automatically, including AI chat results.
  AI queries now stay on Chat. Ambiguous IDs still require actual selection in Local tools.
- Source/refresh/read-failure invalidations remain conservative. This work does not suppress them
  or diagnose the exact triggering event in the user's live session. Instead the next Send can
  bind a newly recorded snapshot without another dialog. No cloud freshness is claimed.
- Late/cancelled results still cannot restore a cancelled session. Data changes during requests
  reject old results. No automatic API retries were added.
- Consecutive sends with unchanged bindings reuse the provider session, retaining request counts.
- Local Load recorded data performs no network request. The old explicit handlers remain for
  low-level compatibility but the chat permission button is no longer shown.

## Verification

Final targeted run: 11 passed in 1.745 seconds: 8 new direct-send tests, updated Enter/Shift+Enter
view test, existing grounded source-preservation test, existing Stop/late-result test.

Covered first/repeated Send, quota-count preservation, rebind after invalidation, empty question,
database read failure before any key/network use, cancellation during preparation, database change
during an API request, staying on Chat for ambiguous candidates, failed-send input preservation.
All use synthetic workbooks/temporary databases and fake keys/transport.

Development runs included test-fixture setup errors (borrowing super()-using setup methods), one
incorrect expected status for a no-tool response, and one mistyped existing test name. These were
corrected before the final run; no production failure was hidden by a passing aggregate count.

`git diff --check` passed. audit_test_run.txt SHA-256 unchanged:
307AA1DF2B507A48D936081F35F0F5367FDC9168AEF1E4EC490A4117A96CE7EC

## Limits

No real key, API, company workbook/database, process-crash reproduction, packaging or DPI/layout
acceptance. The tab switch explains a reproducible navigation jump, not proof of a process crash.
No full suite, commit, push or release. Restart the source application to load the changes.
