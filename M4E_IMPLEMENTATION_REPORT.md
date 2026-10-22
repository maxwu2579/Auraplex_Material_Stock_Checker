# M4E — Inventory assistant source implementation

Date: 2026-10-22. Base: local `d25ad29`. Ready for separate review, not committed/pushed/released.
M4F and live company-data/API validation have not started.

## Delivered

- `checker/assistant_ui.py`: a locally drawn bottom-right robot, responsive separate window/side panel,
  Chat/Local tools/Settings/Evidence tabs, Enter/Shift+Enter, Send/Stop, quick-question drafts, No-default
  historical/API dialogs, masked key save/removal and quota status/notices.
- `checker/assistant.py`: one bounded worker, queued generation-guarded deliveries, session-only separate
  data/API permissions, actual candidate capabilities, read-only Sheet metadata and evidence rendering.
- `checker/assistant_language.py`: conservative per-question Chinese/English/Malay routing and deterministic
  reply/error/warning templates. Explicit instructions override automatic routing; mixed priority EN > MS > ZH.
- `checker/ui.py`: launcher/lifecycle hooks only; source/sync/read failures and background maintenance
  invalidate the assistant. Main CHECK/EXPORT calculation and synchronization paths retain their existing rules.
- `tests/test_m4e.py`, README/roadmap and this milestone's reports.

The provider, credential/outbound/quota modules, Agent core/tools, M2 engine, readers, SQLite queries/schema,
sync, retention, analytics, reports, jobs and packaging scripts have not been changed. No dependency installed.

## UI and workflows

At a normal/small main-window width, chat opens separately rather than covering the material table. At wide
widths (1440 px times the available Tk scaling ratio), it becomes a side panel of 440 px times that ratio.
Layout mode changes preserve draft/transcript/session; hiding/closing cancels the session. The main table,
source freshness warning, CHECK and EXPORT remain accessible. Settings notes scroll on short windows.

Offline Local tools use all nine existing M4C tools. Material/product search must precede an exact selected
stock/BOM/history/analysis/estimate lookup. Candidate tokens are session/basis-bound; original Sheet names,
including whitespace, are retained. Users explicitly choose a Storage Sheet for estimates. Neither the UI
nor the model automatically merges configurations, similar IDs or duplicates. No API is needed for these tools.

AI interpretation uses the existing M4D adapter. Settings never shows/loads an existing secret. Saving/removing
uses the current-user vault on a worker. Outbound consent shows the scoped disclosure and exact first request;
granting it does not send anything. Send requires both historical-data permission and outbound consent.
Provider failure does not remove otherwise valid local data access. No provider fallback or fake answer exists.

## Publication, permissions and source versions

Each assistant operation is bound to a session epoch and cancel event. Only one worker may run; even after
Stop, a newer worker waits until the old one exits. The M4D transport independently bounds outstanding network
work. Workers do not touch Tk; only the host's queue poll/dialog methods do. Large evidence/reply formatting
is done off the Tk thread. Publication locks contain no database/network work.

Closing/collapsing, Stop, source selection/Refresh/sync, main background actions/maintenance and read failures
cancel old work and revoke both permissions. Dialog acceptance rechecks the epoch atomically. Authorization
also compares the reviewed database basis before/after granting. A late authorization cannot restore consent.
Queries compare their result's basis to the explicitly authorized basis, including status-only queries, and
recheck the database before queuing. A different process's import/UNCHANGED log invalidates that basis.

Queued/in-flight obsolete events are discarded. Existing transcript answers remain visibly historical; a host
invalidation adds a warning and clears candidates. Assistant read failure also invalidates the main alert
session through its existing callback. No current-stock verification is inherited from recorded success logs.
These are observations at specified times, not guarantees of permanent local or Google Drive cloud freshness.

## Language and evidence

Automatic routing excludes known candidate IDs, Sheets/file labels, quoted source text and fixed technical
tokens. Unknown/shared vocabulary reuses the prior language, initially English, and displays a notice. A manual
language selector and explicit language requests are available. This lexical detector is deliberately limited;
unusual wording can require manual selection. It is not a general language-recognition/translation service.

Only controlled evidence is rendered. Quantities/units/IDs/status codes and source text are preserved; model
prose cannot supply inventory numbers. Templates translate explanations, errors, estimates and notices. Existing
application windows and canonical source/evidence fields are outside full-UI translation scope. Every answer
has UNVERIFIED / Cloud Not Verified warnings, source versions/hashes/import times and recorded synchronization
attempts. Import or sync times are never described as a new assistant verification. Blank/missing/invalid and
duplicate stock remain distinct; M2 assumed-zero row estimates retain an explicit caveat.

Conversation history is for display, not hidden cross-turn model memory. Each Send is an independent bounded
question. Ambiguous candidates move to Local tools for explicit selection and a direct lookup. Include exact
identity again for a later AI question. There is no chat export, arbitrary SQL, write, Email or purchase tool.

## Quota and local storage

M4D's deterministic Chinese/English/Malay quota notices appear in chat, deduplicated. The status strip keeps
balance/check time/due state, consent state and warning codes visible. Usage means last-request usage, not
remaining Tokens. Unknown, low currency balance, insufficient funds, local cap and output length are separate.
Recheck balance on next Send arms the existing M4D mechanism; it performs no idle/account request itself.

Transcript/draft, consent and candidates are memory-only. Limits: 80 entries/160k transcript characters,
80k per rendered reply, 200k displayed evidence, with truncation marked; tools retain their existing caps.
Host metadata is capped at 200 Storage and 200 product Sheets. Unsaved key text is cleared on surface close.
No new configuration, logs or database table stores questions, secrets or permissions. M4D's documented
same-user vault access, in-memory zeroization and already-sent-request billing limitations still apply.

## Verification and remaining gates

See M4E_TEST_REPORT.md. Synthetic source UI and mock-provider checks are development verification, not an
independent audit, real API acceptance, cloud freshness, a new EXE or a release. No real workbook/database/key
was opened. No installation, new task/service, commit, push or release was performed. Review this source before
local commit; live outbound scope/account/model, packaging and physical/other-PC checks remain separate gates.
