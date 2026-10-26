# Assistant query guidance and alert-size repair — 2026-10-26

Baseline: e060b99. No commit, push, release, dependency installation or real provider call.

## Reproduced causes

- Quick templates end with an unfinished Material ID/product prompt.
- Agent previously discarded a provider clarification with no tool calls and returned NO_TOOL_EVIDENCE.
- 160 synthetic materials generated 193288 bytes of alert data; the 131072-byte tool boundary
  correctly rejected the old 200-row result. The frontend did not explain the reason clearly.

## Changes

- Exact unfinished quick drafts are recognised locally, retained in the input and not submitted.
  Selecting the related quick option also shows a fixed translated example of the required input.
- A no-evidence provider finish becomes NEEDS_INPUT with one allowlisted guidance key. The host
  supplies static three-language wording; arbitrary provider prose and invented quantities remain
  excluded. Clarification and action-required outcomes keep the submitted draft for editing.
- Alerts load 20 detail rows initially. Complete SQL counts and total_rows are unchanged. The
  serialized envelope is still capped at 128 KiB; if necessary the returned detail list is reduced
  geometrically, including to zero. Truncation is disclosed, and full limits are not disabled.
- LIMIT_EXCEEDED remains compatible at the boundary, with optional fixed reasons QUERY_TIMEOUT
  or RESULT_TOO_LARGE for translated actionable messages. A limit result finishes locally rather
  than inviting another paid provider round. Existing outbound projection sends only the same
  allowlisted status/code fields, not the new full local details.

## Targeted verification

- New tests.test_assistant_guidance: **7 passed, 0.437 s**. Includes 160 synthetic materials,
  complete-count preservation, adaptive byte budget, hard-cap refusal, three-language static
  guidance, unfinished quick input/no-send, and no model retry after a tool limit.
- Directly affected existing regressions: **16 passed, 1.857 s** (direct-send 8; bounded-list 3;
  Agent fixed-prose/grounding/cancel 3; tool-size/time safeguards 2).
- Outbound projection privacy regression: **1 passed, 0.004 s**.
- Total successful checks: **24**, approximately **2.3 s test runtime**. No full suite.
- The regression command initially named the disclosure class incorrectly (ProjectionTests instead
  of DisclosureTests), causing one loader error; only the corrected single test was rerun.
- Existing prose-only and direct-send tests changed their expected status to NEEDS_INPUT; absence
  of model-invented data is preserved and explicitly asserted.

## Limits

No real API/key/company database/workbook was accessed. No packaged EXE or browser/DPI/layout
acceptance. There is no new pagination endpoint or implicit multi-turn reference resolution: the
example asks for a complete request. Generic guidance is deliberately conservative and cannot
interpret every possible missing parameter. Extra-long metadata can still exceed the hard cap even
with zero detail rows, in which case a clear refusal is retained. Normal query generation, version
checks and cancellation safeguards remain in force. No inventory calculation, sync/schema,
credential storage, source writes or main cached-mode authorisation policy was changed.
