# M4D — Focused source verification

Date: 2026-10-22. Source implementation evidence, not an independent audit or delivery approval.

## Final run

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_m4d tests.test_m4c -q
```

**80 passed, 0 skipped, 0 failed, 3.175 seconds, exit code 0.**
Includes 31 new M4D tests (eight quota-reminder cases) and all 49 existing M4C tests. `git diff --check` passed.
This is the final run after the quota reminder requirement. Earlier baseline: 72 passed in 3.304 seconds.
Initial M4D-only run: 20 passed in 0.247 seconds;
three additional edge-case tests were added before the final combined run. Afterwards, the disclosure text
was clarified to distinguish requested production quantities from stock/BOM result quantities. All 23 M4D
tests were rerun: **23 passed, zero failures, 0.368 seconds**. No production code changed after that run.
Full suite/M4B were not repeated because the
shared change only adds handling of sanitized ProviderFailure; deterministic tools/analytics were unchanged.

## Covered

- Denied/declined/restarted consent, unsupported policy, and separate cache/outbound authorization.
- Preview matches transmitted synthetic JSON and never loads credentials or starts networking.
- Native Windows vault missing/save/load/replace/delete using a random disposable synthetic target; cleaned
  in finally. The application's actual credential target and database were not accessed.
- Missing/malformed keys, header-injection rejection, input/output limits and per-session attempt cap.
- Standard non-thinking function messages, original Sheet preservation and local argument validation.
- Malformed/duplicate JSON, unknown/write-like tools, extra arguments, illegal quantities, incomplete and
  oversized replies; no partial evidence returned.
- Auth/quota/rate-limit/server/redirect failures with no retry, provider fallback or raw error disclosure.
- Consent revocation, concurrent adapter requests, expired key-load budget and late reply refusal.
- Fixed host/endpoint, TLS hostname/certificate verification and Bearer header construction through a
  simulated HTTPS connection. No actual connection was opened.
- Simulated DNS stall: cancellation returns, another request gets BUSY, release causes no late send.
- Simulated blocked response: timeout/cancellation shuts down the socket, caller and worker terminate.
- Positive projection for all nine tools: company payload/provenance/quantities omitted, candidate IDs/Sheets
  retained; common paths/secret/email patterns and unexpected system messages refused.
- Two-round simulated API + real synthetic SQLite Agent run: host retains stock 100, server never receives
  it or source paths, invented server prose is ignored, workbook/database digests and modification times
  unchanged. API failure leaves authorized direct local stock tools usable.
- Existing M4C safety, exact matching, UNVERIFIED evidence, cancellation, stale-basis and P2 regressions.
- Quota reminder extension: multi-currency low thresholds, dedup/recovery, exhausted-balance refusal and
  top-up recheck, HTTP 402 invalidating old positive credit, failed/malformed balance queries shown as unknown,
  local 80%/100% request-cap notices distinct from output/account limits, last-request Token usage, three-language
  templates and consent-revocation reset. Fixed-endpoint GET construction tested with no inventory request body.

Quota-only M4D development run: 31 passed in 0.428 seconds. Final combined 80-test run above supersedes it.
No production code changed after the final combined run; only reports/roadmap test counts were updated.

## Not executed

No real DeepSeek/other provider, real API key, billing/quota check, company workbook/database, Google Drive,
actual Internet TLS/DNS failure, packaged EXE, new dependency installation, second PC, Windows 10 or DPI/UI
test. Simulated transport checks do not constitute a live API smoke test or native DNS/network acceptance.
Current GUI, M2 numerical engine, sync and reports were not changed. Existing release files were not opened
or rebuilt; their hashes were not recalculated, so this report makes no new hash-verification claim.

No commit, push or release. Independent review and separate live-data approval remain required before live use.
