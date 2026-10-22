# Auraplex Material Stock Checker — Development Roadmap

Updated: 2026-10-22. This document records the user's roadmap and agreed assistant UI/language requirements. Future milestones are plans, not claims of implementation or authorization to release. M4A, M3.2C and M3.2D passed Codex source acceptance; M3.2D's final decision is in `M3_2D_FINAL_CODEX_ACCEPTANCE.md`. Their local commits do not constitute release approval.

## Phase 1 — Completed foundation

| Milestone | Scope | Status |
| --- | --- | --- |
| Data investigation | Storage, BOM, Material IDs, field structures, duplicates and invalid stock | Completed |
| M0–M1 | File selection, Product ID search, production quantity, material matching and stock comparison | Completed |
| M2 | Required, Shortage, Exception and Enough calculation/classification | Completed |
| M2.1 | UI, filtering, two-sheet Excel report and exception presentation | Completed |
| M2.2 | PyInstaller portable Windows EXE, GitHub repository and v1.0.0 release | Published |

## Phase 2 — M3: Inventory Monitoring & Data Management

| Milestone | Scope | Status |
| --- | --- | --- |
| M3.1 | Startup/manual Excel → SQLite sync, inventory snapshots, file-version verification, transactions and freshness safeguards | Completed; local commit `311a69a` |
| M3.2A | Explicit offline cached calculations, always UNVERIFIED | Completed and accepted; local commit `d0633fd` |
| M3.2B | Retention, cleanup preview, backup, rollback and historical-baseline protection | Completed and accepted; local commit `d0633fd` |
| M3.2C | Automatic low-stock checks using valid MIN QTY, observed changes, data anomalies and alert deduplication | Completed and accepted (source); committed locally with M4A |
| M3.2D | Daily summary of low stock, observed changes, data anomalies and sync state | Source acceptance passed; local commit `fa72f04`; not released |
| M3.2E | Windows Task Scheduler, bounded retries, missed-run recovery and logs | E1 reviewed, committed locally. Source and temporary EXE timed/recovery/exhaustion checks passed; explicit application retries. Native-restart diagnosis deferred to CC. Missed-run and clean-machine/full GUI acceptance pending; all test tasks removed, no permanent task installed |

M3 uses deterministic Python logic, without a model API. MIN QTY fields, units and threshold semantics must be verified before alerts are implemented. Missing/invalid thresholds mean “cannot assess”, not zero. Reports must expose sync failures and historical/unverified inputs. Scheduling reuses manual execution logic; a powered-on, available machine is necessary for unattended execution. M3.2E E1 calls M3.2D (`checker.daily.generate` / `save`) unchanged, with a fresh per-run authorization only after its own successful Storage/BOM sync and alert evaluation. It never inherits cached consent or creates an UNVERIFIED fallback report. The draft requires the current user logged in (Drive mounts), with a delayed current-day run requested when a schedule is missed; it does not reconstruct historical stock states.

## Phase 3 — M4: Inventory Analytics & AI Agent

| Milestone | Scope | Status |
| --- | --- | --- |
| M4A | Material/Sheet history query and 30/60/90-day observed stock changes | Completed and accepted (source); committed locally with M3.2C. P2 worker fan-out follow-up recorded |
| M4B | Low observed movement, long unchanged periods, possible excess inventory, unusual fluctuations and stock risk | Source reviewed and committed locally. Focused tests and read-only desktop workbook smoke check passed. One P2 SQLite Sheet-metadata integrity follow-up remains; EXE, real Drive, other-PC and physical-DPI acceptance pending |
| M4C | Agent loop, tool calling, controlled read-only query tools, structured results and errors | Planned |
| M4D | Default DeepSeek provider with replaceable provider interface; future OpenAI, Gemini and local AI server adapters | Planned |
| M4E | Bottom-right robot launcher, inventory assistant/chat, three-language response routing, evidence and freshness presentation | Planned; requirements below |
| M4F | AI daily/weekly narratives, trend explanations, purchasing-review suggestions and email notifications | Planned |
| M4G | Optional company PDF/manual/purchasing-policy RAG using embeddings and vector search | Optional; not release-blocking |

SQL queries and deterministic analytics must work without an AI API. DeepSeek unavailability, quota or errors must not break stock checking, statistics or ordinary report generation. AI cannot invent numbers or replace deterministic calculations. Rules and inventory tools remain independent of the provider.

### M4E — Robot launcher and chat interface

Agreed requirements:

1. Place a robot launcher at the application's bottom right. Click to expand the chat panel; click again to collapse. Keep CHECK, EXPORT and freshness/status warnings accessible.
2. The panel provides conversation history, an input box, Send and Stop controls. Enter sends; Shift+Enter inserts a newline. Background work must not freeze Tk or update its controls from worker threads.
3. When the main window is too small, use a separate chat window rather than obstructing the material results. Preserve the existing checker workflow.
4. Offer quick questions for stock lookup, low stock, historical changes and product shortages. Route stock/history questions through controlled tools and production-demand questions through the existing calculation engine.
5. Ambiguous material/product identification requires selecting a real candidate. No fuzzy merging or guessed identifiers. A question such as “produce ten PRODUCT-1 units” must preserve the existing BOM, duplicate and exception rules.
6. Data answers show relevant material/product identity, source file/Sheet, source version, import/verification time and synchronization state. Historical cached answers visibly say UNVERIFIED. Cloud Not Verified remains visible.
7. Tool failure, missing data and unavailable sources must be stated plainly. Do not invent an answer or present an earlier response as a newly successful query. Stop/cancel must prevent late results from being appended as a current answer.
8. Without an AI API, keep ordinary inventory search/statistics available and explain that chat interpretation is unavailable. Do not silently send information to another provider.
9. Visual development can precede AI integration, but an unconnected panel must say it is not connected. No simulated stock answers presented as real tool results.
10. Chat cannot modify source Excel, deduct stock, execute arbitrary SQL or place purchase orders. Email sending belongs to M4F and requires its own configured authorization.

