# M4F second slice — local report delivery and e-mail drafts: implementation report

Date: 2026-10-23. Implementer: Claude Code. **Uncommitted. Awaiting independent Codex review.** No commit, push, packaging, release, real API call, mail sending or next milestone. This slice is not M4F as a whole: purchase-review suggestions, real sending and automatic notifications remain.

## Baseline of this round

- `HEAD` = `85f8a65` (M4E), plus the uncommitted, reviewed M4F first slice. Its working-tree changes, `M4F_*.md` reports and `audit_test_run.txt` were kept.
- Snapshot saved before any edit: `%TEMP%\MRC_M4F_DELIVERY_baseline\` holds `tracked.diff`, `sha256.txt` and copies of the edited modules.
- After the round, `sha256sum -c` shows these unchanged:
  - `checker/narrative.py`, `providers.py`, `agent.py`, `daily.py`, `daily_ui.py`;
  - `tests/test_m4f.py`;
  - all M4F reports and `audit_test_run.txt`.

| Change in this round | Lines |
|---|---|
| `checker/report_delivery.py` (new) | 593 |
| `tests/test_m4f_delivery.py` (new) | 451 |
| `checker/assistant.py` — `report_guard()` and `data_basis()` only | +14 |
| `checker/assistant_ui.py` — AI-reports tab entries, AI-text capture, delivery worker, e-mail preview | +219 / −7 |
| `checker/assistant_language.py` — new zh/en/ms strings only | +30 |
| `README.md`, `DEVELOPMENT_ROADMAP.md` | sections added |

No new UI design was ported; the existing Tkinter assistant gained three controls and a status note. Frozen and untouched:
- M2 calculation, classification, duplicate and exception rules;
- read-only Excel;
- sync, cache, retention and existing export guards;
- M3.2D daily-summary saving;
- M4E chat and outbound-consent rules.

## Feature 1 — save the current daily/weekly report (HTML + JSON)

`report_delivery.build_document(facts, facts_digest, basis, language, narrative_text=None)`:
- Re-validates the facts with `narrative.validate_facts`, which is the same allowlist as the outbound AI request, so the minimal outbound boundary is kept.
- Checks the digest and that the basis is a sha256 digest.
- Freezes one canonical JSON text:

```text
format, report_id, language, period, saved_utc, verification=UNVERIFIED, cloud=Cloud Not Verified,
statement=Observed Change ≠ Actual Consumption, data_basis_digest, facts_sha256, facts, ai_interpretation|null
```

`render_html` renders from that same text:
- Status banner, report information, local deterministic statistics per period, comparison (null delta → "unknown"), recorded alerts (overlap note), sync attempts, data quality (null → "unknown"), translated limitation codes, and the AI section last.
- Fully escaped. No scripts or external resources.
- Records the JSON's SHA-256 and report ID in `<meta>` tags.

Excluded by construction (the facts allowlist):
- Material IDs, descriptions, Sheet names, local paths;
- source-file hashes, rows, workbooks.

The data-basis digest is a hash of database metadata, not of a file. The report says so and states that it proves no cloud freshness.

**AI interpretation.**
- Included only when the user ticks **Include the AI interpretation**.
- The checkbox is enabled only while `valid_narrative()` holds. That means a `NARRATIVE` result was received for the same session epoch as the preview, with the same facts digest and basis, and the reply passes `narrative.reply_problems` again.
- `build_document` re-runs the guard.
- Rejected, failed, cancelled or stale replies are never stored.
- A new preview, an invalidation or a stale result clears it (`_forget_report`).
- The AI text is a separate, UNVERIFIED section in the reply's language (the whole document uses that language when it is included). It never changes a fact; tests compare the facts in the JSON with the preview.

## Feature 2 — save-time verification and paired publication

`report_delivery.save_report(document, folder, database, basis_of, guard)` follows the M3.2D contract.

1. **Early refusal.** The folder must exist, and the session guard must report the authorisation as still current.
2. **Staging.** HTML and JSON are written exclusively, fsynced and read back inside `.mrc-report-<id>-<rand>.partial`.
3. **Re-check, then publish.** For each name `<stem>`, `<stem> (2)`…:
   - open a read transaction and refuse any journal mode other than DELETE/TRUNCATE/PERSIST (`DeliveryUnsupported`; WAL is never changed);
   - compare `session.data_basis(conn)` (the same tools basis previews are bound to) with the report basis;
   - take `session.report_guard(epoch, basis)` — the session lock, held during the rename — which requires: not closed, same epoch, still authorised, same authorised basis;
   - then do one `os.rename` of the staging folder.
   - A name race retries and re-checks everything.
4. **Failure handling.** The original exception is kept. A staging folder that cannot be removed is reported via `cleanup_warning`, `leftover` and an exception note. Nothing is ever published under a final name in part.

**Lock order.** SQLite read lock first, then the session lock, as in M3.2C/M3.2D. The session never reads SQLite while holding its lock, and writers never take the session lock, so there is no wait cycle. No lock is held while the user chooses a folder; the path dialog runs on the Tk thread before the worker starts.

**What makes a save refuse (`DeliveryStale`, "build the report again"):**
- Refresh, or a sync by this or another program (version, sync record);
- Local History cleanup (`schema_info`), or a new alert evaluation;
- Stop, Disconnect, closing the assistant, or new permissions (epoch).

A report is never relabelled VERIFIED.

**Unsupported or undocumented conditions:**
- WAL database: refused.
- Missing folder: refused.
- On non-Windows systems an existing *empty* directory could be replaced by `rename` (the program targets Windows).
- Network, cloud-synchronised or slow target folders are not tested.
- Crash or power-loss atomicity is not claimed; a `.partial` folder may remain, never a final-name report.

## Feature 3 — e-mail draft (.eml), never sent

**Flow.**
- `email_draft()` requires a report saved from the current preview: `report_saved` is cleared together with the preview.
- A worker builds the preview data. `_verified_attachments` re-reads exactly the two saved files and compares them with the SHA-256 values recorded at publication; a mismatch gives `DeliveryStale`. No directory is scanned.
- `_email_dialog` shows an optional To field, Subject, the read-only body, the attachment names and a notice that the draft is local and not sent.
- **Save .eml draft…** validates the inputs, asks for a path, and a worker runs `build_eml` and then `save_eml`.

**Message content (`build_eml`).**
- `EmailMessage(policy.SMTP)`, `multipart/mixed`:
  - UTF-8 `text/plain` body;
  - the HTML report (`text/html`) and JSON (`application/json`) as attachments;
  - headers `Subject`, `Date`, `X-Unsent: 1`, `Content-Language` (set last, because `set_content` rebuilds `Content-*` headers), and `To` only if given.
- **Body (zh/en/ms, matching the report language).** It contains:
  - the draft notice;
  - UNVERIFIED / Cloud Not Verified / not current stock, production approval or purchase advice;
  - Observed Change ≠ Actual Consumption;
  - "unknown is not 0";
  - windows, coverage, observation counts and comparison status — deltas show "unknown" when null;
  - recorded alerts or "unknown", with the overlap note;
  - issue rows per role, with "unknown" where null;
  - translated limitations;
  - whether the AI interpretation is included, with its caveat;
  - the exact attachment list.

**Header injection is refused before building:**
- `clean_addresses`: plain addresses only; at most 10, separated by `,` or `;`; any control character (CR, LF, tab, U+2028, U+2029, U+0085) is refused.
- `clean_subject`: same control-character rule, 1–200 characters.
- The SMTP policy would also reject linefeeds, as a second layer.

**Writing the file (`save_eml`).**
- `.eml` extension only, and the folder must exist.
- The draft is staged and read back, then published with a no-overwrite rename (`os.link` on POSIX). An existing file is never replaced; ` (2)` is used instead.
- A leftover staging file is reported.

The module has no `smtplib`, socket, `subprocess`, `webbrowser`, `startfile`, `urllib` or `http.client`; a test asserts this.

## UI and background work

- **Report tab.** One new row: the include-AI checkbox, **Save report (HTML + JSON)…** and **E-mail draft (.eml)…**, plus a note on AI availability.
  - Save is enabled only with an authorised preview and no write in progress.
  - E-mail is enabled only after a save from the current preview.
- **Workers.** All file work runs on `daily.DailyRunner` (reused unchanged): one task, and a second click while busy is refused with a message, so nothing queues behind it.
  - Results are drained in the existing 75 ms Tk poll and matched by request ID; only the Tk thread touches widgets.
  - On close, the runner closes and late results are dropped. An in-flight save is then refused at its final check, because closing revokes the session, so nothing is published.
- **Dialogs.**
  - Folder and path dialogs: no lock held.
  - E-mail preview: Cancel is the focused default; Escape cancels.

## Known limits

- The email preview body is read-only; edit the text in your mail program after opening the draft.
- `.eml` handling differs between mail programs; `X-Unsent` is honoured only by some.
- The document language follows the preview, or the AI reply when the reply is included.
- Timestamps are shown as recorded (UTC or ISO local); there is no locale formatting.
- The data-basis digest appears in the report as an opaque binding value.
- Not validated: real company data, real API, real mail clients, network/cloud folders, packaged EXE, other PCs, physical DPI.

Synthetic samples (temporary workbooks and DB, fake transport, all deleted afterwards except the outputs) are in `%TEMP%\MRC_M4F_DELIVERY_samples\`: zh without AI, en and ms with AI, each with its `.eml` draft. They are not in the repository or any package.

## P1-DL1 fix (Codex delivery review) — 2026-10-23

**Problem.** A DAILY save paused at `staged` while a WEEKLY preview was built. The old save then finished and became the WEEKLY preview's `report_saved`, so the e-mail draft could attach the DAILY report. The acceptance check matched only the session, never the preview itself.

**Fix (`checker/assistant_ui.py` and two new strings in `assistant_language.py`; no layout or rule change):**
- **Preview generation.** Every new, replaced or cleared preview increases `report_generation` (in `_forget_report`). A same-period regeneration is therefore a different preview.
- **Presentation identity.** `presentation()` is an immutable tuple: (preview generation, facts digest, data basis, session epoch, output language, SHA-256 of the included AI text or None). It describes exactly what Save would write now.
- **Job identity.** `save_report` captures the presentation before the folder dialog and requires it to be unchanged after the dialog. The job is submitted with it; `delivery_jobs` keeps only the newest job's identity.
- **Accepting a result.** `_drain_delivery` accepts a completed save as `report_saved` only if its submitted presentation equals the current one, within the same session epoch. Otherwise the files stay on disk and the user is told that the report belongs to an earlier preview.
- **Old failures.** A stale failure clears the preview only if it belongs to that preview; an old job's failure never clears a newer preview.
- **E-mail draft.** `saved_report()` returns the saved report only when it was saved from exactly the current presentation. It gates:
  - the e-mail button state;
  - the `email_draft()` handler itself;
  - the preview-result handler;
  - the dialog-open check;
  - the final check in the dialog's save.
  A new preview, another output language, a changed AI choice or a different AI text all detach the saved report; returning to exactly the saved presentation re-attaches it.
- **Unchanged.** Transactions, version and basis checks, the session guard, UNVERIFIED labels, the facts allowlist and source-file protection. `report_delivery.py`, `narrative.py`, `providers.py` and `daily.py` are byte-identical.
