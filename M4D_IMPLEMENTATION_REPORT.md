# M4D — Provider integration source implementation

Date: 2026-10-22. Base: `5b2e75f`. Source implemented, pending separate review. Not committed, pushed or released.
No real API was called, no company data/credential was read, and M4E/M4F have not started.

## Implementation

- `checker/providers.py`: DeepSeek adapter, configurable model/output/request limits, explicit factory,
  detached request preview, strict function-call response parser and fixed-endpoint HTTPS transport.
- `checker/outbound.py`: versioned positive-field disclosure projection; raw tool envelopes never go to API.
- `checker/credentials.py`: per-user Windows Credential Manager save/load/delete. No plaintext fallback.
- `checker/agent.py`: typed sanitized provider errors. Unexpected adapters still return PROVIDER_FAILED;
  cancellation/session/time invalidation takes precedence. Provider protocol and evidence-only output remain.
- `tests/test_m4d.py`: synthetic adapter, transport, credential and end-to-end Agent checks.

No changes to tools, calculation/analytics rules, SQLite/schema, source readers, synchronization, exports,
existing UI, scheduler, requirements or released packages. Module import/construction does not send requests.
The new adapter is a source-level host API; the current GUI has no provider settings or chat controls yet.

## External-data contract

`inventory-routing-v2` allows only the question, fixed tool definitions, model-requested arguments, candidate
material IDs/product Sheets and tool success/error/selection outcomes. Quantities, descriptions, rack/level,
full paths, source versions/hashes/times and the raw database/workbook payload remain in the host's evidence.
An exact request preview is available before credential access. Standard tool-call arguments may include
a user-requested production quantity or days filter, but never raw stock/BOM quantities from tool results.

Sensitive known free-text path/key/email patterns are refused; this is not comprehensive DLP. A question,
Sheet or material identifier may itself be company-sensitive. The current user authorization covers only
development using synthetic data. No approval for transmitting real company information is assumed.
Before a live connection, the trusted host must show the scope/preview and obtain informed approval.

Outbound consent defaults to denied, is distinct from cache consent, is not model-callable, is memory-only,
and is revoked by `revoke_outbound()`. Reauthorization revokes older in-flight requests. A new instance or
process starts denied. M4E must bind revocation to host lifecycle/settings changes and reject late UI jobs.
The adapter does not itself prove local Excel or cloud freshness. All Agent evidence stays UNVERIFIED.

## Transport, limits and failures

Default model: `deepseek-flash`; non-thinking, non-streamed normal function calling. HTTPS certificate and
hostname verification use Python's default trust store; only `api.deepseek.com/chat/completions` is used.
The normal, non-beta API is used. No arbitrary endpoint, redirect, proxy discovery, automatic retry,
provider substitution, web tool, file upload or model-generated external operation is available.

Each consent session allows ten attempts by default (configurable 1–20), with 1,024 output tokens by default
(configurable 1–2,048), 64 KiB request and 256 KiB response caps. Existing Agent step/call/time limits still
apply. Failed requests count. These limits are not a monetary spending cap or billing estimate.

One synchronous adapter call and one transport worker at a time. Caller cancellation/deadline aborts the
socket; late responses are refused. OS DNS cannot be forcibly interrupted by Python: if it outlives the
caller, the transport remains BUSY until it exits, checks cancellation before sending and starts no second
worker. Host must reuse the adapter rather than creating one per click. Already transmitted data cannot
be recalled and a cancelled request may still be billed. No Tk calls or widgets are created by this code.

Sanitized errors distinguish outbound denial, missing key, authentication, quota, rate limit, timeout,
unavailability, busy/limits, unsafe outbound data and malformed replies. Server bodies, credentials and
underlying exception text do not become UI errors. Numeric model prose is never accepted as inventory evidence.
Provider failure does not revoke local cache consent or prevent deterministic local tools/CHECK from working.

## Credentials

The trusted host may save/read/delete a key using WindowsKeyStore, under the actual interactive user's
Windows Credential Manager. It creates no credential/config file, environment variable or CLI argument.
No real key was read or stored. The native test used a random isolated test target and deleted it.
Same-user programs may read Windows credentials; there is no claim of protection against the same account
or administrator compromise. Mutable native buffers are cleared, but Python strings/HTTP buffers may retain
in-memory copies. No installer/account initialization or secret-management UI was added.

## API contract references

Checked on 2026-10-22 against official documentation:

- [DeepSeek tool calls](https://api-docs.deepseek.com/guides/tool_calls/): standard function envelopes,
  assistant tool calls and subsequent tool messages.
- [Chat completion reference](https://api-docs.deepseek.com/api/create-chat-completion/): model name,
  `thinking.type=disabled`, output limit, finish reasons and function-call fields.

Availability/schema compatibility have not been tested with an actual account; model names and provider
contracts may change. No SDK or new dependency is required.

## Next review

Inspect outbound projection and native credential declarations, reproduce denial/revocation/deadline cases,
and review the single-flight DNS/response cleanup behavior. Focused tests are in M4D_TEST_REPORT.md.
Live API authorization, account/model compatibility, packaging, another PC and GUI integration remain open.

## Added requirement: quota reminders

`checker/quota.py` provides deterministic quota state and deduplicated host notices, with Chinese/English/Malay
templates. No LLM decides when credit is low or translates quantities. M4E selects the reply language and
must display these notices; no visible chatbot has been implemented in M4D.

The consent policy is now v2 and discloses a separate authenticated GET to the fixed `/user/balance` endpoint.
It sends no question/inventory data. Check on the first authorized chat request, then no more than once per
300 seconds during requests, including failed checks. There is no idle timer or automatic retry. The check
uses at most one second or one quarter of the remaining call budget. Balance GETs are separate from the
chat-POST attempt counter. Unknown balance does not itself prevent chat, but a still-cleaning transport may
briefly return BUSY after a timeout; no extra overlapping worker is started.

Use `is_available` to detect insufficient funds; HTTP 402 immediately invalidates any older healthy balance.
Malformed/unavailable checks clear the balance and report QUOTA_UNKNOWN. An observed exhaustion remains
blocking until successfully rechecked; after top-up, the host can call `request_balance_refresh()` to recheck
on the next authorized message without resetting the request cap. Observations include the check time and
whether another check is due. Other users/processes may spend credit between checks; no perpetual freshness
or remaining-token estimate is implied.

Default independent low thresholds: USD <= 1.00 and CNY <= 5.00, configurable, no currency conversion/summing.
A low currency can be flagged while another currency has ample credit; the notice explicitly refers to a
currency balance, not overall exhaustion. Notices are separate for account shortage, unknown balance,
80%-used local session cap, reached session cap and incomplete length-limited output. API-supplied last-call
Token counts are displayed only as usage, never available credit. Repeated unchanged notices are deduplicated;
successful recovery removes old notices and a later recurrence may notify again. Revocation/reauthorization
resets observations; old in-flight sessions cannot populate the new monitor. No balances/usage are persisted.

Official balance contract: [DeepSeek Get User Balance](https://api-docs.deepseek.com/api/get-user-balance/)
(checked 2026-10-22). No actual key, balance or billed call was accessed in development/testing.