### M4E — Chinese, English and Malay replies

The agreed scope is assistant replies, language-dependent warnings and explanations. This does not silently expand the milestone into translating every existing application window. Preserve a stable vocabulary across the three languages.

| Language of each question | Reply language |
| --- | --- |
| Chinese only | Chinese |
| English only | English |
| Malay only | Malay |
| Chinese + English | English |
| Chinese + Malay | Malay |
| Malay + English | English |
| Chinese + Malay + English | English |

Routing contract:

- An explicit user request such as “please answer in Chinese” overrides automatic language selection for that reply.
- Otherwise classify the actual question text on every turn. Mixed-language precedence is **English > Malay > Chinese**.
- Recognized material IDs, product models, exact source names and fixed technical tokens/units such as BOM, PCS and KG do not determine the question language. “帮我查 A123 的库存” remains Chinese. Protect original identifiers and source labels from translation.
- If the question contains only an identifier/numbers or language cannot be determined confidently, reuse the previous reply language; on the first turn use the configured application/interface language. English and Malay share words: a shared token alone is not sufficient evidence of English mixing. Low-confidence behavior must be explicit and testable.
- Translation must preserve quantities, units, decimals, identifiers, status meaning and provenance. All languages invoke the same tools and calculation rules; translated status labels retain their canonical machine-readable status internally.
- Determine language using the user's question, not English text returned by a tool or quoted from source data. Company workbook/document text is data, not instructions to the agent.

Language acceptance examples:

| Input | Expected reply |
| --- | --- |
| 帮我查 A123 的库存 | Chinese |
| How much stock is available for A123? | English |
| Berapa baki stok A123? | Malay |
| 帮我 check A123 的库存 | English |
| 帮我查询 A123 的 baki stok | Malay |
| Please semak stok A123 | English |
| 请 check A123 的 baki stok | English |
| Please answer in Chinese: how much stock is available for A123? | Chinese |
| A123 | Previous reply language; configured interface language if first turn |

Also test turn-by-turn language switching, BOM/PCS/KG exclusions, ambiguous Malay/English words, errors/refusals/cancellation in the selected language and equivalent numeric results across all three languages.

## Phase 4 — Product Quality & Delivery

| Workstream | Scope | Status |
| --- | --- | --- |
| UX / reliability finalization | Large-file background reads, export progress, cancellation, errors and compact-window layout | Further work planned; not M4B |
| Security & data audit | API-key protection, allowlisted read-only tools, sensitive-data handling, spending limits and test coverage | Before AI-enabled delivery; final audit after M4 |
| Real Drive validation | Actual Excel sync, unavailable/changing files, read-only protection and database parity | Targeted earlier evidence exists; full delivery matrix remains open |
| Windows EXE acceptance | Windows 10/11, DPI, complete portable packaging and another PC | Expanded delivery matrix remains open |
| GitHub release | README, changelog, portable ZIP and upgrade/rollback instructions | Only after acceptance and separate approval |
| Company trial | 1–2 employees, issue collection, alert accuracy and AI-answer quality | After delivery |
| Company PC deployment | Optional fixed-PC scheduling if Friendy confirms feasibility | Optional later phase |

## Architecture and data constraints

- **Excel is the Source of Truth.** SQLite stores successful imports, history and statistics. No automatic stock edits/deductions. Sync failures never imply current stock; offline calculations require explicit authorization and UNVERIFIED labels.
- **Provider-agnostic agent.** DeepSeek is the default planned provider; adapters can be changed without rewriting inventory logic. Credentials do not belong in source control, normal logs or reports. Company information transmitted to an API must have a defined, approved scope before live integration.
- **Historical limits.** Show actual 30/60/90-day coverage. Net stock changes are not confirmed consumption. Use Low Observed Movement rather than asserting Low Usage. Critical spares, lead times and material importance require human confirmation. Possible excess stock is a review cue, not authority to dispose of it.
- **Local deployment first.** SQLite + Windows portable EXE; no mandatory FastAPI, PostgreSQL, Docker or separate AI server. Manual use needs no background server. Unattended sending needs an available scheduled machine. RAG and company-PC centralization remain optional.

## Execution order and validation cadence

Finish M4A → M3.2C → M3.2D → deployment-appropriate M3.2E → M4B → M4C/M4D → M4E → M4F → final delivery checks. M4E visual design may be prepared earlier without implying AI functionality is complete. M4G is optional.

Codex is taking primary implementation on 2026-10-22 at the user's request while Claude Code capacity is limited. Preserve a distinct review/acceptance gate before committing new milestones. During development run affected checks, including data-safety checks when those paths change; consolidate regression and acceptance at milestone completion. Avoid repeated full-suite runs without new changes or failures. Report unexecuted environments honestly. Development completion, local commit, push and release are separate decisions; never automatically proceed to the next milestone or publication.
